#!/usr/bin/env python
"""Bounded Agent evaluation against an isolated copy of the local textbook DB.

No model request is made without --live. --offline only checks evaluator logic;
it is explicitly not evidence about the real Agent or the real Judge model.
Keep --private-output under an ignored local directory: it contains source text.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
from contextlib import ExitStack, closing
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def normalized_lf_sha256(path: Path) -> str:
    """Compare source content across Git checkouts with different EOL settings."""
    content = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_cases(path: Path, maximum: int) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    cases = value.get("cases") if isinstance(value, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("invalid_case_file")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"] or case["id"] in seen:
            raise ValueError("invalid_or_duplicate_case_id")
        seen.add(case["id"])
        if case.get("expected_outcome", "draft_ready") not in {"draft_ready", "insufficient_evidence"}:
            raise ValueError("invalid_expected_outcome")
        if not isinstance(case.get("request"), dict):
            raise ValueError("invalid_case_request")
    return cases[:maximum]


def copy_source_db(source: Path, target: Path) -> None:
    """SQLite backup includes committed WAL data; the source connection is read-only."""
    source, target = source.resolve(), target.resolve()
    if not source.is_file() or source == target:
        raise ValueError("invalid_source_database")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(target)) as destination:
            original.backup(destination)
            existing = destination.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if ("jobs",) in existing:
                destination.execute("DELETE FROM jobs")
            destination.commit()


class MeteredClient:
    """Observe actual SDK responses without storing prompts, bodies or credentials."""
    def __init__(self, client, role, records):
        self.client, self.role, self.records = client, role, records
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        return MeteredClient(self.client.with_options(**kwargs), self.role, self.records)

    def close(self):
        return self.client.close()

    def create(self, **kwargs):
        started = time.monotonic()
        record = {"role": self.role, "model": kwargs.get("model"), "status": "failed"}
        try:
            response = self.client.chat.completions.create(**kwargs)
            usage = getattr(response, "usage", None)
            record.update(status="completed", finish_reason=getattr(response.choices[0], "finish_reason", None) if response.choices else None,
                          usage={key: getattr(usage, key, None) for key in ("prompt_tokens", "completion_tokens", "total_tokens")})
            return response
        except Exception as exc:
            record["error_code"] = type(exc).__name__
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.records.append(record)


def offline_report() -> dict:
    from backend.evaluation.agent_eval import control_data, validate_judgement, JudgeProtocolError, judgement_summary
    data, expected = control_data()
    data["claims"].append({"claim_id": "mixed_sources_group", "text": "两本教材的片段都规定先准备后实施，并且都要求核对结果。", "source_ids": ["S1", "S2"]})
    expected["mixed_sources_group"] = "insufficient"
    correct = {"claims": [{"claim_id": row["claim_id"], "label": expected[row["claim_id"]],
                            "source_ids": row["source_ids"], "reason": "受控协议自检，不是模型评分"} for row in data["claims"]], "rubric": []}
    accepted = validate_judgement(correct, data)
    checks = [{"id": "valid_protocol_accepted", "passed": accepted == correct},
              {"id": "known_bad_claims_do_not_pass", "passed": not judgement_summary(accepted)["passed"]}]
    for name, bad in (("missing_claim_rejected", {**correct, "claims": correct["claims"][:-1]}),
                      ("extra_field_rejected", {**correct, "passed": True}),
                      ("duplicate_claim_rejected", {**correct, "claims": [correct["claims"][0]] * 4})):
        try:
            validate_judgement(bad, data)
            passed = False
        except JudgeProtocolError:
            passed = True
        checks.append({"id": name, "passed": passed})
    return {"evaluation_version": 1, "mode": "offline_evaluator_self_check", "real_model_calls": 0,
            "passed": all(row["passed"] for row in checks), "checks": checks,
            "prelabelled_protocol_examples": [{"id": key, "label": label, "model_executed": False} for key, label in expected.items()],
            "note": "仅验证评测器协议，未运行真实Agent或真实Judge，不是模型效果评测。"}


def execute_live(args, temporary: Path) -> tuple[dict, dict]:
    # DATABASE_URL is fixed before importing any production modules; dotenv does
    # not override an already-present variable. Never modify the original DB.
    snapshot = temporary / "evaluation.sqlite3"
    if not args.controls_only:
        copy_source_db(args.source_db, snapshot)
    os.environ["DATABASE_URL"] = "sqlite:///" + snapshot.as_posix()
    os.environ["AGENT_MAX_STEPS"] = str(args.max_steps)
    os.environ["AGENT_MAX_RUNTIME_SECONDS"] = str(args.max_runtime_seconds)
    if args.source_chroma:
        source_chroma = args.source_chroma.resolve()
        if not source_chroma.is_dir():
            raise ValueError("invalid_chroma_directory")
        shutil.copytree(source_chroma, temporary / "chroma")
    os.environ["CHROMA_PERSIST_DIR"] = str(temporary / "chroma")

    from backend import config
    from backend.database import Base, engine, SessionLocal, Job, Chunk, Textbook, Chapter, Course, RagIndexState
    from backend.agents import course_agent, lesson_runtime, lesson_policy, rag_agent
    from backend.evaluation.agent_eval import (hard_checks, judge_input, run_judge, aggregate_runs,
                                               control_data, fingerprint, JudgeProtocolError, JUDGE_SYSTEM_PROMPT)
    from backend.services.llm_client import create_openai_client

    if not config.LLM_API_KEY:
        raise ValueError("model_not_configured")
    judge_model = args.judge_model or os.getenv("AGENT_JUDGE_MODEL") or config.LLM_MODEL
    Base.metadata.create_all(bind=engine)
    cases = [] if args.controls_only else load_cases(args.cases, args.max_cases)
    allowed = list(dict.fromkeys(value.strip() for value in args.textbook_ids.split(",") if value.strip()))
    requests = []
    with SessionLocal() as db:
        if cases and db.get(Course, args.course_id) is None:
            raise ValueError("evaluation_course_missing")
        index = db.get(RagIndexState, args.course_id) if cases else None
        if index and index.status == "ready" and index.embedding_available and not args.source_chroma:
            raise ValueError("ready_vector_index_requires_source_chroma_copy")
        for case in cases:
            request = copy.deepcopy(case["request"])
            books = request.get("textbook_ids") or allowed
            if not isinstance(books, list) or not books or len(books) > 12 or any(not isinstance(value, str) for value in books):
                raise ValueError("invalid_evaluation_scope")
            if allowed and not set(books).issubset(allowed):
                raise ValueError("case_outside_allowed_scope")
            request.update(course_id=args.course_id, textbook_ids=list(dict.fromkeys(books)))
            request.setdefault("audience", "护理专业一年级学生")
            request.setdefault("prior_knowledge", "已学习基础组织结构，尚未学习专科内容")
            request.setdefault("duration_minutes", 45)
            request.setdefault("question_count", 3)
            request.setdefault("requirements", ["核心概念"])
            request.setdefault("focus_terms", [])
            request.setdefault("context", {})
            # Validate input shape without calling the API or starting a queue.
            from backend.api.agent import AgentRunCreate
            AgentRunCreate.model_validate(request)
            rows = db.query(Textbook).filter(Textbook.course_id == args.course_id, Textbook.id.in_(books)).all()
            if {book.id for book in rows} != set(books):
                raise ValueError("evaluation_textbooks_missing")
            if any(book.parse_status != "completed" or book.structure_status not in {"confirmed", "legacy_confirmed"} for book in rows):
                raise ValueError("evaluation_requires_prepared_confirmed_textbooks")
            requests.append((case, request))
        scope = sorted({book for _, request in requests for book in request["textbook_ids"]})
        canonical = {chunk.id: {"course_id": args.course_id, "textbook_id": chunk.textbook_id,
                                "textbook": title, "chapter": chapter, "page_start": chunk.page_start,
                                "page_end": chunk.page_end, "section_path": chunk.section_path or [],
                                "content": chunk.content or ""}
                     for chunk, title, chapter in db.query(Chunk, Textbook.title, Chapter.title).join(
                         Textbook, Chunk.textbook_id == Textbook.id).join(Chapter, Chunk.chapter_id == Chapter.id).filter(
                         Textbook.course_id == args.course_id, Textbook.id.in_(scope), Chapter.textbook_id == Textbook.id).all()} if cases else {}
    public = {"evaluation_version": 1, "mode": "live", "label": args.label, "evaluation_run_id": args.run_id,
              "agent_model": config.LLM_MODEL, "judge_model": judge_model,
              "same_model": judge_model == config.LLM_MODEL, "same_provider": True,
              "judge_independence_note": "独立评分请求；同一服务商或模型家族仍可能产生相关偏差。",
              "case_set_sha256": fingerprint([{"case": case, "request": request} for case, request in requests]),
              "agent_code_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                     for path in ("backend/agents/lesson_policy.py", "backend/agents/lesson_runtime.py",
                                                  "backend/agents/lesson_contracts.py", "backend/agents/course_agent.py")},
              "evaluator_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                    for path in ("backend/evaluation/agent_eval.py", "scripts/run_agent_evaluation.py")},
              "rag_code_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                   for path in ("backend/agents/rag_agent.py", "backend/services/retrieval_service.py", "backend/api/rag.py")},
              "rag_code_normalized_lf_sha256": {path: normalized_lf_sha256(ROOT / path)
                                                 for path in ("backend/agents/rag_agent.py", "backend/services/retrieval_service.py", "backend/api/rag.py")},
              "code_hash_algorithm": {"raw_sha256": "SHA-256 of file bytes; Git CRLF/LF conversion can change this value without changing code.",
                                      "normalized_lf_sha256": "UTF-8-sig decode, CRLF/CR to LF, UTF-8 encode, then SHA-256."},
              "judge_system_prompt_sha256": hashlib.sha256(JUDGE_SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
              "source_scope_sha256": fingerprint({key: fingerprint(value) for key, value in sorted(canonical.items())}),
              "source_chunk_count": len(canonical), "isolated_database": True,
              "isolated_vector_copy": bool(args.source_chroma),
              "budgets": {"max_steps": args.max_steps, "max_runtime_seconds": args.max_runtime_seconds,
                          "max_cases": args.max_cases, "repeat": args.repeat},
              "pricing_cost": "not_collected", "runs": []}
    private = {"public": public, "runs": []}
    write_json(args.output, public)
    if args.judge_controls or args.controls_only:
        data, expected = control_data()
        result, detail = run_judge(data, model=judge_model)
        labels = {row["claim_id"]: row["label"] for row in (detail or {}).get("claims", [])}
        checks = [{"id": key, "expected": value, "actual": labels.get(key), "passed": labels.get(key) == value}
                  for key, value in expected.items()]
        public["judge_controls"] = {"status": result["status"], "passed": result["status"] == "graded" and all(row["passed"] for row in checks),
                                    "checks": checks, "usage": result.get("usage"), "elapsed_seconds": result["elapsed_seconds"],
                                    "request_attempted": result.get("request_attempted", False)}
        if result.get("error_code"):
            public["judge_controls"]["error_code"] = result["error_code"]
        private["judge_controls"] = {"input": data, "result": detail}
        write_json(args.output, public)
    for case, request in requests:
        for repetition in range(args.repeat):
            calls = []
            with SessionLocal() as db:
                job_id = "eval_" + hashlib.sha256(os.urandom(16)).hexdigest()[:16]
                db.add(Job(id=job_id, type="course_agent", status="pending", course_id=args.course_id,
                           payload=copy.deepcopy(request), result=course_agent.initial_agent_result(request)))
                db.commit()
            started = time.monotonic()
            with ExitStack() as stack:
                for role, module in (("policy", lesson_policy), ("draft", course_agent), ("rag_answer", rag_agent)):
                    def factory(*, timeout=60, call_role=role):
                        return MeteredClient(create_openai_client(timeout=timeout), call_role, calls)
                    stack.enter_context(patch.object(module, "create_openai_client", side_effect=factory))
                lesson_runtime.process_agent_loop(job_id)
            elapsed = round(time.monotonic() - started, 3)
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                state, status, error = copy.deepcopy(job.result or {}), job.status, job.error
            hard = hard_checks(request, state, status, canonical, expected_outcome=case.get("expected_outcome", "draft_ready"))
            artifact = state.get("lesson_draft") or state.get("artifact")
            grading_input = None
            detail = None
            judge = {"status": "not_applicable" if case.get("expected_outcome") == "insufficient_evidence" else "ungraded", "passed": False,
                     "error_code": "no_artifact"}
            if artifact:
                try:
                    grading_input = judge_input(request, artifact, canonical)
                    judge, detail = run_judge(grading_input, model=judge_model)
                except JudgeProtocolError as exc:
                    judge = {"status": "ungraded", "passed": False, "error_code": str(exc)}
            actions = state.get("trajectory") or []
            row = {"case_id": case["id"], "repetition": repetition + 1, "request_sha256": fingerprint(request),
                   "expected_outcome": case.get("expected_outcome", "draft_ready"), "status": status,
                   "stop_reason": state.get("stop_reason"), "error_code": error or None,
                   "elapsed_seconds": elapsed, "hard": hard, "judge": judge,
                   "budget": state.get("budget"), "generation_method": (artifact or {}).get("generation_method"),
                   "source_count": len(state.get("evidence") or []),
                   "actions": [{"action": item.get("action"), "status": item.get("status"),
                                "error_code": (item.get("observation") or {}).get("error_code")}
                               for item in actions], "model_calls": calls}
            public["runs"].append(row)
            private["runs"].append({"case_id": case["id"], "repetition": repetition + 1, "request": request,
                                     "state": state, "judge_input": grading_input, "judge_result": detail})
            # Progress is labels only; no exception text, prompts, or original text.
            print(json.dumps({"case_id": case["id"], "repetition": repetition + 1, "status": status,
                              "stop_reason": state.get("stop_reason"), "hard_passed": hard["passed"],
                              "judge_status": judge["status"], "judge_passed": judge["passed"]}, ensure_ascii=False), flush=True)
            write_json(args.output, public)
            if args.private_output:
                write_json(args.private_output, private)
    public["summary"] = aggregate_runs(public["runs"])
    all_calls = [call for row in public["runs"] for call in row["model_calls"]]
    judge_results = [row["judge"] for row in public["runs"]]
    if public.get("judge_controls"):
        judge_results.append(public["judge_controls"])
    public["usage"] = {"agent_model_calls": len(all_calls),
                       "agent_tokens_reported": sum((call.get("usage") or {}).get("total_tokens") or 0 for call in all_calls),
                       "agent_calls_without_usage": sum((call.get("usage") or {}).get("total_tokens") is None for call in all_calls),
                       "judge_request_attempts": sum(row.get("request_attempted", False) for row in judge_results),
                       "judge_tokens_reported": sum((row.get("usage") or {}).get("total_tokens") or 0 for row in judge_results),
                       "judge_calls_without_usage": sum(row.get("request_attempted", False) and (row.get("usage") or {}).get("total_tokens") is None for row in judge_results)}
    engine.dispose()
    return public, private


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--source-chroma", type=Path)
    parser.add_argument("--course-id", default="course_default")
    parser.add_argument("--textbook-ids", default="")
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/fixtures/agent_eval_cases.json")
    parser.add_argument("--max-cases", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-runtime-seconds", type=int, default=300)
    parser.add_argument("--judge-model")
    parser.add_argument("--judge-controls", action="store_true")
    parser.add_argument("--controls-only", action="store_true")
    parser.add_argument("--label", default="candidate")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    args.run_id = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
    if not 1 <= args.max_cases <= 30 or not 1 <= args.repeat <= 5 or not 4 <= args.max_steps <= 20 or not 30 <= args.max_runtime_seconds <= 900:
        parser.error("case/repeat/runtime bounds exceeded")
    if args.live and not args.controls_only and not args.source_db:
        parser.error("--live requires --source-db unless --controls-only")
    protected = {args.cases.resolve()}
    if args.source_db:
        protected.add(args.source_db.resolve())
    outputs = [path.resolve() for path in (args.output, args.private_output, args.markdown_output) if path]
    if any(path in protected for path in outputs) or len(outputs) != len(set(outputs)):
        parser.error("report must not overwrite input or another report")
    try:
        if args.offline:
            public, private = offline_report(), None
        else:
            local_temporary = ROOT / ".gstack"
            local_temporary.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="agent-eval-", dir=local_temporary) as temporary:
                try:
                    public, private = execute_live(args, Path(temporary))
                finally:
                    database = sys.modules.get("backend.database")
                    if database is not None:
                        database.engine.dispose()
        write_json(args.output, public)
        if args.private_output and private:
            write_json(args.private_output, private)
        if args.markdown_output:
            from backend.evaluation.agent_eval import render_markdown
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(render_markdown(public), encoding="utf-8")
        print(json.dumps({"report": str(args.output), "mode": public["mode"], "summary": public.get("summary"),
                          "self_check_passed": public.get("passed")}, ensure_ascii=False))
        return 0 if public.get("passed", True) else 1
    except Exception as exc:
        # Runtime messages may include provider URLs or bodies; only a bounded
        # identifier is public. A failed evaluation must never look successful.
        code = str(exc) if isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum() else type(exc).__name__
        # Preserve completed partial runs if an evaluator/cleanup failure occurs.
        failed_report = {"mode": "live" if args.live else "offline_evaluator_self_check", "status": "failed", "error_code": code,
                         "evaluation_run_id": args.run_id}
        if args.output.is_file():
            try:
                partial = json.loads(args.output.read_text(encoding="utf-8"))
                if isinstance(partial, dict) and partial.get("evaluation_run_id") == args.run_id and partial.get("mode") == "live":
                    failed_report = {**partial, "status": "failed", "error_code": code}
            except (ValueError, OSError):
                pass
        write_json(args.output, failed_report)
        print(json.dumps({"status": "failed", "error_code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
