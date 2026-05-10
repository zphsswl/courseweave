"""
Real textbook processing pipeline.
1. Parse all 7 PDFs in 教材/ into chapters and chunks
2. Do NOT create demo nodes - let the layered extraction handle it
"""
import sys, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from backend.database import SessionLocal, Textbook, Chapter, Chunk, KnowledgeNode, KnowledgeEdge, IntegrationDecision, init_db
from backend.services.pdf_parser import parse_textbook, save_parsed_textbook
from backend.services.chunker import chunk_textbook as chunk_service

init_db()

PDF_MAP = [
    ("book_01", "01_局部解剖学.pdf", "局部解剖学"),
    ("book_02", "02_组织学与胚胎学.pdf", "组织学与胚胎学"),
    ("book_03", "03_生理学.pdf", "生理学"),
    ("book_04", "04_医学微生物学.pdf", "医学微生物学"),
    ("book_05", "05_病理学.pdf", "病理学"),
    ("book_06", "06_传染病学.pdf", "传染病学"),
    ("book_07", "07_病理生理学.pdf", "病理生理学"),
]

def process_all():
    db = SessionLocal()
    try:
        for bid, fname, title in PDF_MAP:
            # Find the PDF file
            pdf_path = None
            for search_dir in ["教材", "data/textbooks"]:
                candidate = os.path.join(search_dir, fname)
                if os.path.exists(candidate):
                    pdf_path = candidate
                    break
            if not pdf_path:
                print(f"[SKIP] {title}: file not found")
                continue

            file_size = os.path.getsize(pdf_path)
            print(f"[PARSE] {title} ({file_size//1024}KB)...")

            try:
                book_data = parse_textbook(pdf_path, bid)
                save_parsed_textbook(book_data, fname, file_size, "pdf")
                print(f"  -> {len(book_data['chapters'])} chapters, {book_data['total_pages']} pages, {book_data['total_chars']} chars")

                # Chunk it
                chunk_count = chunk_service(bid)
                print(f"  -> {chunk_count} chunks created")
            except Exception as e:
                print(f"[ERROR] {title}: {e}")
                continue

        db.commit()
        print("\n[DONE] All textbooks processed.")
    finally:
        db.close()


def reset_all():
    """Clean all data and re-register textbooks."""
    db = SessionLocal()
    try:
        db.query(KnowledgeEdge).delete()
        db.query(KnowledgeNode).delete()
        db.query(Chunk).delete()
        db.query(Chapter).delete()
        db.query(IntegrationDecision).delete()
        db.query(Textbook).delete()
        db.commit()
        print("[RESET] All graph data cleared.")
    finally:
        db.close()

    # Re-register
    db = SessionLocal()
    try:
        for bid, fname, title in PDF_MAP:
            book = Textbook(
                id=bid, filename=fname, title=title, format="pdf",
                file_size=0, total_pages=0, total_chars=0,
                parse_status="pending", graph_status="pending", index_status="pending"
            )
            db.merge(book)
        db.commit()
        print(f"[REGISTER] {len(PDF_MAP)} textbooks registered.")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        reset_all()
    process_all()
