"""Read-only teaching bridge; raw source recall stays separate from relations."""
from fastapi import APIRouter, HTTPException, Query

from backend.database import SessionLocal
from backend.services.teaching_bridge import get_bridge_diagnostics, get_teaching_bridge


router = APIRouter(prefix="/api/courses/{course_id}/teaching", tags=["teaching"])


def _selected_ids(values):
    # Accept both repeated query keys and the UI's comma-separated selection.
    return list(dict.fromkeys(part.strip() for value in (values or []) for part in value.split(",") if part.strip()))


@router.get("/bridge")
def teaching_bridge(
    course_id: str,
    q: str = Query(min_length=1, max_length=160),
    textbook_ids: list[str] | None = Query(default=None),
    limit_per_book: int = Query(default=4, ge=1, le=8),
    offset_per_book: int = Query(default=0, ge=0, le=10000),
):
    db = SessionLocal()
    try:
        return get_teaching_bridge(db, course_id, _selected_ids(textbook_ids), q, limit_per_book, offset_per_book)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        db.close()


@router.get("/diagnostics")
def teaching_diagnostics(course_id: str, textbook_ids: list[str] | None = Query(default=None)):
    db = SessionLocal()
    try:
        return get_bridge_diagnostics(db, course_id, _selected_ids(textbook_ids))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        db.close()
