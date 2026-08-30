"""Teacher review API for cross-textbook alignment candidates."""
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import (
    SessionLocal,
    AlignmentCandidate,
    KnowledgeEdge,
    KnowledgeNode,
    ReviewEvent,
    Textbook,
)
from backend.services.alignment_service import (
    CROSS_RELATION_TYPES,
    approve_candidate,
    clean_concept_name,
    is_meaningful_alignment_node,
    select_alignment_nodes,
)


router = APIRouter(prefix="/api/courses/{course_id}/alignments", tags=["alignments"])

GRAPH_COLORS = ["#3E7C6B", "#C4774F", "#5B6FA8", "#9A7042", "#73639A", "#477E91"]


class AlignmentReview(BaseModel):
    action: str = Field(pattern="^(approve|reject|edit)$")
    relation_type: Optional[str] = None
    reason: str = Field(default="", max_length=2000)


def _node_summary(node):
    return {
        "id": node.id,
        "name": node.name,
        "definition": node.definition,
        "textbook_id": node.textbook_id,
        "textbook_title": node.textbook_title,
        "chapter_title": node.chapter_title,
        "page_start": node.page_start,
        "page_end": node.page_end,
        "source_quote": node.source_paragraph,
        "evidence_status": node.evidence_status,
    }


def _graph_node(node, color):
    return {
        "id": node.id,
        "label": clean_concept_name(node.name),
        "definition": node.definition,
        "category": node.category,
        "importance": node.importance,
        "textbook": node.textbook_title,
        "textbook_id": node.textbook_id,
        "chapter": node.chapter_title,
        "page": node.page_start or node.page,
        "page_start": node.page_start,
        "page_end": node.page_end,
        "source_paragraph": node.source_paragraph,
        "source_sentences": node.source_sentences,
        "aliases": node.aliases,
        "color": color,
        "is_merged": node.is_merged,
        "teacher_locked": node.teacher_locked,
        "frequency": 1,
        "size": 48,
        "granularity": node.granularity,
        "review_status": node.review_status,
        "evidence_status": node.evidence_status,
    }


def _edge_evidence(node, evidence=None):
    page_start = (evidence.page_number if evidence else None) or node.page_start or node.page or 0
    page_end = node.page_end or page_start
    return {
        "node_id": node.id,
        "concept": clean_concept_name(node.name),
        "textbook_id": node.textbook_id,
        "textbook": node.textbook_title,
        "chapter": node.chapter_title,
        "page_start": page_start,
        "page_end": page_end,
        "quote": (evidence.source_quote if evidence else None) or node.source_paragraph or "",
        "verified": bool(evidence.quote_verified if evidence else node.evidence_status == "verified"),
    }


