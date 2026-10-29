"""Exercise the real single-agent controller with offline decisions and an owned DB.

Only the RAG transport, draft model and decision policy are substituted. Scope,
source hydration, checkpoints, budgets and delivery checks run as production code.
"""
import copy
import os
import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import patch

with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
    from backend.agents import course_agent as lesson
    from backend.agents import lesson_runtime as runtime
    from backend.agents import orchestrator
    from backend.agents.lesson_policy import DecisionUnavailable
    from backend.database import Base, Chapter, Chunk, Course, Job, Textbook

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def choose(name, **arguments):
    return {"action": name, "arguments": arguments, "summary": f"执行 {name}"}


class ScriptedPolicy:
    """Capture real observations so tests assert feedback, not model self-assessment."""

    def __init__(self, *decisions):
        self.decisions = list(decisions)
        self.observed_states = []

    def __call__(self, payload, state, *, timeout):
        self.observed_states.append(copy.deepcopy(state))
        if not self.decisions:
            raise AssertionError("Runtime requested an unexpected extra decision")
        decision = self.decisions.pop(0)
        if isinstance(decision, BaseException):
            raise decision
        return decision(payload, state) if callable(decision) else decision


class ManualClock:
    def __init__(self):
        self.current = 100.0

    def monotonic(self):
        return self.current


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def constraints(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.patches = ExitStack()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.patches.close)
        for module in (runtime, lesson, orchestrator):
            self.patches.enter_context(patch.object(module, "SessionLocal", self.sessions))
        self.patches.enter_context(patch.dict(os.environ, {
            "AGENT_MAX_STEPS": "12", "AGENT_MAX_RAG_QUERIES": "6",
            "AGENT_MAX_DRAFTS": "3", "AGENT_MAX_RUNTIME_SECONDS": "300",
        }))
        self.rag = self.patches.enter_context(patch.object(runtime, "query_rag_tool", return_value={"items": []}))
        self.generate = self.patches.enter_context(patch.object(lesson, "_generate_artifact", side_effect=self.good_draft))
        with self.sessions() as db:
            db.add_all([Course(id="runtime_course", title="运行器回归"), Course(id="foreign_course", title="隔离课程")])
            db.flush()
            for book_id, course_id, title in (("book_a", "runtime_course", "教材甲"), ("book_b", "runtime_course", "教材乙"), ("foreign_book", "foreign_course", "外部教材")):
                db.add(Textbook(id=book_id, course_id=course_id, title=title, filename=f"{book_id}.txt", format="txt",
                                total_pages=30, parse_status="completed", structure_status="confirmed", graph_status="pending"))
            db.flush()
            for book_id in ("book_a", "book_b", "foreign_book"):
                db.add(Chapter(id=f"{book_id}_chapter", textbook_id=book_id, title="来源模块", page_start=1, page_end=30, order_index=0))
            db.flush()
            for chunk_id, book_id, title, page, content in (
                ("chunk_a", "book_a", "教材甲", 10, "教材甲原文：模块的形成过程包含准备与实施两个阶段。"),
                ("chunk_b", "book_b", "教材乙", 20, "教材乙原文：模块的实施需要观察反馈并核对结果。"),
                ("foreign_chunk", "foreign_book", "外部教材", 5, "FOREIGN_SOURCE_MUST_NOT_ENTER_THE_LESSON"),
            ):
                db.add(Chunk(id=chunk_id, textbook_id=book_id, chapter_id=f"{book_id}_chapter", textbook_title=title,
                             chapter_title="来源模块", section_path=["来源模块"], page_start=page, page_end=page,
                             chunk_index=0, content=content, char_count=len(content)))
            db.commit()
        self.payload = {
            "course_id": "runtime_course", "topic": "模块", "goal": "基于两本教材安排45分钟教学",
            "textbook_ids": ["book_a", "book_b"], "audience": "一年级学生", "prior_knowledge": "已学基础模块",
            "duration_minutes": 45, "question_count": 1, "requirements": ["核心概念"], "focus_terms": [], "context": {},
        }

    def make_job(self, *, state=None, budget=None, selected=False, status="pending"):
        payload = copy.deepcopy(self.payload)
        if selected:
            payload["context"]["selected_chunk_ids"] = ["chunk_a", "chunk_b"]
        result = lesson.initial_agent_result(payload)
        result.update(runtime.runtime_fields())
        if state:
            result.update(copy.deepcopy(state))
        if budget:
            result["budget"].update(budget)
        job_id = "runtime_" + uuid.uuid4().hex[:12]
        with self.sessions() as db:
            db.add(Job(id=job_id, course_id=payload["course_id"], type="course_agent", status=status, payload=payload, result=result))
            db.commit()
        return job_id

    def saved(self, job_id):
        with self.sessions() as db:
            row = db.get(Job, job_id)
            return {"status": row.status, "error": row.error, "stage": row.stage, "result": copy.deepcopy(row.result)}

    def resume(self, job_id, *, answer=None):
        with self.sessions() as db:
            row = db.get(Job, job_id)
            result = copy.deepcopy(row.result)
            if answer is not None:
                result.setdefault("teacher_answers", []).append({"request_id": result["approval"]["request_id"], "answer": answer})
                result["approval"] = None
            row.result, row.status = result, "pending"
            db.commit()

    def sources(self):
        return runtime._read_sources(self.payload, ["chunk_a", "chunk_b"])

    def good_draft(self, payload, books, items, *, minutes=45):
        references = [f"S{index}" for index in range(1, len(items) + 1)]
        return lesson._normalize_artifact({
            "title": "模块课堂初稿", "executive_summary": "根据教材原文组织讲授，内容仍待教师审核。",
            "teaching_objectives": ["依据原文说明形成过程与反馈步骤"],
            "knowledge_sequence": [{"title": "形成过程与反馈", "explanation": "对照原文逐步讲解", "source_ids": references}],
            "lesson_blocks": [{"title": "讲解与讨论", "minutes": minutes, "content": "对照两本教材讨论并核对原文", "source_ids": references}],
            "classroom_questions": ["两本教材各提供了哪些原文依据？"],
        }, payload["topic"], lesson._citations(items), "llm_grounded")

    def assert_ready(self, job_id):
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "completed", saved)
        self.assertEqual(saved["result"]["stop_reason"], "delivery_ready")
        self.assertEqual(saved["result"]["delivery"]["status"], "draft_ready")
        self.assertFalse(saved["result"]["quality"]["semantic_reviewed"])
        return saved["result"]

    def test_empty_query_changes_then_validation_failure_drives_a_real_revision(self):
        job_id = self.make_job()
        self.rag.side_effect = [{"items": [], "retrieval_trace": {"reason": "no_evidence"}},
                                {"items": [{"id": "chunk_a"}, {"id": "chunk_b"}]}]
        draft_requests = []

        def draft(payload, books, items):
            draft_requests.append(copy.deepcopy(payload))
            return self.good_draft(payload, books, items, minutes=40 if len(draft_requests) == 1 else 45)

        self.generate.side_effect = draft
        script = ScriptedPolicy(
            choose("query_rag", question="模块基础"), choose("query_rag", question="模块的形成与反馈"),
            choose("write_draft"), choose("validate_draft"),
            choose("write_draft", instructions="按检查反馈补足45分钟"), choose("finish"),
        )
        runtime.process_agent_loop(job_id, policy=script)
        state = self.assert_ready(job_id)
        self.assertEqual([row["action"] for row in state["trajectory"]], ["query_rag", "query_rag", "write_draft", "validate_draft", "write_draft", "finish"])
        self.assertEqual(script.observed_states[1]["observations"]["last_tool_result"]["added_count"], 0)
        self.assertEqual(script.observed_states[4]["delivery"]["status"], "needs_work")
        self.assertTrue(any("课时安排" in value for value in draft_requests[1]["_agent_feedback"]["missing_items"]))
        self.assertEqual(draft_requests[1]["_agent_previous_draft"]["lesson_blocks"][0]["minutes"], 40)
        self.assertEqual(state["artifact"]["lesson_blocks"][0]["minutes"], 45)
        self.assertEqual(state["artifact_versions"][0]["artifact"]["lesson_blocks"][0]["minutes"], 40)
        self.assertEqual(self.rag.call_count, 2)
        self.assertEqual(state["budget"]["drafts_used"], 2)

    def test_rejected_schema_feedback_reaches_next_policy_before_a_valid_finish(self):
        job_id = self.make_job(selected=True)
        invalid = choose('finish')
        invalid['summary'] = {'private': 'PRIVATE_MODEL_VALUE'}
        script = ScriptedPolicy(choose('write_draft'), invalid, choose('finish'))
        runtime.process_agent_loop(job_id, policy=script)
        state = self.assert_ready(job_id)
        feedback = script.observed_states[2]['observations']['last_tool_result']
        self.assertEqual(feedback['error_code'], 'invalid_schema')
        self.assertEqual(feedback['validation_issues'], [{'field': 'summary', 'type': 'string_type'}])
        self.assertIn('finish', feedback['allowed_actions'])
        self.assertNotIn('PRIVATE_MODEL_VALUE', str(state))
        self.assertEqual(state['trajectory'][1]['status'], 'rejected')

    def test_premature_finish_and_foreign_scope_are_rejected_before_valid_delivery(self):
        job_id = self.make_job()
        script = ScriptedPolicy(
            choose("finish", summary="我认为已经完成"),
            choose("query_rag", question="模块", textbook_ids=["foreign_book"]),
            choose("read_source", chunk_id="foreign_chunk"),
            choose("read_source", chunk_id="chunk_a"), choose("read_source", chunk_id="chunk_b"),
            choose("write_draft"), choose("finish"),
        )
        runtime.process_agent_loop(job_id, policy=script)
        state = self.assert_ready(job_id)
        self.assertEqual([row["status"] for row in state["trajectory"][:3]], ["rejected"] * 3)
        self.assertEqual({row["id"] for row in state["evidence"]}, {"chunk_a", "chunk_b"})
        self.assertEqual(state["budget"]["rag_queries_used"], 0)
        self.rag.assert_not_called()

    def test_rag_metadata_and_source_text_are_reloaded_from_owned_records(self):
        job_id = self.make_job()
        self.rag.return_value = {"items": [{"id": "chunk_a", "textbook_id": "foreign_book", "content": "FORGED_QUOTE", "page_start": 999}]}
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("query_rag", question="模块"), choose("read_source", chunk_id="chunk_b"), choose("write_draft"), choose("finish"),
        ))
        state = self.assert_ready(job_id)
        evidence = next(row for row in state["evidence"] if row["id"] == "chunk_a")
        self.assertEqual((evidence["textbook_id"], evidence["page_start"]), ("book_a", 10))
        self.assertIn("教材甲原文", evidence["content"])
        self.assertNotIn("FORGED_QUOTE", str(state["artifact"]))

    def test_empty_stored_source_cannot_count_as_a_books_supporting_evidence(self):
        with self.sessions() as db:
            db.get(Chunk, "chunk_a").content = " \n\t "
            db.commit()
        job_id = self.make_job()
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("read_source", chunk_id="chunk_a"), choose("read_source", chunk_id="chunk_b"),
            choose("write_draft"), choose("finish"),
            choose("ask_teacher", question="教材甲没有可读原文，是否修复该教材后继续？"),
        ))
        saved = self.saved(job_id)
        self.assertEqual(saved["result"]["trajectory"][0]["status"], "rejected")
        self.assertNotIn("chunk_a", {row["id"] for row in saved["result"].get("evidence") or []})
        self.assertEqual(saved["status"], "waiting_user")
        self.assertNotEqual(saved["result"]["delivery"]["status"], "draft_ready")

    def test_cross_book_chapter_reference_cannot_bypass_rag_scope_checks(self):
        # Both FKs are valid, but the chapter belongs to a different book/course.
        # A source's book and chapter must describe the same local origin.
        with self.sessions() as db:
            db.get(Chunk, "chunk_a").chapter_id = "foreign_book_chapter"
            db.commit()
        job_id = self.make_job()
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("read_source", chunk_id="chunk_a"), choose("read_source", chunk_id="chunk_b"),
            choose("write_draft"), choose("finish"),
            choose("ask_teacher", question="教材甲来源的章节归属异常，是否修复来源后继续？"),
        ))
        saved = self.saved(job_id)
        self.assertEqual(saved["result"]["trajectory"][0]["status"], "rejected")
        self.assertNotIn("chunk_a", {row["id"] for row in saved["result"].get("evidence") or []})
        self.assertEqual(saved["status"], "waiting_user")
        self.assertNotEqual(saved["result"]["delivery"]["status"], "draft_ready")

    def test_current_chapter_title_is_authoritative_over_stale_chunk_title_cache(self):
        with self.sessions() as db:
            db.get(Chapter, "book_a_chapter").title = "教师已核对的新目录标题"
            db.get(Chunk, "chunk_a").chapter_title = "尚未同步的旧目录缓存"
            db.commit()
        job_id = self.make_job()
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("read_source", chunk_id="chunk_a"), choose("read_source", chunk_id="chunk_b"),
            choose("write_draft"), choose("finish"),
        ))
        state = self.assert_ready(job_id)
        source = next(row for row in state["evidence"] if row["id"] == "chunk_a")
        citation = next(row for row in state["artifact"]["citations"] if row["chunk_id"] == "chunk_a")
        self.assertEqual(source["chapter_id"], "book_a_chapter")
        self.assertEqual(source["chapter"], "教师已核对的新目录标题")
        self.assertEqual(citation["chapter"], "教师已核对的新目录标题")
        self.assertIn("教材甲原文", source["content"])

    def test_four_distinct_empty_searches_stop_without_claiming_delivery(self):
        job_id = self.make_job()
        script = ScriptedPolicy(*(choose("query_rag", question=f"模块切面{index}") for index in range(4)))
        runtime.process_agent_loop(job_id, policy=script)
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["result"]["stop_reason"], "no_progress")
        self.assertEqual(saved["result"]["delivery"]["status"], "needs_work")
        self.assertEqual(self.rag.call_count, 4)
        self.generate.assert_not_called()

    def test_rewording_public_summaries_cannot_repeat_an_unchanged_tool_forever(self):
        job_id = self.make_job()
        decisions = [{**choose("query_rag", question="同一问题"), "summary": f"公开摘要{index}"} for index in range(4)]
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(*decisions))
        state = self.saved(job_id)["result"]
        self.assertEqual(state["stop_reason"], "no_progress")
        self.assertEqual(self.rag.call_count, 2)
        self.assertEqual([row["status"] for row in state["trajectory"]], ["completed", "completed", "rejected", "rejected"])

    def test_step_budget_keeps_collected_sources_as_an_honest_partial_result(self):
        job_id = self.make_job(budget={"max_steps": 2})
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(choose("inspect_course"), choose("read_source", chunk_id="chunk_a")))
        state = self.saved(job_id)["result"]
        self.assertEqual(state["stop_reason"], "step_budget")
        self.assertEqual(state["budget"]["steps_used"], 2)
        self.assertEqual(state["delivery"]["status"], "evidence_only")
        self.assertEqual(state["evidence"][0]["id"], "chunk_a")

    def test_alternating_unchanged_observation_tools_cannot_reset_no_progress_forever(self):
        sources = self.sources()
        job_id = self.make_job(selected=True, state={"artifact": self.good_draft(self.payload, [], sources)})
        script = ScriptedPolicy(
            choose("inspect_course"), choose("read_source", chunk_id="chunk_a"), choose("validate_draft"),
            choose("inspect_course"), choose("read_source", chunk_id="chunk_a"), choose("validate_draft"),
            choose("inspect_course"),
        )
        runtime.process_agent_loop(job_id, policy=script)
        saved = self.saved(job_id)
        self.assertEqual(saved["result"]["stop_reason"], "no_progress")
        self.assertEqual(saved["result"]["budget"]["steps_used"], 7)
        self.assertEqual(saved["result"]["no_progress_count"], 4)
        self.assertEqual([row["progress_made"] for row in saved["result"]["trajectory"][:6]],
                         [True, True, True, False, False, False])
        self.assertEqual(saved["result"]["delivery"]["status"], "draft_ready")
        self.assertNotEqual(saved["result"]["stop_reason"], "delivery_ready")

    def test_validated_draft_schema_rejection_supplies_a_legal_finish_example(self):
        job_id = self.make_job(selected=True)
        invalid = {"action": "finish", "arguments": {}, "summary": {"private": "PRIVATE_VALUE"}}
        script = ScriptedPolicy(choose("write_draft"), choose("validate_draft"), invalid, choose("finish"))
        runtime.process_agent_loop(job_id, policy=script)
        self.assert_ready(job_id)
        feedback = script.observed_states[3]["observations"]["last_tool_result"]
        self.assertEqual(feedback["decision_example"]["action"], "finish")
        self.assertEqual(feedback["decision_example"]["arguments"], {})
        self.assertIsInstance(feedback["decision_example"]["summary"], str)
        self.assertNotIn("PRIVATE_VALUE", str(feedback))

    def test_progress_observation_tokens_survive_process_recovery(self):
        sources = self.sources()
        job_id = self.make_job(selected=True, state={"artifact": self.good_draft(self.payload, [], sources)})
        with self.assertRaises(KeyboardInterrupt):
            runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
                choose("inspect_course"), choose("read_source", chunk_id="chunk_a"), choose("validate_draft"),
                KeyboardInterrupt("process interrupted before next decision"),
            ))
        checkpoint = self.saved(job_id)["result"]
        tokens = [row["progress_token"] for row in checkpoint["trajectory"]]
        self.assertEqual(len(set(tokens)), 3)
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("inspect_course"), choose("read_source", chunk_id="chunk_a"), choose("validate_draft"),
            choose("inspect_course"),
        ))
        state = self.saved(job_id)["result"]
        self.assertEqual(state["stop_reason"], "no_progress")
        self.assertEqual([row["progress_token"] for row in state["trajectory"][:3]], tokens)
        self.assertEqual(state["no_progress_count"], 4)

    def test_validation_of_a_changed_draft_is_new_progress(self):
        sources = self.sources()
        job_id = self.make_job(selected=True, state={"artifact": self.good_draft(self.payload, [], sources, minutes=40)})
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("validate_draft"), choose("write_draft", instructions="修订为45分钟"),
            choose("validate_draft"), choose("finish"),
        ))
        state = self.assert_ready(job_id)
        checks = [row for row in state["trajectory"] if row["action"] == "validate_draft"]
        self.assertEqual([row["progress_made"] for row in checks], [True, True])
        self.assertNotEqual(checks[0]["progress_token"], checks[1]["progress_token"])

    def test_rag_budget_rejects_an_extra_call_but_allows_completion_from_existing_sources(self):
        job_id = self.make_job(budget={"max_rag_queries": 1})
        self.rag.return_value = {"items": [{"id": "chunk_a"}]}
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("query_rag", question="模块基础"), choose("query_rag", question="模块反馈"),
            choose("read_source", chunk_id="chunk_b"), choose("write_draft"), choose("finish"),
        ))
        state = self.assert_ready(job_id)
        self.assertEqual(state["trajectory"][1]["status"], "rejected")
        self.assertIn("预算", state["trajectory"][1]["error"])
        self.assertEqual(state["budget"]["rag_queries_used"], 1)
        self.rag.assert_called_once()

    def test_draft_budget_prevents_extra_generation_and_preserves_failed_draft_for_teacher(self):
        job_id = self.make_job(selected=True, budget={"max_drafts": 1})
        self.generate.side_effect = lambda payload, books, items: self.good_draft(payload, books, items, minutes=40)
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("write_draft"), choose("validate_draft"), choose("write_draft", instructions="补足课时"),
            choose("ask_teacher", question="生成预算已用完，是否基于保留初稿继续人工调整？"),
        ))
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "waiting_user")
        self.assertEqual(saved["result"]["artifact"]["lesson_blocks"][0]["minutes"], 40)
        self.assertEqual(saved["result"]["delivery"]["status"], "needs_work")
        self.assertEqual(saved["result"]["trajectory"][2]["status"], "rejected")
        self.assertEqual(saved["result"]["budget"]["drafts_used"], 1)
        self.generate.assert_called_once()

    def test_already_consumed_runtime_budget_stops_before_another_model_call(self):
        job_id = self.make_job(budget={"max_runtime_seconds": 30, "elapsed_seconds": 30})
        script = ScriptedPolicy()
        runtime.process_agent_loop(job_id, policy=script)
        state = self.saved(job_id)["result"]
        self.assertEqual(state["stop_reason"], "time_budget")
        self.assertEqual(script.observed_states, [])
        self.rag.assert_not_called()
        self.generate.assert_not_called()

    def test_policy_spending_the_remaining_time_cannot_start_its_proposed_tool(self):
        job_id = self.make_job(budget={"max_runtime_seconds": 30})
        clock = ManualClock()

        def slow_policy(payload, state):
            clock.current += 31
            return choose("query_rag", question="模块依据")

        script = ScriptedPolicy(slow_policy)
        with patch.object(runtime, "time", clock):
            runtime.process_agent_loop(job_id, policy=script)
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["result"]["stop_reason"], "time_budget")
        self.assertEqual(saved["result"]["budget"]["steps_used"], 1)
        self.assertEqual(saved["result"]["budget"]["rag_queries_used"], 0)
        self.assertEqual(len(script.observed_states), 1)
        self.rag.assert_not_called()
        self.generate.assert_not_called()

    def test_chapter_pause_saves_active_elapsed_time_and_resume_excludes_teacher_wait(self):
        with self.sessions() as db:
            db.get(Textbook, "book_a").structure_status = "review"
            db.commit()
        job_id = self.make_job(budget={"elapsed_seconds": 11})
        clock = ManualClock()
        real_books = runtime._books

        def preparation_taking_seven_seconds(payload):
            clock.current += 7
            return real_books(payload)

        first_policy = ScriptedPolicy()
        with patch.object(runtime, "time", clock), patch.object(runtime, "_books", side_effect=preparation_taking_seven_seconds):
            runtime.process_agent_loop(job_id, policy=first_policy)
        paused = self.saved(job_id)
        self.assertEqual(paused["status"], "waiting_user")
        self.assertEqual(paused["result"]["approval"]["type"], "chapter_review")
        self.assertEqual(paused["result"]["budget"]["elapsed_seconds"], 18)
        self.assertEqual(first_policy.observed_states, [])
        with self.sessions() as db:
            db.get(Textbook, "book_a").structure_status = "confirmed"
            db.commit()
        self.resume(job_id)
        clock.current += 3600  # The teacher's hour away must not consume execution time.

        def resumed_preparation_taking_two_seconds(payload):
            clock.current += 2
            return real_books(payload)

        with patch.object(runtime, "time", clock), patch.object(runtime, "_books", side_effect=resumed_preparation_taking_two_seconds):
            runtime.process_agent_loop(job_id, policy=ScriptedPolicy(choose("ask_teacher", question="本课是否安排小组练习？")))
        resumed = self.saved(job_id)
        self.assertEqual(resumed["status"], "waiting_user")
        self.assertEqual(resumed["result"]["approval"]["type"], "teacher_question")
        self.assertEqual(resumed["result"]["budget"]["elapsed_seconds"], 20)
        self.rag.assert_not_called()

    def test_ask_teacher_persists_then_resume_reuses_query_and_passes_answer_to_draft(self):
        job_id = self.make_job()
        self.rag.return_value = {"items": [{"id": "chunk_a"}, {"id": "chunk_b"}]}
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("query_rag", question="模块依据"), choose("ask_teacher", question="学生是否已学基础模块？", options=["已学", "未学"]),
        ))
        paused = self.saved(job_id)
        self.assertEqual(paused["status"], "waiting_user")
        self.assertEqual(paused["result"]["approval"]["type"], "teacher_question")
        # An unacknowledged waiting run must not spontaneously resume itself.
        untouched = ScriptedPolicy()
        runtime.process_agent_loop(job_id, policy=untouched)
        self.assertEqual(untouched.observed_states, [])
        self.resume(job_id, answer="已学")
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(choose("write_draft"), choose("finish")))
        state = self.assert_ready(job_id)
        self.assertEqual([row["action"] for row in state["trajectory"]], ["query_rag", "ask_teacher", "write_draft", "finish"])
        self.assertEqual(self.generate.call_args.args[0]["_agent_teacher_answers"][0]["answer"], "已学")
        self.assertEqual(state["budget"]["rag_queries_used"], 1)
        self.rag.assert_called_once()

    def test_tool_interruption_resumes_without_replaying_completed_query_or_leaving_running_rows(self):
        job_id = self.make_job()
        self.rag.side_effect = [{"items": [{"id": "chunk_a"}, {"id": "chunk_b"}]}, KeyboardInterrupt("simulated process loss")]
        with self.assertRaises(KeyboardInterrupt):
            runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
                choose("query_rag", question="模块依据"), choose("query_rag", question="模块补充切面"),
            ))
        interrupted = self.saved(job_id)
        self.assertEqual(interrupted["status"], "processing")
        self.assertEqual(interrupted["result"]["trajectory"][-1]["status"], "running")
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(choose("write_draft"), choose("finish")))
        state = self.assert_ready(job_id)
        self.assertEqual(self.rag.call_count, 2)
        self.assertEqual(state["budget"]["rag_queries_used"], 2)
        self.assertEqual(state["trajectory"][1]["status"], "failed")
        self.assertEqual(state["trajectory"][1]["error"], "interrupted")
        self.assertFalse(any(row["status"] == "running" for row in state["trajectory"]))
        self.assertFalse(any(row["status"] == "running" for row in state["plan"]))

    def test_user_cancel_while_rag_returns_cannot_be_overwritten_by_late_sources(self):
        job_id = self.make_job()
        cancelled_state = []

        def cancel_during_tool(*args, **kwargs):
            with self.sessions() as db:
                row = db.get(Job, job_id)
                state = copy.deepcopy(row.result)
                state["stop_reason"] = "user_cancelled"
                state["trajectory"][-1]["status"] = "cancelled"
                row.status, row.result, row.stage = "cancelled", state, "cancelled"
                db.commit()
                cancelled_state.append(copy.deepcopy(state))
            return {"items": [{"id": "chunk_a"}, {"id": "chunk_b"}]}

        self.rag.side_effect = cancel_during_tool
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(choose("query_rag", question="模块依据")))
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "cancelled")
        self.assertEqual(saved["result"], cancelled_state[0])
        self.assertEqual(saved["result"].get("evidence"), [])
        self.generate.assert_not_called()

    def test_source_change_after_draft_rejects_finish_and_keeps_original_citations(self):
        job_id = self.make_job(selected=True)

        def change_source_then_finish(payload, state):
            with self.sessions() as db:
                db.get(Chunk, "chunk_a").content = "已变化的教材正文"
                db.commit()
            return choose("finish")

        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("write_draft"), change_source_then_finish,
            choose("ask_teacher", question="原文已变化，是否保留本稿并基于新来源新建任务？"),
        ))
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "waiting_user")
        self.assertEqual(saved["result"]["trajectory"][1]["status"], "rejected")
        self.assertIn("原文已经变化", saved["result"]["trajectory"][1]["error"])
        self.assertIn("教材甲原文", saved["result"]["artifact"]["citations"][0]["quote"])
        self.assertNotEqual(saved["result"].get("stop_reason"), "delivery_ready")

    def test_finish_rechecks_latest_draft_instead_of_trusting_cached_passed_quality(self):
        sources = self.sources()
        invalid = self.good_draft(self.payload, [], sources, minutes=40)
        job_id = self.make_job(state={"evidence": sources, "artifact": invalid,
                                     "quality": {"task_completion": {"status": "draft_ready"}, "semantic_reviewed": True},
                                     "delivery": {"status": "draft_ready"}, "validated_signature": "stale-check"})
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("finish", summary="模型宣称已完成"),
            choose("ask_teacher", question="当前课时仍不足，是否保留初稿继续修订？"),
        ))
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "waiting_user")
        self.assertEqual(saved["result"]["trajectory"][0]["status"], "rejected")
        self.assertEqual(saved["result"]["delivery"]["status"], "needs_work")
        self.assertFalse(saved["result"]["quality"]["semantic_reviewed"])
        self.assertTrue(any("课时安排" in item for item in saved["result"]["delivery"]["missing_items"]))

    def test_teacher_saved_draft_cannot_be_replaced_by_model_revision(self):
        sources = self.sources()
        original = self.good_draft(self.payload, [], sources)
        teacher = {**copy.deepcopy(original), "title": "教师亲自保存的稿件", "teacher_edited": True}
        job_id = self.make_job(state={"evidence": sources, "artifact": original, "lesson_draft": teacher, "draft_revision": 3})
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(choose("write_draft", instructions="重写"), choose("finish")))
        state = self.assert_ready(job_id)
        self.assertEqual(state["trajectory"][0]["status"], "rejected")
        self.assertEqual(state["lesson_draft"], teacher)
        self.assertEqual(state["artifact"], original)
        self.assertEqual(state["draft_revision"], 3)
        self.generate.assert_not_called()

    def test_source_drift_on_restart_preserves_saved_teacher_work(self):
        sources = self.sources()
        teacher = self.good_draft(self.payload, [], sources)
        teacher.update(title="需要保留的教师稿", teacher_edited=True)
        job_id = self.make_job(state={"evidence": sources, "lesson_draft": teacher, "draft_revision": 5})
        with self.sessions() as db:
            db.get(Chunk, "chunk_a").content = "重新解析后的不同内容"
            db.commit()
        script = ScriptedPolicy()
        runtime.process_agent_loop(job_id, policy=script)
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["result"]["lesson_draft"], teacher)
        self.assertEqual(saved["result"]["draft_revision"], 5)
        self.assertEqual(script.observed_states, [])
        self.generate.assert_not_called()

    def test_decision_failure_retains_evidence_and_retry_continues_from_checkpoint(self):
        job_id = self.make_job()
        self.rag.return_value = {"items": [{"id": "chunk_a"}, {"id": "chunk_b"}]}
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(
            choose("query_rag", question="模块依据"), DecisionUnavailable("model_timeout"),
        ))
        failed = self.saved(job_id)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "model_timeout")
        self.assertEqual(failed["result"]["stop_reason"], "decision_unavailable")
        self.assertEqual({row["id"] for row in failed["result"]["evidence"]}, {"chunk_a", "chunk_b"})
        self.assertEqual(failed["result"]["trajectory"][-1]["status"], "failed")
        self.resume(job_id)
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(choose("write_draft"), choose("finish")))
        self.assert_ready(job_id)
        self.rag.assert_called_once()

    def test_unexpected_policy_exception_keeps_saved_draft_and_does_not_expose_private_error(self):
        sources = self.sources()
        original = self.good_draft(self.payload, [], sources)
        job_id = self.make_job(state={"evidence": sources, "artifact": original})
        runtime.process_agent_loop(job_id, policy=ScriptedPolicy(RuntimeError("PRIVATE_ENDPOINT_AND_KEY")))
        saved = self.saved(job_id)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["result"]["artifact"], original)
        self.assertEqual(saved["error"], "RuntimeError")
        self.assertNotIn("PRIVATE_ENDPOINT_AND_KEY", str(saved))


if __name__ == "__main__":
    unittest.main()
