import uuid
from backend.config import CHUNK_SIZE, CHUNK_OVERLAP
from backend.database import SessionLocal, Chapter, Chunk, Textbook

def chunk_textbook(textbook_id: str) -> int:
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if not book:
            return 0

        chapters = db.query(Chapter).filter(Chapter.textbook_id == textbook_id).all()
        existing = db.query(Chunk).filter(Chunk.textbook_id == textbook_id).count()
        if existing > 0:
            return existing

        total = 0
        for ch in chapters:
            chunks = _split_text(ch.content, CHUNK_SIZE, CHUNK_OVERLAP)
            for idx, chunk_text in enumerate(chunks):
                chunk = Chunk(
                    id=f"{ch.id}_chunk_{idx:04d}",
                    textbook_id=textbook_id,
                    chapter_id=ch.id,
                    textbook_title=book.title,
                    chapter_title=ch.title,
                    page_start=ch.page_start,
                    page_end=ch.page_end,
                    content=chunk_text,
                    char_count=len(chunk_text),
                    chunk_index=idx
                )
                db.add(chunk)
                total += 1

        book.index_status = "completed"
        db.commit()
        return total
    finally:
        db.close()

def _split_text(text: str, chunk_size: int, overlap: int) -> list:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks
