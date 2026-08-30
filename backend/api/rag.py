from fastapi import APIRouter, HTTPException, Query

from backend.agents.rag_agent import query_rag, build_rag_index, query_node_rag
from backend.database import DEFAULT_COURSE_ID
from backend.services.retrieval_service import get_index_status


router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.post("/index")
def index_rag(payload: dict | None = None):
    course_id = (payload or {}).get("course_id") or DEFAULT_COURSE_ID
    try:
        return build_rag_index(course_id)
    except Exception as exc:
        raise HTTPException(500, f"索引建立失败: {str(exc)}") from exc


@router.get("/status")
def rag_status(course_id: str = Query(DEFAULT_COURSE_ID)):
    return get_index_status(course_id)


@router.post("/query")
def ask_question(payload: dict):
    question = str(payload.get("question", "")).strip()
    if len(question) < 2:
        raise HTTPException(400, "问题不能为空且至少需要 2 个字符")
    mode = payload.get("mode", "all")
    if mode not in {"all", "compare"}:
        raise HTTPException(400, "mode 仅支持 all 或 compare")
    textbook_ids = payload.get("textbook_ids")
    if textbook_ids is not None and not isinstance(textbook_ids, list):
        raise HTTPException(400, "textbook_ids 必须是数组")
    if mode == "compare" and textbook_ids and len(set(textbook_ids)) < 2:
        raise HTTPException(400, "跨教材对比至少选择两本教材")
    try:
        return query_rag(
            question=question,
            course_id=payload.get("course_id") or DEFAULT_COURSE_ID,
            textbook_ids=textbook_ids,
            mode=mode,
            top_k=int(payload.get("top_k", 8)),
        )
    except Exception as exc:
        raise HTTPException(500, f"教材检索失败: {str(exc)}") from exc


@router.post("/node-query")
def ask_node_question(payload: dict):
    node_id = str(payload.get("node_id", "")).strip()
    question = str(payload.get("question", "")).strip()
    if not node_id:
        raise HTTPException(400, "缺少 node_id")
    if not question:
        raise HTTPException(400, "问题不能为空")
    try:
        return query_node_rag(node_id, question, payload.get("course_id"))
    except Exception as exc:
        raise HTTPException(500, f"节点检索失败: {str(exc)}") from exc
