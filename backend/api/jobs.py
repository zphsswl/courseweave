from fastapi import APIRouter, HTTPException
from backend.agents.orchestrator import create_job, get_job, process_textbook, process_graph_extraction, process_integration, process_rag_index
from backend.database import SessionLocal, Textbook
from backend.services.job_queue import enqueue_job, retry_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.post("/parse")
def start_parse(payload: dict):
    textbook_id = payload.get("textbook_id")
    if not textbook_id:
        raise HTTPException(400, "缺少 textbook_id")
    force = payload.get("force", False)
    job_id = create_job("parse", {"textbook_id": textbook_id, "force": force})
    enqueue_job(job_id)
    return get_job(job_id)

@router.post("/extract-graph")
def start_extract(payload: dict):
    textbook_id = payload.get("textbook_id")
    if not textbook_id:
        raise HTTPException(400, "缺少 textbook_id")
    force = payload.get("force", False)
    job_id = create_job("extract_graph", {"textbook_id": textbook_id, "force": force})
    enqueue_job(job_id)
    return get_job(job_id)

@router.post("/integrate")
def start_integrate(payload: dict):
    course_id = payload.get("course_id", "course_default")
    textbook_ids = list(dict.fromkeys(payload.get("textbook_ids") or []))
    if len(textbook_ids) < 2:
        raise HTTPException(400, "请至少选择两本已生成知识树的教材")
    db = SessionLocal()
    try:
        ready_ids = {
            book.id for book in db.query(Textbook).filter(
                Textbook.course_id == course_id,
                Textbook.id.in_(textbook_ids),
                Textbook.graph_status.in_(("completed", "review")),
            ).all()
        }
    finally:
        db.close()
    if ready_ids != set(textbook_ids):
        raise HTTPException(400, "所选教材不存在或尚未生成知识树")
    job_id = create_job(
        "integrate",
        {"course_id": course_id, "textbook_ids": textbook_ids},
        course_id=course_id,
    )
    enqueue_job(job_id)
    return get_job(job_id)

@router.post("/rag-index")
def start_rag_index(payload: dict | None = None):
    course_id = (payload or {}).get("course_id", "course_default")
    job_id = create_job("rag_index", {"course_id": course_id}, course_id=course_id)
    enqueue_job(job_id)
    return get_job(job_id)

@router.get("/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


@router.post("/{job_id}/retry")
def retry_failed_job(job_id: str):
    if not retry_job(job_id):
        raise HTTPException(409, "任务不可重试、正在运行或已达到重试上限")
    return get_job(job_id)
