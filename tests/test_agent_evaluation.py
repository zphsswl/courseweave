"""Evaluator tests use constructed sources; they do not claim real model quality."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
    from backend.agents.course_agent import _normalize_artifact, _citations
    from backend.evaluation.agent_eval import (
        JudgeProtocolError, aggregate_runs, control_data, hard_checks, judge_input,
        judgement_summary, run_judge, validate_judgement, render_markdown,
    )

_spec = importlib.util.spec_from_file_location("agent_evaluation_cli", Path(__file__).parents[1] / "scripts/run_agent_evaluation.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class AgentEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.request = {"course_id": "test_course", "topic": "模块流程", "goal": "讲解模块流程并核对结果",
                        "textbook_ids": ["book_a"], "duration_minutes": 20, "question_count": 1,
                        "audience": "一年级学生", "prior_knowledge": "基础模块", "requirements": ["核心概念"]}
        source = {"id": "chunk_a", "textbook_id": "book_a", "textbook": "教材甲", "chapter": "流程",
                  "page_start": 2, "page_end": 2, "content": "模块流程先准备后实施，最后核对结果。", "section_path": ["流程"]}
        self.canonical = {"chunk_a": {**source, "course_id": "test_course"}}
        self.artifact = _normalize_artifact({
            "title": "模块课堂", "executive_summary": "模块流程先准备后实施，最后核对结果。",
            "teaching_objectives": ["说出模块流程顺序"],
            "knowledge_sequence": [{"title": "模块顺序", "explanation": "先准备后实施再核对", "source_ids": ["S1"]}],
            "lesson_blocks": [{"title": "流程讲解", "content": "依据原文讲解与练习流程", "minutes": 20, "source_ids": ["S1"]}],
            "classroom_questions": ["准备之后是什么阶段？"],
        }, self.request["topic"], _citations([source]), "llm_grounded")
        self.state = {"artifact": self.artifact, "evidence": [source], "stop_reason": "delivery_ready",
                      "trajectory": [{"action": "finish", "status": "completed"}],
                      "budget": {"steps_used": 4, "max_steps": 12, "rag_queries_used": 1, "max_rag_queries": 6,
                                 "drafts_used": 1, "max_drafts": 3}}

    def judgement(self, data=None):
        data = data or judge_input(self.request, self.artifact, self.canonical)
        return {"claims": [{"claim_id": row["claim_id"], "label": "supported", "source_ids": row["source_ids"] or ["S1"],
                            "reason": "原文明确支持该流程。"} for row in data["claims"]],
                "rubric": [{"criterion": key, "label": "pass", "reason": "满足本项可观察标准。"} for key in data["rubric_criteria"]]}

    def test_normal_finish_requires_real_finish_and_recomputed_artifact(self):
        self.assertTrue(hard_checks(self.request, self.state, "completed", self.canonical)["passed"])
        self.state["stop_reason"] = "no_progress"
        self.state["quality"] = {"score": 100}
        self.state["delivery"] = {"status": "draft_ready"}
        result = hard_checks(self.request, self.state, "completed", self.canonical)
        self.assertFalse(result["normal_finish"])
        self.assertFalse(result["passed"])
        self.assertTrue(result["artifact_ready"])

    def test_claimed_delivery_without_finish_does_not_pass(self):
        self.state["trajectory"] = []
        self.assertFalse(hard_checks(self.request, self.state, "completed", self.canonical)["passed"])

    def test_minutes_and_question_count_are_program_checks(self):
        self.artifact["lesson_blocks"][0]["minutes"] = 19
        self.artifact["classroom_questions"] = []
        failed = hard_checks(self.request, self.state, "completed", self.canonical)["failed_checks"]
        self.assertIn("artifact:duration_minutes", failed)
        self.assertIn("artifact:question_count", failed)

    def test_canonical_source_quote_page_and_scope_cannot_be_forged(self):
        for key, value in (("quote", "伪造的原文"), ("page_start", 999), ("textbook_id", "other_book"),
                           ("section_path", ["伪造的小节位置"])):
            with self.subTest(key=key):
                altered = copy.deepcopy(self.state)
                altered["artifact"]["citations"][0][key] = value
                result = hard_checks(self.request, altered, "completed", self.canonical)
                self.assertFalse(result["passed"])
                self.assertIn("canonical_citations", result["failed_checks"])

    def test_budget_overspend_is_not_offset_by_good_artifact(self):
        self.state["budget"]["drafts_used"] = 4
        self.assertIn("bounded_calls", hard_checks(self.request, self.state, "completed", self.canonical)["failed_checks"])

    def test_honest_no_evidence_wait_is_separate_from_normal_success(self):
        self.state.update(artifact=None, evidence=[], stop_reason=None,
                          trajectory=[{"action": "query_rag", "status": "completed", "observation": {"evidence_count": 0}}],
                          approval={"type": "teacher_question"},
                          observations={"last_tool_result": {"question": "当前未找到相关证据，是否调整材料？"}})
        result = hard_checks(self.request, self.state, "waiting_user", {}, expected_outcome="insufficient_evidence")
        self.assertTrue(result["safe_refusal"])
        self.assertTrue(result["expectation_met"])
        self.assertFalse(result["passed"])
        self.assertFalse(result["normal_finish"])

    def test_invalid_protocol_loop_without_a_query_is_not_honest_refusal(self):
        self.state.update(artifact=None, evidence=[], stop_reason="no_progress",
                          trajectory=[{"action": "invalid_action", "status": "rejected"}] * 4,
                          delivery={"missing_items": ["多轮操作未取得进展"]})
        result = hard_checks(self.request, self.state, "completed", {}, expected_outcome="insufficient_evidence")
        self.assertFalse(result["expectation_met"])
        self.assertFalse(result["empty_query_observed"])

    def test_unqueried_teacher_question_is_not_honest_refusal(self):
        self.state.update(artifact=None, evidence=[], stop_reason=None,
                          trajectory=[{"action": "ask_teacher", "status": "completed"}],
                          approval={"type": "teacher_question"},
                          observations={"last_tool_result": {"question": "想要什么颜色？"}})
        result = hard_checks(self.request, self.state, "waiting_user", {}, expected_outcome="insufficient_evidence")
        self.assertFalse(result["expectation_met"])

    def test_empty_query_with_bounded_stop_can_meet_only_safety_expectation(self):
        self.state.update(artifact=None, evidence=[], stop_reason="step_budget",
                          trajectory=[{"action": "query_rag", "status": "completed", "observation": {"evidence_count": 0}}],
                          delivery={"missing_items": ["保留未完成项"]})
        result = hard_checks(self.request, self.state, "completed", {}, expected_outcome="insufficient_evidence")
        self.assertTrue(result["expectation_met"])
        self.assertFalse(result["normal_finish"])
        self.assertFalse(result["passed"])

    def test_failed_or_boolean_empty_query_is_not_evidence_of_retrieval(self):
        for action in ({"action": "query_rag", "status": "rejected", "observation": {"evidence_count": 0}},
                       {"action": "query_rag", "status": "completed", "observation": {"evidence_count": False}}):
            self.state.update(artifact=None, evidence=[], stop_reason="step_budget", trajectory=[action],
                              delivery={"missing_items": ["保留未完成项"]})
            self.assertFalse(hard_checks(self.request, self.state, "completed", {}, expected_outcome="insufficient_evidence")["expectation_met"])

    def test_public_program_report_hides_focus_and_custom_requirement_text(self):
        request = copy.deepcopy(self.request)
        request.update(focus_terms=["PRIVATE_SOURCE_MARKER_FOCUS"], requirements=["PRIVATE_SOURCE_MARKER_REQUIREMENT"])
        result = hard_checks(request, self.state, "completed", self.canonical)
        self.assertNotIn("PRIVATE_SOURCE_MARKER", json.dumps(result))
        self.assertTrue(any(value.startswith("artifact:focus_") for value in result["failed_checks"]))
        self.assertTrue(any(value.startswith("artifact:requirement_") for value in result["failed_checks"]))

    def test_timeout_or_provider_failure_is_not_an_honest_refusal(self):
        self.state.update(artifact=None, evidence=[], stop_reason="decision_unavailable", delivery={"missing_items": ["模型不可用"]})
        result = hard_checks(self.request, self.state, "failed", {}, expected_outcome="insufficient_evidence")
        self.assertFalse(result["expectation_met"])

    def test_judge_uses_canonical_text_instead_of_artifact_quote(self):
        self.artifact["citations"][0]["quote"] = "PRIVATE_FORGED_QUOTE"
        data = judge_input(self.request, self.artifact, self.canonical)
        self.assertEqual(data["sources"][0]["content"], self.canonical["chunk_a"]["content"])
        self.assertNotIn("PRIVATE_FORGED_QUOTE", json.dumps(data))
        self.assertIn("lesson_blocks:0", {row["claim_id"] for row in data["claims"]})
        self.assertIn("classroom_questions:0", {row["claim_id"] for row in data["claims"]})

    def test_judge_receives_canonical_section_and_page_range_metadata(self):
        self.canonical["chunk_a"].update(section_path=["第四章 血液循环", "第一节 | 心脏的泵血功能"], page_start=102, page_end=104)
        self.artifact["citations"][0].update(section_path=["UNTRUSTED_FAKE_SECTION"], page_start=999, page_end=999)
        data = judge_input(self.request, self.artifact, self.canonical)
        source = data["sources"][0]
        self.assertEqual(source["section_path"], ["第四章 血液循环", "第一节 | 心脏的泵血功能"])
        self.assertEqual(source["page_start"], 102)
        self.assertEqual(source["page_end"], 104)
        self.assertEqual(source["chunk_id"], "chunk_a")
        self.assertNotIn("UNTRUSTED_FAKE_SECTION", json.dumps(data))

    def test_missing_unknown_duplicate_or_unreferenced_judge_claim_rejected(self):
        data = judge_input(self.request, self.artifact, self.canonical)
        valid = self.judgement(data)
        self.assertEqual(validate_judgement(valid, data), valid)
        broken = []
        short = copy.deepcopy(valid)
        short["claims"].pop()
        broken.append(short)
        extra = copy.deepcopy(valid)
        extra["claims"][0]["claim_id"] = "unknown"
        broken.append(extra)
        duplicate = copy.deepcopy(valid)
        duplicate["claims"][1] = duplicate["claims"][0]
        broken.append(duplicate)
        forged = copy.deepcopy(valid)
        forged["claims"][0]["source_ids"] = ["S999"]
        broken.append(forged)
        empty = copy.deepcopy(valid)
        empty["claims"][0]["source_ids"] = []
        broken.append(empty)
        for value in broken:
            with self.assertRaises(JudgeProtocolError):
                validate_judgement(value, data)

    def test_missing_or_unassessable_rubric_never_passes(self):
        data = judge_input(self.request, self.artifact, self.canonical)
        value = self.judgement(data)
        value["rubric"].pop()
        with self.assertRaises(JudgeProtocolError):
            validate_judgement(value, data)
        value = self.judgement(data)
        value["rubric"][0]["label"] = "unassessable"
        self.assertFalse(judgement_summary(validate_judgement(value, data))["passed"])

    def test_judge_protocol_rejects_non_string_labels_without_type_errors(self):
        data = judge_input(self.request, self.artifact, self.canonical)
        for kind in ("claims", "rubric"):
            for label in ([], {}, True, 1, None):
                with self.subTest(kind=kind, label=label):
                    value = self.judgement(data)
                    value[kind][0]["label"] = label
                    with self.assertRaises(JudgeProtocolError):
                        validate_judgement(value, data)

    def test_insufficient_evidence_does_not_become_contradiction_or_pass(self):
        data = judge_input(self.request, self.artifact, self.canonical)
        value = self.judgement(data)
        value["claims"][0]["label"] = "insufficient"
        value["claims"][0]["source_ids"] = []
        result = judgement_summary(validate_judgement(value, data))
        self.assertFalse(result["passed"])
        self.assertEqual(result["claim_labels"]["insufficient"], 1)
        self.assertEqual(result["unsupported_claim_ids"], ["executive_summary"])

    def test_control_labels_are_relations_to_constructed_sources(self):
        data, expected = control_data()
        self.assertEqual(expected["reversed_order"], "contradicted")
        self.assertEqual(expected["absence_claim"], "insufficient")
        self.assertEqual(len(data["claims"]), 4)

    def test_judge_prompt_preserves_quantifier_and_explicit_subset_scope(self):
        from backend.evaluation.agent_eval import JUDGE_SYSTEM_PROMPT
        self.assertIn("不得扩大要求", JUDGE_SYSTEM_PROMPT)
        self.assertIn("五个阶段的时长", JUDGE_SYSTEM_PROMPT)
        self.assertIn("不同分句的范围不能相互替换", JUDGE_SYSTEM_PROMPT)

    def test_normalized_source_hash_ignores_git_eol_conversion(self):
        temporary_root = Path(__file__).parents[1] / ".gstack"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            lf, crlf = Path(directory) / "lf.py", Path(directory) / "crlf.py"
            lf.write_bytes("# 原文\nvalue = 1\n".encode("utf-8"))
            crlf.write_bytes("# 原文\r\nvalue = 1\r\n".encode("utf-8"))
            self.assertNotEqual(lf.read_bytes(), crlf.read_bytes())
            self.assertEqual(cli.normalized_lf_sha256(lf), cli.normalized_lf_sha256(crlf))

    def test_judge_failure_is_ungraded_and_never_leaks_provider_error(self):
        data = judge_input(self.request, self.artifact, self.canonical)
        client = Mock()
        client.with_options.return_value.chat.completions.create.side_effect = TimeoutError("PRIVATE_API_KEY PRIVATE_TEXTBOOK")
        result, private = run_judge(data, model="different-model", create_client=lambda **_: client)
        self.assertEqual(result["status"], "ungraded")
        self.assertFalse(result["passed"])
        self.assertIsNone(private)
        self.assertNotIn("PRIVATE", json.dumps(result))
        client.close.assert_called_once()

    def test_judge_bad_json_and_truncation_are_ungraded(self):
        data = judge_input(self.request, self.artifact, self.canonical)
        for content, reason in (("not JSON", "stop"), (json.dumps(self.judgement(data)), "length")):
            with self.subTest(reason=reason):
                client = Mock()
                client.with_options.return_value.chat.completions.create.return_value = SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=reason)], usage=None)
                result, _ = run_judge(data, model="different-model", create_client=lambda **_: client)
                self.assertFalse(result["passed"])
                self.assertEqual(result["status"], "ungraded")

    def test_truncated_judge_response_preserves_reported_usage_and_attempt(self):
        data = judge_input(self.request, self.artifact, self.canonical)
        client = Mock()
        client.with_options.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{unfinished"), finish_reason="length")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150))
        result, _ = run_judge(data, model="different-model", create_client=lambda **_: client)
        self.assertEqual(result["status"], "ungraded")
        self.assertTrue(result["request_attempted"])
        self.assertEqual(result["usage"]["total_tokens"], 150)

    def test_aggregate_includes_ungraded_tasks_in_main_denominator(self):
        row = {"expected_outcome": "draft_ready", "status": "completed", "stop_reason": "delivery_ready",
               "elapsed_seconds": 1, "hard": {"normal_finish": True, "passed": True, "expectation_met": True},
               "judge": {"status": "graded", "passed": True}}
        failed = copy.deepcopy(row)
        failed["judge"] = {"status": "ungraded", "passed": False}
        summary = aggregate_runs([row, failed])
        self.assertEqual(summary["judge_pass_rate_all_normal_tasks"], 0.5)
        self.assertEqual(summary["judge_pass_rate_graded_only"], 1)
        self.assertEqual(summary["joint_pass_rate"], 0.5)
        self.assertEqual(summary["rubric_pass_rate_all_normal_tasks"]["goal_alignment"], 0)

    def test_markdown_report_distinguishes_offline_checks_and_live_effect(self):
        report = cli.offline_report()
        rendered = render_markdown(report)
        self.assertIn("真实模型请求为 0", rendered)
        self.assertIn("不能据此判断 Agent 或教学质量", rendered)
        self.assertTrue(any(row["id"] == "mixed_sources_group" and row["label"] == "insufficient" and not row["model_executed"]
                            for row in report["prelabelled_protocol_examples"]))

    def test_source_snapshot_does_not_copy_old_jobs_or_modify_original(self):
        temporary_root = Path(__file__).parents[1] / ".gstack"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            source, target = Path(directory) / "original.db", Path(directory) / "copy.db"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE jobs (id TEXT)")
                db.execute("CREATE TABLE chunks (id TEXT, content TEXT)")
                db.execute("INSERT INTO jobs VALUES ('teacher_saved_job')")
                db.execute("INSERT INTO chunks VALUES ('s1', '原文')")
                db.commit()
            cli.copy_source_db(source, target)
            with closing(sqlite3.connect(source)) as db:
                self.assertEqual(db.execute("SELECT id FROM jobs").fetchall(), [("teacher_saved_job",)])
            with closing(sqlite3.connect(target)) as db:
                self.assertEqual(db.execute("SELECT id FROM jobs").fetchall(), [])
                self.assertEqual(db.execute("SELECT content FROM chunks").fetchall(), [("原文",)])
            with self.assertRaises(ValueError):
                cli.copy_source_db(source, source)

    def test_offline_self_check_has_no_claim_of_real_model_effect(self):
        result = cli.offline_report()
        self.assertTrue(result["passed"])
        self.assertEqual(result["real_model_calls"], 0)
        self.assertEqual(result["mode"], "offline_evaluator_self_check")


if __name__ == "__main__":
    unittest.main()
