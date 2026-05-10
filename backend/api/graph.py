from fastapi import APIRouter, HTTPException, Query
from backend.database import SessionLocal, KnowledgeNode, KnowledgeEdge
from typing import Optional
import random

router = APIRouter(prefix="/api/graph", tags=["graph"])

COLORS = ["#E74C3C", "#3498DB", "#2ECC71", "#F39C12", "#9B59B6", "#1ABC9C", "#E67E22"]

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
        # Layered graph fields
        "granularity": n.granularity,
        "display_level": n.display_level,
        "created_by": n.created_by,
        "parent_id": n.parent_id,
        "node_role": n.node_role,
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
    }

@router.get("/book/{textbook_id}")
def get_book_graph(
    textbook_id: str,
    relation_type: Optional[str] = Query(None, description="Filter by relation type"),
):
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.textbook_id == textbook_id).all()
        node_ids = [n.id for n in nodes]
        edges_query = db.query(KnowledgeEdge).filter(
            KnowledgeEdge.source.in_(node_ids)
        )
        if relation_type:
            edges_query = edges_query.filter(KnowledgeEdge.relation_type == relation_type)
        edges = edges_query.all()

        book_idx = hash(textbook_id) % len(COLORS)
        color = COLORS[book_idx]

        book_idx = hash(textbook_id) % len(COLORS)
        color = COLORS[book_idx]
        return {
            "nodes": [_serialize_node(n, color) for n in nodes],
            "edges": [_serialize_edge(e) for e in edges],
        }
    finally:
        db.close()

@router.get("/integrated")
def get_integrated_graph(
    relation_type: Optional[str] = Query(None),
    textbook_id: Optional[str] = Query(None),
    min_importance: Optional[int] = Query(None),
):
    db = SessionLocal()
    try:
        nodes_query = db.query(KnowledgeNode)
        if textbook_id:
            nodes_query = nodes_query.filter(KnowledgeNode.textbook_id == textbook_id)
        if min_importance:
            nodes_query = nodes_query.filter(KnowledgeNode.importance >= min_importance)
        nodes = nodes_query.all()
        node_ids = [n.id for n in nodes]

        edges_query = db.query(KnowledgeEdge).filter(
            KnowledgeEdge.source.in_(node_ids)
        )
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
        }
    finally:
        db.close()
