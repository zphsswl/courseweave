"""Course-scoped hybrid retrieval with lexical, vector and graph signals."""
import hashlib
import re
import time
from collections import defaultdict
from datetime import datetime

from rank_bm25 import BM25Okapi
from sqlalchemy import or_

from backend.database import (
    SessionLocal,
    DEFAULT_COURSE_ID,
    Textbook,
    Chunk,
    KnowledgeNode,
    KnowledgeEdge,
    RagIndexState,
)
from backend.services.embeddings import embeddings_available, embed_texts, embed_text
from backend.services.vector_store import build_index as build_vector_index, search_index


_SCOPE_CACHE = {}
_LEXICAL_CACHE = {}
_CACHE_TTL_SECONDS = 60
_ENGLISH_QUERY_STOPWORDS = {
    "about", "administered", "and", "compare", "constrains", "does", "during",
    "explain", "for", "how", "perform", "processes", "the", "thresholds", "what",
    "with", "was",
}

_CHINESE_QUERY_STOP_PHRASES = {
    "分别解释", "进行比较", "知识结构", "侧重点", "基本病理变化", "基本结构特点",
    "受哪些主要因素影响", "受哪些因素影响", "受哪些因素调节", "由哪些",
    "病因和发病机制", "发生发展", "常见的", "主要的", "主要通过", "基本机制",
    "基本类型", "基本阶段", "哪些方面", "哪些时期", "哪些阶段", "哪些基本",
    "有什么不同", "有什么联系", "有什么特点", "有什么区别", "是什么", "为什么",
    "有哪些", "如何", "怎样", "怎么", "是否", "包括", "需要", "主要", "基本",
    "常见", "分别", "解释", "比较", "角度", "过程", "方面", "特点", "意义",
    "形成", "发生", "发展", "变化", "完成", "调节", "维持", "可分为", "分为",
    "阶段", "时期", "类型", "来源", "步骤", "衔接", "联系", "不同", "哪些", "经历",
    "各期", "包含", "组成", "鉴别", "应从", "方式", "关键", "组织结构",
    "演变", "病理", "进行", "什么", "一个", "机体", "从", "中", "对", "的", "了",
}

_QUERY_INTENT_GROUPS = (
    (
        ("基本类型", "常见类型", "分类", "分型", "可分为"),
        ("类型", "分类", "分型", "分为", "包括", "表现为"),
    ),
    (
        ("哪些阶段", "哪些时期", "各期", "分期", "演变", "发生发展"),
        ("分期", "阶段", "时期", "发展过程", "分为", "演变"),
    ),
    (
        ("哪些条件", "什么条件", "需要哪些条件"),
        ("条件", "影响因素"),
    ),
    (
        ("基本机制", "发生机制", "发病机制", "为什么"),
        ("机制", "原因", "发生机制", "发病机制"),
    ),
    (
        ("组织结构", "主要由", "由哪些", "包含哪些", "包括哪些", "由什么组成"),
        ("结构", "组成", "构成", "包括", "包含"),
    ),
    (
        ("临床表现", "主要改变", "病理变化"),
        ("临床表现", "病理变化", "表现", "改变"),
    ),
)


def tokenize(text_value: str):
    text_value = (text_value or "").lower()
    tokens = re.findall(r"[a-z0-9]+|[一-鿿]", text_value)
    chinese = "".join(char for char in text_value if "一" <= char <= "鿿")
    for size in (2, 3, 4):
        tokens.extend(
            chinese[index:index + size]
            for index in range(max(0, len(chinese) - size + 1))
        )
    return [token for token in tokens if token.strip()]


def _textbook_aliases(title: str) -> set[str]:
    value = re.sub(r"\s+", "", (title or "").lower())
    aliases = {value} if value else set()
    if value.startswith("医学") and len(value) > 2:
        aliases.add(value[2:])
    if value.startswith("局部") and len(value) > 2:
        aliases.add(value[2:])
    if "与" in value:
        aliases.update(part for part in value.split("与") if len(part) >= 3)
    return aliases


