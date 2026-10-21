"""Read-only, source-first cross-textbook exploration for a teaching topic.

This path intentionally uses lexical retrieval only. It neither calls a model nor
builds an index, and retrieved passages never become graph relations implicitly.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from backend.database import (
    AlignmentCandidate, Chunk, Course, Job, KnowledgeEdge, KnowledgeNode,
    RelationEvidence, Textbook,
)
from backend.services.retrieval_service import (
    _lexical_results, _prepare_query, _query_is_supported_by_content,
)
from backend.services.source_titles import passage_concept_metadata


MAX_BOOKS = 12
MAX_PER_BOOK = 8
MAX_QUOTE_CHARS = 1400
MAX_OFFSET_PER_BOOK = 10000
NO_EVIDENCE_MESSAGE = "本次未召回与该主题匹配的原文，不代表两本教材没有关联。可换用更具体的概念名，或查看教材章节。"


def validate_bridge_scope(db, course_id: str, textbook_ids: list[str]):
    """Validate the entire scope; never silently substitute a different book."""
    selected = list(dict.fromkeys(value.strip() for value in textbook_ids if value.strip()))
    if not selected or len(selected) > MAX_BOOKS:
        raise ValueError(f"请选择 1 至 {MAX_BOOKS} 本教材")
    if not db.query(Course.id).filter(Course.id == course_id).first():
        raise LookupError("知识空间不存在")
    books = db.query(Textbook).filter(
        Textbook.course_id == course_id, Textbook.id.in_(selected),
    ).all()
    book_map = {book.id: book for book in books}
    if set(book_map) != set(selected):
        raise ValueError("部分教材不存在或不属于当前知识空间")
    return [book_map[book_id] for book_id in selected]


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _exact_anchor_score(value: str, anchors: list[str]) -> float:
    normalized = _normalized(value)
    return sum(min(len(anchor), 20) for anchor in anchors if _normalized(anchor) in normalized)


def _heading_text(value: str) -> str:
    heading = _normalized(value)
    return re.sub(
        r"^(?:第[一二三四五六七八九十百零〇\d]+[章节篇部]|"
        r"[（(]?[一二三四五六七八九十百零〇\d]+[）).．、]|[ivxlcdm]+[.、])",
        "", heading,
    ).lstrip("|｜:：、.． ")


def _is_topic_heading(value: str, topic: str) -> bool:
    """Recognize a literal topic title, allowing numbering and a translation."""
    heading = _heading_text(value)
    if not heading.startswith(topic):
        return False
    suffix = heading[len(topic):]
    # A Chinese continuation changes the topic (e.g. organ -> organ hormone).
    # English translations in Chinese textbooks do not change its scope.
    return not suffix or bool(re.fullmatch(r"[（(]?[a-z][a-z0-9,\-/()（）]*[）)]?", suffix))


def _is_topic_section_heading(value: str, topic: str) -> bool:
    """Recognize a concise section scoped to a topic, e.g. 'X 的功能'.

    This is a weaker ranking cue than exact identity, never proof of equivalence.
    Lists, prose sentences and headings beginning with another subject do not
    qualify. The same rule applies to all subject areas.
    """
    heading = _heading_text(value)
    return (
        heading.startswith(topic)
        and 0 < len(heading) - len(topic) <= 18
        and not re.search(r"[。；，:：!?！？、与和及]", heading[len(topic):])
        and bool(re.fullmatch(r"[一-鿿a-z0-9（）()\-]+", heading))
    )


def _topic_overview_bonus(query: str, chunk, features) -> float:
    """Prefer a topic's introduction when the teacher asks for the topic alone.

    This applies only to literal concept lookups. Questions about a mechanism,
    procedure or other requested facet keep the ordinary answer-aware ranking.
    No passage is added or removed by this preference.
    """
    anchors = features["anchors"]
    if len(anchors) != 1 or _normalized(query) != _normalized(anchors[0]):
        return 0.0
    topic = _normalized(anchors[0])
    path = chunk.section_path if isinstance(chunk.section_path, list) else []
    labels = [chunk.chapter_title or "", *path]
    exact_positions = [index for index, label in enumerate(labels) if _is_topic_heading(label, topic)]
    path_bonus = max((1.2 / (1 + (len(labels) - index - 1) * 0.35) for index in exact_positions), default=0.0)
    scoped_positions = [index for index, label in enumerate(labels) if _is_topic_section_heading(label, topic)]
    path_bonus = max(path_bonus, max((0.8 / (1 + (len(labels) - index - 1) * 0.35) for index in scoped_positions), default=0.0))
    opening_lines = [line.strip() for line in (chunk.content or "")[:400].splitlines() if line.strip()][:8]
    opening_bonus = 1.8 if any(_is_topic_heading(line, topic) for line in opening_lines) else 0.0
    # A focused section may have a title such as 'X 的功能' rather than X alone.
    # Only the opening line earns this weaker cue; a later subheading in a
    # continuation paragraph must not outrank the actual section introduction.
    if opening_lines and _is_topic_section_heading(opening_lines[0], topic):
        opening_bonus = max(opening_bonus, 1.4)
    # Only explicit structural labels identify supporting exercises/procedures;
    # ordinary prose mentioning an experiment or action is not penalized.
    auxiliary_markers = r"操作|习题|练习|实训|实验步骤|实验方法|实验流程|实验操作|exercises?|procedures?"
    auxiliary = bool(re.search(auxiliary_markers, " ".join(labels), re.I)) and not re.search(auxiliary_markers, query, re.I)
    return path_bonus + opening_bonus - (1.4 if auxiliary else 0.0)


def _page_image(book, page: int):
    if book.format.lower() != "pdf" or page <= 0:
        return None
    if book.total_pages and page > book.total_pages:
        return None
    return f"/api/textbooks/{quote(book.id, safe='')}/teaching/pages/{page}/image"


def _passage(chunk, book, anchors: list[str], score: float, query: str = ""):
    """Return an unchanged excerpt, centered on the first literal topic match."""
    content = chunk.content or ""
    lowered = content.lower()
    positions = [lowered.find(anchor.lower()) for anchor in anchors if anchor.lower() in lowered]
    first_match = min(positions) if positions else 0
    start = max(0, first_match - 180) if len(content) > MAX_QUOTE_CHARS else 0
    end = min(len(content), start + MAX_QUOTE_CHARS)
    start = max(0, min(start, end - MAX_QUOTE_CHARS))
    page_start = max(0, int(chunk.page_start or 0))
    page_end = max(page_start, int(chunk.page_end or page_start))
    # A chunk may span many pages. Expose a bounded list and the full range.
    page_images = [
        {"page_number": page, "url": url}
        for page in range(page_start, min(page_end, page_start + 3) + 1)
        if (url := _page_image(book, page))
    ]
    path = chunk.section_path if isinstance(chunk.section_path, list) else []
    title = path[-1] if path else chunk.chapter_title or book.title
    heading_match = any(
        _normalized(anchor) in _normalized(label)
        for anchor in anchors if len(_normalized(anchor)) >= 2
        for label in [chunk.chapter_title or "", *path]
    )
    return {
        "id": chunk.id,
        "chapter_id": chunk.chapter_id,
        "chapter": chunk.chapter_title or "",
        "section_path": path,
        "title": title,
        **passage_concept_metadata(chunk, book.id, query or " ".join(anchors)),
        "match_kind": "topic_heading" if heading_match else "mention",
        "page_start": page_start,
        "page_end": page_end,
        "quote": content[start:end],
        "quote_truncated": start > 0 or end < len(content),
        "quote_start": start,
        "quote_end": end,
        "score": round(score, 5),
        "score_kind": "lexical_relevance",
        "review_status": "unreviewed",
        "page_image_url": _page_image(book, page_start),
        "page_image_urls": page_images,
    }


def _rank_book_candidates(query: str, chunks, features):
    """Share the RAG lexical ranking without activating its vector/model path.

    An exact-anchor fallback handles tiny corpora whose BM25 IDF is zero or
    negative. It requires a literal anchor, rather than relaxing relation gates.
    """
    # Rank the complete scope before slicing, so changing page size or offset
    # never changes the order and cannot duplicate/drop items between pages.
    lexical = _lexical_results(query, chunks, limit=len(chunks), query_features=features)
    by_id = {chunk.id: chunk for chunk in chunks}
    ranks = {chunk_id: rank for chunk_id, _, rank, _ in lexical}
    anchors = features["anchors"]
    candidates = []
    for chunk in chunks:
        content = chunk.content or ""
        if not content.strip():
            continue
        context = " ".join([chunk.chapter_title or "", *(
            chunk.section_path if isinstance(chunk.section_path, list) else []
        ), content])
        literal_score = _exact_anchor_score(content, anchors)
        if chunk.id not in ranks:
            if not literal_score or not _query_is_supported_by_content(query, context):
                continue
        rank_score = 1.0 / ranks[chunk.id] if chunk.id in ranks else 0.0
        candidates.append((rank_score + literal_score * 0.04 + _topic_overview_bonus(query, chunk, features), chunk.id))
    candidates.sort(key=lambda item: (-item[0], by_id[item[1]].chunk_index or 0, item[1]))
    chosen = []
    seen = set()
    for score, chunk_id in candidates:
        chunk = by_id[chunk_id]
        fingerprint = _normalized(chunk.content)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        chosen.append((chunk, score))
    return chosen


def _rank_book_passages(query: str, chunks, features, limit: int):
    """Backward-compatible top-k view of the complete, deduplicated ranking."""
    return _rank_book_candidates(query, chunks, features)[:limit]


def _confirmed_relations(db, course_id: str, books, query: str, limit: int = 40):
    book_map = {book.id: book for book in books}
    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.course_id == course_id,
        KnowledgeNode.textbook_id.in_(book_map),
    ).all()
    node_map = {node.id: node for node in nodes}
    if not node_map:
        return []
    edges = db.query(KnowledgeEdge).filter(
        KnowledgeEdge.course_id == course_id,
        KnowledgeEdge.is_cross_textbook.is_(True),
        KnowledgeEdge.review_status == "approved",
        KnowledgeEdge.source.in_(node_map), KnowledgeEdge.target.in_(node_map),
    ).order_by(KnowledgeEdge.updated_at.desc()).all()
    scoped_edges = []
    for edge in edges:
        source, target = node_map[edge.source], node_map[edge.target]
        if source.textbook_id == target.textbook_id:
            continue
        if not any(_query_is_supported_by_content(query, " ".join([
            node.name or "", node.definition or "", node.source_paragraph or "",
        ])) for node in (source, target)):
            continue
        scoped_edges.append(edge)
        if len(scoped_edges) >= limit:
            break
    evidence_rows = db.query(RelationEvidence).filter(
        RelationEvidence.edge_id.in_([edge.id for edge in scoped_edges]),
        RelationEvidence.textbook_id.in_(book_map),
    ).all() if scoped_edges else []
    evidence_map = {(row.edge_id, row.evidence_role): row for row in evidence_rows}

    def endpoint(edge, role):
        node = node_map[edge.source if role == "source" else edge.target]
        row = evidence_map.get((edge.id, role))
        if row is not None and row.textbook_id != node.textbook_id:
            row = None
        page_start = (row.page_number if row else None) or node.page_start or node.page or 0
        return {
            "node_id": node.id, "concept": node.name,
            "textbook_id": node.textbook_id, "textbook": book_map[node.textbook_id].title,
            "chapter": node.chapter_title, "page_start": page_start,
            "page_end": node.page_end or page_start,
            "quote": row.source_quote if row else node.source_paragraph or "",
            "verified": bool(row.quote_verified if row else node.evidence_status == "verified"),
            "page_image_url": _page_image(book_map[node.textbook_id], page_start),
        }

    return [{
        "id": edge.id, "source": edge.source, "target": edge.target,
        "relation_type": edge.relation_type, "description": edge.description,
        "review_status": "approved", "source_evidence": endpoint(edge, "source"),
        "target_evidence": endpoint(edge, "target"),
    } for edge in scoped_edges]


def get_teaching_bridge(db, course_id: str, textbook_ids: list[str], query: str, limit_per_book: int = 4, offset_per_book: int = 0):
    query = (query or "").strip()
    if not 1 <= len(query) <= 160:
        raise ValueError("请输入 1 至 160 字的概念或主题")
    if not 1 <= limit_per_book <= MAX_PER_BOOK:
        raise ValueError(f"每本教材返回数量须为 1 至 {MAX_PER_BOOK}")
    if not 0 <= offset_per_book <= MAX_OFFSET_PER_BOOK:
        raise ValueError(f"每本教材的偏移量须为 0 至 {MAX_OFFSET_PER_BOOK}")
    books = validate_bridge_scope(db, course_id, textbook_ids)
    features = _prepare_query(query, [(book.id, book.title) for book in books])
    groups = []
    for book in books:
        chunks = db.query(Chunk).filter(Chunk.textbook_id == book.id).order_by(Chunk.chunk_index).all()
        candidates = _rank_book_candidates(query, chunks, features)
        ranked = candidates[offset_per_book:offset_per_book + limit_per_book]
        items = [_passage(chunk, book, features["anchors"], score, query) for chunk, score in ranked]
        groups.append({
            "textbook_id": book.id, "title": book.title,
            "status": "evidence_found" if candidates else "no_evidence", "items": items,
            "total_matches": len(candidates), "offset": offset_per_book,
            "has_more": offset_per_book + len(items) < len(candidates),
            "message": ("以下是检索到的教材原文，尚未判断跨教材关系。" if items else "已到本书检索候选末尾。") if candidates else NO_EVIDENCE_MESSAGE,
        })
    confirmed = _confirmed_relations(db, course_id, books, query)
    return {
        "query": query, "textbook_ids": [book.id for book in books], "groups": groups,
        "confirmed_relations": confirmed, "method": "lexical_only", "limit_per_book": limit_per_book, "offset_per_book": offset_per_book,
        "message": "检索原文，尚未判断关系；只有教师已确认的关系单独列出。" if any(group["total_matches"] for group in groups) else NO_EVIDENCE_MESSAGE,
    }


def get_bridge_diagnostics(db, course_id: str, textbook_ids: list[str]):
    """Show only a run for this exact selection, never course-wide totals."""
    books = validate_bridge_scope(db, course_id, textbook_ids)
    selected = {book.id for book in books}
    # JSON payload filtering remains portable across SQLite/Postgres.
    latest = None
    for job in db.query(Job).filter(Job.course_id == course_id, Job.type == "integrate").order_by(Job.created_at.desc()).yield_per(100):
        scope = (job.payload or {}).get("textbook_ids") or []
        if set(scope) == selected:
            latest = job
            break
    node_ids = db.query(KnowledgeNode.id).filter(
        KnowledgeNode.course_id == course_id, KnowledgeNode.textbook_id.in_(selected),
    )
    pending_count = db.query(AlignmentCandidate).filter(
        AlignmentCandidate.course_id == course_id,
        AlignmentCandidate.source_node_id.in_(node_ids),
        AlignmentCandidate.target_node_id.in_(node_ids), AlignmentCandidate.status.in_(["pending", "edited"]),
    ).count()
    fields = ("eligible_nodes", "candidate_pairs", "qualified_pairs", "judged", "candidates_created")
    result = latest.result or {} if latest else {}
    return {
        "textbook_ids": [book.id for book in books], "pending_review": pending_count,
        "latest_run": {
            "id": latest.id, "status": latest.status, "stage": latest.stage,
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
            **{field: result.get(field) for field in fields},
        } if latest else None,
        "message": "显示的是当前所选教材组合最近一次生成记录。缺少的指标表示当次任务未记录。" if latest else "当前所选教材组合没有生成记录；可先检索原文。没有记录不代表教材之间没有关联。",
    }
