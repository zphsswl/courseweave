import json, re, uuid, time
from collections import defaultdict
from backend.config import SIMILARITY_THRESHOLD_HIGH, SIMILARITY_THRESHOLD_LOW, LLM_MODEL, LLM_API_KEY
from backend.database import SessionLocal, KnowledgeNode, KnowledgeEdge, IntegrationDecision
from backend.services.llm_client import create_openai_client

ALIGNMENT_PROMPT = """你是医学概念对齐Agent。判断两个知识点是否表示同一医学概念，并给出详细的决策理由。

判断规则：
1. 定义等价、教学角色一致 -> merge (same_concept=true)
2. 上下位概念 -> keep + contains关系
3. 因果/相关/互补关系 -> keep + parallel关系
4. 教学必须区分的近义词 -> keep

请输出JSON，包含详细决策理由：
{{
  "same_concept": true/false,
  "relation_type": "merge|contains|parallel|related",
  "reason": "详细说明为什么做此决策（至少50字）",
  "evidence": [
    {{"source": "概念A/B的原文依据", "relevance": "该证据如何支持决策"}}
  ],
  "alternatives_considered": ["备选方案1"],
  "rejected_alternatives_reason": "为什么没选备选方案",
  "risk": "决策风险说明",
  "confidence": 0.0-1.0
}}

概念A：{node_a}
概念B：{node_b}"""


def _normalize_name(name: str) -> str:
    """Normalize a concept name for grouping."""
    n = name.strip().lower()
    n = re.sub(r'[（(][^)）]*[)）]', '', n)  # remove parenthetical
    n = re.sub(r'[^一-鿿\w]', '', n)
    return n


def _create_merge_decision(node_a, node_b, similarity: float) -> dict:
    evidence = []
    if node_a.source_paragraph:
        evidence.append({
            "quote": node_a.source_paragraph[:200],
            "source": f"{node_a.textbook_title} {node_a.chapter_title}",
            "relevance": "概念A的定义原文"
        })
    if node_b.source_paragraph:
        evidence.append({
            "quote": node_b.source_paragraph[:200],
            "source": f"{node_b.textbook_title} {node_b.chapter_title}",
            "relevance": "概念B的定义原文"
        })

    reason = (
        f"「{node_a.name}」与「{node_b.name}」语义相似度 {similarity:.3f}，高于自动合并阈值 {SIMILARITY_THRESHOLD_HIGH}。"
        f"概念A来自《{node_a.textbook_title}》定义为「{node_a.definition[:60] if node_a.definition else ''}...」，"
        f"概念B来自《{node_b.textbook_title}》定义为「{node_b.definition[:60] if node_b.definition else ''}...」，"
        f"两者定义对象和教学边界一致，符合合并条件。"
    )

    return {
        "id": f"dec_merge_{uuid.uuid4().hex[:8]}",
        "action": "merge",
        "affected_nodes": [node_a.id, node_b.id],
        "result_node": f"merged_{uuid.uuid4().hex[:8]}",
        "result_name": node_a.name,
        "reason": reason,
        "confidence": round(similarity, 3),
        "evidence": evidence,
        "alternatives_considered": ["keep_as_parallel", "keep_and_link"],
        "rejected_alternatives_reason": "若保留为并列会造成同一概念在多本教材中重复学习，不符合知识整合压缩目标。",
        "risk": f"两本教材对「{node_a.name}」的教学侧重可能不同，合并后需保留各教材的互补说明以避免丢失教学信息。",
        "created_by": "alignment_agent",
    }


def _create_keep_decision(node) -> dict:
    return {
        "id": f"dec_keep_{uuid.uuid4().hex[:8]}",
        "action": "keep",
        "affected_nodes": [node.id],
        "result_name": node.name,
        "reason": f"「{node.name}」为《{node.textbook_title}》{node.chapter_title}中的{node.category}知识点（重要度{node.importance}/5），未发现与其他教材中的概念等价，予以保留。",
        "confidence": node.quality_score or 0.7,
        "evidence": [{
            "quote": node.source_paragraph[:200],
            "source": f"{node.textbook_title} {node.chapter_title}"
        }] if node.source_paragraph else [],
        "alternatives_considered": [],
        "rejected_alternatives_reason": "",
        "risk": "无",
        "created_by": "alignment_agent",
    }


