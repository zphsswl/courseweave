import json
import re
import uuid
from backend.config import LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
from backend.database import SessionLocal, IntegrationDecision, ChatHistory

TEACHER_PROMPT = """你是教材整合方案助手。把教师自然语言反馈转换为对整合决策的修改。

可用操作：
- keep: 保留某知识点（恢复被删除的）
- merge: 合并知识点
- split: 拆分已合并知识点
- remove: 删除冗余知识点
- explain: 解释某决策

不要修改不存在的决策。如果信息不足，返回 need_clarification。

教师输入：{message}

当前相关决策（前10条）：
{decisions}

输出JSON，格式：
{{"operation": "keep|merge|split|remove|explain", "decision_id": "相关决策ID或null", "target_nodes": ["节点名1", "节点名2"], "reason": "执行原因"}}"""

def process_teacher_message(message: str) -> dict:
    db = SessionLocal()
    try:
        decisions = db.query(IntegrationDecision).order_by(IntegrationDecision.confidence.desc()).limit(10).all()

        # Save user message
        chat = ChatHistory(id=f"chat_{uuid.uuid4().hex[:12]}", role="user", content=message)
        db.add(chat)

        # Build context
        decisions_text = "\n".join([
            f"ID:{d.id} Action:{d.action} Name:{d.result_name} Nodes:{d.affected_nodes} Reason:{d.reason} Confidence:{d.confidence}"
            for d in decisions
        ])

        try:
            import openai
            client = openai.OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
            prompt = TEACHER_PROMPT.format(message=message, decisions=decisions_text[:4000])
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800
            )
            text = resp.choices[0].message.content.strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            parsed = json.loads(text)
        except Exception:
            parsed = _rule_based_teacher_parse(message)

        response_text = ""
        decision_id = parsed.get("decision_id")
        operation = parsed.get("operation", "explain")

        if operation == "split" and decision_id:
            dec = db.query(IntegrationDecision).filter(IntegrationDecision.id == decision_id).first()
            if dec:
                dec.action = "split"
                dec.teacher_override = True
                dec.teacher_feedback = message
                response_text = f"已将决策 {decision_id}（{dec.result_name}）改为拆分。知识点将保持独立。"
        elif operation == "merge" and parsed.get("target_nodes"):
            new_dec = IntegrationDecision(
                id=f"dec_teacher_{uuid.uuid4().hex[:8]}",
                action="merge",
                affected_nodes=[],
                result_name=" + ".join(parsed["target_nodes"]),
                reason=f"教师指令合并: {message}",
                confidence=1.0,
                teacher_override=True,
                teacher_feedback=message
            )
            db.add(new_dec)
            response_text = f"已创建新的合并决策，将 {', '.join(parsed['target_nodes'])} 合并为统一知识点。"
        elif operation == "remove" and decision_id:
            dec = db.query(IntegrationDecision).filter(IntegrationDecision.id == decision_id).first()
            if dec:
                dec.action = "remove"
                dec.teacher_override = True
                dec.teacher_feedback = message
                response_text = f"已将 {dec.result_name} 标记为删除。"
        elif operation == "keep":
            target = parsed.get("target_nodes", [])
            response_text = f"已保留知识点：{', '.join(target)}，压缩算法将不再删除它们。"
            from backend.database import KnowledgeNode
            for name in target:
                nodes = db.query(KnowledgeNode).filter(KnowledgeNode.name.like(f"%{name}%")).all()
                for n in nodes:
                    n.teacher_locked = True
        elif operation == "explain":
            if decision_id:
                dec = db.query(IntegrationDecision).filter(IntegrationDecision.id == decision_id).first()
                if dec:
                    response_text = f"决策 {decision_id}：{dec.action} - {dec.result_name}。理由：{dec.reason}。置信度：{dec.confidence}。{'（教师已修改）' if dec.teacher_override else ''}"
            else:
                response_text = f"关于「{message}」，系统当前有如下相关决策：\n{decisions_text[:1000]}\n请指定具体决策ID以进行操作。"
        else:
            response_text = f"收到您的反馈：「{message}」。已根据教学意图更新知识图谱整合方案。{parsed.get('reason', '')}"

        # Save assistant response
        resp_chat = ChatHistory(id=f"chat_{uuid.uuid4().hex[:12]}", role="assistant", content=response_text, related_decision_id=decision_id or "")
        db.add(resp_chat)
        db.commit()

        return {"response": response_text, "operation": operation, "parsed": parsed}
    finally:
        db.close()

def _rule_based_teacher_parse(message: str) -> dict:
    """Rule-based fallback for teacher message parsing."""
    msg = message.lower()
    if "分开" in msg or "拆分" in msg or "不是" in msg:
        return {"operation": "split", "decision_id": None, "target_nodes": [], "reason": "教师认为概念不同需要拆分"}
    elif "合并" in msg or "合并" in msg:
        return {"operation": "merge", "decision_id": None, "target_nodes": [], "reason": "教师要求合并"}
    elif "保留" in msg or "不要删" in msg or "保留" in msg:
        return {"operation": "keep", "decision_id": None, "target_nodes": [], "reason": "教师要求保留"}
    elif "删除" in msg or "删除" in msg or "冗余" in msg:
        return {"operation": "remove", "decision_id": None, "target_nodes": [], "reason": "教师认为冗余"}
    elif "为什么" in msg or "解释" in msg or "why" in msg:
        return {"operation": "explain", "decision_id": None, "target_nodes": [], "reason": "教师询问原因"}
    else:
        return {"operation": "explain", "decision_id": None, "target_nodes": [], "reason": "无法明确解析教师意图"}
