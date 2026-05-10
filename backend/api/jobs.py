from fastapi import APIRouter, BackgroundTasks, HTTPException
from backend.agents.orchestrator import create_job, get_job, process_textbook, process_graph_extraction, process_integration, process_rag_index

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.post("/parse")
def start_parse(payload: dict, bg: BackgroundTasks):
    textbook_id = payload.get("textbook_id")
    if not textbook_id:
        raise HTTPException(400, "缺少 textbook_id")
    force = payload.get("force", False)
    job_id = create_job("parse", {"textbook_id": textbook_id, "force": force})
    bg.add_task(process_textbook, job_id, textbook_id, force)
    return get_job(job_id)

@router.post("/extract-graph")
def start_extract(payload: dict, bg: BackgroundTasks):
    textbook_id = payload.get("textbook_id")
    if not textbook_id:
        raise HTTPException(400, "缺少 textbook_id")
    force = payload.get("force", False)
    job_id = create_job("extract_graph", {"textbook_id": textbook_id, "force": force})
    bg.add_task(process_graph_extraction, job_id, textbook_id, force)
    return get_job(job_id)

@router.post("/integrate")
def start_integrate(bg: BackgroundTasks):
    job_id = create_job("integrate", {})
    bg.add_task(process_integration, job_id)
    return get_job(job_id)

@router.post("/rag-index")
def start_rag_index(bg: BackgroundTasks):
    job_id = create_job("rag_index", {})
    bg.add_task(process_rag_index, job_id)
    return get_job(job_id)

@router.get("/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job