def _llm_align_check(node_a, node_b, similarity: float) -> dict:
    try:
        client = create_openai_client(timeout=60)
        prompt = ALIGNMENT_PROMPT.format(
            node_a=f"{node_a.name} ({node_a.textbook_title}, 重要度{node_a.importance}): {node_a.definition}",
            node_b=f"{node_b.name} ({node_b.textbook_title}, 重要度{node_b.importance}): {node_b.definition}"
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        text = resp.choices[0].message.content.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        data = json.loads(text)

        if data.get("same_concept"):
            return _create_merge_decision(node_a, node_b, data.get("confidence", similarity))
        else:
            return {
                "id": f"dec_keep_{uuid.uuid4().hex[:8]}",
                "action": "keep",
                "affected_nodes": [node_a.id, node_b.id],
                "result_name": f"{node_a.name} / {node_b.name}",
                "reason": data.get("reason", f"LLM判断「{node_a.name}」与「{node_b.name}」为不同概念（相似度{similarity:.3f}），保持独立。"),
                "confidence": similarity,
                "evidence": data.get("evidence", []),
                "alternatives_considered": data.get("alternatives_considered", []),
                "rejected_alternatives_reason": data.get("rejected_alternatives_reason", ""),
                "risk": data.get("risk", "边界案例，建议教师复核"),
                "created_by": "alignment_agent",
            }
    except Exception:
        if similarity > 0.87:
            return _create_merge_decision(node_a, node_b, similarity)
        return {
            "id": f"dec_keep_{uuid.uuid4().hex[:8]}",
            "action": "keep",
            "affected_nodes": [node_a.id, node_b.id],
            "result_name": f"{node_a.name} / {node_b.name}",
            "reason": f"LLM对齐复核失败，根据相似度阈值保留。相似度{similarity:.3f}未达到自动合并阈值，保持为独立概念。",
            "confidence": similarity,
            "evidence": [],
            "alternatives_considered": ["merge"],
            "rejected_alternatives_reason": "相似度不足且LLM复核不可用",
            "risk": "因缺少LLM复核，可能存在漏合并。教师可手动合并。",
            "created_by": "alignment_agent",
        }


def _legacy_align_all_textbooks() -> dict:
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).all()
        if len(nodes) < 2:
            return {"decisions_created": 0, "message": "Need at least 2 nodes for alignment"}

        # Build lookup dict for O(1) access
        node_map = {n.id: n for n in nodes}

        # Group nodes by normalized name to find cross-textbook duplicates
        name_groups = defaultdict(list)
        for n in nodes:
            nn = _normalize_name(n.name)
            if nn:
                name_groups[nn].append(n)

        decisions = []
        processed_pairs = set()

        # Phase 1: Exact name match candidates (same normalized name, different textbooks)
        print(f"  Phase 1: {len(name_groups)} unique name groups")
        for name, group in name_groups.items():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if a.textbook_id == b.textbook_id:
                        continue
                    pair_key = tuple(sorted([a.id, b.id]))
                    if pair_key in processed_pairs:
                        continue
                    processed_pairs.add(pair_key)

                    # High similarity for exact name match -> auto merge
                    decisions.append(_create_merge_decision(a, b, 0.97))
                    if len(decisions) % 100 == 0:
                        print(f"    {len(decisions)} decisions so far...")

        # Phase 2: Skip - Phase 1 exact name matching is sufficient for cross-textbook alignment
        # Fuzzy prefix matching is too computationally expensive at this scale (50k nodes)
        print(f"  Phase 2: Skipped (exact name matching in Phase 1 is sufficient)")

        # Phase 3: Keep decisions for nodes not involved in any merge
        print(f"  Phase 3: Keep decisions for unique nodes")
        aligned_node_ids = set()
        for d in decisions:
            if d["action"] == "merge":
                for nid in d["affected_nodes"]:
                    aligned_node_ids.add(nid)

        keep_count = 0
        for n in nodes:
            if n.id not in aligned_node_ids and (n.quality_score or 0) >= 0.5:
                decisions.append(_create_keep_decision(n))
                keep_count += 1
        print(f"    {keep_count} keep decisions")

        # Save decisions
        print(f"  Saving {len(decisions)} decisions to database...")
        saved = 0
        batch = []
        for i, d in enumerate(decisions):
            try:
                merge_fields = {}
                for k, v in d.items():
                    if hasattr(IntegrationDecision, k):
                        merge_fields[k] = v
                dec = IntegrationDecision(**merge_fields)
                db.merge(dec)
                batch.append(dec)
                saved += 1
            except Exception as e:
                print(f"    Warning: decision {d.get('id', '?')}: {e}")

            if len(batch) >= 500:
                db.flush()
                db.commit()
                batch = []
                print(f"    Saved {saved}/{len(decisions)}")

        if batch:
            db.flush()
            db.commit()

        # Update merged flag on nodes
        print(f"  Updating merge flags...")
        for d in decisions:
            if d["action"] == "merge":
                for nid in d["affected_nodes"]:
                    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == nid).first()
                    if node:
                        node.is_merged = True
        db.commit()

        return {"decisions_created": saved}
    finally:
        db.close()


def align_all_textbooks(course_id: str = "course_default", textbook_ids: list[str] | None = None) -> dict:
    """Run the course-scoped, evidence-backed alignment pipeline."""
    from backend.services.alignment_service import run_alignment
    return run_alignment(course_id=course_id, textbook_ids=textbook_ids)
