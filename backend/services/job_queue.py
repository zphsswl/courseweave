"""Single-worker, database-backed job queue for local and portfolio deployments."""

from __future__ import annotations

import queue
import threading

from backend.database import Job, SessionLocal


_job_ids: queue.Queue[str] = queue.Queue()
_enqueued: set[str] = set()
_state_lock = threading.Lock()
_worker_started = False


def enqueue_job(job_id: str) -> bool:
    with _state_lock:
        if job_id in _enqueued:
            return False
        _enqueued.add(job_id)
        _job_ids.put(job_id)
        return True


def _dispatch_job(job_id: str) -> None:
    from backend.agents.orchestrator import (
        process_graph_extraction,
        process_integration,
        process_rag_index,
        process_textbook,
    )

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.status not in {"pending", "processing"}:
            return
        job_type = job.type
        payload = dict(job.payload or {})
        course_id = job.course_id or payload.get("course_id") or "course_default"
    finally:
        db.close()

    if job_type == "parse":
        process_textbook(job_id, payload["textbook_id"], bool(payload.get("force", False)))
    elif job_type == "extract_graph":
        process_graph_extraction(job_id, payload["textbook_id"], bool(payload.get("force", False)))
    elif job_type == "integrate":
        process_integration(job_id, course_id, list(payload.get("textbook_ids") or []))
    elif job_type == "rag_index":
        process_rag_index(job_id)
    elif job_type == "course_agent":
        from backend.agents.course_agent import process_course_agent
        process_course_agent(job_id)
    else:
        from backend.agents.orchestrator import update_job
        update_job(job_id, status="failed", error=f"不支持的任务类型：{job_type}")


def _worker_loop() -> None:
    while True:
        job_id = _job_ids.get()
        try:
            _dispatch_job(job_id)
        finally:
            with _state_lock:
                _enqueued.discard(job_id)
            _job_ids.task_done()


def start_job_worker() -> int:
    """Start once, then enqueue every durable pending job found in SQLite."""
    global _worker_started
    with _state_lock:
        if not _worker_started:
            threading.Thread(target=_worker_loop, name="courseweave-job-worker", daemon=True).start()
            _worker_started = True

    db = SessionLocal()
    try:
        pending_ids = [row[0] for row in db.query(Job.id).filter(Job.status == "pending").order_by(Job.created_at).all()]
    finally:
        db.close()
    for job_id in pending_ids:
        enqueue_job(job_id)
    return len(pending_ids)


def retry_job(job_id: str) -> bool:
    from backend.agents.orchestrator import _write_with_retry

    found = False

    def reset(db):
        nonlocal found
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or job.status != "failed" or (job.retry_count or 0) >= 3:
            return
        found = True
        job.status = "pending"
        job.error = ""
        job.message = "任务已重新排队"
        job.retry_count = (job.retry_count or 0) + 1

    _write_with_retry(reset)
    if found:
        enqueue_job(job_id)
    return found
