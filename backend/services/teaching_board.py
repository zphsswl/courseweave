"""Teacher-owned lesson comparison boards, stored without a worker or new schema.

Selections refer to original chunks; source text is always reloaded server-side.
Confirmed connections describe this lesson only and never change the course graph.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from urllib.parse import quote
import uuid

from backend.database import Chunk, Course, Job, Textbook
from backend.services.source_titles import passage_concept_metadata


BOARD_TYPE = "teaching_board"
RELATION_TYPES = {
    "equivalent_to", "extends", "prerequisite", "contrasts_with", "conflicts_with", "related_to",
}
MAX_BOOKS = 12
MAX_SELECTIONS = 80
MAX_CONNECTIONS = 120
MAX_QUOTE_CHARS = 1400


class BoardConflict(Exception):
    """The board changed, is active, or references source material that changed."""


def _text(value, label, maximum, required=False):
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label}须为文本")
    value = value.strip()
    if len(value) > maximum or (required and not value):
        raise ValueError(f"{label}须为 {'1 至 ' if required else '不超过 '}{maximum} 字")
    return value


def _course_exists(db, course_id):
    if not db.query(Course.id).filter(Course.id == course_id).first():
        raise LookupError("知识空间不存在")


def _books(db, course_id, selected):
    _course_exists(db, course_id)
    if not isinstance(selected, list) or not 1 <= len(selected) <= MAX_BOOKS:
        raise ValueError(f"请选择 1 至 {MAX_BOOKS} 本教材")
    selected = list(dict.fromkeys(_text(book_id, "教材编号", 160, required=True) for book_id in selected))
    rows = db.query(Textbook).filter(Textbook.course_id == course_id, Textbook.id.in_(selected)).all()
    mapping = {row.id: row for row in rows}
    if set(mapping) != set(selected):
        raise ValueError("部分教材不存在或不属于当前知识空间")
    return selected, mapping


def _load_job(db, course_id, board_id):
    job = db.query(Job).filter(Job.id == board_id, Job.course_id == course_id, Job.type == BOARD_TYPE).first()
    if job is None:
        raise LookupError("本课对照板不存在")
    return job


def _normalize_payload(db, course_id, payload):
    if not isinstance(payload, dict):
        raise ValueError("对照板内容格式无效")
    topic = _text(payload.get("topic"), "课题", 160, required=True)
    selected, book_map = _books(db, course_id, payload.get("textbook_ids"))
    selections = payload.get("selections", [])
    connections = payload.get("connections", [])
    if not isinstance(selections, list) or len(selections) > MAX_SELECTIONS:
        raise ValueError(f"每课最多选择 {MAX_SELECTIONS} 条原文材料")
    if not isinstance(connections, list) or len(connections) > MAX_CONNECTIONS:
        raise ValueError(f"每课最多保存 {MAX_CONNECTIONS} 条教学关系")

    normalized_selections = []
    seen_chunks = set()
    for row in selections:
        if not isinstance(row, dict):
            raise ValueError("所选材料格式无效")
        chunk_id = _text(row.get("chunk_id"), "原文编号", 160, required=True)
        if chunk_id in seen_chunks:
            raise ValueError("同一原文材料不能重复选择")
        seen_chunks.add(chunk_id)
        teaching_title = row.get("teaching_title", "")
        if not isinstance(teaching_title, str):
            raise ValueError("讲授标题须为文本")
        normalized_selections.append({
            "chunk_id": chunk_id,
            "teaching_title": _text(teaching_title, "讲授标题", 100),
            "dimension": _text(row.get("dimension", ""), "讲解维度", 60),
            "note": _text(row.get("note", ""), "教师备注", 1000),
        })
    chunks = db.query(Chunk).filter(Chunk.id.in_(seen_chunks), Chunk.textbook_id.in_(selected)).all() if seen_chunks else []
    chunk_map = {chunk.id: chunk for chunk in chunks}
    if set(chunk_map) != seen_chunks:
        raise ValueError("部分原文材料不存在或不属于当前课程所选教材")
    if any(not (chunk.content or "").strip() for chunk in chunks):
        raise ValueError("原文材料为空，不能加入对照板")

    normalized_connections = []
    seen_ids, seen_relations = set(), set()
    symmetric = {"equivalent_to", "contrasts_with", "conflicts_with", "related_to"}
    for row in connections:
        if not isinstance(row, dict):
            raise ValueError("教学关系格式无效")
        connection_id = _text(row.get("id", ""), "关系编号", 160) or f"connection_{uuid.uuid4().hex[:16]}"
        if connection_id in seen_ids:
            raise ValueError("教学关系编号不能重复")
        seen_ids.add(connection_id)
        source = _text(row.get("source_chunk_id"), "起点原文编号", 160, required=True)
        target = _text(row.get("target_chunk_id"), "终点原文编号", 160, required=True)
        if source not in chunk_map or target not in chunk_map:
            raise ValueError("教学关系两端必须都是本课已选材料")
        if chunk_map[source].textbook_id == chunk_map[target].textbook_id:
            raise ValueError("跨教材教学关系必须连接不同教材的材料")
        relation_type = row.get("relation_type")
        if relation_type not in RELATION_TYPES:
            raise ValueError("不支持的教学关系类型")
        status = row.get("status", "draft")
        if status not in {"draft", "confirmed"}:
            raise ValueError("教学关系状态须为 draft 或 confirmed")
        reason = _text(row.get("reason", ""), "关系说明", 1000, required=status == "confirmed")
        pair = tuple(sorted((source, target))) if relation_type in symmetric else (source, target)
        key = (pair, relation_type)
        if key in seen_relations:
            raise ValueError("同一对材料的相同教学关系不能重复")
        seen_relations.add(key)
        normalized_connections.append({
            "id": connection_id, "source_chunk_id": source, "target_chunk_id": target,
            "relation_type": relation_type, "reason": reason, "status": status,
        })
    return {
        "topic": topic, "textbook_ids": selected,
        "selections": normalized_selections, "connections": normalized_connections,
    }, book_map, chunk_map


def _source_selection(selection, chunk, book, topic):
    content = chunk.content or ""
    match = content.lower().find(topic.lower())
    start = max(0, match - 180) if match >= 0 and len(content) > MAX_QUOTE_CHARS else 0
    end = min(len(content), start + MAX_QUOTE_CHARS)
    start = max(0, min(start, end - MAX_QUOTE_CHARS))
    page_start = int(chunk.page_start or 0)
    page_end = max(page_start, int(chunk.page_end or page_start))
    page_image_url = (
        f"/api/textbooks/{quote(book.id, safe='')}/teaching/pages/{page_start}/image"
        if book.format.lower() == "pdf" and page_start > 0 and (not book.total_pages or page_start <= book.total_pages) else None
    )
    path = chunk.section_path if isinstance(chunk.section_path, list) else []
    return {
        **selection, "id": chunk.id, "textbook_id": book.id, "textbook_title": book.title,
        **passage_concept_metadata(chunk, book.id, topic),
        "chapter": chunk.chapter_title or "", "chapter_id": chunk.chapter_id,
        "section_path": path, "title": path[-1] if path else chunk.chapter_title or book.title,
        "page_start": page_start, "page_end": page_end, "quote": content[start:end],
        "quote_start": start, "quote_end": end, "quote_truncated": start > 0 or end < len(content),
        "page_image_url": page_image_url,
    }


def _summary(job):
    payload = job.payload if isinstance(job.payload, dict) else {}
    selections = payload.get("selections") or []
    connections = payload.get("connections") or []
    return {
        "id": job.id, "course_id": job.course_id, "scope": "lesson", "status": job.status,
        "topic": payload.get("topic", ""), "textbook_ids": payload.get("textbook_ids") or [],
        "revision": (job.result or {}).get("revision", 1),
        "selection_count": len(selections), "connection_count": len(connections),
        "confirmed_count": sum(row.get("status") == "confirmed" for row in connections),
        "draft_count": sum(row.get("status", "draft") == "draft" for row in connections),
        "created_at": job.created_at.isoformat() + "Z" if job.created_at else None,
        "updated_at": job.updated_at.isoformat() + "Z" if job.updated_at else None,
    }


def _hydrate(db, job):
    try:
        payload, books, chunks = _normalize_payload(db, job.course_id, job.payload or {})
    except (ValueError, LookupError) as exc:
        raise BoardConflict("本课引用的教材或原文已变化，请重新选择材料后保存") from exc
    selections = [_source_selection(selection, chunks[selection["chunk_id"]], books[chunks[selection["chunk_id"]].textbook_id], payload["topic"]) for selection in payload["selections"]]
    return {
        **_summary(job), "selections": selections, "connections": payload["connections"],
        "selection_counts": dict(Counter(selection["textbook_id"] for selection in selections)),
        "textbooks": [{"id": book_id, "title": books[book_id].title} for book_id in payload["textbook_ids"]],
        "message": "教师为本课整理的材料与教学关系；不代表全课程图谱已审核。",
    }


def list_teaching_boards(db, course_id, limit=30, offset=0):
    _course_exists(db, course_id)
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("对照板列表分页参数无效")
    query = db.query(Job).filter(Job.course_id == course_id, Job.type == BOARD_TYPE)
    total = query.count()
    jobs = query.order_by(Job.updated_at.desc(), Job.id).offset(offset).limit(limit).all()
    selected_ids = {row.get("chunk_id") for job in jobs for row in (job.payload or {}).get("selections", [])}
    book_map = {row.id: row.textbook_id for row in db.query(Chunk).join(Textbook, Textbook.id == Chunk.textbook_id).filter(Chunk.id.in_(selected_ids), Textbook.course_id == course_id).all()} if selected_ids else {}
    items = []
    for job in jobs:
        summary = _summary(job)
        ids = [row.get("chunk_id") for row in (job.payload or {}).get("selections", [])]
        summary["selection_counts"] = dict(Counter(book_map[chunk_id] for chunk_id in ids if chunk_id in book_map))
        summary["missing_source_count"] = sum(chunk_id not in book_map for chunk_id in ids)
        items.append(summary)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_teaching_board(db, course_id, board_id):
    return _hydrate(db, _load_job(db, course_id, board_id))


def get_teaching_sources(db, course_id, textbook_ids, chunk_ids, query):
    """Hydrate legacy draft references without changing any board or revision."""
    query = _text(query, "材料检索主题", 160, required=True)
    selected_books, books = _books(db, course_id, textbook_ids)
    if not isinstance(chunk_ids, list) or not 1 <= len(chunk_ids) <= MAX_SELECTIONS:
        raise ValueError(f"请提供 1 至 {MAX_SELECTIONS} 条原文编号")
    selected_chunks = list(dict.fromkeys(_text(chunk_id, "原文编号", 160, required=True) for chunk_id in chunk_ids))
    rows = db.query(Chunk).filter(Chunk.id.in_(selected_chunks), Chunk.textbook_id.in_(selected_books)).all()
    chunks = {chunk.id: chunk for chunk in rows}
    if set(chunks) != set(selected_chunks):
        raise ValueError("部分原文材料不存在或不属于当前课程所选教材")
    if any(not (chunk.content or "").strip() for chunk in rows):
        raise ValueError("部分原文材料为空，无法补齐来源")
    return {"items": [
        _source_selection(
            {"chunk_id": chunk_id, "teaching_title": "", "dimension": "未归类", "note": ""},
            chunks[chunk_id], books[chunks[chunk_id].textbook_id], query,
        )
        for chunk_id in selected_chunks
    ]}


def create_teaching_board(db, course_id, payload):
    normalized, _, _ = _normalize_payload(db, course_id, payload)
    job = Job(
        id=f"board_{uuid.uuid4().hex[:16]}", course_id=course_id, type=BOARD_TYPE,
        status="completed", stage="saved", progress=1, total=1,
        payload=normalized, result={"revision": 1, "scope": "lesson"}, message="本课对照板已保存",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _hydrate(db, job)


def update_teaching_board(db, course_id, board_id, payload, expected_revision):
    if type(expected_revision) is not int or expected_revision < 1:
        raise ValueError("保存时须提供有效的 expected_revision")
    job = _load_job(db, course_id, board_id)
    if job.status != "completed":
        raise BoardConflict("此对照板正在处理，暂不能编辑")
    if (job.result or {}).get("revision", 1) != expected_revision:
        raise BoardConflict("对照板已在其他位置更新，请重新载入后合并修改")
    normalized, _, _ = _normalize_payload(db, course_id, payload)
    # The revision predicate makes the final write atomic even when two clients
    # both loaded and validated the same prior revision.
    changed = db.query(Job).filter(
        Job.id == board_id, Job.course_id == course_id, Job.type == BOARD_TYPE,
        Job.status == "completed", Job.result["revision"].as_integer() == expected_revision,
    ).update({
        Job.payload: normalized, Job.result: {"revision": expected_revision + 1, "scope": "lesson"},
        Job.updated_at: datetime.utcnow(),
    }, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise BoardConflict("对照板已在其他位置更新，请重新载入后合并修改")
    db.commit()
    db.refresh(job)
    return _hydrate(db, job)


def get_board_agent_context(db, course_id, board_id, selected_chunk_ids=None):
    """Resolve an optional subset against live course-scoped original sources."""
    board = get_teaching_board(db, course_id, board_id)
    selection_map = {row["chunk_id"]: row for row in board["selections"]}
    if selected_chunk_ids is not None and not isinstance(selected_chunk_ids, list):
        raise ValueError("本课所选材料编号格式无效")
    if any(not isinstance(chunk_id, str) for chunk_id in (selected_chunk_ids or [])):
        raise ValueError("本课所选材料编号格式无效")
    requested = list(dict.fromkeys(selected_chunk_ids or selection_map))
    if not requested:
        raise ValueError("本课尚未选择原文材料，不能作为备课依据")
    if any(chunk_id not in selection_map for chunk_id in requested):
        raise ValueError("部分材料不属于当前本课对照板")
    # The board's selection array is the teacher's teaching sequence. A caller
    # can select a subset, but cannot accidentally reorder that sequence merely
    # by sending checkbox IDs in a different order.
    requested_set = set(requested)
    selected = [row["chunk_id"] for row in board["selections"] if row["chunk_id"] in requested_set]
    chunks = {chunk.id: chunk for chunk in db.query(Chunk).filter(Chunk.id.in_(selected)).all()}
    selections = [{**selection_map[chunk_id], "content": chunks[chunk_id].content or ""} for chunk_id in selected]
    selected_set = set(selected)
    return {
        "board_id": board["id"], "board_revision": board["revision"], "revision": board["revision"],
        "topic": board["topic"], "textbook_ids": list(dict.fromkeys(row["textbook_id"] for row in selections)),
        "board_textbook_ids": board["textbook_ids"], "selected_chunk_ids": selected,
        "selections": selections,
        "connections": [row for row in board["connections"] if row["source_chunk_id"] in selected_set and row["target_chunk_id"] in selected_set],
        "scope": "lesson",
    }
