import json
import re
import time
import uuid
from typing import Callable, Optional
from backend.config import LLM_MODEL, LLM_API_KEY
from backend.database import (
    SessionLocal,
    Chapter,
    Chunk,
    KnowledgeNode,
    KnowledgeEdge,
    RelationEvidence,
    AlignmentCandidate,
    Textbook,
    IntegrationDecision,
)
from backend.services.quality_gate import (
    GENERIC_CONCEPT_TYPES,
    ALLOWED_RELATION_TYPES,
    validate_node_candidate,
    validate_edge_candidate,
    find_source_chunk,
    is_front_matter_title,
)
from backend.services.model_runtime import record_model_failure, record_model_success
from backend.services.llm_client import create_openai_client

VALID_RELATION_TYPES = ALLOWED_RELATION_TYPES
VALID_CATEGORIES = GENERIC_CONCEPT_TYPES

# ── Topic extraction prompt ──
TOPIC_PROMPT = """你是教材结构化 Agent。请只依据给定章节原文，抽取本章的大类知识结构，适用于任意学科。

要求：
1. 输出纯 JSON（不要 Markdown 代码块）。
2. 先给出 1 个 chapter_topic（本章核心主题）。
3. 再给出 3-8 个 section_topic（本章下的主要知识大类）。
4. chapter_topic 和每个 section_topic 都必须给出 source_quote，且必须是原文中的连续句子。
5. 不要抽取细碎事实、孤立数字、目录项。

输出格式：
{{"chapter_topic": {{"name": "...", "definition": "...", "learning_objective": "...", "source_quote": "..."}}, "section_topics": [{{"local_id": "s1", "name": "...", "scope": "...", "source_quote": "..."}}], "edges": [{{"source": "chapter_topic", "target": "s1", "relation_type": "contains", "description": "..."}}]}}

教材：{textbook}
章节：{chapter}
原文内容（前6000字）：
{content}"""

# ── Concept extraction prompt ──
CONCEPT_PROMPT = """你是教材知识点抽取 Agent。请只在指定的 section_topic 范围内从原文中抽取核心知识点，适用于任意学科。

关系类型只能为：prerequisite、causes、contrasts_with、equivalent_to、applies_to、supports、conflicts_with、related_to、contains、part_of、example_of。

数量：当前 section 至少 3 个、最多 8 个知识点。每个知识点必须有 source_quote。每个核心知识点至少建立 1 条关系。

输出纯 JSON：
{{"nodes": [{{"local_id": "n1", "name": "...", "aliases": [], "definition": "...", "concept_type": "concept|definition|principle|process|formula|method|example|condition|exception", "importance": 3, "granularity": "core_concept", "source_quote": "...", "quality_reason": "..."}}], "edges": [{{"source": "n1", "target": "n2", "relation_type": "prerequisite|causes|contrasts_with|equivalent_to|applies_to|supports|conflicts_with|related_to|contains|part_of|example_of", "description": "...", "source_quote": "所有语义关系必须提供原文依据"}}], "parent_edges": [{{"source": "section_id", "target": "n1", "relation_type": "contains", "description": "..."}}]}}

教材：{textbook}  章节：{chapter}
当前大类：{section_name}（范围：{section_scope}）
原文内容：
{content}"""


ProgressCallback = Callable[[int, int, str], None]
_llm_retry_after = 0.0


