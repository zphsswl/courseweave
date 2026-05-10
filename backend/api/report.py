from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from backend.agents.report_agent import generate_report, export_report_markdown

router = APIRouter(prefix="/api/report", tags=["report"])

@router.get("/summary")
def report_summary():
    return generate_report()

@router.post("/export")
def report_export():
    md = export_report_markdown()
    return PlainTextResponse(content=md, media_type="text/markdown")
