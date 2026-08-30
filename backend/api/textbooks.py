from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from backend.database import (
    SessionLocal,
    Course,
    Textbook,
    TextbookPage,
    Chapter,
    KnowledgeNode,
    KnowledgeEdge,
    RelationEvidence,
    AlignmentCandidate,
    Chunk,
    IntegrationDecision,
    DEFAULT_COURSE_ID,
)
from backend.config import MAX_UPLOAD_SIZE_MB
from pydantic import BaseModel, Field
import uuid
import os
import hashlib

router = APIRouter(prefix="/api/textbooks", tags=["textbooks"])

UPLOAD_DIR = "data/textbooks"


class ChapterStructureItem(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    order_index: int = Field(ge=0)
    parent_id: str = Field(default="", max_length=160)
    level: int = Field(default=1, ge=1, le=6)


class ChapterStructureUpdate(BaseModel):
    chapters: list[ChapterStructureItem]
    confirmed: bool = True

@router.post("/upload")
async def upload_textbook(
    file: UploadFile = File(...),
    course_id: str = Form(DEFAULT_COURSE_ID),
):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    original_filename = os.path.basename(file.filename or "")
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ""
    if ext not in ("pdf", "md", "txt"):
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 PDF, MD, TXT")

    db = SessionLocal()
    try:
        course = db.query(Course).filter(Course.id == course_id).first()
        if course is None:
            raise HTTPException(404, "课程不存在，请先创建课程")
    finally:
        db.close()

    textbook_id = f"book_{uuid.uuid4().hex[:8]}"
    save_path = os.path.join(UPLOAD_DIR, f"{textbook_id}.{ext}")
    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    file_size = 0
    digest = hashlib.sha256()
    try:
        with open(save_path, "xb") as output:
            while chunk := await file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > max_bytes:
                    raise HTTPException(413, f"文件超过 {MAX_UPLOAD_SIZE_MB}MB 限制")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise
    finally:
        await file.close()

    if file_size == 0:
        os.remove(save_path)
        raise HTTPException(400, "不能上传空文件")

    content_hash = digest.hexdigest()
    db = SessionLocal()
    try:
        duplicate = db.query(Textbook).filter(
            Textbook.course_id == course_id,
            Textbook.content_hash == content_hash,
        ).first()
        if duplicate is not None:
            os.remove(save_path)
            raise HTTPException(409, f"该课程已上传相同教材：{duplicate.title}")
    finally:
        db.close()

    title = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
    book = Textbook(
        id=textbook_id,
        course_id=course_id,
        filename=f"{textbook_id}.{ext}",
        original_filename=original_filename,
        title=title,
        format=ext,
        file_size=file_size,
        content_hash=content_hash,
        parse_status="pending"
    )
    db = SessionLocal()
    try:
        db.merge(book)
        db.commit()
    except Exception:
        db.rollback()
        if os.path.exists(save_path):
            os.remove(save_path)
        raise
    finally:
        db.close()

    return {
        "id": textbook_id,
        "textbook_id": textbook_id,
        "course_id": course_id,
        "filename": original_filename,
        "original_filename": original_filename,
        "title": title,
        "format": ext,
        "file_size": file_size,
        "content_hash": content_hash,
        "total_pages": 0,
        "total_chars": 0,
        "chapter_count": 0,
        "parse_status": "pending",
        "graph_status": "pending",
        "index_status": "pending",
        "structure_status": "pending",
        "parse_warnings": [],
    }

@router.get("")
def list_textbooks(course_id: str | None = Query(default=None)):
    db = SessionLocal()
    try:
        query = db.query(Textbook)
        if course_id:
            query = query.filter(Textbook.course_id == course_id)
        books = query.order_by(Textbook.created_at.desc()).all()
        results = []
        for b in books:
            ch_count = db.query(Chapter).filter(Chapter.textbook_id == b.id).count()
            results.append({
                "id": b.id,
                "course_id": b.course_id,
                "filename": b.filename,
                "original_filename": b.original_filename,
                "title": b.title,
                "format": b.format,
                "file_size": b.file_size,
                "total_pages": b.total_pages,
                "total_chars": b.total_chars,
                "chapter_count": ch_count,
                "parse_status": b.parse_status,
                "graph_status": b.graph_status,
                "index_status": b.index_status,
                "structure_status": b.structure_status,
                "parse_warnings": b.parse_warnings or [],
            })
        return results
    finally:
        db.close()

@router.delete("/{textbook_id}")
def delete_textbook(textbook_id: str):
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if not book:
            raise HTTPException(404, "教材不存在")
        course_id = book.course_id
        # Delete relational evidence and review candidates before source nodes.
        node_ids = db.query(KnowledgeNode.id).filter(KnowledgeNode.textbook_id == textbook_id)
        edge_ids = db.query(KnowledgeEdge.id).filter(
            (KnowledgeEdge.source.in_(
                node_ids
            )) |
            (KnowledgeEdge.target.in_(
                node_ids
            ))
        )
        db.query(RelationEvidence).filter(
            RelationEvidence.edge_id.in_(edge_ids)
        ).delete(synchronize_session=False)
        db.query(AlignmentCandidate).filter(
            (AlignmentCandidate.source_node_id.in_(node_ids)) |
            (AlignmentCandidate.target_node_id.in_(node_ids))
        ).delete(synchronize_session=False)
        db.query(KnowledgeEdge).filter(KnowledgeEdge.id.in_(edge_ids)).delete(synchronize_session=False)
        db.query(KnowledgeNode).filter(KnowledgeNode.textbook_id == textbook_id).delete(synchronize_session=False)
        db.query(Chunk).filter(Chunk.textbook_id == textbook_id).delete(synchronize_session=False)
        db.query(Chapter).filter(Chapter.textbook_id == textbook_id).delete(synchronize_session=False)
        db.query(TextbookPage).filter(TextbookPage.textbook_id == textbook_id).delete(synchronize_session=False)
        db.query(IntegrationDecision).filter(
            IntegrationDecision.affected_nodes.contains([textbook_id])
        ).delete(synchronize_session=False)
        db.delete(book)
        db.commit()
        from backend.services.retrieval_service import invalidate_course_cache
        invalidate_course_cache(course_id)
        stored_path = os.path.join(UPLOAD_DIR, book.filename)
        if os.path.exists(stored_path):
            os.remove(stored_path)
        return {"status": "deleted", "id": textbook_id}
    finally:
        db.close()

@router.get("/{textbook_id}/chapters")
def get_chapters(textbook_id: str):
    db = SessionLocal()
    try:
        chapters = db.query(Chapter).filter(
            Chapter.textbook_id == textbook_id
        ).order_by(Chapter.order_index, Chapter.page_start).all()
        return [{
            "id": c.id,
            "title": c.title,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "char_count": c.char_count,
            "order_index": c.order_index,
            "parent_id": c.parent_id,
            "level": c.level,
            "review_status": c.review_status,
        } for c in chapters]
    finally:
        db.close()


@router.patch("/{textbook_id}/chapters")
def update_chapter_structure(textbook_id: str, payload: ChapterStructureUpdate):
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if book is None:
            raise HTTPException(404, "教材不存在")
        chapter_ids = [item.id for item in payload.chapters]
        if len(chapter_ids) != len(set(chapter_ids)):
            raise HTTPException(400, "章节列表包含重复 ID")
        chapters = db.query(Chapter).filter(
            Chapter.textbook_id == textbook_id,
            Chapter.id.in_(chapter_ids),
        ).all() if chapter_ids else []
        if len(chapters) != len(chapter_ids):
            raise HTTPException(400, "章节列表包含不属于当前教材的章节")
        updates = {item.id: item for item in payload.chapters}
        for chapter in chapters:
            item = updates[chapter.id]
            chapter.title = item.title.strip()
            chapter.order_index = item.order_index
            chapter.parent_id = item.parent_id
            chapter.level = item.level
            chapter.review_status = "confirmed" if payload.confirmed else "unreviewed"
        book.structure_status = "confirmed" if payload.confirmed else "review"
        db.commit()
        return {
            "textbook_id": textbook_id,
            "structure_status": book.structure_status,
            "chapter_count": len(chapters),
        }
    finally:
        db.close()


@router.get("/{textbook_id}/pages/{page_number}")
def get_textbook_page(textbook_id: str, page_number: int):
    db = SessionLocal()
    try:
        page = db.query(TextbookPage).filter(
            TextbookPage.textbook_id == textbook_id,
            TextbookPage.page_number == page_number,
        ).first()
        if page is None:
            raise HTTPException(404, "教材页不存在")
        return {
            "textbook_id": textbook_id,
            "page_number": page.page_number,
            "printed_page_number": page.printed_page_number,
            "text": page.text,
            "char_count": page.char_count,
            "has_text": page.has_text,
            "extraction_method": page.extraction_method,
        }
    finally:
        db.close()