@router.get("/graph")
def get_alignment_graph(
    course_id: str,
    textbook_ids: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=1200, ge=1, le=2000),
):
    """Return a direct, grouped graph of selected textbooks and AI links."""
    selected_ids = list(dict.fromkeys(textbook_ids or []))
    if len(selected_ids) < 2:
        return {"nodes": [], "edges": [], "groups": [], "total_nodes": 0, "total_edges": 0}

    db = SessionLocal()
    try:
        books = db.query(Textbook).filter(
            Textbook.course_id == course_id,
            Textbook.id.in_(selected_ids),
        ).all()
        book_map = {book.id: book for book in books}
        ordered_ids = [book_id for book_id in selected_ids if book_id in book_map]
        color_map = {
            book_id: GRAPH_COLORS[index % len(GRAPH_COLORS)]
            for index, book_id in enumerate(ordered_ids)
        }
        available_counts = {
            book_id: len(select_alignment_nodes(
                db,
                course_id=course_id,
                textbook_id=book_id,
                limit=None,
            ))
            for book_id in ordered_ids
        }

        eligible_ids = db.query(KnowledgeNode.id).filter(
            KnowledgeNode.course_id == course_id,
            KnowledgeNode.textbook_id.in_(ordered_ids),
        )
        candidate_query = db.query(AlignmentCandidate).filter(
            AlignmentCandidate.course_id == course_id,
            AlignmentCandidate.status != "rejected",
            AlignmentCandidate.source_node_id.in_(eligible_ids),
            AlignmentCandidate.target_node_id.in_(eligible_ids),
        )
        total_available_edges = candidate_query.count()
        candidates = candidate_query.order_by(
            AlignmentCandidate.confidence.desc()
        ).limit(limit).all()

        candidate_node_ids = {
            node_id
            for candidate in candidates
            for node_id in (candidate.source_node_id, candidate.target_node_id)
        }
        approved_edges = []
        if candidate_node_ids:
            approved_edges = db.query(KnowledgeEdge).filter(
                KnowledgeEdge.course_id == course_id,
                KnowledgeEdge.is_cross_textbook == True,
                KnowledgeEdge.source.in_(candidate_node_ids),
                KnowledgeEdge.target.in_(candidate_node_ids),
            ).all()

        approved_edge_ids = [edge.id for edge in approved_edges]
        evidence_rows = db.query(RelationEvidence).filter(
            RelationEvidence.edge_id.in_(approved_edge_ids)
        ).all() if approved_edge_ids else []
        evidence_map = {
            (row.edge_id, row.evidence_role): row
            for row in evidence_rows
        }

        linked_node_ids = candidate_node_ids | {
            node_id for edge in approved_edges for node_id in (edge.source, edge.target)
        }
        nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.id.in_(linked_node_ids),
            KnowledgeNode.textbook_id.in_(ordered_ids),
        ).all() if linked_node_ids else []
        node_map = {
            node.id: node for node in nodes
            if is_meaningful_alignment_node(node)
        }

        edges = []
        approved_pairs = set()
        for edge in approved_edges:
            if edge.source not in node_map or edge.target not in node_map:
                continue
            approved_pairs.add(frozenset((edge.source, edge.target)))
            edges.append({
                "id": edge.id,
                "source": edge.source,
                "target": edge.target,
                "relation_type": edge.relation_type,
                "description": edge.description,
                "confidence": edge.confidence,
                "is_cross_textbook": True,
                "review_status": edge.review_status or "approved",
                "why": edge.description,
                "source_evidence": _edge_evidence(
                    node_map[edge.source], evidence_map.get((edge.id, "source"))
                ),
                "target_evidence": _edge_evidence(
                    node_map[edge.target], evidence_map.get((edge.id, "target"))
                ),
            })
        for candidate in candidates:
            pair = frozenset((candidate.source_node_id, candidate.target_node_id))
            if pair in approved_pairs or candidate.source_node_id not in node_map or candidate.target_node_id not in node_map:
                continue
            edges.append({
                "id": f"candidate_{candidate.id}",
                "source": candidate.source_node_id,
                "target": candidate.target_node_id,
                "relation_type": candidate.proposed_relation,
                "description": candidate.reason,
                "confidence": candidate.confidence,
                "is_cross_textbook": True,
                "review_status": "suggested",
                "why": candidate.reason,
                "source_evidence": _edge_evidence(node_map[candidate.source_node_id]),
                "target_evidence": _edge_evidence(node_map[candidate.target_node_id]),
            })

        graph_nodes = [
            _graph_node(node, color_map.get(node.textbook_id, "#667085"))
            for node in nodes
        ]
        groups = [
            {
                "id": book_id,
                "title": book_map[book_id].title,
                "color": color_map[book_id],
                "node_count": available_counts[book_id],
                "linked_node_count": sum(1 for node in nodes if node.textbook_id == book_id),
            }
            for book_id in ordered_ids
        ]
        return {
            "nodes": graph_nodes,
            "edges": edges,
            "groups": groups,
            "textbook_colors": color_map,
            "total_nodes": len(graph_nodes),
            "total_edges": len(edges),
            "total_available_edges": total_available_edges,
            "truncated": total_available_edges > limit,
        }
    finally:
        db.close()


