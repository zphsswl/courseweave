import uuid
from backend.database import SessionLocal, KnowledgeNode, KnowledgeEdge, IntegrationDecision, Textbook
from backend.config import COMPRESSION_TARGET

def compress_knowledge() -> dict:
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).all()
        decisions = db.query(IntegrationDecision).all()
        textbooks = db.query(Textbook).all()

        total_original_chars = sum(t.total_chars for t in textbooks)

        merged_ids = set()
        for d in decisions:
            if d.action == "merge" and not d.teacher_override:
                merged_ids.update(d.affected_nodes)

        keep_nodes = [n for n in nodes if n.teacher_locked]
        merge_nodes = [n for n in nodes if n.id in merged_ids and not n.teacher_locked]
        other_nodes = [n for n in nodes if n.id not in merged_ids and not n.teacher_locked]

        # Score each node
        for n in other_nodes:
            n._score = _score_node(n, textbooks)

        other_nodes.sort(key=lambda n: n._score, reverse=True)

        # Calculate current essence chars
        essence_chars = sum(len(n.definition or "") + len(n.source_paragraph or "") for n in keep_nodes)
        essence_chars += sum(len(n.definition or "") for n in merge_nodes[:len(merge_nodes)])

        selected = list(keep_nodes) + list(merge_nodes)
        for n in other_nodes:
            node_chars = len(n.definition or "") + len(n.source_paragraph or "")
            if total_original_chars == 0 or (essence_chars + node_chars) / total_original_chars <= COMPRESSION_TARGET:
                essence_chars += node_chars
                selected.append(n)
            else:
                _create_remove_decision(db, n)

        # Protect prerequisites
        edge_pre = db.query(KnowledgeEdge).filter(KnowledgeEdge.relation_type == "prerequisite").all()
        selected_ids = {n.id for n in selected}
        for edge in edge_pre:
            if edge.target in selected_ids and edge.source not in selected_ids:
                src_node = db.query(KnowledgeNode).filter(KnowledgeNode.id == edge.source).first()
                if src_node:
                    selected.append(src_node)
                    selected_ids.add(src_node.id)
                    essence_chars += len(src_node.definition or "")

        # Chapter coverage protection
        chapter_covered = {}
        for n in selected:
            key = (n.textbook_id, n.chapter_title)
            chapter_covered[key] = chapter_covered.get(key, 0) + 1
        for n in other_nodes:
            key = (n.textbook_id, n.chapter_title)
            if key not in chapter_covered:
                selected.append(n)
                chapter_covered[key] = 1
                essence_chars += len(n.definition or "")

        compression_ratio = essence_chars / max(total_original_chars, 1)

        # Persist essence status to DB
        for n in nodes:
            n.is_essence = n.id in selected_ids
        db.commit()

        result = {
            "original_chars": total_original_chars,
            "essence_chars": essence_chars,
            "compression_ratio": round(compression_ratio, 4),
            "compression_pct": f"{round(compression_ratio * 100, 1)}%",
            "original_nodes": len(nodes),
            "essence_nodes": len(selected),
            "node_compression_ratio": round(len(selected) / max(len(nodes), 1), 4),
            "within_target": compression_ratio <= COMPRESSION_TARGET
        }

        return result
    finally:
        db.close()

def _score_node(node, textbooks) -> float:
    """Score node for retention priority."""
    db2 = SessionLocal()
    try:
        textbooks_count = len(set(n.textbook_id for n in db2.query(KnowledgeNode).filter(KnowledgeNode.name == node.name).all()))
    finally:
        db2.close()
    textbooks_count = max(textbooks_count, 1)
    return (
        0.35 * min(textbooks_count / 7, 1.0) +
        0.25 * (node.importance / 5) +
        0.20 * 0.5 +
        0.10 * (1.0 if node.category in ("核心概念", "机制") else 0.5) +
        0.10 * (1.0 if node.teacher_locked else 0.0)
    )

def _create_remove_decision(db, node):
    dec = IntegrationDecision(
        id=f"dec_remove_{uuid.uuid4().hex[:8]}",
        action="remove",
        affected_nodes=[node.id],
        result_name=node.name,
        reason=f"低重要度评分({node.importance}/5)，为达成{COMPRESSION_TARGET*100:.0f}%压缩目标而从精华库移除。节点为{node.category}类知识点，可降为引用来源保留。",
        confidence=0.6
    )
    db.add(dec)
    db.flush()
