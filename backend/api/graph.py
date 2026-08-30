"""Knowledge graph API with pagination to prevent browser freeze on large graphs."""
from fastapi import APIRouter, HTTPException, Query
from backend.database import SessionLocal, KnowledgeNode, KnowledgeEdge
from typing import Optional
from sqlalchemy import func

router = APIRouter(prefix="/api/graph", tags=["graph"])

COLORS = ["#E74C3C", "#3498DB", "#2ECC71", "#F39C12", "#9B59B6", "#1ABC9C", "#E67E22"]

MAX_INTEGRATED_NODES = 3000
MAX_BOOK_NODES = 8000

def _serialize_node(n, color=None, name_counts=None):
    return {
        "id": n.id,
        "label": n.name,
        "definition": n.definition,
        "category": n.category,
        "importance": n.importance,
        "textbook": n.textbook_title,
        "chapter": n.chapter_title,
        "page": n.page,
        "page_start": n.page_start,
        "page_end": n.page_end,
        "source_paragraph": n.source_paragraph,
        "source_sentences": n.source_sentences,
        "aliases": n.aliases,
        "color": color or "#999",
        "is_merged": n.is_merged,
        "teacher_locked": n.teacher_locked,
        "frequency": name_counts.get(n.name, 1) if name_counts else 1,
        "size": 20 + ((name_counts.get(n.name, 1) if name_counts else 1) * 5) + (n.importance * 4),
        "quality_score": n.quality_score,
        "learning_objective": n.learning_objective,
        "is_essence": n.is_essence,
        "granularity": n.granularity,
        "display_level": n.display_level,
        "created_by": n.created_by,
        "parent_id": n.parent_id,
        "node_role": n.node_role,
        "course_id": n.course_id,
        "canonical_concept_id": n.canonical_concept_id,
        "review_status": n.review_status,
        "evidence_status": n.evidence_status,
    }

def _serialize_edge(e):
    return {
        "id": e.id,
        "source": e.source,
        "target": e.target,
        "relation_type": e.relation_type,
        "description": e.description,
        "confidence": e.confidence,
        "source_quote": e.source_quote,
        "relation_subtype": e.relation_subtype,
        "is_cross_textbook": e.is_cross_textbook,
        "course_id": e.course_id,
        "review_status": e.review_status,
    }

@router.get("/book/{textbook_id}")
def get_book_graph(
    textbook_id: str,
    relation_type: Optional[str] = Query(None),
    min_importance: Optional[int] = Query(None),
    granularity: Optional[str] = Query(None),
    limit: int = Query(MAX_BOOK_NODES),
):
    db = SessionLocal()
    try:
        nodes_query = db.query(KnowledgeNode).filter(KnowledgeNode.textbook_id == textbook_id)
        if min_importance:
            nodes_query = nodes_query.filter(KnowledgeNode.importance >= min_importance)
        if granularity:
            nodes_query = nodes_query.filter(KnowledgeNode.granularity == granularity)
        total_nodes = nodes_query.count()

        nodes = nodes_query.order_by(KnowledgeNode.importance.desc()).limit(limit).all()
        node_ids = [n.id for n in nodes]

        edges_query = db.query(KnowledgeEdge).filter(KnowledgeEdge.source.in_(node_ids))
        if relation_type:
            edges_query = edges_query.filter(KnowledgeEdge.relation_type == relation_type)
        edges = edges_query.all()

        book_idx = hash(textbook_id) % len(COLORS)
        color = COLORS[book_idx]

        return {
            "nodes": [_serialize_node(n, color) for n in nodes],
            "edges": [_serialize_edge(e) for e in edges],
            "total_nodes": total_nodes,
            "truncated": len(nodes) < total_nodes,
        }
    finally:
        db.close()

