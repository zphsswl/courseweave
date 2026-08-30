"""Public API for the goal-driven lesson preparation agent."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.agents.course_agent import initial_agent_result
from backend.agents.orchestrator import _write_with_retry, create_job, get_job, update_job
from backend.database import Course, Job, SessionLocal, Textbook
from backend.services.job_queue import enqueue_job, retry_job


router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentRunCreate(BaseModel):
    course_id: str = Field(default="course_default", min_length=1, max_length=160)
    topic: str = Field(min_length=2, max_length=160)
    goal: str = Field(min_length=4, max_length=500)
    textbook_ids: list[str] = Field(min_length=1, max_length=6)
    requirements: list[str] = Field(default_factory=list, max_length=8)


def _validate_scope(payload: AgentRunCreate) -> list[str]:
    textbook_ids = list(dict.fromkeys(payload.textbook_ids))
    db = SessionLocal()
    try:
        if not db.query(Course.id).filter(Course.id == payload.course_id).first():
            raise HTTPException(404, "知识空间不存在")
        found_ids = {
            row[0]
            for row in db.query(Textbook.id).filter(
                Textbook.course_id == payload.course_id,
                Textbook.id.in_(textbook_ids),
            ).all()
        }
        if found_ids != set(textbook_ids):
            raise HTTPException(400, "部分教材不存在或不属于当前知识空间")
    finally:
        db.close()
    return textbook_ids


@router.post("/runs")
def create_agent_run(payload: AgentRunCreate):
    textbook_ids = _validate_scope(payload)
    normalized = payload.model_dump()
    normalized["topic"] = payload.topic.strip()
    normalized["goal"] = payload.goal.strip()
    normalized["textbook_ids"] = textbook_ids
    normalized["requirements"] = list(dict.fromkeys(
        value.strip() for value in payload.requirements if value.strip()
    ))
    job_id = create_job("course_agent", normalized, course_id=payload.course_id)
    update_job(
        job_id,
        result=initial_agent_result(normalized),
        total=100,
        progress=0,
        stage="pending",
        message="Agent 任务已进入队列",
    )
    enqueue_job(job_id)
    return get_job(job_id)


@router.get("/runs")
def list_agent_runs(
    course_id: str = Query(default="course_default"),
    limit: int = Query(default=12, ge=1, le=50),
):
    db = SessionLocal()
    try:
        ids = [
            row[0]
            for row in db.query(Job.id).filter(
                Job.course_id == course_id,
                Job.type == "course_agent",
            ).order_by(Job.created_at.desc()).limit(limit).all()
        ]
    finally:
        db.close()
    return [get_job(job_id) for job_id in ids]


@router.get("/runs/{job_id}")
def get_agent_run(job_id: str):
    job = get_job(job_id)
    if not job or job.get("type") != "course_agent":
        raise HTTPException(404, "Agent 任务不存在")
    return job


@router.post("/runs/{job_id}/resume")
def resume_agent_run(job_id: str):
    blocked_books = []
    found = False

    def resume(db):
        nonlocal blocked_books, found
        job = db.query(Job).filter(Job.id == job_id, Job.type == "course_agent").first()
        if not job:
            return
        found = True
        if job.status != "waiting_user":
            return
        textbook_ids = list((job.payload or {}).get("textbook_ids") or [])
        blocked_books = [
            book.title
            for book in db.query(Textbook).filter(Textbook.id.in_(textbook_ids)).all()
            if book.structure_status != "confirmed"
        ]
        if blocked_books:
            return
        job.status = "pending"
        job.stage = "pending"
        job.message = "教师确认已收到，Agent 正在继续"
        job.error = ""

    _write_with_retry(resume)
    if not found:
        raise HTTPException(404, "Agent 任务不存在")
    if blocked_books:
        raise HTTPException(409, f"仍有教材未确认章节：{'、'.join(blocked_books)}")
    job = get_job(job_id)
    if job["status"] != "pending":
        raise HTTPException(409, "当前任务不在等待教师确认状态")
    enqueue_job(job_id)
    return get_job(job_id)


@router.post("/runs/{job_id}/retry")
def retry_agent_run(job_id: str):
    job = get_job(job_id)
    if not job or job.get("type") != "course_agent":
        raise HTTPException(404, "Agent 任务不存在")
    if not retry_job(job_id):
        raise HTTPException(409, "任务不可重试、正在运行或已达到重试上限")
    return get_job(job_id)
