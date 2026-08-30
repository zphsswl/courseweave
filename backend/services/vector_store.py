"""Vector store service — ChromaDB with lazy import to avoid segfault."""
import os
import re
from backend.config import CHROMA_PERSIST_DIR

_client = None

def _ensure_chroma():
    """Lazy-import chromadb only when actually needed."""
    global _client
    if _client is not None:
        return _client
    try:
        import chromadb
        from chromadb.config import Settings
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        return _client
    except Exception:
        return None

def get_chroma_client():
    return _ensure_chroma()

def _collection_name(course_id: str = "course_default"):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", course_id)
    return f"textbook_chunks_{safe}"[:63]


def build_index(chunks: list[dict], embeddings: list[list[float]], course_id: str = "course_default"):
    client = _ensure_chroma()
    if client is None:
        return False
    try:
        client.delete_collection(_collection_name(course_id))
    except Exception:
        pass
    try:
        collection = client.create_collection(_collection_name(course_id), metadata={"hnsw:space": "cosine"})
        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            batch_emb = embeddings[i:i + batch_size]
            ids = [c["id"] for c in batch]
            docs = [c["content"] for c in batch]
            metas = [{
                "course_id": course_id,
                "textbook_id": c.get("textbook_id", ""),
                "textbook": c["textbook"],
                "chapter": c["chapter"],
                "page": c["page"],
                "page_end": c.get("page_end", c["page"]),
            } for c in batch]
            collection.add(ids=ids, embeddings=batch_emb, documents=docs, metadatas=metas)
        return True
    except Exception:
        return False

def search_index(query_embedding: list[float], top_k: int = 8, course_id: str = "course_default") -> list[dict]:
    client = _ensure_chroma()
    if client is None:
        return []
    try:
        collection = client.get_collection(_collection_name(course_id))
        results = collection.query(query_embeddings=[query_embedding], n_results=top_k)
        items = []
        if results.get("ids") and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                items.append({
                    "id": results["ids"][0][i],
                    "content": results.get("documents", [[""]])[0][i] if results.get("documents") else "",
                    "metadata": results.get("metadatas", [[""]])[0][i] if results.get("metadatas") else {},
                    "distance": results.get("distances", [[0]])[0][i] if results.get("distances") else 0,
                })
        return items
    except Exception:
        return []