def extract_textbook_graph(
    textbook_id: str,
    force: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
) -> dict:
    db = SessionLocal()
    # We commit after each small extraction unit. Keeping ORM values available
    # avoids reloading them while the next (potentially slow) model call runs.
    db.expire_on_commit = False
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if not book:
            raise ValueError(f"Textbook {textbook_id} not found")

        if force:
            _clean_textbook_graph(db, textbook_id)
            db.commit()

        existing_nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.textbook_id == textbook_id
        ).count()
        if existing_nodes > 0 and book.graph_status in ("completed", "review"):
            return {"textbook_id": textbook_id, "nodes": existing_nodes,
                    "edges": 0, "message": "Already extracted (use force=true to re-extract)"}

        # Pre-extraction check
        chapter_count = db.query(Chapter).filter(Chapter.textbook_id == textbook_id).count()
        chunk_count = db.query(Chunk).filter(Chunk.textbook_id == textbook_id).count()
        if chapter_count == 0:
            return {"textbook_id": textbook_id, "nodes": 0, "edges": 0,
                    "error": "请先解析教材并生成章节，再提取知识图谱。当前章节数为0。"}
        if chunk_count == 0:
            return {"textbook_id": textbook_id, "nodes": 0, "edges": 0,
                    "error": "请先生成教材chunk，再提取知识图谱。当前chunk数为0。"}

        if book.structure_status not in ("confirmed", "legacy_confirmed"):
            return {
                "textbook_id": textbook_id,
                "nodes": 0,
                "edges": 0,
                "error": "请先确认教材章节结构，再提取知识图谱。",
                "structure_status": book.structure_status,
            }

        book.graph_status = "processing"
        db.commit()
        if progress_callback:
            progress_callback(3, 100, "正在准备教材章节")

        stats = _layered_extract(db, book, progress_callback=progress_callback)
        book.graph_status = "review" if stats["fallback_calls"] or stats["rejected_nodes"] else "completed"
        db.commit()
        return {"textbook_id": textbook_id, **stats, "graph_status": book.graph_status}
    finally:
        db.close()


def _clean_textbook_graph(db, textbook_id: str):
    """Remove all graph data for a textbook before re-extraction."""
    node_ids = [r[0] for r in db.query(KnowledgeNode.id).filter(
        KnowledgeNode.textbook_id == textbook_id).all()]
    edge_ids = db.query(KnowledgeEdge.id).filter(
        (KnowledgeEdge.source.in_(node_ids)) |
        (KnowledgeEdge.target.in_(node_ids))
    )
    db.query(RelationEvidence).filter(
        RelationEvidence.edge_id.in_(edge_ids)
    ).delete(synchronize_session=False)
    db.query(AlignmentCandidate).filter(
        (AlignmentCandidate.source_node_id.in_(node_ids)) |
        (AlignmentCandidate.target_node_id.in_(node_ids))
    ).delete(synchronize_session=False)
    db.query(KnowledgeEdge).filter(KnowledgeEdge.id.in_(edge_ids)).delete(synchronize_session=False)
    db.query(KnowledgeNode).filter(
        KnowledgeNode.textbook_id == textbook_id).delete(synchronize_session=False)
    db.query(Chapter).filter(Chapter.textbook_id == textbook_id).update(
        {Chapter.extraction_status: "pending"}, synchronize_session=False
    )
    db.query(IntegrationDecision).filter(
        IntegrationDecision.affected_nodes.contains([textbook_id])
    ).delete(synchronize_session=False)
    db.flush()


def _clean_chapter_graph(db, textbook_id: str, chapter_title: str):
    """Discard only an interrupted chapter transaction before regenerating it."""
    node_ids = [row[0] for row in db.query(KnowledgeNode.id).filter(
        KnowledgeNode.textbook_id == textbook_id,
        KnowledgeNode.chapter_title == chapter_title,
    ).all()]
    if not node_ids:
        return
    edge_ids = [row[0] for row in db.query(KnowledgeEdge.id).filter(
        (KnowledgeEdge.source.in_(node_ids)) | (KnowledgeEdge.target.in_(node_ids))
    ).all()]
    if edge_ids:
        db.query(RelationEvidence).filter(RelationEvidence.edge_id.in_(edge_ids)).delete(
            synchronize_session=False
        )
        db.query(KnowledgeEdge).filter(KnowledgeEdge.id.in_(edge_ids)).delete(
            synchronize_session=False
        )
    db.query(AlignmentCandidate).filter(
        (AlignmentCandidate.source_node_id.in_(node_ids)) |
        (AlignmentCandidate.target_node_id.in_(node_ids))
    ).delete(synchronize_session=False)
    db.query(KnowledgeNode).filter(KnowledgeNode.id.in_(node_ids)).delete(
        synchronize_session=False
    )
    db.flush()


