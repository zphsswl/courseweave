"""Real text integration API."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from backend.services.integration_service import integrate_concept, integrate_all_merges, get_compression_summary

router = APIRouter(prefix="/api/integration", tags=["integration"])

@router.get("/compression")
def compression_stats():
    """Get overall compression metrics."""
    return get_compression_summary()

@router.post("/run")
def run_integration(bg: BackgroundTasks):
    """Run text integration on all merge decisions."""
    bg.add_task(integrate_all_merges)
    return {"status": "started", "message": "文本整合已启动，正在合并各教材知识点定义..."}

@router.post("/concept/{decision_id}")
def integrate_single_concept(decision_id: str):
    """Integrate a single merge decision."""
    result = integrate_concept(decision_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result

@router.get("/results")
def integration_results():
    """Get all integration results with integrated text."""
    from backend.database import SessionLocal, IntegrationDecision
    db = SessionLocal()
    try:
        decs = db.query(IntegrationDecision).filter(
            IntegrationDecision.integrated_chars > 0
        ).order_by(IntegrationDecision.compression_ratio).all()
        return [{
            "id": d.id,
            "action": d.action,
            "result_name": d.result_name,
            "source_textbook_count": d.source_textbook_count,
            "original_chars": d.original_chars,
            "integrated_chars": d.integrated_chars,
            "compression_ratio": d.compression_ratio,
            "compression_pct": f"{round(d.compression_ratio * 100, 1)}%",
            "integrated_text": d.integrated_text,
            "integrated_definition": d.integrated_definition,
            "source_texts": d.source_texts,
            "confidence": d.confidence,
        } for d in decs]
    finally:
        db.close()
