"""Strict, database-free contracts for the single lesson agent's next action."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


LessonAction = Literal[
    "inspect_course", "query_rag", "read_source", "write_draft",
    "validate_draft", "ask_teacher", "finish",
]


class DecisionValidationError(ValueError):
    """A rejected action; messages never echo model text or supplied arguments."""

    def __init__(self, code: str, issues: list[dict] | None = None):
        self.code = code
        self.issues = issues or []
        super().__init__(f"备课动作无效：{code}")


def _safe_issues(error: ValidationError, prefix: str = '') -> list[dict]:
    """Expose only server-defined field names/types, never model values or keys."""
    fields = {'action', 'arguments', 'summary', 'question', 'textbook_ids', 'mode',
              'top_k', 'chunk_id', 'instructions', 'options'}
    result = []
    for issue in error.errors(include_input=False, include_url=False)[:5]:
        parts = [prefix] if prefix else []
        for part in issue.get('loc', ())[:4]:
            parts.append(str(part) if isinstance(part, int) else part if part in fields else '<extra_field>')
        kind = issue.get('type', '')
        result.append({'field': '.'.join(parts), 'type': kind if re.fullmatch(r'[a-z_]{1,60}', kind) else 'invalid'})
    return result


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Decision(_StrictModel):
    action: LessonAction
    arguments: dict[str, Any]
    summary: str = Field(min_length=1, max_length=300)


class _NoArguments(_StrictModel):
    pass


class _QueryArguments(_StrictModel):
    question: str = Field(min_length=2, max_length=500)
    textbook_ids: list[str] = Field(default_factory=list, max_length=12)
    mode: Literal["all", "compare"] = "all"
    top_k: int = Field(default=8, ge=3, le=15)


class _ReadArguments(_StrictModel):
    chunk_id: str = Field(min_length=1, max_length=160)


class _WriteArguments(_StrictModel):
    instructions: str = Field(default="", max_length=2000)


class _AskArguments(_StrictModel):
    question: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=4)


class _FinishArguments(_StrictModel):
    summary: str = Field(default="", max_length=500)


_ARGUMENT_MODELS = {
    "inspect_course": _NoArguments,
    "query_rag": _QueryArguments,
    "read_source": _ReadArguments,
    "write_draft": _WriteArguments,
    "validate_draft": _NoArguments,
    "ask_teacher": _AskArguments,
    "finish": _FinishArguments,
}


def _local_id(value: str) -> bool:
    # IDs name server-owned records, never remote resources or filesystem paths.
    return bool(
        value and len(value) <= 160 and value == value.strip()
        and not any(char in value for char in ("/", "\\"))
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
        and not value.lower().startswith(("http:", "https:", "file:", "ftp:", "data:", "javascript:", "www."))
        and value not in {".", ".."}
    )


def validate_decision(raw: Any, payload: dict) -> Decision:
    """Parse a model action and normalize defaults inside the immutable book scope.

    Source membership is checked again by the read_source tool against the DB;
    this layer intentionally has no database or network access.
    """
    if isinstance(raw, str):
        if len(raw) > 32768:
            raise DecisionValidationError("decision_too_large")
        try:
            raw = json.loads(raw)
        except (ValueError, RecursionError):
            raise DecisionValidationError("invalid_json") from None
    if isinstance(raw, Decision):
        raw = raw.model_dump()
    try:
        decision = Decision.model_validate(raw)
    except ValidationError as exc:
        raise DecisionValidationError("invalid_schema", _safe_issues(exc)) from None
    except TypeError:
        raise DecisionValidationError("invalid_schema") from None
    try:
        arguments = _ARGUMENT_MODELS[decision.action].model_validate(decision.arguments).model_dump()
    except ValidationError as exc:
        raise DecisionValidationError("invalid_arguments", _safe_issues(exc, 'arguments')) from None
    except TypeError:
        raise DecisionValidationError("invalid_arguments") from None
    if decision.action == "query_rag":
        scope = payload.get("textbook_ids") if isinstance(payload, dict) else None
        if not isinstance(scope, list) or not scope or any(not isinstance(value, str) or not _local_id(value) for value in scope):
            raise DecisionValidationError("invalid_task_scope")
        requested = arguments["textbook_ids"] or scope
        if any(not _local_id(value) for value in requested) or not set(requested).issubset(scope):
            raise DecisionValidationError("textbook_scope_violation")
        arguments["textbook_ids"] = list(dict.fromkeys(requested))
    if decision.action == "read_source" and not _local_id(arguments["chunk_id"]):
        raise DecisionValidationError("invalid_source_id")
    if decision.action == "ask_teacher":
        if any(not option.strip() or len(option) > 500 for option in arguments["options"]):
            raise DecisionValidationError("invalid_teacher_options")
        arguments["options"] = [option.strip() for option in arguments["options"]]
    return Decision(action=decision.action, arguments=arguments, summary=decision.summary)


def decision_fingerprint(decision: Decision) -> str:
    """Identify repeated execution, independent of the public summary's wording."""
    arguments = dict(decision.arguments)
    if decision.action == "query_rag":
        arguments["textbook_ids"] = sorted(set(arguments.get("textbook_ids") or []))
    elif decision.action == "finish":
        arguments = {}  # Rewording a delivery summary does not change the stop action.
    encoded = json.dumps({"action": decision.action, "arguments": arguments},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