def _prepare_query(question: str, textbooks: list[tuple[str, str]] | None = None):
    """Separate requested books and high-signal medical phrases from question prose."""
    cleaned = (question or "").lower()
    intent_terms = []
    for triggers, related_terms in _QUERY_INTENT_GROUPS:
        if any(trigger in cleaned for trigger in triggers):
            intent_terms.extend(related_terms)
    stage_triggers, stage_terms = _QUERY_INTENT_GROUPS[1]
    if any(trigger in cleaned for trigger in stage_triggers):
        # “可分为哪些阶段” describes temporal staging, not taxonomy. Letting
        # the generic type intent leak in promotes “特殊类型” over “分期”.
        intent_terms = list(stage_terms)
    requested_books = []
    aliases = []
    for textbook_id, title in textbooks or []:
        for alias in _textbook_aliases(title):
            aliases.append((alias, textbook_id))
    for alias, textbook_id in sorted(aliases, key=lambda item: len(item[0]), reverse=True):
        if alias and alias in cleaned:
            if textbook_id not in requested_books:
                requested_books.append(textbook_id)
            cleaned = cleaned.replace(alias, " ")

    for phrase in sorted(_CHINESE_QUERY_STOP_PHRASES, key=len, reverse=True):
        cleaned = cleaned.replace(phrase, " ")
    chinese_terms = []
    for term in re.findall(r"[一-鿿]+", cleaned):
        parts = [part for part in re.split(r"[和与及到对]", term) if part]
        chinese_terms.extend(
            part for part in (parts or [term])
            if not all(char in "和与及或、" for char in part)
        )
    english_terms = [
        term for term in re.findall(r"[a-z][a-z0-9-]+", cleaned)
        if len(term) >= 2 and term not in _ENGLISH_QUERY_STOPWORDS
    ]
    query_tokens = list(english_terms)
    for term in chinese_terms:
        if len(term) == 1:
            query_tokens.append(term)
            continue
        for size in range(2, min(4, len(term)) + 1):
            query_tokens.extend(term[index:index + size] for index in range(len(term) - size + 1))
    anchor_terms = sorted(
        {term for term in [*chinese_terms, *english_terms] if len(term) >= 2},
        key=len,
        reverse=True,
    )
    return {
        "tokens": query_tokens,
        "anchors": anchor_terms,
        "topics": chinese_terms[:3] or english_terms[:3],
        "intent_terms": list(dict.fromkeys(intent_terms)),
        "requested_books": requested_books,
    }


def _answer_query_kind(question: str) -> str:
    """Return the evidence shape requested by an explicit list-style question."""
    normalized = re.sub(r"\s+", "", question or "")
    if any(marker in normalized for marker in ("各期", "哪些阶段", "哪些时期", "分期", "如何演变")):
        return "stage"
    if re.search(r"(?:哪些|什么|包含|包括)[^？?，,。]{0,6}细胞", normalized):
        return "cells"
    if any(
        marker in normalized
        for marker in (
            "包括哪些", "包含哪些", "哪些基本", "基本类型", "有哪些",
            "可分为", "由哪些", "哪些条件", "哪些方式", "三个基本环节",
        )
    ):
        return "list"
    return ""


def _gram_coverage(value: str, grams: set[str]) -> float:
    if not grams:
        return 0.0
    return len({gram for gram in grams if gram in value}) / len(grams)


def _answer_form_strength(question: str, content: str) -> float:
    """Measure whether a passage has the requested answer form, not just query words.

    The subject gate is applied separately during ranking. Keeping this helper focused
    on the body text prevents a chapter title such as ``细胞和组织的适应与损伤``
    from turning an unrelated child section into list evidence.
    """
    kind = _answer_query_kind(question)
    if not kind:
        return 0.0
    normalized = re.sub(r"\s+", "", content or "")

    if kind == "stage":
        labels = {
            label
            for label in re.findall(r"[一-鿿]{2,10}(?:期|阶段)", normalized)
            if label not in {
                "此期", "该期", "各期", "时期", "分期", "早期", "晚期",
                "同期", "阶段", "急性期", "慢性期",
            }
        }
        explicit_count = bool(re.search(r"(?:分为|经历|划分为).{0,12}(?:三|四|五|六|\d)期", normalized))
        return min(1.0, len(labels) / 2.0 + (0.5 if explicit_count else 0.0))

    if kind == "cells":
        if not re.search(r"包括|包含|组成|构成", normalized):
            return 0.0
        labels = set(re.findall(r"[一-鿿]{1,8}细胞(?!癌|瘤)", normalized))
        return min(1.0, len(labels) / 3.0)

    # A generic overview must contain a relation cue and a real enumeration in
    # the same sentence. This distinguishes “适应表现为萎缩、肥大、增生、化生”
    # from a chunk that merely repeats “细胞适应” elsewhere in the paragraph.
    best = 0.0
    for sentence in re.split(r"[。！？!?]", normalized):
        if not re.search(r"包括|包含|组成|构成|表现为|分为|可见", sentence):
            continue
        separators = len(re.findall(r"[、；]", sentence))
        numbered = len(re.findall(r"[①②③④⑤⑥⑦⑧⑨⑩]|[（(]\d+[）)]", sentence))
        conjunction = int(bool(re.search(r"[和与及]", sentence)))
        if separators + numbered < 2:
            continue
        best = max(best, min(1.0, (separators + numbered + conjunction) / 3.0))
    return best


