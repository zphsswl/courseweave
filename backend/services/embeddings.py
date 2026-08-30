"""Embedding service — lazy import to avoid segfault on module load."""
import numpy as np
from backend.config import EMBEDDING_MODEL

_embedding_model = None

def _get_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
        except Exception:
            return None
    return _embedding_model

def embeddings_available() -> bool:
    return _get_model() is not None


def embed_texts(texts: list[str], allow_fallback: bool = True) -> list[list[float]]:
    model = _get_model()
    if model is None:
        return _fallback_embed(texts) if allow_fallback else []
    try:
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()
    except Exception:
        return _fallback_embed(texts) if allow_fallback else []

def embed_text(text: str, allow_fallback: bool = True) -> list[float]:
    embeddings = embed_texts([text], allow_fallback=allow_fallback)
    return embeddings[0] if embeddings else []

def cosine_similarity(a: list[float], b: list[float]) -> float:
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-8))

def _fallback_embed(texts: list[str]) -> list[list[float]]:
    import hashlib
    results = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        vec = []
        for i in range(0, 32, 4):
            val = int.from_bytes(h[i:i+4], 'big') / 0xFFFFFFFF
            vec.append(val * 2 - 1)
        while len(vec) < 384:
            vec.append(0.0)
        results.append(vec[:384])
    return results