@router.get("/integrated")
def get_integrated_graph(
    course_id: Optional[str] = Query(None),
    relation_type: Optional[str] = Query(None),
    textbook_id: Optional[str] = Query(None),
    min_importance: Optional[int] = Query(None),
    granularity: Optional[str] = Query(None),
    essence_only: bool = Query(False),
    limit: int = Query(MAX_INTEGRATED_NODES),
    offset: int = Query(0),
):
    db = SessionLocal()
    try:
        nodes_query = db.query(KnowledgeNode)
        if course_id:
            nodes_query = nodes_query.filter(KnowledgeNode.course_id == course_id)
        if textbook_id:
            nodes_query = nodes_query.filter(KnowledgeNode.textbook_id == textbook_id)
        if min_importance:
            nodes_query = nodes_query.filter(KnowledgeNode.importance >= min_importance)
        if granularity:
            nodes_query = nodes_query.filter(KnowledgeNode.granularity == granularity)
        if essence_only:
            nodes_query = nodes_query.filter(KnowledgeNode.is_essence == True)
        total_nodes = nodes_query.count()

        nodes = nodes_query.order_by(
            KnowledgeNode.importance.desc(),
            KnowledgeNode.textbook_id
        ).offset(offset).limit(limit).all()
        node_ids = [n.id for n in nodes]

        edges_query = db.query(KnowledgeEdge).filter(KnowledgeEdge.source.in_(node_ids))
        if relation_type:
            edges_query = edges_query.filter(KnowledgeEdge.relation_type == relation_type)
        edges = edges_query.all()

        textbook_colors = {}
        for n in nodes:
            if n.textbook_id not in textbook_colors:
                textbook_colors[n.textbook_id] = COLORS[len(textbook_colors) % len(COLORS)]

        name_counts = {}
        for n in nodes:
            name_counts[n.name] = name_counts.get(n.name, 0) + 1

        return {
            "nodes": [_serialize_node(n, textbook_colors.get(n.textbook_id, "#999"), name_counts) for n in nodes],
            "edges": [_serialize_edge(e) for e in edges],
            "textbook_colors": {k: v for k, v in textbook_colors.items()},
            "total_nodes": total_nodes,
            "truncated": len(nodes) < total_nodes,
            "offset": offset,
            "limit": limit,
        }
    finally:
        db.close()

@router.get("/integrated/stats")
def get_integrated_graph_stats(course_id: Optional[str] = Query(None)):
    """Get node/edge counts by category without loading graph data."""
    db = SessionLocal()
    try:
        node_scope = db.query(KnowledgeNode)
        edge_scope = db.query(KnowledgeEdge)
        if course_id:
            node_scope = node_scope.filter(KnowledgeNode.course_id == course_id)
            edge_scope = edge_scope.filter(KnowledgeEdge.course_id == course_id)
        total_nodes = node_scope.count()
        essence_nodes = node_scope.filter(KnowledgeNode.is_essence == True).count()
        total_edges = edge_scope.count()

        by_granularity = {}
        grouped_nodes = db.query(KnowledgeNode)
        if course_id:
            grouped_nodes = grouped_nodes.filter(KnowledgeNode.course_id == course_id)
        rows = grouped_nodes.with_entities(KnowledgeNode.granularity, func.count()).group_by(KnowledgeNode.granularity).all()
        for g, c in rows:
            by_granularity[g or "unknown"] = c

        by_textbook = {}
        rows = grouped_nodes.with_entities(KnowledgeNode.textbook_title, func.count()).group_by(KnowledgeNode.textbook_title).all()
        for t, c in rows:
            by_textbook[t] = c

        by_importance = {}
        rows = grouped_nodes.with_entities(KnowledgeNode.importance, func.count()).group_by(KnowledgeNode.importance).all()
        for imp, c in rows:
            by_importance[imp] = c

        return {
            "total_nodes": total_nodes,
            "essence_nodes": essence_nodes,
            "total_edges": total_edges,
            "by_granularity": by_granularity,
            "by_textbook": by_textbook,
            "by_importance": by_importance,
            "max_render_recommended": MAX_INTEGRATED_NODES,
        }
    finally:
        db.close()
