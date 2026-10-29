"""Server-owned RAG transport boundary; evidence is always reloaded locally.

``endpoint`` and ``timeout`` are server configuration, never model tool arguments.
Input/scope errors raise ValueError. Transport or response failures return no
evidence and stable warning codes, without exposing URLs or exception details.
This module does not change retrieval, prompts, or the public RAG API.
"""
import json
import math
import os
from urllib.parse import urlsplit

import httpx

from backend.agents.rag_agent import query_rag
from backend.database import Chapter, Chunk, Course, SessionLocal, Textbook


MAX_QUESTION_LENGTH = 2000
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TIMEOUT_SECONDS = 30
_NO_EVIDENCE = "当前课程教材中未找到足够证据。"
_EVIDENCE_ONLY = "已保留可回查的教材原文，请基于下列来源重新核对结论。"
_METHODS = {"llm_grounded", "evidence_fallback", "no_evidence"}


def _result(transport, warnings=None):
    return {
        "answer": _NO_EVIDENCE, "items": [], "retrieval_trace": {},
        "answer_method": "no_evidence", "semantic_reviewed": False,
        "transport": transport, "warnings": list(warnings or []),
    }


def _validate_input(question, course_id, textbook_ids, mode, top_k):
    if not isinstance(question, str) or not 2 <= len(question.strip()) <= MAX_QUESTION_LENGTH:
        raise ValueError("question must contain 2 to 2000 characters")
    if not isinstance(course_id, str) or not course_id.strip() or len(course_id) > 128:
        raise ValueError("course_id is required")
    if not isinstance(textbook_ids, list) or not 1 <= len(textbook_ids) <= 12:
        raise ValueError("textbook_ids must select 1 to 12 textbooks")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 128 for value in textbook_ids):
        raise ValueError("textbook_ids contains an invalid identifier")
    if not isinstance(mode, str) or mode not in {"all", "compare"}:
        raise ValueError("mode must be all or compare")
    if type(top_k) is not int or not 1 <= top_k <= 15:
        raise ValueError("top_k must be an integer from 1 to 15")
    books = list(dict.fromkeys(value.strip() for value in textbook_ids))
    if mode == "compare" and len(books) < 2:
        raise ValueError("compare requires at least two textbooks")
    return question.strip(), course_id.strip(), books


def _check_scope(db, course_id, textbook_ids):
    if db.get(Course, course_id) is None:
        raise ValueError("course does not exist")
    rows = db.query(Textbook.id).filter(
        Textbook.course_id == course_id, Textbook.id.in_(textbook_ids),
    ).all()
    if {row[0] for row in rows} != set(textbook_ids):
        raise ValueError("all selected textbooks must belong to the course")


def _http_query(endpoint, payload, timeout):
    """Do not append a path, follow redirects, use env proxies, or log bodies."""
    try:
        parsed = urlsplit(endpoint)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not (
            parsed.username or parsed.password or parsed.fragment
        )
        # Validate a malformed port before httpx can include the URL in an error.
        parsed.port
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("RAG endpoint must be an HTTP query URL without credentials or fragments")
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout), follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", endpoint, json=payload) as response:
                if 300 <= response.status_code < 400:
                    return None, "rag_http_redirect_refused"
                if not 200 <= response.status_code < 300:
                    return None, "rag_http_error"
                length = response.headers.get("content-length", "")
                if length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
                    return None, "rag_response_too_large"
                body = bytearray()
                for part in response.iter_bytes(chunk_size=65536):
                    if len(body) + len(part) > MAX_RESPONSE_BYTES:
                        return None, "rag_response_too_large"
                    body.extend(part)
                if not body.strip():
                    return None, "rag_empty_response"
                return json.loads(body), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "rag_invalid_response"
    except Exception:
        # Exception text can include endpoint credentials, proxy URLs, or bodies.
        return None, "rag_http_unavailable"


