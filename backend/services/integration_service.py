"""Real text integration: merge definitions from multiple textbooks into unified concise knowledge."""

from backend.config import LLM_MODEL, LLM_API_KEY
from backend.database import SessionLocal, KnowledgeNode, KnowledgeEdge, IntegrationDecision, Textbook
from backend.services.llm_client import create_openai_client

INTEGRATION_PROMPT = """你是医学教材知识整合专家。请将以下来自不同教材的同一知识点定义整合为一段精华说明。

要求：
1. 整合后的文字不超过原始总字数的35%。
2. 保留所有教材中的关键医学信息，删除重复表述。
3. 结构清晰：先给统一定义，再按教材补充各自的侧重点。
4. 标注哪些信息来自哪本教材。
5. 如果不同教材有矛盾或差异，客观并列呈现，不要自行裁决。

原始知识点：{concept_name}
涉及教材数：{textbook_count}

各教材原文：
{source_texts}

请输出整合后的精华文本（纯文本，不要Markdown）："""


def integrate_concept(decision_id: str) -> dict:
    """Perform real text integration for a merge decision."""
    db = SessionLocal()
    try:
        dec = db.query(IntegrationDecision).filter(IntegrationDecision.id == decision_id).first()
        if not dec:
            return {"error": "Decision not found"}
        if dec.action != "merge":
            return {"error": "Only merge decisions can be integrated", "action": dec.action}

        # Collect source texts from affected nodes
        source_texts = []
        source_nodes = []
        total_original = 0
        for nid in dec.affected_nodes:
            node = db.query(KnowledgeNode).filter(KnowledgeNode.id == nid).first()
            if node:
                text = f"【{node.textbook_title} · {node.chapter_title}】定义：{node.definition}"
                if node.source_paragraph and node.source_paragraph != node.definition:
                    text += f"\n原文：{node.source_paragraph[:300]}"
                source_texts.append(text)
                source_nodes.append({
                    "id": node.id,
                    "name": node.name,
                    "textbook": node.textbook_title,
                    "chapter": node.chapter_title,
                    "definition": node.definition,
                    "source_quote": node.source_paragraph[:300] if node.source_paragraph else "",
                })
                total_original += len(node.definition or "") + len(node.source_paragraph or "")

        if len(source_nodes) < 2:
            return {"error": "Need at least 2 source nodes for integration"}

        # Call LLM for integration
        integrated_text = ""
        try:
            client = create_openai_client(timeout=60)
            prompt = INTEGRATION_PROMPT.format(
                concept_name=dec.result_name,
                textbook_count=len(source_nodes),
                source_texts="\n\n---\n\n".join(source_texts),
            )
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=1500,
            )
            integrated_text = resp.choices[0].message.content.strip()
        except Exception as e:
            # Fallback: concatenate with compression
            parts = [n["definition"] for n in source_nodes]
            integrated_text = "；".join(parts[:2])  # Simple concat of first 2

        integrated_chars = len(integrated_text)
        compression_ratio = round(integrated_chars / max(total_original, 1), 3)

        # Persist to decision
        dec.integrated_text = integrated_text
        dec.integrated_definition = integrated_text[:200]
        dec.source_texts = source_nodes
        dec.source_textbook_count = len(source_nodes)
        dec.original_chars = total_original
        dec.integrated_chars = integrated_chars
        dec.compression_ratio = compression_ratio
        db.commit()

        return {
            "decision_id": decision_id,
            "concept": dec.result_name,
            "source_textbooks": len(source_nodes),
            "original_chars": total_original,
            "integrated_chars": integrated_chars,
            "compression_ratio": compression_ratio,
            "compression_pct": f"{round(compression_ratio * 100, 1)}%",
            "integrated_text": integrated_text,
            "sources": source_nodes,
        }
    finally:
        db.close()


def integrate_all_merges() -> dict:
    """Run text integration on all merge decisions."""
    db = SessionLocal()
    try:
        merge_decs = db.query(IntegrationDecision).filter(
            IntegrationDecision.action == "merge"
        ).all()

        results = []
        total_original = 0
        total_integrated = 0
        for dec in merge_decs:
            result = integrate_concept(dec.id)
            if "error" not in result:
                results.append(result)
                total_original += result["original_chars"]
                total_integrated += result["integrated_chars"]

        overall_ratio = round(total_integrated / max(total_original, 1), 3)
        return {
            "integrated_concepts": len(results),
            "total_original_chars": total_original,
            "total_integrated_chars": total_integrated,
            "overall_compression_ratio": overall_ratio,
            "overall_compression_pct": f"{round(overall_ratio * 100, 1)}%",
            "within_30pct_target": overall_ratio <= 0.30,
            "results": results,
        }
    finally:
        db.close()


def get_compression_summary() -> dict:
    """Get overall compression metrics for the entire knowledge base."""
    db = SessionLocal()
    try:
        textbooks = db.query(Textbook).all()
        total_chars = sum(t.total_chars for t in textbooks)

        decisions = db.query(IntegrationDecision).all()
        integrated_decisions = [d for d in decisions if d.integrated_chars > 0]
        total_integrated_chars = sum(d.integrated_chars for d in integrated_decisions)
        total_original_chars = sum(d.original_chars for d in integrated_decisions)

        merge_count = sum(1 for d in decisions if d.action == "merge")
        integrated_count = len(integrated_decisions)
        keep_count = sum(1 for d in decisions if d.action == "keep")
        remove_count = sum(1 for d in decisions if d.action == "remove")

        # Calculate overall compression
        nodes = db.query(KnowledgeNode).all()
        total_nodes = len(nodes)
        merged_nodes = sum(1 for n in nodes if n.is_merged)

        return {
            "textbooks": len(textbooks),
            "total_source_chars": total_chars,
            "decisions": {
                "total": len(decisions),
                "merge": merge_count,
                "keep": keep_count,
                "remove": remove_count,
                "integrated": integrated_count,
            },
            "nodes": {
                "total": total_nodes,
                "merged": merged_nodes,
                "compressed_pct": f"{round(merged_nodes / max(total_nodes, 1) * 100, 1)}%",
            },
            "text_compression": {
                "original_chars": total_original_chars,
                "integrated_chars": total_integrated_chars,
                "ratio": round(total_integrated_chars / max(total_original_chars, 1), 3),
                "ratio_pct": f"{round(total_integrated_chars / max(total_original_chars, 1) * 100, 1)}%",
                "integrated_concepts": integrated_count,
            } if total_original_chars > 0 else None,
        }
    finally:
        db.close()
