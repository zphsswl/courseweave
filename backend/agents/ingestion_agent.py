from backend.services.pdf_parser import parse_textbook, save_parsed_textbook
from backend.services.chunker import chunk_textbook as chunk_textbook_service
from backend.database import SessionLocal, Textbook, Chapter, Chunk

def ingest_textbook(textbook_id: str, force: bool = False):
    """Parse a textbook file and save structured data."""
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if not book:
            raise ValueError(f"Textbook {textbook_id} not found")

        # Force re-parse: clear old chapters and chunks
        if force:
            db.query(Chunk).filter(Chunk.textbook_id == textbook_id).delete()
            db.query(Chapter).filter(Chapter.textbook_id == textbook_id).delete()
            book.parse_status = "pending"
            db.commit()

        file_path = f"data/textbooks/{book.filename}"
        import os
        if not os.path.exists(file_path):
            file_path = f"教材/{book.filename}"

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Textbook file not found: {book.filename}")

        file_size = os.path.getsize(file_path)
        book_data = parse_textbook(file_path, textbook_id)
        save_parsed_textbook(book_data, book.filename, file_size, book.format)
        return {"textbook_id": textbook_id, "total_pages": book_data["total_pages"], "total_chars": book_data["total_chars"], "chapters": len(book_data["chapters"])}
    finally:
        db.close()

def chunk_textbook(textbook_id: str) -> int:
    """Chunk a parsed textbook into retrievable segments."""
    return chunk_textbook_service(textbook_id)