def _local_items(raw_citations, course_id, textbook_ids, top_k):
    warnings, citations = [], []
    for citation in raw_citations:
        chunk_id = citation.get("chunk_id") if isinstance(citation, dict) else None
        if not isinstance(chunk_id, str) or not chunk_id or len(chunk_id) > 128:
            warnings.append("rag_citation_rejected")
            continue
        citations.append(citation)
    chunk_ids = {citation["chunk_id"] for citation in citations}
    with SessionLocal() as db:
        # Recheck after a potentially slow remote call: scope may have changed.
        _check_scope(db, course_id, textbook_ids)
        rows = db.query(Chunk, Textbook, Chapter).join(
            Textbook, Chunk.textbook_id == Textbook.id,
        ).join(Chapter, Chunk.chapter_id == Chapter.id).filter(
            Chunk.id.in_(chunk_ids), Textbook.course_id == course_id,
            Textbook.id.in_(textbook_ids), Chapter.textbook_id == Chunk.textbook_id,
        ).all() if chunk_ids else []
        local = {chunk.id: (chunk, book, chapter) for chunk, book, chapter in rows}
        items, seen = [], set()
        for citation in citations:
            row = local.get(citation["chunk_id"])
            if row is None:
                warnings.append("rag_citation_rejected")
                continue
            chunk, book, chapter = row
            if any(key in citation and citation[key] != expected for key, expected in (
                ("course_id", course_id), ("textbook_id", book.id), ("chapter_id", chapter.id),
            )):
                warnings.append("rag_citation_rejected")
                continue
            if not (chunk.content or "").strip():
                warnings.append("rag_empty_chunk_rejected")
                continue
            if chunk.id in seen:
                warnings.append("rag_duplicate_citation")
                continue
            seen.add(chunk.id)
            if len(items) >= top_k:
                warnings.append("rag_citations_trimmed")
                continue
            retrievers = citation.get("retrievers")
            items.append({
                "id": chunk.id, "textbook_id": book.id, "textbook": book.title,
                "chapter_id": chapter.id, "chapter": chapter.title,
                "section_path": [value for value in (chunk.section_path or []) if isinstance(value, str)],
                "page_start": chunk.page_start or 0,
                "page_end": chunk.page_end or chunk.page_start or 0,
                "content": chunk.content,
                "retrievers": list(dict.fromkeys(value for value in retrievers if value in {"bm25", "vector", "graph"}))
                if isinstance(retrievers, list) and all(isinstance(value, str) for value in retrievers) else [],
            })
    return items, list(dict.fromkeys(warnings))


def query_rag_tool(question, course_id, textbook_ids, mode="all", top_k=8, *, endpoint=None, timeout=30):
    """Query existing RAG, then return only locally verified, scoped full chunks.

    The optional AGENT_RAG_URL is the complete server-owned query endpoint.
    A shorter timeout may be configured; it cannot exceed 30 seconds. HTTP
    responses are limited to 1 MiB. Source validation is not semantic review.
    """
    question, course_id, textbook_ids = _validate_input(question, course_id, textbook_ids, mode, top_k)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive number")
    timeout = min(timeout, MAX_TIMEOUT_SECONDS)
    endpoint = os.environ.get("AGENT_RAG_URL", "") if endpoint is None else endpoint
    if not isinstance(endpoint, str):
        raise ValueError("RAG endpoint must be a string")
    endpoint = endpoint.strip()
    transport = "http" if endpoint else "internal"
    with SessionLocal() as db:
        _check_scope(db, course_id, textbook_ids)
    payload = {"question": question, "course_id": course_id, "textbook_ids": textbook_ids, "mode": mode, "top_k": top_k}
    if endpoint:
        raw, warning = _http_query(endpoint, payload, timeout)
        if warning:
            return _result(transport, [warning])
    else:
        try:
            raw = query_rag(**payload)
        except Exception:
            return _result(transport, ["rag_internal_unavailable"])
    if not isinstance(raw, dict) or not isinstance(raw.get("citations"), list) or len(raw["citations"]) > 100:
        return _result(transport, ["rag_invalid_response"])
    items, warnings = _local_items(raw["citations"], course_id, textbook_ids, top_k)
    result = _result(transport, warnings)
    result["items"] = items
    trace = raw.get("retrieval_trace")
    result["retrieval_trace"] = trace if isinstance(trace, dict) else {}
    if items:
        answer, method = raw.get("answer"), raw.get("answer_method")
        if warnings or not isinstance(answer, str) or not answer.strip() or not isinstance(method, str) or method not in _METHODS or method == "no_evidence":
            # Removing sources invalidates upstream [S#] numbering and coverage.
            result.update(answer=_EVIDENCE_ONLY, answer_method="evidence_fallback")
        else:
            result.update(answer=answer, answer_method=method)
    return result