@router.get("")
def list_alignment_candidates(
    course_id: str,
    status: str = Query(default="pending"),
    textbook_ids: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    db = SessionLocal()
    try:
        query = db.query(AlignmentCandidate).filter(
            AlignmentCandidate.course_id == course_id,
        )
        if status != "all":
            query = query.filter(AlignmentCandidate.status == status)
        if textbook_ids:
            eligible_node_ids = db.query(KnowledgeNode.id).filter(
                KnowledgeNode.course_id == course_id,
                KnowledgeNode.textbook_id.in_(textbook_ids),
            )
            query = query.filter(
                AlignmentCandidate.source_node_id.in_(eligible_node_ids),
                AlignmentCandidate.target_node_id.in_(eligible_node_ids),
            )
        total = query.count()
        candidates = query.order_by(
            AlignmentCandidate.confidence.desc(),
            AlignmentCandidate.created_at.desc(),
        ).offset(offset).limit(limit).all()
        node_ids = {
            node_id
            for candidate in candidates
            for node_id in (candidate.source_node_id, candidate.target_node_id)
        }
        node_map = {
            node.id: node
            for node in db.query(KnowledgeNode).filter(KnowledgeNode.id.in_(node_ids)).all()
        } if node_ids else {}
        return {
            "items": [
                {
                    "id": candidate.id,
                    "proposed_relation": candidate.proposed_relation,
                    "confidence": candidate.confidence,
                    "reason": candidate.reason,
                    "differences": candidate.differences,
                    "status": candidate.status,
                    "scores": {
                        "name": candidate.name_similarity,
                        "definition": candidate.definition_similarity,
                        "context": candidate.context_similarity,
                    },
                    "source": _node_summary(node_map[candidate.source_node_id])
                    if candidate.source_node_id in node_map else None,
                    "target": _node_summary(node_map[candidate.target_node_id])
                    if candidate.target_node_id in node_map else None,
                }
                for candidate in candidates
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        db.close()


@router.patch("/{candidate_id}")
def review_alignment_candidate(course_id: str, candidate_id: str, payload: AlignmentReview):
    db = SessionLocal()
    try:
        candidate = db.query(AlignmentCandidate).filter(
            AlignmentCandidate.id == candidate_id,
            AlignmentCandidate.course_id == course_id,
        ).first()
        if candidate is None:
            raise HTTPException(404, "关联候选不存在")
        if candidate.status not in ("pending", "edited"):
            raise HTTPException(409, "该候选已经完成审核")

        relation_type = payload.relation_type or candidate.proposed_relation
        if relation_type not in CROSS_RELATION_TYPES - {"none"}:
            raise HTTPException(400, "不支持的跨教材关系类型")
        node_a = db.query(KnowledgeNode).filter(KnowledgeNode.id == candidate.source_node_id).first()
        node_b = db.query(KnowledgeNode).filter(KnowledgeNode.id == candidate.target_node_id).first()
        if node_a is None or node_b is None:
            raise HTTPException(409, "关联节点已被删除，请重新生成候选")

        before = {
            "status": candidate.status,
            "relation_type": candidate.proposed_relation,
            "reason": candidate.reason,
        }
        candidate.proposed_relation = relation_type
        if payload.reason.strip():
            candidate.reason = payload.reason.strip()

        if payload.action == "approve":
            if not node_a.source_paragraph or not node_b.source_paragraph:
                raise HTTPException(400, "关联两侧都必须有原文证据才能通过")
            edge = approve_candidate(db, candidate, node_a, node_b, actor_id="demo_user")
            if edge is None:
                raise HTTPException(409, "两个节点已属于不同统一概念，需要先处理概念冲突")
            result = {"status": "approved", "edge_id": edge.id}
        elif payload.action == "reject":
            candidate.status = "rejected"
            candidate.reviewed_by = "demo_user"
            candidate.reviewed_at = datetime.utcnow()
            db.add(ReviewEvent(
                id=f"review_{uuid.uuid4().hex[:12]}",
                course_id=course_id,
                target_type="alignment",
                target_id=candidate.id,
                action="reject",
                before=before,
                after={"status": "rejected"},
                reason=payload.reason.strip(),
                actor_id="demo_user",
            ))
            result = {"status": "rejected"}
        else:
            candidate.status = "edited"
            candidate.reviewed_by = "demo_user"
            candidate.reviewed_at = datetime.utcnow()
            db.add(ReviewEvent(
                id=f"review_{uuid.uuid4().hex[:12]}",
                course_id=course_id,
                target_type="alignment",
                target_id=candidate.id,
                action="edit",
                before=before,
                after={
                    "status": "edited",
                    "relation_type": relation_type,
                    "reason": candidate.reason,
                },
                reason=payload.reason.strip(),
                actor_id="demo_user",
            ))
            result = {"status": "edited"}
        db.commit()
        return {"id": candidate.id, "relation_type": candidate.proposed_relation, **result}
    finally:
        db.close()
