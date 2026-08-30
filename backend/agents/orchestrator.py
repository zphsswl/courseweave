import uuid
import time
from datetime import datetime
from sqlalchemy.exc import OperationalError
from backend.database import SessionLocal, Job, Textbook


SQLITE_WRITE_RETRIES = 6


def _write_with_retry(operation, attempts: int = SQLITE_WRITE_RETRIES):
    """Run one short database write, retrying only transient SQLite lock errors."""
    for attempt in range(attempts):
        db = SessionLocal()
        try:
            value = operation(db)
            db.commit()
            return value
        except OperationalError as exc:
            db.rollback()
            locked = "database is locked" in str(exc).lower()
            if not locked or attempt == attempts - 1:
                raise
            time.sleep(0.05 * (2 ** attempt))
        finally:
            db.close()

def create_job(job_type: str, payload: dict = None, course_id: str = None) -> str:
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    def create(db):
        db.add(Job(
            id=job_id,
            course_id=course_id,
            type=job_type,
            status="pending",
            payload=payload or {}
        ))
    _write_with_retry(create)
    return job_id

def update_job(job_id: str, status: str = None, progress: int = None, total: int = None, message: str = None, result: dict = None, error: str = None, stage: str = None):
    def update(db):
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
            if stage is not None:
                job.stage = stage
    _write_with_retry(update)

def get_job(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        return {
            "id": job.id, "course_id": job.course_id, "type": job.type, "status": job.status,
            "progress": job.progress, "total": job.total,
            "message": job.message, "result": job.result,
            "error": job.error, "stage": job.stage,
            "retry_count": job.retry_count or 0,
            "recoverable": job.status == "failed" and (job.retry_count or 0) < 3,
            "payload": job.payload or {},
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }
    finally:
        db.close()

def process_textbook(job_id: str, textbook_id: str, force: bool = False):
    """Full pipeline: parse -> chunk"""
    try:
        update_job(job_id, status="processing", progress=1, total=4, stage="parse", message="正在读取教材文件")
        from backend.agents.ingestion_agent import ingest_textbook
        result = ingest_textbook(textbook_id, force=force)
        update_job(job_id, progress=3, total=4, stage="chunk", message="正在生成可检索内容块")
        from backend.agents.ingestion_agent import chunk_textbook as do_chunk
        chunk_count = do_chunk(textbook_id)
        update_job(job_id, status="completed", total=4, progress=4, stage="completed", message="教材解析完成", result={"textbook_id": textbook_id, "chapters": result.get("chapters", 0), "chunks": chunk_count})
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))

def process_graph_extraction(job_id: str, textbook_id: str, force: bool = False):
    try:
        update_job(job_id, status="processing", progress=1, total=100, stage="extract", message="正在准备知识树生成")
        from backend.agents.kg_extraction_agent import extract_textbook_graph
        result = extract_textbook_graph(
            textbook_id,
            force=force,
            progress_callback=lambda progress, total, message: update_job(
                job_id,
                progress=progress,
                total=total,
                message=message,
            ),
        )
        if result.get("error"):
            raise ValueError(result["error"])
        update_job(job_id, status="completed", progress=100, total=100, stage="completed", message="知识树生成完成", result=result)
    except Exception as e:
        db = SessionLocal()
        try:
            book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
            if book:
                book.graph_status = "failed"
                db.commit()
        finally:
            db.close()
        update_job(job_id, status="failed", message="知识树生成失败", error=str(e))

def process_integration(job_id: str, course_id: str = "course_default", textbook_ids: list[str] | None = None):
    try:
        update_job(job_id, status="processing", progress=1, total=3, stage="align", message="正在读取所选教材的核心概念")
        from backend.agents.alignment_agent import align_all_textbooks
        align_result = align_all_textbooks(course_id=course_id, textbook_ids=textbook_ids)
        update_job(job_id, status="completed", progress=3, total=3, stage="completed", message="跨教材关联图生成完成", result=align_result)
    except Exception as e:
        update_job(job_id, status="failed", message="跨教材关联生成失败", error=str(e))

def process_rag_index(job_id: str):
    try:
        update_job(job_id, status="processing", stage="index", message="正在构建 RAG 索引")
        from backend.agents.rag_agent import build_rag_index
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            course_id = (job.course_id if job else None) or "course_default"
        finally:
            db.close()
        result = build_rag_index(course_id)
        update_job(job_id, status="completed", stage="completed", result=result)
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))