def _query_is_supported_by_content(question: str, content: str, strict: bool = False) -> bool:
    """Reject ASCII out-of-domain matches caused only by bibliography stopwords."""
    if re.search(r"[一-鿿]", question or ""):
        cleaned = (question or "").lower()
        for phrase in sorted(_CHINESE_QUERY_STOP_PHRASES, key=len, reverse=True):
            cleaned = cleaned.replace(phrase, " ")
        segments = [
            part
            for term in re.findall(r"[一-鿿]+", cleaned)
            for part in re.split(r"[和与及到从对]", term)
            if part
        ]
        searchable = re.sub(r"\s+", "", content or "").lower()
        supported_segments = []
        for term in segments:
            if len(term) <= 3:
                supported_segments.append(term in searchable)
                continue
            ordered_bigrams = [
                term[index:index + 2]
                for index in range(len(term) - 1)
            ]
            bigrams = set(ordered_bigrams)
            matched = {gram for gram in bigrams if gram in searchable}
            # A single coincidental n-gram is inevitable in a full medical
            # library (for example “细胞” in a question about cellular
            # automata). Require broad topic coverage while still allowing
            # natural Chinese variants such as “细胞和组织的适应”.
            coverage_supported = (
                len(matched) >= 2
                and len(matched) / len(bigrams) >= 0.6
            )
            if strict and coverage_supported:
                first_positions = [match.start() for match in re.finditer(re.escape(ordered_bigrams[0]), searchable)]
                last_positions = [match.start() for match in re.finditer(re.escape(ordered_bigrams[-1]), searchable)]
                coverage_supported = bool(
                    first_positions
                    and last_positions
                    and min(abs(left - right) for left in first_positions for right in last_positions) <= 120
                )
            supported_segments.append(coverage_supported)
        if not supported_segments:
            return False
        return any(supported_segments)
    query_terms = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]+", question or "")
        if len(token) >= 4 and token.lower() not in _ENGLISH_QUERY_STOPWORDS
    }
    if not query_terms:
        return False
    content_terms = set(re.findall(r"[a-z][a-z0-9-]+", (content or "").lower()))
    matched = query_terms & content_terms
    if len(query_terms) == 1:
        return bool(matched)
    normalized_content = " ".join(re.findall(r"[a-z][a-z0-9-]+", (content or "").lower()))
    ordered_terms = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]+", question or "")
        if token.lower() in query_terms
    ]
    adjacent_phrase = any(
        f"{ordered_terms[index]} {ordered_terms[index + 1]}" in normalized_content
        for index in range(len(ordered_terms) - 1)
    )
    high_coverage = len(matched) / len(query_terms) >= 0.6 and any(len(term) >= 7 for term in matched)
    return adjacent_phrase or high_coverage


def _query_has_scope_support(question: str, chunks) -> bool:
    """Reject a Chinese query when one of its specific topics is absent course-wide."""
    if not re.search(r"[一-鿿]", question or ""):
        return True
    cleaned = (question or "").lower()
    for phrase in sorted(_CHINESE_QUERY_STOP_PHRASES, key=len, reverse=True):
        cleaned = cleaned.replace(phrase, " ")
    segments = [
        part
        for term in re.findall(r"[一-鿿]+", cleaned)
        for part in re.split(r"[和与及到从对]", term)
        if len(part) >= 2
    ]
    if not segments:
        return False
    searchable_chunks = [_retrieval_text(chunk) for chunk in chunks]
    return all(
        any(_query_is_supported_by_content(segment, content, strict=True) for content in searchable_chunks)
        for segment in segments
    )


def _section_labels(chunk):
    return [str(value).strip() for value in (chunk.section_path or []) if str(value).strip()]


