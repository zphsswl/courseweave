from fastapi import APIRouter
from backend.config import get_model_status

router = APIRouter(prefix="/api/model", tags=["model"])

@router.get("/status")
def model_status():
    """Show current LLM model configuration (no API key exposed)."""
    return get_model_status()
