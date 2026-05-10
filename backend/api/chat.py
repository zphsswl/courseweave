from fastapi import APIRouter, HTTPException
from backend.database import SessionLocal, IntegrationDecision, ChatHistory
from backend.agents.teacher_dialogue_agent import process_teacher_message

router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat")
def teacher_chat(payload: dict):
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(400, "消息不能为空")
    try:
        return process_teacher_message(message)
    except Exception as e:
        return {"response": f"处理出错: {str(e)}", "operation": "error"}

@router.get("/decisions")
def list_decisions(skip: int = 0, limit: int = 50):
    db = SessionLocal()
    try:
        decisions = db.query(IntegrationDecision).order_by(
            IntegrationDecision.confidence.desc()
        ).offset(skip).limit(limit).all()
        return [{
            "id": d.id,
            "action": d.action,
            "affected_nodes": d.affected_nodes,
            "result_node": d.result_node,
            "result_name": d.result_name,
            "reason": d.reason,
            "confidence": d.confidence,
            "teacher_override": d.teacher_override,
            "teacher_feedback": d.teacher_feedback,
            "created_at": d.created_at.isoformat() if d.created_at else ""
        } for d in decisions]
    finally:
        db.close()

@router.patch("/decisions/{decision_id}")
def update_decision(decision_id: str, payload: dict):
    db = SessionLocal()
    try:
        dec = db.query(IntegrationDecision).filter(IntegrationDecision.id == decision_id).first()
        if not dec:
            raise HTTPException(404, "决策不存在")
        if "action" in payload:
            dec.action = payload["action"]
        if "reason" in payload:
            dec.reason = payload["reason"]
        dec.teacher_override = True
        dec.teacher_feedback = payload.get("feedback", "")
        db.commit()
        return {"status": "updated", "id": decision_id}
    finally:
        db.close()

@router.get("/chat/history")
def chat_history(skip: int = 0, limit: int = 50):
    db = SessionLocal()
    try:
        chats = db.query(ChatHistory).order_by(ChatHistory.created_at.desc()).offset(skip).limit(limit).all()
        return [{"id": c.id, "role": c.role, "content": c.content, "related_decision_id": c.related_decision_id, "created_at": c.created_at.isoformat() if c.created_at else ""} for c in chats]
    finally:
        db.close()
