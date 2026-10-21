"""Teacher-controlled lesson boards; saving never starts background generation."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.database import SessionLocal
from backend.services.teaching_board import (
    BoardConflict, create_teaching_board, get_teaching_board, get_teaching_sources,
    list_teaching_boards, update_teaching_board,
)


router = APIRouter(prefix="/api/courses/{course_id}/teaching/boards", tags=["teaching"])


class BoardSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str = Field(min_length=1, max_length=160)
    teaching_title: str = Field(default="", max_length=100)
    dimension: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=1000)


class BoardConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default="", max_length=160)
    source_chunk_id: str = Field(min_length=1, max_length=160)
    target_chunk_id: str = Field(min_length=1, max_length=160)
    relation_type: Literal["equivalent_to", "extends", "prerequisite", "contrasts_with", "conflicts_with", "related_to"]
    reason: str = Field(default="", max_length=1000)
    status: Literal["draft", "confirmed"] = "draft"


class BoardContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1, max_length=160)
    textbook_ids: list[str] = Field(min_length=1, max_length=12)
    selections: list[BoardSelection] = Field(default_factory=list, max_length=80)
    connections: list[BoardConnection] = Field(default_factory=list, max_length=120)


class BoardUpdate(BoardContent):
    expected_revision: int = Field(ge=1, strict=True)


def _request(operation):
    db = SessionLocal()
    try:
        return operation(db)
    except BoardConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    finally:
        db.close()


@router.get("")
def list_boards(course_id: str, limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    return _request(lambda db: list_teaching_boards(db, course_id, limit, offset))


@router.post("", status_code=201)
def create_board(course_id: str, payload: BoardContent):
    return _request(lambda db: create_teaching_board(db, course_id, payload.model_dump(exclude_unset=True)))


@router.get("/sources")
def read_board_sources(
    course_id: str,
    textbook_ids: list[str] | None = Query(default=None),
    chunk_ids: list[str] | None = Query(default=None),
    q: str = Query(default=""),
):
    """Resolve legacy source references; must precede the dynamic board route."""
    def parse_ids(values):
        return [part.strip() for value in (values or []) for part in value.split(",") if part.strip()]
    return _request(lambda db: get_teaching_sources(db, course_id, parse_ids(textbook_ids), parse_ids(chunk_ids), q))


@router.get("/{board_id}")
def read_board(course_id: str, board_id: str):
    return _request(lambda db: get_teaching_board(db, course_id, board_id))


@router.patch("/{board_id}")
def save_board(course_id: str, board_id: str, payload: BoardUpdate):
    normalized = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
    return _request(lambda db: update_teaching_board(db, course_id, board_id, normalized, payload.expected_revision))
