from fastapi import APIRouter, Query
from backend.config import get_model_status
from backend.services.model_runtime import get_model_runtime_status, probe_model

router = APIRouter(prefix="/api/model", tags=["model"])

@router.get("/status")
def model_status(refresh: bool = Query(default=False)):
    """Show configuration plus last-known runtime availability, without exposing secrets."""
    runtime = probe_model(force=False) if refresh else get_model_runtime_status()
    return {**get_model_status(), **runtime}


@router.post("/probe")
def model_probe():
    """Run a tiny availability check and classify billing/auth failures."""
    return {**get_model_status(), **probe_model(force=True)}
