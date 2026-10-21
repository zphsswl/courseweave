from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from backend.agents.report_agent import generate_report, export_report_markdown
from backend.database import DEFAULT_COURSE_ID

router = APIRouter(prefix="/api/report", tags=["report"])

@router.get("/summary")
def report_summary(course_id: str = DEFAULT_COURSE_ID):
    return generate_report(course_id)

@router.post("/export")
def report_export(payload: dict | None = None, course_id: str = DEFAULT_COURSE_ID):
    md = export_report_markdown((payload or {}).get("course_id") or course_id)
    return PlainTextResponse(content=md, media_type="text/markdown")