def _retrieval_text(chunk):
    """Add structural context for ranking without altering the quoted source text."""
    fields = [chunk.textbook_title or "", chunk.chapter_title or "", *_section_labels(chunk)]
    context = " ".join(dict.fromkeys(field for field in fields if field))
    return f"{context}\n{chunk.content or ''}".strip()


def _scoped_chunks(db, course_id: str, textbook_ids=None):
    query = db.query(Chunk).join(Textbook, Textbook.id == Chunk.textbook_id).filter(
        Textbook.course_id == course_id,
    )
    if textbook_ids:
        query = query.filter(Chunk.textbook_id.in_(textbook_ids))
    return query.order_by(
        Chunk.textbook_id,
        Chunk.chapter_id,
        Chunk.chunk_index,
        Chunk.id,
    ).all()


def _scope_key(course_id: str, textbook_ids=None):
    return course_id, tuple(sorted(textbook_ids or []))


def _cached_scoped_chunks(db, course_id: str, textbook_ids=None):
    key = _scope_key(course_id, textbook_ids)
    cached = _SCOPE_CACHE.get(key)
    if cached and time.monotonic() - cached["created"] < _CACHE_TTL_SECONDS:
        return cached["chunks"]
    chunks = _scoped_chunks(db, course_id, textbook_ids)
    _SCOPE_CACHE[key] = {"created": time.monotonic(), "chunks": chunks}
    _LEXICAL_CACHE.pop(key, None)
    return chunks


def invalidate_course_cache(course_id: str):
    for cache in (_SCOPE_CACHE, _LEXICAL_CACHE):
        for key in [item for item in cache if item[0] == course_id]:
            cache.pop(key, None)


def _content_signature(chunks):
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.id.encode("utf-8"))
        digest.update(_retrieval_text(chunk).encode("utf-8"))
    return digest.hexdigest()


def build_course_index(course_id: str = DEFAULT_COURSE_ID):
    db = SessionLocal()
    try:
        invalidate_course_cache(course_id)
        chunks = _scoped_chunks(db, course_id)
        state = db.query(RagIndexState).filter(RagIndexState.course_id == course_id).first()
        if state is None:
            state = RagIndexState(course_id=course_id)
            db.add(state)
        state.status = "building"
        state.error = ""
        db.commit()
        if not chunks:
            state.status = "not_built"
            state.chunk_count = 0
            state.index_method = ""
            db.commit()
            return {"indexed": False, "chunk_count": 0, "method": "none", "message": "课程没有可索引知识块"}

        vector_ready = False
        vector_error = ""
        if embeddings_available():
            embeddings = []
            for start in range(0, len(chunks), 128):
                batch = chunks[start:start + 128]
                embeddings.extend(embed_texts([_retrieval_text(chunk) for chunk in batch], allow_fallback=False))
            if len(embeddings) == len(chunks):
                vector_ready = build_vector_index([
                    {
                        "id": chunk.id,
                        "content": _retrieval_text(chunk),
                        "textbook_id": chunk.textbook_id,
                        "textbook": chunk.textbook_title,
                        "chapter": chunk.chapter_title,
                        "page": chunk.page_start,
                        "page_end": chunk.page_end,
                    }
                    for chunk in chunks
                ], embeddings, course_id=course_id)
                if not vector_ready:
                    vector_error = "向量存储不可用，已降级为 BM25 检索。"

        state.status = "ready"
        state.chunk_count = len(chunks)
        state.index_method = "bm25_vector" if vector_ready else "bm25"
        state.embedding_available = vector_ready
        state.content_signature = _content_signature(chunks)
        state.error = vector_error
        state.built_at = datetime.utcnow()
        db.commit()
        return {
            "indexed": True,
            "chunk_count": len(chunks),
            "method": state.index_method,
            "embedding_available": vector_ready,
            "message": "混合索引已构建" if vector_ready else "BM25 索引已就绪；向量能力不可用时不会伪装为语义检索",
            "warning": vector_error,
        }
    except Exception as exc:
        state = db.query(RagIndexState).filter(RagIndexState.course_id == course_id).first()
        if state:
            state.status = "failed"
            state.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            db.commit()
        raise
    finally:
        db.close()


