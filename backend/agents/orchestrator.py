import uuid
from datetime import datetime
from backend.database import SessionLocal, Job

def create_job(job_type: str, payload: dict = None) -> str:
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        job = Job(
            id=job_id,
            type=job_type,
            status="pending",
            payload=payload or {}
        )
        db.add(job)
        db.commit()
        return job_id
    finally:
        db.close()

def update_job(job_id: str, status: str = None, progress: int = None, total: int = None, message: str = None, result: dict = None, error: str = None):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if total is not None:
                job.total = total
            if message is not None:
                job.message = message
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            db.commit()
    finally:
        db.close()

def get_job(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        return {
            "id": job.id, "type": job.type, "status": job.status,
            "progress": job.progress, "total": job.total,
            "message": job.message, "result": job.result,
            "error": job.error, "created_at": job.created_at.isoformat()
        }
    finally:
        db.close()

def process_textbook(job_id: str, textbook_id: str, force: bool = False):
    """Full pipeline: parse -> chunk"""
    try:
        update_job(job_id, status="processing", message="Parsing textbook..." + (" (force re-parse)" if force else ""))
        from backend.agents.ingestion_agent import ingest_textbook
        result = ingest_textbook(textbook_id, force=force)
        update_job(job_id, progress=1, total=2, message="Chunking...")
        from backend.agents.ingestion_agent import chunk_textbook as do_chunk
        chunk_count = do_chunk(textbook_id)
        update_job(job_id, status="completed", total=2, progress=2, result={"textbook_id": textbook_id, "chapters": result.get("chapters", 0), "chunks": chunk_count})
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))

def process_graph_extraction(job_id: str, textbook_id: str, force: bool = False):
    try:
        update_job(job_id, status="processing", message="Extracting layered knowledge graph...")
        from backend.agents.kg_extraction_agent import extract_textbook_graph
        result = extract_textbook_graph(textbook_id, force=force)
        update_job(job_id, status="completed", result=result)
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))

def process_integration(job_id: str):
    try:
        update_job(job_id, status="processing", message="Aligning concepts across textbooks...")
        from backend.agents.alignment_agent import align_all_textbooks
        align_result = align_all_textbooks()
        update_job(job_id, progress=1, total=2, message="Compressing to 30% target...")
        from backend.agents.compression_agent import compress_knowledge
        compress_result = compress_knowledge()
        update_job(job_id, status="completed", result={**align_result, **compress_result})
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))

def process_rag_index(job_id: str):
    try:
        update_job(job_id, status="processing", message="Building RAG index...")
        from backend.agents.rag_agent import build_rag_index
        result = build_rag_index()
        update_job(job_id, status="completed", result=result)
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))
