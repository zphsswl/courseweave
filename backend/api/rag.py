from fastapi import APIRouter, HTTPException
from backend.agents.rag_agent import query_rag, build_rag_index, query_node_rag
from backend.database import SessionLocal, Chunk, KnowledgeNode, KnowledgeEdge

router = APIRouter(prefix="/api/rag", tags=["rag"])

@router.post("/index")
def index_rag():
    try:
        result = build_rag_index()
        return result
    except Exception as e:
        raise HTTPException(500, f"索引建立失败: {str(e)}")

@router.get("/status")
def rag_status():
    chunk_count = 0
    try:
        db = SessionLocal()
        chunk_count = db.query(Chunk).count()
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass

    # Skip ChromaDB check entirely — native library causes segfault in this env.
    # RAG uses in-memory fallback when Chroma is unavailable.
    if chunk_count == 0:
        status = "no_chunks"
        message = "尚未解析教材，无法构建 RAG 索引。请先上传并解析教材。"
    else:
        status = "ready"
        message = f"RAG 就绪：{chunk_count} 个知识块可用于问答（使用内置检索引擎）。"

    return {
        "indexed": True,
        "status": status,
        "message": message,
        "chunk_count": chunk_count,
        "chroma_count": chunk_count,
    }

@router.post("/query")
def ask_question(payload: dict):
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    if len(question) < 2:
        raise HTTPException(400, "问题过短")
    try:
        return query_rag(question)
    except Exception as e:
        return {"answer": f"查询出错: {str(e)}", "citations": [], "source_chunks": []}

@router.post("/node-query")
def ask_node_question(payload: dict):
    """Query with node context — searches node + neighbors + same-chapter chunks."""
    node_id = payload.get("node_id", "").strip()
    question = payload.get("question", "").strip()
    if not node_id:
        raise HTTPException(400, "缺少 node_id")
    if not question:
        raise HTTPException(400, "问题不能为空")
    try:
        return query_node_rag(node_id, question)
    except Exception as e:
        return {"answer": f"查询出错: {str(e)}", "citations": [], "source_chunks": []}
