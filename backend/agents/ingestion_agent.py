from backend.services.pdf_parser import parse_textbook, save_parsed_textbook
from backend.services.chunker import chunk_textbook as chunk_textbook_service
from backend.database import (
    SessionLocal,
    Textbook,
    TextbookPage,
    Chapter,
    Chunk,
    KnowledgeNode,
    IntegrationDecision,
    RagIndexState,
)


def _invalidate_textbook_derivatives(db, book: Textbook) -> None:
    """Remove every artifact derived from the old parse before replacing it."""
    node_ids = {
        row[0] for row in db.query(KnowledgeNode.id).filter(
            KnowledgeNode.textbook_id == book.id
        ).all()
    }
    from backend.agents.kg_extraction_agent import _clean_textbook_graph
    _clean_textbook_graph(db, book.id)
    if node_ids:
        for decision in db.query(IntegrationDecision).all():
            if node_ids.intersection(decision.affected_nodes or []):
                db.delete(decision)
    db.query(Chunk).filter(Chunk.textbook_id == book.id).delete(synchronize_session=False)
    db.query(Chapter).filter(Chapter.textbook_id == book.id).delete(synchronize_session=False)
    db.query(TextbookPage).filter(TextbookPage.textbook_id == book.id).delete(synchronize_session=False)
    index_state = db.query(RagIndexState).filter(RagIndexState.course_id == book.course_id).first()
    if index_state:
        index_state.status = "stale"
        index_state.error = "教材已重新解析，需要重建索引"
    book.parse_status = "pending"
    book.structure_status = "pending"
    book.graph_status = "pending"
    book.index_status = "pending"

def ingest_textbook(textbook_id: str, force: bool = False):
    """Parse a textbook file and save structured data."""
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if not book:
            raise ValueError(f"Textbook {textbook_id} not found")

        file_path = f"data/textbooks/{book.filename}"
        import os
        if not os.path.exists(file_path):
            file_path = f"教材/{book.filename}"

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Textbook file not found: {book.filename}")

        file_size = os.path.getsize(file_path)
        # Parse first. A malformed replacement file must not destroy the last
        # usable graph before we know the new source can be read successfully.
        book_data = parse_textbook(file_path, textbook_id)
        if force:
            _invalidate_textbook_derivatives(db, book)
            db.commit()
            from backend.services.retrieval_service import invalidate_course_cache
            invalidate_course_cache(book.course_id)
        save_parsed_textbook(book_data, book.filename, file_size, book.format)
        from backend.services.retrieval_service import invalidate_course_cache
        invalidate_course_cache(book.course_id)
        return {"textbook_id": textbook_id, "total_pages": book_data["total_pages"], "total_chars": book_data["total_chars"], "chapters": len(book_data["chapters"])}
    finally:
        db.close()

def chunk_textbook(textbook_id: str) -> int:
    """Chunk a parsed textbook into retrievable segments."""
    return chunk_textbook_service(textbook_id)
