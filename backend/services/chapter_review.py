"""Apply page corrections without silently invalidating existing teaching evidence."""
from __future__ import annotations

import hashlib
from fastapi import HTTPException
from backend.database import Chapter, Chunk, Job, KnowledgeNode, RagIndexState, TextbookPage


def range_capability(db, book):
    if book.format != "pdf":
        return False, "文本教材没有 PDF 物理页码，可核对标题和层级。"
    if book.parse_status != "completed" or book.graph_status == "processing":
        return False, "请先等待教材处理完成。"
    if db.query(KnowledgeNode.id).filter(KnowledgeNode.textbook_id == book.id).first():
        return False, "已有知识点引用这些页码。为保护旧引用，此处仅修改标题和层级；请在教材副本中重新解析后调整范围。"
    jobs = db.query(Job).filter(Job.type.in_(("course_agent", "teaching_board", "parse", "extract_graph"))).all()
    for job in jobs:
        payload = job.payload or {}
        references = payload.get("textbook_ids") or []
        if book.id in references or (payload.get("textbook_id") == book.id and job.status in {"pending", "processing"}):
            return False, "教材已有备课材料引用或正在处理。请保留当前版本，在教材副本中修正页码。"
    if not db.query(TextbookPage.id).filter(TextbookPage.textbook_id == book.id).first():
        return False, "缺少逐页正文，无法同步修正引用位置。"
    return True, "页码修改会按所选 PDF 整页重建相关章节正文与检索材料；请对照原页确认边界。"


def apply_structure(db, book, items, confirmed):
    chapters = db.query(Chapter).filter(Chapter.textbook_id == book.id).all()
    by_id = {chapter.id: chapter for chapter in chapters}
    ids = [item.id for item in items]
    if not ids or len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise HTTPException(400, "请提交本教材完整且不重复的章节列表")
    ordered = sorted(items, key=lambda item: item.order_index)
    if len({item.order_index for item in ordered}) != len(ordered):
        raise HTTPException(400, "章节顺序不能重复")
    changed = []
    ranges = {}
    parents = []
    previous_start = 0
    for item in ordered:
        chapter = by_id[item.id]
        if not item.title.strip():
            raise HTTPException(400, "章节标题不能为空")
        start = item.page_start if item.page_start is not None else chapter.page_start
        end = item.page_end if item.page_end is not None else chapter.page_end
        if not 1 <= start <= end <= (book.total_pages or end):
            raise HTTPException(400, "页码须在教材范围内，且起始页不能晚于结束页")
        if start < previous_start:
            raise HTTPException(400, "章节页码须按目录顺序排列")
        previous_start = start
        while parents and parents[-1].level >= item.level:
            parents.pop()
        if (parents and item.level > parents[-1].level + 1) or (not parents and item.level != 1):
            raise HTTPException(400, "章节层级不能跳级")
        expected_parent = parents[-1].id if parents else ""
        if item.parent_id != expected_parent:
            raise HTTPException(400, "父章节与目录层级不一致，请重新加载后核对")
        if parents:
            parent_start, parent_end = ranges[parents[-1].id]
            if start < parent_start or end > parent_end:
                raise HTTPException(400, "子章节页码必须在父章节范围内")
        ranges[item.id] = start, end
        parents.append(item)
        if (start, end) != (chapter.page_start, chapter.page_end):
            changed.append(chapter)
    if changed:
        allowed, reason = range_capability(db, book)
        if not allowed:
            raise HTTPException(409, reason)
    for item in ordered:
        chapter = by_id[item.id]
        previous_title = chapter.title
        chapter.title, chapter.order_index = item.title.strip(), item.order_index
        chapter.parent_id, chapter.level = item.parent_id, item.level
        chapter.review_status = "confirmed" if confirmed else "unreviewed"
        if chapter not in changed:
            # Keep original paragraph offsets when only a title or level changes.
            for chunk in db.query(Chunk).filter(Chunk.chapter_id == chapter.id).all():
                old_title = chunk.chapter_title
                chunk.chapter_title = chapter.title
                chunk.section_path = [chapter.title if value == old_title else value for value in (chunk.section_path or [])]
            # Nodes do not store chapter_id. A source chunk is the direct link;
            # matching only chapter_title could rename an unrelated same-title
            # chapter or a legacy node whose location is unknown.
            if previous_title != chapter.title:
                chapter_chunks = db.query(Chunk.id).filter(Chunk.chapter_id == chapter.id, Chunk.textbook_id == book.id)
                for node in db.query(KnowledgeNode).filter(
                    KnowledgeNode.textbook_id == book.id,
                    KnowledgeNode.source_chunk_id.in_(chapter_chunks),
                ).all():
                    node.chapter_title = chapter.title
            continue
        start, end = ranges[chapter.id]
        pages = db.query(TextbookPage).filter(TextbookPage.textbook_id == book.id, TextbookPage.page_number.between(start, end)).order_by(TextbookPage.page_number).all()
        if len(pages) != end - start + 1:
            raise HTTPException(409, "所选范围缺少页面正文，未保存修改")
        parts, spans, offset = [], [], 0
        for page in pages:
            content = (page.text or "").strip()
            if not content:
                continue
            if parts:
                offset += 2
            parts.append(content)
            spans.append({"page_number": page.page_number, "chapter_start": offset, "chapter_end": offset + len(content)})
            offset += len(content)
        if not parts:
            raise HTTPException(409, "所选范围没有可读正文，未保存修改")
        chapter.content, chapter.source_spans = "\n\n".join(parts), spans
        chapter.char_count = len(chapter.content)
        chapter.page_start, chapter.page_end = start, end
        chapter.extraction_status = "pending"
        db.query(Chunk).filter(Chunk.chapter_id == chapter.id).delete(synchronize_session=False)
        from backend.services.chunker import _split_semantic_text_with_offsets, _pages_for_range, CHUNK_SIZE, CHUNK_OVERLAP
        for index, (left, right, content, path) in enumerate(_split_semantic_text_with_offsets(chapter.content, CHUNK_SIZE, CHUNK_OVERLAP, chapter_title=chapter.title, textbook_title=book.title)):
            first, last = _pages_for_range(spans, left, right, start, end)
            db.add(Chunk(id=f"{chapter.id}_chunk_{index:04d}", textbook_id=book.id, chapter_id=chapter.id, textbook_title=book.title, chapter_title=chapter.title, content=content, char_count=len(content), chunk_index=index, page_start=first, page_end=last, section_path=path, content_hash=hashlib.sha256(content.encode()).hexdigest()))
    state = db.get(RagIndexState, book.course_id)
    if state:
        state.status = "stale"
    book.structure_status = "confirmed" if confirmed else "review"
    return len(chapters)