def _layered_extract(db, book, progress_callback: Optional[ProgressCallback] = None) -> dict:
    """Phase 1: topic extraction → Phase 2: concept extraction per section."""
    chapters = db.query(Chapter).filter(Chapter.textbook_id == book.id).all()
    stats = {
        "nodes": 0,
        "edges": 0,
        "rejected_nodes": 0,
        "rejected_edges": 0,
        "fallback_calls": 0,
        "verified_evidence": 0,
        "skipped_front_matter": 0,
    }

    front_matter = [chapter for chapter in chapters if is_front_matter_title(chapter.title)]
    for chapter in front_matter:
        chapter.extraction_status = "completed"
    if front_matter:
        stats["skipped_front_matter"] = len(front_matter)
        db.commit()

    eligible_chapters = [
        chapter for chapter in chapters
        if len(chapter.content) >= 200 and not is_front_matter_title(chapter.title)
    ]
    chapter_total = max(len(eligible_chapters), 1)

    for chapter_index, ch in enumerate(eligible_chapters):
        chapter_start = 5 + round((chapter_index / chapter_total) * 90)
        chapter_end = 5 + round(((chapter_index + 1) / chapter_total) * 90)
        if ch.extraction_status == "completed":
            if progress_callback:
                progress_callback(chapter_end, 100, f"已恢复已完成章节：{ch.title}")
            continue
        if ch.extraction_status == "processing":
            _clean_chapter_graph(db, book.id, ch.title)
        ch.extraction_status = "processing"
        db.commit()
        if progress_callback:
            progress_callback(
                chapter_start,
                100,
                f"正在分析第 {chapter_index + 1}/{len(eligible_chapters)} 章：{ch.title}",
            )

        content = ch.content[:6000]
        topics = _call_llm_topic(book.title, ch.title, content)
        if not topics:
            ch.extraction_status = "completed"
            db.commit()
            if progress_callback:
                progress_callback(chapter_end, 100, f"已跳过无法识别的章节：{ch.title}")
            continue
        topic_method = topics.get("_meta", {}).get("method", "llm")
        if topic_method != "llm":
            stats["fallback_calls"] += 1

        ct = topics.get("chapter_topic", {})
        sections = topics.get("section_topics", [])

        # Create chapter_topic node
        ct_id = f"{book.id}_{ch.id}_topic"
        ct_quote = ct.get("source_quote", "")
        ct_quality = validate_node_candidate({
            "name": ct.get("name", ch.title),
            "definition": ct.get("definition", ""),
            "concept_type": "concept",
            "source_quote": ct_quote,
        }, content)
        if not ct_quality.accepted:
            stats["rejected_nodes"] += 1
            continue
        ct_node = KnowledgeNode(
            id=ct_id, name=ct.get("name", ch.title),
            aliases=[], definition=ct.get("definition", ""),
            category="concept", importance=4,
            course_id=book.course_id,
            textbook_id=book.id, textbook_title=book.title,
            chapter_title=ch.title,
            page=ch.page_start, page_start=ch.page_start, page_end=ch.page_end,
            source_paragraph=ct_quote,
            source_sentences=[ct_quote] if ct_quote else [],
            granularity="chapter_topic",
            learning_objective=ct.get("learning_objective", ""),
            quality_score=ct_quality.score, confidence=ct_quality.score,
            quality_flags=ct_quality.flags,
            source_type="llm" if topic_method == "llm" else "rule",
            created_by="topic_extraction",
            review_status=_review_status(topic_method, ct_quality),
            evidence_status="verified" if ct_quality.evidence_verified else "invalid",
            model_version=LLM_MODEL if topic_method == "llm" else "",
            prompt_version="topic_v2_generic",
        )
        db.merge(ct_node)
        stats["nodes"] += 1
        stats["verified_evidence"] += int(ct_quality.evidence_verified)

        # Create section_topic nodes
        section_nodes = []
        for s in sections[:8]:  # max 8 sections per chapter
            section_quality = validate_node_candidate({
                "name": s.get("name", ""),
                "definition": s.get("scope", ""),
                "concept_type": "concept",
                "source_quote": s.get("source_quote", ""),
            }, content)
            if not section_quality.accepted:
                stats["rejected_nodes"] += 1
                continue
            sid = f"{book.id}_{ch.id}_sec_{s.get('local_id', '')}"
            sn = KnowledgeNode(
                id=sid, name=s.get("name", ""),
                aliases=[], definition=s.get("scope", ""),
                category="concept", importance=3,
                course_id=book.course_id,
                textbook_id=book.id, textbook_title=book.title,
                chapter_title=ch.title,
                page=ch.page_start, page_start=ch.page_start, page_end=ch.page_end,
                source_paragraph=s.get("source_quote", ""),
                source_sentences=[s.get("source_quote", "")],
                granularity="section_topic",
                learning_objective=s.get("scope", ""),
                quality_score=section_quality.score, confidence=section_quality.score,
                quality_flags=section_quality.flags,
                source_type="llm" if topic_method == "llm" else "rule",
                created_by="topic_extraction",
                review_status=_review_status(topic_method, section_quality),
                evidence_status="verified" if section_quality.evidence_verified else "invalid",
                model_version=LLM_MODEL if topic_method == "llm" else "",
                prompt_version="topic_v2_generic",
            )
            db.merge(sn)
            stats["nodes"] += 1
            stats["verified_evidence"] += int(section_quality.evidence_verified)
            section_nodes.append({
                "id": sid,
                "name": sn.name,
                "definition": sn.definition or "",
                "source_quote": sn.source_paragraph or "",
            })

            # Chapter contains section
            db.add(KnowledgeEdge(
                id=f"edge_{uuid.uuid4().hex[:10]}",
                course_id=book.course_id,
                source=ct_id, target=sid,
                relation_type="contains",
                description=f"「{ch.title}」包含「{s.get('name', '')}」",
                confidence=0.95,
                created_by="topic_extraction",
                review_status="auto_verified",
                prompt_version="topic_v2_generic",
            ))
            stats["edges"] += 1

        # Release the SQLite writer lock before the slower concept model calls.
        # This is critical: job updates and other actions must remain writable.
        db.commit()
        topic_progress = chapter_start + max(1, round((chapter_end - chapter_start) * 0.2))
        if progress_callback:
            progress_callback(topic_progress, 100, f"已识别章节结构：{ch.title}")

        # Phase 2: Extract core concepts per section
        chunks = db.query(Chunk).filter(Chunk.chapter_id == ch.id).order_by(Chunk.chunk_index).all()

        chapter_concept_names = {_concept_identity(item["name"]) for item in section_nodes}
        for section_index, sn in enumerate(section_nodes):
            # Gather relevant content for this section
            section_content, relevant_chunks = _gather_section_content(
                chunks, sn["name"], sn["definition"], sn["source_quote"]
            )
            if len(section_content) < 100:
                # Never reuse the start of a chapter for every unmatched
                # section. It fabricates duplicate child concepts under
                # unrelated headings.
                if progress_callback:
                    progress_callback(
                        topic_progress,
                        100,
                        f"已保留主题，未找到可靠概念范围：{ch.title} · {sn['name']}",
                    )
                continue

            concepts = _call_llm_concept(
                book.title, ch.title,
                sn["name"], sn["definition"],
                section_content[:4000]
            )
            if not concepts:
                if progress_callback:
                    section_fraction = (section_index + 1) / max(len(section_nodes), 1)
                    progress_callback(
                        topic_progress + round((chapter_end - topic_progress) * section_fraction),
                        100,
                        f"已跳过无法识别的知识组：{sn['name']}",
                    )
                continue
            concept_method = concepts.get("_meta", {}).get("method", "llm")
            if concept_method != "llm":
                stats["fallback_calls"] += 1

            local_to_id = {}
            for c in concepts.get("nodes", [])[:8]:  # max 8 per section
                concept_identity = _concept_identity(c.get("name", ""))
                if not concept_identity or concept_identity in chapter_concept_names:
                    continue
                quality = validate_node_candidate(c, section_content)
                if not quality.accepted:
                    stats["rejected_nodes"] += 1
                    continue
                cid = f"{book.id}_{ch.id}_c_{uuid.uuid4().hex[:6]}"
                source_chunk = find_source_chunk(c.get("source_quote", ""), relevant_chunks)
                concept_type = c.get("concept_type", "concept")
                node = KnowledgeNode(
                    id=cid, name=c.get("name", ""),
                    course_id=book.course_id,
                    aliases=c.get("aliases", []),
                    definition=c.get("definition", ""),
                    category=concept_type if concept_type in VALID_CATEGORIES else "concept",
                    importance=c.get("importance", 3),
                    textbook_id=book.id, textbook_title=book.title,
                    chapter_title=ch.title,
                    page=source_chunk.page_start if source_chunk else ch.page_start,
                    page_start=source_chunk.page_start if source_chunk else ch.page_start,
                    page_end=source_chunk.page_end if source_chunk else ch.page_end,
                    source_chunk_id=source_chunk.id if source_chunk else "",
                    source_paragraph=c.get("source_quote", ""),
                    source_sentences=[c.get("source_quote", "")] if c.get("source_quote") else [],
                    granularity="core_concept",
                    learning_objective=c.get("quality_reason", ""),
                    quality_score=quality.score,
                    confidence=quality.score,
                    quality_flags=quality.flags,
                    source_type="llm" if concept_method == "llm" else "rule",
                    created_by="concept_extraction",
                    review_status=_review_status(concept_method, quality),
                    evidence_status="verified" if quality.evidence_verified else "invalid",
                    model_version=LLM_MODEL if concept_method == "llm" else "",
                    prompt_version="concept_v2_generic",
                )
                db.merge(node)
                stats["nodes"] += 1
                stats["verified_evidence"] += int(quality.evidence_verified)
                chapter_concept_names.add(concept_identity)
                local_to_id[c.get("local_id", "")] = cid

                # Section contains concept
                db.add(KnowledgeEdge(
                    id=f"edge_{uuid.uuid4().hex[:10]}",
                    course_id=book.course_id,
                    source=sn["id"], target=cid,
                    relation_type="contains",
                    description=f"「{sn['name']}」包含知识点「{c.get('name', '')}」",
                    confidence=0.90,
                    created_by="concept_extraction",
                    review_status="auto_verified",
                    prompt_version="concept_v2_generic",
                ))
                stats["edges"] += 1

            # Concept-to-concept edges
            for e in concepts.get("edges", []):
                src = local_to_id.get(e.get("source", ""))
                tgt = local_to_id.get(e.get("target", ""))
                rt = e.get("relation_type", "")
                edge_quality = validate_edge_candidate(
                    e,
                    section_content,
                    set(local_to_id.keys()),
                )
                if src and tgt and rt in VALID_RELATION_TYPES and edge_quality.accepted:
                    edge_id = f"edge_{uuid.uuid4().hex[:10]}"
                    db.add(KnowledgeEdge(
                        id=edge_id,
                        course_id=book.course_id,
                        source=src, target=tgt,
                        relation_type=rt,
                        description=e.get("description", ""),
                        source_quote=e.get("source_quote", ""),
                        confidence=min(float(e.get("confidence", 0.7)), edge_quality.score),
                        created_by="concept_extraction",
                        review_status="auto_verified" if edge_quality.evidence_verified else "needs_review",
                        model_version=LLM_MODEL if concept_method == "llm" else "",
                        prompt_version="concept_v2_generic",
                    ))
                    stats["edges"] += 1
                    if e.get("source_quote"):
                        evidence_chunk = find_source_chunk(e.get("source_quote", ""), relevant_chunks)
                        if evidence_chunk:
                            db.add(RelationEvidence(
                                id=f"evidence_{uuid.uuid4().hex[:12]}",
                                edge_id=edge_id,
                                textbook_id=book.id,
                                chunk_id=evidence_chunk.id,
                                page_number=evidence_chunk.page_start,
                                source_quote=e.get("source_quote", ""),
                                evidence_role="supports",
                                quote_verified=edge_quality.evidence_verified,
                            ))
                else:
                    stats["rejected_edges"] += 1

            # Each section is an independent short transaction. Model calls for
            # later sections therefore never inherit a long-lived writer lock.
            db.commit()
            if progress_callback:
                section_fraction = (section_index + 1) / max(len(section_nodes), 1)
                section_progress = topic_progress + round(
                    (chapter_end - topic_progress) * section_fraction
                )
                progress_callback(
                    section_progress,
                    100,
                    f"已完成 {ch.title} · {sn['name']}",
                )

        # Cross-section relations within chapter
        db.commit()
        ch.extraction_status = "completed"
        db.commit()
        if progress_callback and not section_nodes:
            progress_callback(chapter_end, 100, f"已完成章节：{ch.title}")

    # Do not synthesize semantic relations from category order. Cross-section and
    # cross-textbook links are generated later from evidence-backed candidates.

    # KnowledgeNode is the source-specific concept occurrence. Keep all new graph
    # records inside the textbook's course so later retrieval cannot cross courses.
    db.query(KnowledgeNode).filter(
        KnowledgeNode.textbook_id == book.id,
    ).update({KnowledgeNode.course_id: book.course_id}, synchronize_session=False)
    node_ids = db.query(KnowledgeNode.id).filter(KnowledgeNode.textbook_id == book.id)
    db.query(KnowledgeEdge).filter(
        (KnowledgeEdge.source.in_(node_ids)) | (KnowledgeEdge.target.in_(node_ids))
    ).update({KnowledgeEdge.course_id: book.course_id}, synchronize_session=False)

    # The progress callback writes through a separate SQLAlchemy session.
    # Release this session's SQLite writer lock before reporting 97%, or the
    # otherwise successful extraction is incorrectly marked as failed.
    db.commit()

    if progress_callback:
        progress_callback(97, 100, "正在整理知识树连接")
    return stats


