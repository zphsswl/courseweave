"""Shared, sanitized runtime health for the configured language model."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time

from backend.config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER
from backend.services.llm_client import create_openai_client


_lock = threading.Lock()
_last_probe_monotonic = 0.0
_state = {
    "availability": "not_configured" if not LLM_API_KEY else "unknown",
    "message": "未配置模型 API Key" if not LLM_API_KEY else "尚未检测模型可用性",
    "last_checked_at": None,
    "last_error_code": None,
}
PROBE_CACHE_SECONDS = 300


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_model_error(exc: Exception) -> dict:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    text = str(exc).lower()
    if status_code == 402 or "402" in text or "balance" in text or "余额" in text or "insufficient" in text:
        return {
            "availability": "balance_insufficient",
            "message": "模型余额不足，系统已降级为规则抽取与原文证据模式",
            "last_error_code": "402",
        }
    if status_code in {401, 403} or "authentication" in text or "api key" in text:
        return {
            "availability": "authentication_failed",
            "message": "模型鉴权失败，系统已降级运行；请检查 API Key",
            "last_error_code": str(status_code or "auth"),
        }
    if "timeout" in text or "timed out" in text:
        return {
            "availability": "unavailable",
            "message": "模型请求超时，系统已暂时降级运行",
            "last_error_code": "timeout",
        }
    if "connection" in text or "connecterror" in text or "winerror 10061" in text:
        return {
            "availability": "unavailable",
            "message": "无法连接模型服务，系统已暂时降级；请检查网络或代理设置",
            "last_error_code": "connection_failed",
        }
    if status_code in {400, 404} and ("model" in text or "模型" in text):
        return {
            "availability": "degraded",
            "message": "当前模型名称不可用，系统已降级；请检查模型配置",
            "last_error_code": "model_not_found",
        }
    if "probe_empty_response" in text:
        return {
            "availability": "degraded",
            "message": "模型连通但健康检测返回空内容，系统已暂时降级",
            "last_error_code": "empty_response",
        }
    return {
        "availability": "degraded",
        "message": "模型调用失败，系统已降级为规则抽取与原文证据模式",
        "last_error_code": str(status_code or "runtime_error"),
    }


def record_model_success() -> None:
    global _last_probe_monotonic
    with _lock:
        _state.update({
            "availability": "available",
            "message": "模型可用",
            "last_checked_at": _utc_now(),
            "last_error_code": None,
        })
        _last_probe_monotonic = time.monotonic()


def record_model_failure(exc: Exception) -> None:
    global _last_probe_monotonic
    classified = classify_model_error(exc)
    with _lock:
        _state.update(classified)
        _state["last_checked_at"] = _utc_now()
        _last_probe_monotonic = time.monotonic()


def get_model_runtime_status() -> dict:
    with _lock:
        snapshot = dict(_state)
    snapshot.update({
        "degraded": snapshot["availability"] not in {"available", "unknown"},
        "fallback_mode": "规则抽取 + BM25 检索 + 原文证据",
        "provider": LLM_PROVIDER,
        "model": LLM_MODEL,
        "api_key_configured": bool(LLM_API_KEY),
    })
    return snapshot


def probe_model(force: bool = False) -> dict:
    global _last_probe_monotonic
    if not LLM_API_KEY:
        return get_model_runtime_status()
    with _lock:
        cache_fresh = time.monotonic() - _last_probe_monotonic < PROBE_CACHE_SECONDS
    if cache_fresh and not force:
        return get_model_runtime_status()
    try:
        client = create_openai_client(timeout=20)
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": "只输出一个英文单词 OK，不要解释。"}],
            temperature=0,
            max_tokens=64,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content if response.choices else None
        if not content or not content.strip():
            raise RuntimeError("probe_empty_response")
        record_model_success()
    except Exception as exc:
        record_model_failure(exc)
    return get_model_runtime_status()
