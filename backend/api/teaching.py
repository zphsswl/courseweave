"""Source-only classroom reading and PDF page preview routes."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.teaching_service import (
    TeachingSourceError,
    get_teaching_content,
    render_teaching_page,
    search_teaching_content,
)


router = APIRouter(prefix="/api/textbooks", tags=["teaching"])


@router.get("/{textbook_id}/teaching")
def teaching_content(textbook_id: str, db: Session = Depends(get_db)):
    try:
        return get_teaching_content(db, textbook_id)
    except TeachingSourceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/{textbook_id}/teaching/search")
def teaching_search(
    textbook_id: str,
    q: str = Query(min_length=1, max_length=160),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        return search_teaching_content(db, textbook_id, q, limit)
    except TeachingSourceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/{textbook_id}/teaching/pages/{page_number}/image")
def teaching_page_image(
    textbook_id: str,
    page_number: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    try:
        image, digest = render_teaching_page(db, textbook_id, page_number)
    except TeachingSourceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return Response(content=image, media_type="image/png", headers={
        "Cache-Control": "private, max-age=60",
        "X-Content-Type-Options": "nosniff",
        "ETag": f'"{digest}"',
    })
