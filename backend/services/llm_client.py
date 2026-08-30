"""Create OpenAI-compatible clients with explicit proxy behavior.

Local desktop environments often inject HTTP(S)_PROXY values for unrelated
tools.  Letting httpx consume them implicitly can make an otherwise healthy
model endpoint look unavailable.  Proxy use is therefore opt-in through
LLM_TRUST_ENV_PROXY.
"""

from __future__ import annotations

import openai

from backend.config import LLM_API_KEY, LLM_BASE_URL, LLM_TRUST_ENV_PROXY


def create_openai_client(*, timeout: float = 60) -> openai.OpenAI:
    return openai.OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        timeout=timeout,
        http_client=openai.DefaultHttpxClient(trust_env=LLM_TRUST_ENV_PROXY),
    )
