from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.database import SessionLocal, Textbook, Chapter, KnowledgeNode, KnowledgeEdge, Chunk, IntegrationDecision
import uuid
import os
import shutil

router = APIRouter(prefix="/api/textbooks", tags=["textbooks"])

UPLOAD_DIR = "data/textbooks"

@router.post("/upload")
async def upload_textbook(file: UploadFile = File(...)):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("pdf", "md", "txt"):
        raise HTTPException(400, f"不支持的文件格式: {ext}。支持 PDF, MD, TXT")

    textbook_id = f"book_{uuid.uuid4().hex[:8]}"
    save_path = os.path.join(UPLOAD_DIR, f"{textbook_id}.{ext}")

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    title = file.filename.rsplit(".", 1)[0] if "." in file.filename else file.filename
    book = Textbook(
        id=textbook_id,
        filename=f"{textbook_id}.{ext}",
        title=title,
        format=ext,
        file_size=len(content),
        parse_status="pending"
    )
    db = SessionLocal()
    try:
        db.merge(book)
        db.commit()
    finally:
        db.close()

    return {"textbook_id": textbook_id, "filename": file.filename, "title": title, "format": ext, "file_size": len(content)}

@router.get("")
def list_textbooks():
    db = SessionLocal()
    try:
        books = db.query(Textbook).all()
        results = []
        for b in books:
            ch_count = db.query(Chapter).filter(Chapter.textbook_id == b.id).count()
            results.append({
                "id": b.id,
                "filename": b.filename,
                "title": b.title,
                "format": b.format,
                "file_size": b.file_size,
                "total_pages": b.total_pages,
                "total_chars": b.total_chars,
                "chapter_count": ch_count,
                "parse_status": b.parse_status,
                "graph_status": b.graph_status,
                "index_status": b.index_status
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
        # Delete related data
        db.query(KnowledgeEdge).filter(
            (KnowledgeEdge.source.in_(
                db.query(KnowledgeNode.id).filter(KnowledgeNode.textbook_id == textbook_id)
            )) |
            (KnowledgeEdge.target.in_(
                db.query(KnowledgeNode.id).filter(KnowledgeNode.textbook_id == textbook_id)
            ))
        ).delete(synchronize_session=False)
        db.query(KnowledgeNode).filter(KnowledgeNode.textbook_id == textbook_id).delete(synchronize_session=False)
        db.query(Chunk).filter(Chunk.textbook_id == textbook_id).delete(synchronize_session=False)
        db.query(Chapter).filter(Chapter.textbook_id == textbook_id).delete(synchronize_session=False)
        db.query(IntegrationDecision).filter(
            IntegrationDecision.affected_nodes.contains([textbook_id])
        ).delete(synchronize_session=False)
        db.delete(book)
        db.commit()
        return {"status": "deleted", "id": textbook_id}
    finally:
        db.close()

@router.get("/{textbook_id}/chapters")
def get_chapters(textbook_id: str):
    db = SessionLocal()
    try:
        chapters = db.query(Chapter).filter(Chapter.textbook_id == textbook_id).order_by(Chapter.page_start).all()
        return [{
            "id": c.id,
            "title": c.title,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "char_count": c.char_count
        } for c in chapters]
    finally:
        db.close()
