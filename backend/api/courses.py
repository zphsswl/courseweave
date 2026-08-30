"""Course-scoped APIs for multi-textbook knowledge workspaces."""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_

from backend.database import (
    SessionLocal,
    Course,
    Textbook,
    CanonicalConcept,
    KnowledgeNode,
    KnowledgeEdge,
    RelationEvidence,
    AlignmentCandidate,
    DEFAULT_COURSE_ID,
)


router = APIRouter(prefix="/api/courses", tags=["courses"])


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    subject: str = Field(default="", max_length=120)
    default_granularity: str = Field(default="core", pattern="^(outline|core|detailed)$")


class CourseUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    subject: Optional[str] = Field(default=None, max_length=120)
    status: Optional[str] = Field(
        default=None,
        pattern="^(draft|processing|review|published|archived)$",
    )
    default_granularity: Optional[str] = Field(
        default=None,
        pattern="^(outline|core|detailed)$",
    )


def _serialize_course(course, textbook_count=0, concept_count=0, pending_reviews=0):
    return {
        "id": course.id,
        "owner_id": course.owner_id,
        "title": course.title,
        "description": course.description,
        "subject": course.subject,
        "status": course.status,
        "default_granularity": course.default_granularity,
        "textbook_count": textbook_count,
        "canonical_concept_count": concept_count,
        "pending_review_count": pending_reviews,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }


@router.get("")
def list_courses(owner_id: str = Query("demo_user", max_length=120)):
    db = SessionLocal()
    try:
        courses = db.query(Course).filter(
            Course.owner_id == owner_id,
            Course.status != "archived",
        ).order_by(Course.updated_at.desc()).all()
        result = []
        for course in courses:
            textbook_count = db.query(Textbook).filter(Textbook.course_id == course.id).count()
            concept_count = db.query(CanonicalConcept).filter(CanonicalConcept.course_id == course.id).count()
            pending_reviews = db.query(AlignmentCandidate).filter(
                AlignmentCandidate.course_id == course.id,
                AlignmentCandidate.status == "pending",
            ).count()
            result.append(_serialize_course(course, textbook_count, concept_count, pending_reviews))
        return result
    finally:
        db.close()


@router.post("", status_code=201)
def create_course(payload: CourseCreate):
    course = Course(
        id=f"course_{uuid.uuid4().hex[:12]}",
        owner_id="demo_user",
        title=payload.title.strip(),
        description=payload.description.strip(),
        subject=payload.subject.strip(),
        default_granularity=payload.default_granularity,
    )
    db = SessionLocal()
    try:
        db.add(course)
        db.commit()
        db.refresh(course)
        return _serialize_course(course)
    finally:
        db.close()


@router.get("/{course_id}")
def get_course(course_id: str):
    db = SessionLocal()
    try:
        course = db.query(Course).filter(Course.id == course_id).first()
        if course is None:
            raise HTTPException(404, "课程不存在")
        textbook_count = db.query(Textbook).filter(Textbook.course_id == course.id).count()
        concept_count = db.query(CanonicalConcept).filter(CanonicalConcept.course_id == course.id).count()
        pending_reviews = db.query(AlignmentCandidate).filter(
            AlignmentCandidate.course_id == course.id,
            AlignmentCandidate.status == "pending",
        ).count()
        return _serialize_course(course, textbook_count, concept_count, pending_reviews)
    finally:
        db.close()


@router.patch("/{course_id}")
def update_course(course_id: str, payload: CourseUpdate):
    db = SessionLocal()
    try:
        course = db.query(Course).filter(Course.id == course_id).first()
        if course is None:
            raise HTTPException(404, "课程不存在")
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(course, field, value)
        db.commit()
        db.refresh(course)
        return _serialize_course(course)
    finally:
        db.close()


@router.delete("/{course_id}")
def delete_course(course_id: str):
    """Remove a knowledge space from the active list without destroying its source data."""
    if course_id == DEFAULT_COURSE_ID:
        raise HTTPException(400, "默认知识空间不能删除")
    db = SessionLocal()
    try:
        course = db.query(Course).filter(Course.id == course_id).first()
        if course is None or course.status == "archived":
            raise HTTPException(404, "知识空间不存在")
        course.status = "archived"
        db.commit()
        return {"status": "deleted", "id": course_id}
    finally:
        db.close()