def _gather_section_content(chunks, section_name: str, section_scope: str, source_quote: str = ""):
    """Gather a contiguous span anchored by this section's verified evidence."""
    def compact(value: str) -> str:
        return re.sub(r"\s+", "", value or "")

    quote_anchor = compact(source_quote)[:28]
    name_anchor = compact(section_name)
    start_index = None
    for index, chunk in enumerate(chunks):
        haystack = compact(chunk.content)
        if (quote_anchor and quote_anchor in haystack) or (name_anchor and name_anchor in haystack):
            start_index = index
            break
    if start_index is None:
        return "", []

    relevant_chunks = []
    relevant_text = []
    for ck in chunks[start_index:start_index + 4]:
        relevant_chunks.append(ck)
        relevant_text.append(ck.content)
        if sum(len(item) for item in relevant_text) >= 4000:
            break
    return "\n".join(relevant_text), relevant_chunks


def _call_llm_topic(book_title: str, chapter_title: str, content: str) -> dict | None:
    """Call LLM for chapter/section topic extraction."""
    global _llm_retry_after
    try:
        if time.monotonic() < _llm_retry_after:
            raise RuntimeError("LLM is temporarily unavailable for this extraction run")
        if not LLM_API_KEY:
            raise RuntimeError("LLM API key is not configured")
        client = create_openai_client(timeout=60)
        prompt = TOPIC_PROMPT.format(textbook=book_title, chapter=chapter_title, content=content[:6000])
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=2000,
        )
        data = _parse_json_safely(resp.choices[0].message.content)
        if not data.get("chapter_topic"):
            raise ValueError("LLM response is missing chapter_topic")
        data["_meta"] = {"method": "llm", "error": ""}
        record_model_success()
        return data
    except Exception as exc:
        record_model_failure(exc)
        if "402" in str(exc) or "balance" in str(exc).lower():
            _llm_retry_after = time.monotonic() + 90
        data = _rule_topic(chapter_title, content)
        data["_meta"] = {
            "method": "rule_fallback",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }
        return data