def get_index_status(course_id: str = DEFAULT_COURSE_ID):
    db = SessionLocal()
    try:
        state = db.query(RagIndexState).filter(RagIndexState.course_id == course_id).first()
        current_chunks = _scoped_chunks(db, course_id)
        current_signature = _content_signature(current_chunks) if current_chunks else ""
        if state is None:
            return {
                "indexed": False,
                "status": "not_built",
                "chunk_count": len(current_chunks),
                "method": "none",
                "message": "尚未构建课程索引",
            }
        status = state.status
        if status == "ready" and current_signature != state.content_signature:
            status = "stale"
        return {
            "indexed": status == "ready",
            "status": status,
            "chunk_count": len(current_chunks),
            "indexed_chunk_count": state.chunk_count,
            "method": state.index_method,
            "embedding_available": state.embedding_available,
            "message": state.error or ("索引可用" if status == "ready" else "教材已变化，请重新构建索引"),
            "built_at": state.built_at.isoformat() if state.built_at else None,
        }
    finally:
        db.close()


def _lexical_results(question: str, chunks, limit=60, cache_key=None, query_features=None):
    cached = _LEXICAL_CACHE.get(cache_key) if cache_key else None
    chunk_signature = _content_signature(chunks)
    if cached and cached["chunk_signature"] == chunk_signature:
        bm25 = cached["bm25"]
    else:
        corpus = [tokenize(_retrieval_text(chunk)) for chunk in chunks]
        if not any(corpus):
            return []
        bm25 = BM25Okapi(corpus)
        if cache_key:
            _LEXICAL_CACHE[cache_key] = {"chunk_signature": chunk_signature, "bm25": bm25}
    query_features = query_features or _prepare_query(question)
    query_tokens = query_features["tokens"] or tokenize(question)
    if not query_tokens:
        return []
    scores = bm25.get_scores(query_tokens)
    anchors = query_features["anchors"]
    topic = (query_features.get("topics") or [""])[0]
    topic_tail = topic[-2:] if len(topic) >= 2 and re.search(r"[一-鿿]", topic) else topic
    intent_terms = query_features.get("intent_terms") or []
    topics = [term for term in query_features.get("topics", []) if len(term) >= 2]
    primary_subject = topics[0] if topics else ""
    stage_query = any(
        marker in (question or "")
        for marker in ("各期", "哪些阶段", "哪些时期", "分期", "演变", "发生发展")
    )
    topic_grams = {
        topic[index:index + 2]
        for index in range(max(0, len(topic) - 1))
    }

    positive_indices = [index for index in range(len(chunks)) if scores[index] > 0]
    candidate_indices = [
        index
        for index in positive_indices
        if _query_is_supported_by_content(question, _retrieval_text(chunks[index]))
    ]
    if not candidate_indices:
        return []
    primary_topic = (query_features.get("topics") or [""])[0]
    if len(primary_topic) >= 3 and not re.search(r"[和与及到]", question or ""):
        primary_candidates = [
            index for index in candidate_indices
            if _query_is_supported_by_content(primary_topic, _retrieval_text(chunks[index]))
        ]
        if primary_candidates:
            # Keep immediate continuations from the exact same semantic section.
            # A heading such as “大叶性肺炎” commonly appears in the first chunk,
            # while the next chunk starts directly with “（2）红色肝样变期”.
            # A subject-only hard filter would discard that strongest evidence.
            primary_neighbourhoods = defaultdict(list)
            for index in primary_candidates:
                chunk = chunks[index]
                key = (chunk.textbook_id, chunk.chapter_id, tuple(_section_labels(chunk)))
                primary_neighbourhoods[key].append(int(chunk.chunk_index or 0))
            candidate_indices = [
                index
                for index in positive_indices
                if index in primary_candidates
                or any(
                    abs(int(chunks[index].chunk_index or 0) - seed) <= 2
                    for seed in primary_neighbourhoods.get(
                        (
                            chunks[index].textbook_id,
                            chunks[index].chapter_id,
                            tuple(_section_labels(chunks[index])),
                        ),
                        [],
                    )
                )
            ]

    def rank_features(index: int):
        chapter = re.sub(r"\s+", "", chunks[index].chapter_title or "").lower()
        labels = _section_labels(chunks[index])
        section = re.sub(r"\s+", "", " ".join(labels[1:] if len(labels) > 1 else labels)).lower()
        content = re.sub(r"\s+", "", chunks[index].content or "").lower()
        searchable = re.sub(r"\s+", "", _retrieval_text(chunks[index])).lower()
        matched = [term for term in anchors if term in searchable]
        topic_coverage = (
            len({gram for gram in topic_grams if gram in searchable}) / len(topic_grams)
            if topic_grams else 0.0
        )
        chapter_topic_coverage = (
            len({gram for gram in topic_grams if gram in chapter}) / len(topic_grams)
            if topic_grams else 0.0
        )
        section_topic_coverage = (
            len({gram for gram in topic_grams if gram in section}) / len(topic_grams)
            if topic_grams else 0.0
        )
        body_topic_coverage = _gram_coverage(content, topic_grams)
        path_topic_positions = [
            position
            for position, label in enumerate(labels)
            if _gram_coverage(re.sub(r"\s+", "", label).lower(), topic_grams) >= 0.75
        ]
        overview_scope = 0.0
        if path_topic_positions:
            remaining_depth = len(labels) - 1 - max(path_topic_positions)
            overview_scope = 1.0 / (1.0 + remaining_depth)
        overview_heading = int(
            "基本病理变化" in re.sub(r"\s+", "", question or "")
            and "基本病理变化" in content
        )
        intent_path_score = sum(len(term) ** 2 for term in intent_terms if term in section)
        intent_content_score = sum(len(term) ** 2 for term in intent_terms if term in content)
        stage_evidence = 0.0
        if stage_query:
            labels = set(re.findall(
                r"(?:^|\n)\s*(?:[（(](?:\d+|[一二三四五六七八九十]+)[）)])?\s*([^：:\n]{2,12}(?:期|阶段))\s*[:：]",
                chunks[index].content or "",
            ))
            overview = bool(re.search(
                r"(?:分为|划分为|经历)(?:以下)?[一二三四五六七八九十\d]+(?:个)?(?:期|阶段)",
                content,
            ))
            if labels:
                stage_evidence = min(1.0, (len(labels) + int(overview)) / 2.0)
        return {
            "bm25": float(scores[index]),
            "topic": topic_coverage,
            "chapter_topic": chapter_topic_coverage,
            "section_topic": section_topic_coverage,
            "section_exact": (
                sum(1 for value in topics if value in section) / len(topics)
                if topics else 0.0
            ),
            "all_topic": (
                sum(1 for value in topics if value in searchable) / len(topics)
                if topics else 0.0
            ),
            "intent_path": intent_path_score,
            "intent_content": intent_content_score,
            "stage_evidence": stage_evidence,
            "anchor": sum(min(len(term), 8) ** 2 for term in matched),
            "tail": int(bool(topic_tail and topic_tail in section)),
            "subject": max(body_topic_coverage, section_topic_coverage),
            "answer_form": (
                0.0
                if stage_query
                else _answer_form_strength(question, chunks[index].content or "")
            ),
            "overview_scope": overview_scope,
            "overview_heading": overview_heading,
        }

    features = {index: rank_features(index) for index in candidate_indices}
    # Restore the subject for a continuation chunk only when a nearby chunk in
    # the exact same section has a strong body/path match. This is deliberately
    # narrower than chapter-level propagation, which would make every list in a
    # broad chapter look like an answer to the chapter topic.
    subject_seeds = defaultdict(list)
    for index, value in features.items():
        if value["subject"] < 0.75:
            continue
        chunk = chunks[index]
        key = (chunk.textbook_id, chunk.chapter_id, tuple(_section_labels(chunk)))
        subject_seeds[key].append(int(chunk.chunk_index or 0))
    for index, value in features.items():
        chunk = chunks[index]
        key = (chunk.textbook_id, chunk.chapter_id, tuple(_section_labels(chunk)))
        chunk_index = int(chunk.chunk_index or 0)
        if any(abs(chunk_index - seed) <= 2 for seed in subject_seeds.get(key, [])):
            value["subject"] = max(value["subject"], 1.0)

    max_bm25 = max(value["bm25"] for value in features.values()) or 1.0
    max_intent_path = max(value["intent_path"] for value in features.values()) or 1.0
    max_intent_content = max(value["intent_content"] for value in features.values()) or 1.0
    max_anchor = max(value["anchor"] for value in features.values()) or 1.0
    overview_query = any(
        marker in (question or "")
        for marker in ("基本类型", "包括哪些", "哪些基本", "基本病理变化", "共同结构特点")
    )
    intent_path_weight = 0.06 if overview_query else 0.38
    answer_query = bool(_answer_query_kind(question))

    def rank_key(index: int):
        value = features[index]
        intent_gate = value["subject"] if answer_query else 1.0
        score = (
            0.46 * value["bm25"] / max_bm25
            + 0.12 * value["topic"]
            + 0.08 * value["chapter_topic"]
            + 0.08 * value["section_topic"]
            + 0.08 * value["section_exact"]
            + 0.12 * value["all_topic"]
            + intent_path_weight * value["intent_path"] / max_intent_path * intent_gate
            + 0.04 * value["intent_content"] / max_intent_content * intent_gate
            + 0.02 * value["anchor"] / max_anchor
            + 0.70 * value["answer_form"] * value["subject"]
            + 0.65 * value["stage_evidence"] * value["subject"]
            + (0.45 * value["overview_scope"] if overview_query else 0.0)
            + (0.45 * value["overview_heading"] if overview_query else 0.0)
        )
        if answer_query:
            score -= 0.18 * (1.0 - value["subject"])
        return score, value["bm25"], value["tail"]

    ranked_indices = sorted(candidate_indices, key=rank_key, reverse=True)
    return [
        (chunks[index].id, float(scores[index]), rank + 1, "bm25")
        for rank, index in enumerate(ranked_indices[:limit])
    ]


