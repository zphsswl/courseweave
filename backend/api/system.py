"""System diagnostics and health checks."""
import os
from fastapi import APIRouter
from backend.database import SessionLocal, Textbook, Chapter, Chunk, KnowledgeNode, KnowledgeEdge, IntegrationDecision

router = APIRouter(prefix="/api/system", tags=["system"])

@router.get("/diagnostics")
def diagnostics():
    db = SessionLocal()
    try:
        db_path = os.path.abspath(os.path.join("data", "medessence.db"))
        db_exists = os.path.exists(db_path)
        db_size = os.path.getsize(db_path) if db_exists else 0

        tables_ok = False
        problems = []
        counts = {}
        try:
            counts = {
                "textbooks": db.query(Textbook).count(),
                "chapters": db.query(Chapter).count(),
                "chunks": db.query(Chunk).count(),
                "nodes": db.query(KnowledgeNode).count(),
                "edges": db.query(KnowledgeEdge).count(),
                "decisions": db.query(IntegrationDecision).count(),
            }
            tables_ok = True
        except Exception as e:
            problems.append(f"tables_error: {str(e)}")

        if counts.get("textbooks", 0) == 0:
            problems.append("no_textbooks")
        if counts.get("chapters", 0) == 0:
            problems.append("no_chapters")
        if counts.get("chunks", 0) == 0:
            problems.append("no_chunks_rag_cannot_build")
        if counts.get("nodes", 0) == 0:
            problems.append("no_knowledge_nodes")
        if counts.get("edges", 0) == 0:
            problems.append("no_knowledge_edges")

        return {
            "database": {
                "path": db_path,
                "exists": db_exists,
                "size_kb": round(db_size / 1024, 1),
                "tables_ok": tables_ok,
            },
            "counts": counts,
            "problems": problems,
            "status": "healthy" if tables_ok and not problems else "degraded" if tables_ok else "critical",
        }
    finally:
        db.close()