def _call_llm_concept(book_title: str, chapter_title: str,
                      section_name: str, section_scope: str,
                      content: str) -> dict | None:
    """Call LLM for concept extraction within a section."""
    global _llm_retry_after
    try:
        if time.monotonic() < _llm_retry_after:
            raise RuntimeError("LLM is temporarily unavailable for this extraction run")
        if not LLM_API_KEY:
            raise RuntimeError("LLM API key is not configured")
        client = create_openai_client(timeout=60)
        prompt = CONCEPT_PROMPT.format(
            textbook=book_title, chapter=chapter_title,
            section_name=section_name, section_scope=section_scope,
            content=content[:4000],
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=2500,
        )
        data = _parse_json_safely(resp.choices[0].message.content)
        if "nodes" not in data:
            raise ValueError("LLM response is missing nodes")
        data["_meta"] = {"method": "llm", "error": ""}
        record_model_success()
        return data
    except Exception as exc:
        record_model_failure(exc)
        if "402" in str(exc) or "balance" in str(exc).lower():
            _llm_retry_after = time.monotonic() + 90
        data = _rule_concepts(content, section_name)
        data["_meta"] = {
            "method": "rule_fallback",
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }
        return data


def _rule_topic(chapter_title: str, content: str) -> dict:
    """Conservative fallback: extract compact, explicit headings with exact evidence."""
    chapter_name = _clean_heading(chapter_title)
    chapter_quote = _first_meaningful_excerpt(content, 240)
    heading_pattern = re.compile(
        r"(?m)^(?:第[一二三四五六七八九十\d]+节\s*[^\n]{2,32}|"
        r"[一二三四五六七八九十]+[、．.)]\s*[^\n]{2,32})$"
    )
    sections = []
    seen = set()
    for match in heading_pattern.finditer(content):
        name = _clean_heading(match.group(0))
        if not 2 <= len(name) <= 24 or name in seen or re.search(r"(?:\.{4,}|…{2,})", match.group(0)):
            continue
        seen.add(name)
        evidence = _excerpt_from(content, match.start(), 220)
        scope = _scope_after_heading(evidence, name)
        sections.append({
            "local_id": f"s{len(sections)+1}",
            "name": name,
            "scope": scope,
            "source_quote": evidence,
        })
        if len(sections) >= 8:
            break
    return {
        "chapter_topic": {
            "name": chapter_name,
            "definition": chapter_quote,
            "learning_objective": f"理解{chapter_name}的核心概念、机制与教材依据",
            "source_quote": chapter_quote,
        },
        "section_topics": sections,
        "edges": [],
    }