def _graph_chunk_ids(db, course_id: str, question: str, allowed_chunk_ids: set[str], query_features=None):
    query_features = query_features or _prepare_query(question)
    terms = [
        term for term in query_features.get("topics", [])
        if len(term) >= 2
    ][:3]
    if not terms:
        return []
    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.course_id == course_id,
        KnowledgeNode.evidence_status == "verified",
        or_(*[KnowledgeNode.name.ilike(f"%{term}%") for term in terms]),
    ).limit(50).all()
    node_ids = {node.id for node in nodes}
    canonical_ids = {node.canonical_concept_id for node in nodes if node.canonical_concept_id}
    if canonical_ids:
        nodes.extend(db.query(KnowledgeNode).filter(
            KnowledgeNode.course_id == course_id,
            KnowledgeNode.canonical_concept_id.in_(canonical_ids),
        ).limit(100).all())
        node_ids.update(node.id for node in nodes)
    if node_ids:
        edges = db.query(KnowledgeEdge).filter(
            KnowledgeEdge.course_id == course_id,
            KnowledgeEdge.is_cross_textbook.is_(True),
            or_(KnowledgeEdge.source.in_(node_ids), KnowledgeEdge.target.in_(node_ids)),
        ).limit(100).all()
        neighbor_ids = {edge.source for edge in edges} | {edge.target for edge in edges}
        if neighbor_ids:
            nodes.extend(db.query(KnowledgeNode).filter(KnowledgeNode.id.in_(neighbor_ids)).all())
    return [
        node.source_chunk_id
        for node in nodes
        if node.source_chunk_id and node.source_chunk_id in allowed_chunk_ids
    ]