@router.get("/{course_id}/concepts")
def list_canonical_concepts(
    course_id: str,
    q: Optional[str] = Query(default=None, max_length=120),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    db = SessionLocal()
    try:
        query = db.query(CanonicalConcept).filter(CanonicalConcept.course_id == course_id)
        if q:
            query = query.filter(CanonicalConcept.canonical_name.ilike(f"%{q.strip()}%"))
        if status:
            query = query.filter(CanonicalConcept.status == status)
        total = query.count()
        concepts = query.order_by(CanonicalConcept.canonical_name).offset(offset).limit(limit).all()
        occurrence_counts = dict(
            db.query(KnowledgeNode.canonical_concept_id, func.count(KnowledgeNode.id))
            .filter(KnowledgeNode.canonical_concept_id.in_([concept.id for concept in concepts]))
            .group_by(KnowledgeNode.canonical_concept_id)
            .all()
        ) if concepts else {}
        return {
            "items": [
                {
                    "id": concept.id,
                    "canonical_name": concept.canonical_name,
                    "aliases": concept.aliases or [],
                    "concept_type": concept.concept_type,
                    "definition_summary": concept.definition_summary,
                    "status": concept.status,
                    "teacher_locked": concept.teacher_locked,
                    "occurrence_count": occurrence_counts.get(concept.id, 0),
                }
                for concept in concepts
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        db.close()


@router.get("/{course_id}/concepts/{concept_id}")
def get_canonical_concept(course_id: str, concept_id: str):
    db = SessionLocal()
    try:
        concept = db.query(CanonicalConcept).filter(
            CanonicalConcept.id == concept_id,
            CanonicalConcept.course_id == course_id,
        ).first()
        if concept is None:
            raise HTTPException(404, "统一概念不存在")

        occurrences = db.query(KnowledgeNode).filter(
            KnowledgeNode.course_id == course_id,
            KnowledgeNode.canonical_concept_id == concept_id,
        ).order_by(KnowledgeNode.textbook_title, KnowledgeNode.page_start).all()
        occurrence_ids = [node.id for node in occurrences]
        relations = db.query(KnowledgeEdge).filter(
            KnowledgeEdge.course_id == course_id,
            KnowledgeEdge.is_cross_textbook.is_(True),
            or_(
                KnowledgeEdge.source.in_(occurrence_ids),
                KnowledgeEdge.target.in_(occurrence_ids),
            ),
        ).all() if occurrence_ids else []
        edge_ids = [edge.id for edge in relations]
        evidence_by_edge = {}
        if edge_ids:
            for evidence in db.query(RelationEvidence).filter(RelationEvidence.edge_id.in_(edge_ids)).all():
                evidence_by_edge.setdefault(evidence.edge_id, []).append({
                    "textbook_id": evidence.textbook_id,
                    "chunk_id": evidence.chunk_id,
                    "page_number": evidence.page_number,
                    "source_quote": evidence.source_quote,
                    "evidence_role": evidence.evidence_role,
                    "quote_verified": evidence.quote_verified,
                })

        return {
            "id": concept.id,
            "canonical_name": concept.canonical_name,
            "aliases": concept.aliases or [],
            "concept_type": concept.concept_type,
            "definition_summary": concept.definition_summary,
            "status": concept.status,
            "teacher_locked": concept.teacher_locked,
            "occurrences": [
                {
                    "id": node.id,
                    "name": node.name,
                    "definition": node.definition,
                    "textbook_id": node.textbook_id,
                    "textbook_title": node.textbook_title,
                    "chapter_title": node.chapter_title,
                    "page_start": node.page_start,
                    "page_end": node.page_end,
                    "source_quote": node.source_paragraph,
                    "confidence": node.confidence,
                    "review_status": node.review_status,
                    "evidence_status": node.evidence_status,
                }
                for node in occurrences
            ],
            "cross_relations": [
                {
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "relation_type": edge.relation_type,
                    "description": edge.description,
                    "confidence": edge.confidence,
                    "review_status": edge.review_status,
                    "evidence": evidence_by_edge.get(edge.id, []),
                }
                for edge in relations
            ],
        }
    finally:
        db.close()


@router.get("/defaults/current")
def get_default_course():
    return {"course_id": DEFAULT_COURSE_ID}
