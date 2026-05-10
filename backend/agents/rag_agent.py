from backend.config import LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
from backend.database import SessionLocal, Chunk, KnowledgeNode, KnowledgeEdge
from backend.services.embeddings import embed_text
from backend.services.vector_store import build_index, search_index

RAG_PROMPT = """你是医学教材知识库问答Agent。
你只能依据给定的教材片段回答问题，不允许使用外部知识。
如果片段中没有答案，回答"当前知识库中未找到相关信息"。
回答必须包含引用，引用格式为：[教材名称, 章节名称, 第X页]。
不要编造页码、章节或教材名称。

教材片段：
{context}

问题：{question}

回答："""

NODE_RAG_PROMPT = """你是医学教材节点问答助手。
你只能依据当前知识节点、关联节点和检索到的教材原文回答。

当前节点：{node_name}（类别：{node_category}）
定义：{node_definition}
来源：{textbook}，{chapter}，第{page}页

关联关系：
{neighbor_info}

教材原文片段：
{context}

用户问题：{question}

要求：
1. 先直接回答问题。
2. 如果涉及关系，说明是前置依赖、并列、包含还是应用。
3. 必须给引用：[教材, 章节, 第X页]。
4. 如果依据不足，回答"当前节点上下文中未找到相关信息"。

回答："""

def build_rag_index() -> dict:
    db = SessionLocal()
    try:
        chunks = db.query(Chunk).all()
        if not chunks:
            return {"indexed": 0, "message": "No chunks to index"}

        # Skip ChromaDB/sentence-transformers to avoid segfault in this environment
        # RAG uses direct keyword search on chunks instead
        return {"indexed": len(chunks), "method": "direct_search",
                "message": f"已就绪 {len(chunks)} 个知识块，使用直接检索模式。无需 ChromaDB。"}
    finally:
        db.close()

def query_rag(question: str) -> dict:
    # Use direct keyword search as primary (avoids ChromaDB/sentence-transformers segfault)
    results = _direct_chunk_search(question, top_k=8)

    if not results:
        return {"answer": "当前知识库中未找到相关信息", "citations": [], "source_chunks": []}

    top5 = results[:5]
    context = "\n\n".join([f"[{r['metadata'].get('textbook', '')}, {r['metadata'].get('chapter', '')}, 第{r['metadata'].get('page', 0)}页]\n{r['content']}" for r in top5])

    try:
        import openai
        client = openai.OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        prompt = RAG_PROMPT.format(context=context[:6000], question=question)
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1500
        )
        answer = resp.choices[0].message.content
    except Exception:
        answer = _fallback_answer(question, top5)

    citations = []
    for r in top5:
        citations.append({
            "textbook": r["metadata"].get("textbook", ""),
            "chapter": r["metadata"].get("chapter", ""),
            "page": r["metadata"].get("page", 0),
            "relevance_score": round(1 - r.get("distance", 0), 3)
        })

    source_chunks = [r["content"][:500] for r in top5]

    return {"answer": answer, "citations": citations, "source_chunks": source_chunks}

def _direct_chunk_search(question: str, top_k: int = 8) -> list:
    """Direct keyword search on chunks as fallback when ChromaDB is unavailable."""
    db = SessionLocal()
    try:
        chunks = db.query(Chunk).all()
        if not chunks:
            return []
        # Use substring matching for better relevance
        scored = []
        for c in chunks:
            score = 0
            content_lower = c.content
            # Exact substring match bonus
            for q_char in question:
                if q_char in content_lower:
                    score += 1
            # Bigram overlap bonus (2-char sequences)
            q_bigrams = {question[i:i+2] for i in range(len(question)-1)}
            for bg in q_bigrams:
                if bg in content_lower:
                    score += 2
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, c in scored[:top_k]:
            results.append({
                "id": c.id,
                "content": c.content,
                "metadata": {
                    "textbook": c.textbook_title or "",
                    "chapter": c.chapter_title or "",
                    "page": c.page_start or 1,
                },
                "distance": 1.0 - min(score / max(len(question) * 3, 1), 0.99),
            })
        return results
    finally:
        db.close()

def _fallback_answer(question: str, results: list) -> str:
    if not results:
        return "当前知识库中未找到相关信息"
    best = results[0]
    return f"根据教材内容：{best['content'][:300]}...\n[{best['metadata'].get('textbook', '')}, {best['metadata'].get('chapter', '')}, 第{best['metadata'].get('page', 0)}页]"


def query_node_rag(node_id: str, question: str) -> dict:
    """Query with node context: node definition + neighbor nodes + same-chapter chunks."""
    db = SessionLocal()
    try:
        node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
        if not node:
            return {"answer": "未找到该知识点节点", "citations": [], "source_chunks": []}

        # Get neighbor edges (1-hop)
        edges_out = db.query(KnowledgeEdge).filter(KnowledgeEdge.source == node_id).all()
        edges_in = db.query(KnowledgeEdge).filter(KnowledgeEdge.target == node_id).all()

        neighbor_ids = set()
        neighbor_info_lines = []
        for e in edges_out:
            neighbor_ids.add(e.target)
            neighbor_info_lines.append(
                f"- {node.name} --[{e.relation_type}]--> {e.target}：{e.description or ''}"
            )
        for e in edges_in:
            neighbor_ids.add(e.source)
            neighbor_info_lines.append(
                f"- {e.source} --[{e.relation_type}]--> {node.name}：{e.description or ''}"
            )
        neighbor_info = "\n".join(neighbor_info_lines) if neighbor_info_lines else "（无已建立的关联关系）"

        # Get same-chapter chunks for context
        chunks = db.query(Chunk).filter(
            Chunk.textbook_id == node.textbook_id,
            Chunk.chapter_title == node.chapter_title,
        ).limit(5).all()

        context = ""
        if node.source_paragraph:
            context += f"[{node.textbook_title}, {node.chapter_title}, 第{node.page}页]\n{node.source_paragraph}\n\n"
        for ck in chunks:
            if ck.content not in context:
                context += f"[{ck.textbook_title or node.textbook_title}, {ck.chapter_title or node.chapter_title}, 第{ck.page_start}页]\n{ck.content[:500]}\n\n"

        if not context.strip():
            context = node.definition or "（无原文上下文）"

        try:
            import openai
            client = openai.OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
            prompt = NODE_RAG_PROMPT.format(
                node_name=node.name,
                node_category=node.category or "核心概念",
                node_definition=node.definition or "（无定义）",
                textbook=node.textbook_title,
                chapter=node.chapter_title,
                page=node.page or node.page_start or 1,
                neighbor_info=neighbor_info,
                context=context[:5000],
                question=question,
            )
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=1000,
            )
            answer = resp.choices[0].message.content
        except Exception:
            answer = f"根据《{node.textbook_title}》{node.chapter_title}，「{node.name}」的定义为：{node.definition}\n\n关联关系：\n{neighbor_info}\n\n关于「{question}」：当前节点上下文中未找到足够信息，建议在教材问答中进行全局检索。"

        citations = [{
            "textbook": node.textbook_title,
            "chapter": node.chapter_title,
            "page": node.page or 1,
            "relevance_score": 1.0,
        }]
        source_chunks = [node.source_paragraph] if node.source_paragraph else []

        return {"answer": answer, "citations": citations, "source_chunks": source_chunks}
    finally:
        db.close()