def _rule_concepts(content: str, section_name: str) -> dict:
    """Extract only explicit definition sentences; never turn arbitrary prose into concepts."""
    nodes = []
    seen = set()

    def append_node(name_value: str, quote_value: str):
        name = _clean_heading(name_value)
        name = re.split(r"[，,；;：:]", name, maxsplit=1)[0].strip()
        quote = quote_value.lstrip("。！？\n").strip()
        identity = _concept_identity(name)
        if (
            not 2 <= len(identity) <= 18
            or identity in seen
            or len(quote) < 12
            or not re.search(r"[\u4e00-\u9fff]", identity)
            or re.search(r"(?:不能|不应|不可)称为", quote)
            or re.search(r"[（(]图\s*\d", name)
        ):
            return
        seen.add(identity)
        nodes.append({
            "local_id": f"n{len(nodes)+1}",
            "name": name,
            "aliases": [],
            "definition": quote,
            "concept_type": "definition",
            "importance": 3,
            "granularity": "core_concept",
            "source_quote": quote,
            "quality_reason": f"教材在“{section_name}”中给出显式定义",
        })

    # “X 是指 Y” defines the term before the marker. Disallow commas in X so
    # an entire sentence prefix can never become a node name.
    before_pattern = re.compile(
        r"(?:^|[。！？\n])(?P<name>[^，,。！？\n]{2,26}?)(?:是指|定义为)"
        r"(?P<body>[^。！？\n]{6,120})[。！？]"
    )
    for match in before_pattern.finditer(content):
        append_node(match.group("name"), match.group(0))
        if len(nodes) >= 4:
            break

    # “……称为 X” defines the term after the marker. The previous implementation
    # incorrectly named the sentence fragment before “称为”, producing entries
    # such as “应器所致”.
    after_pattern = re.compile(
        r"(?:^|[。！？\n])(?P<body>[^。！？\n]{6,120}?)(?:称为|称作)"
        r"(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()\-\s]{2,32}?)"
        r"(?=或|[，,。！？；;])"
    )
    for match in after_pattern.finditer(content):
        segment = content[match.start():].lstrip("。！？\n")
        sentence_end = re.search(r"[。！？；;]", segment[:240])
        quote = segment[:sentence_end.end()] if sentence_end else segment[:220]
        append_node(match.group("name"), quote)
        if len(nodes) >= 4:
            break

    return {"nodes": nodes, "edges": [], "parent_edges": []}