def retrieve(
    question: str,
    course_id: str = DEFAULT_COURSE_ID,
    textbook_ids=None,
    mode: str = "all",
    top_k: int = 8,
):
    db = SessionLocal()
    try:
        cache_key = _scope_key(course_id, textbook_ids)
        chunks = _cached_scoped_chunks(db, course_id, textbook_ids)
        if not chunks:
            return {"results": [], "trace": {"course_id": course_id, "reason": "no_chunks"}}
        if not _query_has_scope_support(question, chunks):
            return {
                "results": [],
                "trace": {
                    "course_id": course_id,
                    "reason": "unsupported_query_topics",
                    "scoped_chunks": len(chunks),
                },
            }
        chunk_map = {chunk.id: chunk for chunk in chunks}
        textbook_rows = [
            (row[0], row[1])
            for row in db.query(Textbook.id, Textbook.title).filter(
                Textbook.course_id == course_id,
                Textbook.id.in_({chunk.textbook_id for chunk in chunks}),
            ).all()
        ]
        query_features = _prepare_query(question, textbook_rows)
        lexical_ranking = _lexical_results(
            question,
            chunks,
            cache_key=cache_key,
            query_features=query_features,
        )
        rankings = [lexical_ranking]
        if mode == "compare" and query_features["requested_books"]:
            represented_books = {
                chunk_map[chunk_id].textbook_id
                for chunk_id, _, _, _ in lexical_ranking
                if chunk_id in chunk_map
            }
            for book_id in query_features["requested_books"]:
                if book_id in represented_books:
                    continue
                book_chunks = [chunk for chunk in chunks if chunk.textbook_id == book_id]
                if not book_chunks:
                    continue
                book_ranking = _lexical_results(
                    question,
                    book_chunks,
                    cache_key=_scope_key(course_id, [book_id]),
                    query_features=query_features,
                )
                if book_ranking:
                    rankings.append(book_ranking)

        state = db.query(RagIndexState).filter(RagIndexState.course_id == course_id).first()
        vector_used = False
        indexed_scope = chunks if not textbook_ids else _cached_scoped_chunks(db, course_id)
        if (
            state
            and state.status == "ready"
            and state.embedding_available
            and state.content_signature == _content_signature(indexed_scope)
        ):
            query_embedding = embed_text(question, allow_fallback=False)
            if query_embedding:
                vector_items = search_index(query_embedding, top_k=30, course_id=course_id)
                vector_ranking = [
                    (item["id"], 1.0 - float(item.get("distance", 1.0)), rank + 1, "vector")
                    for rank, item in enumerate(vector_items)
                    if item["id"] in chunk_map
                ]
                if vector_ranking:
                    rankings.append(vector_ranking)
                    vector_used = True

        graph_ids = _graph_chunk_ids(
            db,
            course_id,
            question,
            set(chunk_map),
            query_features=query_features,
        )
        graph_used = bool(graph_ids and not rankings[0])
        if graph_used:
            rankings.append([(chunk_id, 1.0, rank + 1, "graph") for rank, chunk_id in enumerate(graph_ids)])

        fused_scores = defaultdict(float)
        retrievers = defaultdict(set)
        raw_scores = defaultdict(dict)
        for ranking in rankings:
            for chunk_id, raw_score, rank, retriever in ranking:
                weight = {"bm25": 1.0, "vector": 0.8, "graph": 0.05}.get(retriever, 1.0)
                fused_scores[chunk_id] += weight / (60 + rank)
                retrievers[chunk_id].add(retriever)
                raw_scores[chunk_id][retriever] = raw_score
        ranked_ids = [
            chunk_id
            for chunk_id in sorted(fused_scores, key=fused_scores.get, reverse=True)
            if _query_is_supported_by_content(question, _retrieval_text(chunk_map[chunk_id]))
        ]

        selected = []
        if mode == "compare" or (textbook_ids and len(textbook_ids) > 1):
            preferred_books = query_features["requested_books"] or list(textbook_ids or [])
            if preferred_books:
                for book_id in preferred_books:
                    best = next(
                        (chunk_id for chunk_id in ranked_ids if chunk_map[chunk_id].textbook_id == book_id),
                        None,
                    )
                    if best and best not in selected:
                        selected.append(best)
                    if len(selected) >= top_k:
                        break
            else:
                seen_books = set()
                for chunk_id in ranked_ids:
                    chunk = chunk_map[chunk_id]
                    if chunk.textbook_id not in seen_books:
                        selected.append(chunk_id)
                        seen_books.add(chunk.textbook_id)
                    if len(selected) >= top_k:
                        break
        for chunk_id in ranked_ids:
            if chunk_id not in selected:
                selected.append(chunk_id)
            if len(selected) >= top_k:
                break

        results = []
        for rank, chunk_id in enumerate(selected):
            chunk = chunk_map[chunk_id]
            results.append({
                "id": chunk.id,
                "content": chunk.content,
                "textbook_id": chunk.textbook_id,
                "textbook": chunk.textbook_title,
                "chapter": chunk.chapter_title,
                "section_path": _section_labels(chunk),
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "score": fused_scores[chunk_id],
                "retrievers": sorted(retrievers[chunk_id]),
                "raw_scores": raw_scores[chunk_id],
                "rank": rank + 1,
            })
        return {
            "results": results,
            "trace": {
                "course_id": course_id,
                "mode": mode,
                "scoped_chunks": len(chunks),
                "vector_used": vector_used,
                "graph_expansions": len(graph_ids),
                "query_anchors": query_features["anchors"],
                "requested_textbook_ids": query_features["requested_books"],
                "retrievers": ["bm25"] + (["vector"] if vector_used else []) + (["graph"] if graph_used else []),
            },
        }
    finally:
        db.close()
