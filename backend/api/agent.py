"""Public API for the goal-driven lesson preparation agent."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func

from backend.agents.course_agent import initial_agent_result, lesson_markdown, validate_lesson_draft, verify_artifact
from backend.agents.orchestrator import _write_with_retry, create_job, get_job, update_job
from backend.database import Chapter, Chunk, Course, Job, SessionLocal, Textbook
from backend.services.job_queue import enqueue_job, retry_job


router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentContextCreate(BaseModel):
    source_book_id: str | None = Field(default=None, max_length=160)
    section_id: str | None = Field(default=None, max_length=300)
    board_id: str | None = Field(default=None, max_length=160)
    selected_chunk_ids: list[str] = Field(default_factory=list, max_length=48)
    supplemental_chunk_ids: list[str] = Field(default_factory=list, max_length=48)


class AgentRunCreate(BaseModel):
    course_id: str = Field(default="course_default", min_length=1, max_length=160)
    topic: str = Field(min_length=2, max_length=160)
    goal: str = Field(min_length=4, max_length=500)
    audience: str = Field(default="", max_length=160)
    prior_knowledge: str = Field(default="", max_length=500)
    textbook_ids: list[str] = Field(min_length=1, max_length=12)
    requirements: list[str] = Field(default_factory=list, max_length=8)
    duration_minutes: int = Field(default=45, ge=1, le=240, strict=True)
    question_count: int = Field(default=3, ge=0, le=12, strict=True)
    focus_terms: list[str] = Field(default_factory=list, max_length=12)
    context: AgentContextCreate | None = None


class LessonDraftUpdate(BaseModel):
    expected_revision: int = Field(ge=0, strict=True)
    artifact: dict


class AgentTeacherResponse(BaseModel):
    request_id: str = Field(min_length=1, max_length=160)
    answer: str = Field(min_length=1, max_length=2000)


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
    if len(normalized["topic"]) < 2 or len(normalized["goal"]) < 4:
        raise HTTPException(422, "主题和目标不能只包含空白")
    normalized["textbook_ids"] = textbook_ids
    normalized["requirements"] = list(dict.fromkeys(
        value.strip() for value in payload.requirements if value.strip()
    ))
    if any(len(value) > 80 for value in normalized["requirements"]):
        raise HTTPException(422, "每个关注项不得超过 80 字")
    normalized["focus_terms"] = list(dict.fromkeys(value.strip() for value in payload.focus_terms))
    if any(not 2 <= len(value) <= 80 for value in normalized["focus_terms"]):
        raise HTTPException(422, "检索切面须为 2 至 80 字的具体术语")
    context = payload.context.model_dump(exclude_none=True) if payload.context else {}
    db = SessionLocal()
    try:
        if context.get("source_book_id") and context["source_book_id"] not in textbook_ids:
            raise HTTPException(400, "授课来源教材不在本次选择范围内")
        if context.get("section_id"):
            chapter_id = context["section_id"].split(":section:", 1)[0]
            chapter = db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.textbook_id.in_(textbook_ids)).first()
            if not chapter or (context.get("source_book_id") and chapter.textbook_id != context["source_book_id"]):
                raise HTTPException(400, "授课小节不属于本次教材范围")
        if context.get("board_id"):
            from backend.services.teaching_board import BoardConflict, get_board_agent_context
            try:
                supplemental = set(context.get("supplemental_chunk_ids") or [])
                original = get_board_agent_context(db, payload.course_id, context["board_id"], None)
                members = set(original["selected_chunk_ids"])
                requested = context.get("selected_chunk_ids") or []
                if set(requested) - members - supplemental:
                    raise ValueError("选定原文不属于本课对照板或补充材料")
                board_ids = [chunk_id for chunk_id in requested if chunk_id in members]
                board = get_board_agent_context(db, payload.course_id, context["board_id"], board_ids or None)
                # A repeated question citation must not discard its teacher title, note or connections.
                context["supplemental_chunk_ids"] = [chunk_id for chunk_id in context.get("supplemental_chunk_ids") or [] if chunk_id not in members]
            except BoardConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if not set(board["textbook_ids"]).issubset(textbook_ids):
                raise HTTPException(400, "知识板选定原文包含本次未选择的教材")
            context.update(board)
        chunk_ids = list(dict.fromkeys((context.get("selected_chunk_ids") or []) + (context.get("supplemental_chunk_ids") or [])))
        if len(chunk_ids) > 48 or any(not 1 <= len(value) <= 160 for value in chunk_ids):
            raise HTTPException(422, "最多选择 48 条有效原文编号")
        if chunk_ids:
            found = {row[0] for row in db.query(Chunk.id).filter(Chunk.id.in_(chunk_ids), Chunk.textbook_id.in_(textbook_ids)).all()}
            if found != set(chunk_ids):
                raise HTTPException(400, "选定原文不存在或不属于本次课程教材")
        context["selected_chunk_ids"] = chunk_ids
    finally:
        db.close()
    normalized["context"] = context
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
@router.get("/runs/{job_id}/lesson")
def get_agent_run(job_id: str):
    job = get_job(job_id)
    if not job or job.get("type") != "course_agent":
        raise HTTPException(404, "Agent 任务不存在")
    return job


@router.patch("/runs/{job_id}/draft")
def save_lesson_draft(job_id: str, payload: LessonDraftUpdate):
    def save(db):
        job = db.query(Job).filter(Job.id == job_id, Job.type == "course_agent").first()
        if not job:
            raise HTTPException(404, "Agent 任务不存在")
        if job.status in {"pending", "processing", "waiting_user"}:
            raise HTTPException(409, "任务仍在执行或等待确认，请结束后再编辑")
        state = dict(job.result or {})
        if int(state.get("draft_revision") or 0) != payload.expected_revision:
            raise HTTPException(409, "稿件已被更新，请重新读取后合并修改")
        request = dict(job.payload or {})
        book_ids = request.get("textbook_ids") or []
        course_id = job.course_id or request.get("course_id")
        found = {row[0] for row in db.query(Textbook.id).filter(Textbook.course_id == course_id, Textbook.id.in_(book_ids)).all()}
        if found != set(book_ids) or not book_ids:
            raise HTTPException(409, "任务教材范围已变化，请重新创建任务")
        try:
            draft = validate_lesson_draft(payload.artifact, state.get("artifact") or {}, request)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        quality = verify_artifact(draft, book_ids, request)
        state.update(lesson_draft=draft, draft_revision=payload.expected_revision + 1, delivery=quality["task_completion"], quality=quality)
        changed = db.query(Job).filter(
            Job.id == job_id, Job.type == "course_agent",
            Job.status.notin_(["pending", "processing", "waiting_user"]),
            func.coalesce(Job.result["draft_revision"].as_integer(), 0) == payload.expected_revision,
        ).update({Job.result: state}, synchronize_session=False)
        if changed != 1:
            raise HTTPException(409, "稿件或任务状态已被更新，请重新读取")
    _write_with_retry(save)
    return get_agent_run(job_id)


@router.get("/runs/{job_id}/export")
def export_lesson(job_id: str, format: str = Query(default="markdown", pattern="^(markdown|html)$")):
    job = get_agent_run(job_id)
    state = job.get("result") or {}
    artifact = state.get("lesson_draft") or state.get("artifact")
    if not artifact:
        raise HTTPException(409, "当前任务尚无可导出的产物")
    text = lesson_markdown(artifact, job.get("payload") or {}, state.get("delivery"))
    if format == "html":
        from backend.services.lesson_print import lesson_print_html
        return Response(lesson_print_html(text, artifact.get("title") or "课堂教案"), media_type="text/html; charset=utf-8", headers={"X-Content-Type-Options": "nosniff"})
    return Response(text, media_type="text/markdown; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="courseweave-lesson.md"',
        "X-Content-Type-Options": "nosniff",
    })


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
            raise HTTPException(409, "当前任务不在等待教师确认状态")
        if ((job.result or {}).get('approval') or {}).get('type') == 'teacher_question':
            raise HTTPException(409, '请提交教师补充回答后继续')
        textbook_ids = list((job.payload or {}).get("textbook_ids") or [])
        blocked_books = [
            book.title
            for book in db.query(Textbook).filter(Textbook.id.in_(textbook_ids)).all()
            if book.structure_status not in {"confirmed", "legacy_confirmed"}
        ]
        if blocked_books:
            return
        changed = db.query(Job).filter(Job.id == job_id, Job.status == 'waiting_user', Job.result == job.result).update({
            'status': 'pending', 'stage': 'pending', 'message': '教师确认已收到，Agent 正在继续',
            'error': '', 'updated_at': datetime.now(timezone.utc)}, synchronize_session=False)
        if not changed:
            raise HTTPException(409, '任务状态已变化，请刷新后重试')

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


@router.post('/runs/{job_id}/respond')
def respond_to_agent(job_id: str, payload: AgentTeacherResponse):
    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(422, '回答不能为空白')
    def respond(db):
        job = db.query(Job).filter(Job.id == job_id, Job.type == 'course_agent').first()
        if not job:
            raise HTTPException(404, 'Agent任务不存在')
        state = copy.deepcopy(job.result or {})
        approval = state.get('approval') or {}
        if job.status != 'waiting_user' or approval.get('type') != 'teacher_question' or approval.get('request_id') != payload.request_id:
            raise HTTPException(409, '待回答的问题已变化，请刷新当前任务')
        answers = state.get('teacher_answers') or []
        if len(answers) >= 4:
            raise HTTPException(409, '本次任务已达到教师补充次数上限')
        state['teacher_answers'] = [*answers, {'request_id': payload.request_id, 'question': approval['question'],
                                              'answer': answer, 'answered_at': datetime.now(timezone.utc).isoformat()}]
        state['approval'] = None
        changed = db.query(Job).filter(Job.id == job_id, Job.status == 'waiting_user', Job.result == job.result).update({
            'result': state, 'status': 'pending', 'stage': 'pending', 'message': '已收到教师补充，Agent将继续决策',
            'error': '', 'updated_at': datetime.now(timezone.utc)}, synchronize_session=False)
        if not changed:
            raise HTTPException(409, '任务状态已变化，请刷新后重试')
    _write_with_retry(respond)
    enqueue_job(job_id)
    return get_job(job_id)


@router.post('/runs/{job_id}/cancel')
def cancel_agent_run(job_id: str):
    def cancel(db):
        job = db.query(Job).filter(Job.id == job_id, Job.type == 'course_agent').first()
        if not job:
            raise HTTPException(404, 'Agent任务不存在')
        state = copy.deepcopy(job.result or {})
        if state.get('agent_version') != 'lesson_agent_v3':
            raise HTTPException(409, '历史流程不支持此停止操作')
        if job.status == 'cancelled':
            return
        if job.status not in {'pending', 'processing', 'waiting_user'}:
            raise HTTPException(409, '当前任务已经结束')
        state['stop_reason'] = 'user_cancelled'
        state['approval'] = None
        changed = db.query(Job).filter(Job.id == job_id, Job.status.in_(['pending', 'processing', 'waiting_user']), Job.result == job.result).update({
            'result': state, 'status': 'cancelled', 'stage': 'cancelled',
            'message': '任务已停止，已完成的原文与草稿保留', 'error': '',
            'updated_at': datetime.now(timezone.utc)}, synchronize_session=False)
        if not changed:
            raise HTTPException(409, '任务状态已变化，请刷新')
    _write_with_retry(cancel)
    return get_job(job_id)


@router.post("/runs/{job_id}/retry")
def retry_agent_run(job_id: str):
    job = get_job(job_id)
    if not job or job.get("type") != "course_agent":
        raise HTTPException(404, "Agent 任务不存在")
    if not retry_job(job_id):
        raise HTTPException(409, "任务不可重试、正在运行或已达到重试上限")
    return get_job(job_id)