def _concept_identity(value: str) -> str:
    name = _clean_heading(value)
    name = re.sub(r"[（(][^）)]{0,80}[）)]", "", name)
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", name).lower()


def _clean_heading(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").replace("|", " ").replace("｜", " ").strip()
    text = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", text)
    text = re.sub(r"^(?:第[一二三四五六七八九十\d]+节|[一二三四五六七八九十]+[、．.)]|\d+[、．.)])\s*", "", text)
    text = re.sub(r"^[（(]?\d+[）)]\s*", "", text)
    text = re.split(r"(?:\.{4,}|…{2,}|·{4,})", text, maxsplit=1)[0]
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return text.strip(" ：:，,。；;、-—")


def _excerpt_from(content: str, start: int, max_chars: int) -> str:
    value = (content or "")[start:start + max_chars].strip()
    sentence = re.search(r"^.{12,}?[。！？]", value, re.DOTALL)
    return (sentence.group(0) if sentence else value).strip()


def _first_meaningful_excerpt(content: str, max_chars: int) -> str:
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    for line in lines:
        if len(line) >= 20 and not re.search(r"(?:\.{4,}|…{2,})", line):
            return _excerpt_from(content, content.find(line), max_chars)
    return (content or "")[:max_chars].strip()


def _scope_after_heading(evidence: str, heading: str) -> str:
    value = re.sub(r"^.*?" + re.escape(heading), "", evidence, count=1).strip(" ：:，,。；;、-—\n")
    return value[:180].strip() or f"教材中关于{heading}的核心内容"


def _review_status(method: str, quality) -> str:
    if method != "llm" or not quality.evidence_verified or quality.score < 0.75:
        return "needs_review"
    return "auto_verified"


def _parse_json_safely(text: str) -> dict:
    """Parse JSON from LLM output."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}
