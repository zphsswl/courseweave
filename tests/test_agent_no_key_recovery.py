"""Independent regression: loss of model configuration must not erase saved work."""
import copy
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
with patch("dotenv.load_dotenv", return_value=False):
    from backend.agents import course_agent as lesson, lesson_runtime as runtime, orchestrator
    from backend.database import Base, Chapter, Chunk, Course, Job, Textbook

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class AgentNoKeyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.patches = ExitStack()
        for module in (lesson, runtime, orchestrator):
            self.patches.enter_context(patch.object(module, "SessionLocal", self.sessions))
        self.patches.enter_context(patch.object(lesson, "LLM_API_KEY", ""))
        with self.sessions() as db:
            db.add(Course(id="recovery-course", title="恢复测试"))
            db.flush()
            db.add(Textbook(id="recovery-book", course_id="recovery-course", title="当前教材", filename="book.txt",
                            format="txt", parse_status="completed", structure_status="confirmed"))
            db.flush()
            db.add(Chapter(id="recovery-chapter", textbook_id="recovery-book", title="模块"))
            db.flush()
            db.add(Chunk(id="recovery-chunk", textbook_id="recovery-book", chapter_id="recovery-chapter",
                         textbook_title="当前教材", chapter_title="模块", content="用于核验恢复流程的真实本地原文。",
                         section_path=["模块"], page_start=2, page_end=2))
            db.commit()
        self.payload = {"course_id": "recovery-course", "textbook_ids": ["recovery-book"], "topic": "模块备课",
                        "goal": "核对原文后编排课堂", "duration_minutes": 45, "question_count": 0,
                        "requirements": [], "focus_terms": [], "context": {}}
        self.sources = runtime._read_sources(self.payload, ["recovery-chunk"])
        self.original = lesson._normalize_artifact({
            "title": "必须保留的模型初稿", "executive_summary": "基于当前教材组织课堂，仍需教师核对。",
            "teaching_objectives": ["说明模块内容"],
            "knowledge_sequence": [{"title": "模块", "explanation": "核对教材原文", "source_ids": ["S1"]}],
            "lesson_blocks": [{"title": "模块讲解", "minutes": 45, "content": "按原文安排课堂", "source_ids": ["S1"]}],
        }, self.payload["topic"], lesson._citations(self.sources), "llm_grounded")

    def tearDown(self):
        self.patches.close()
        self.engine.dispose()

    def make_job(self, *, teacher=False, trajectory=False, mode="model_driven", artifact=True):
        state = lesson.initial_agent_result(self.payload)
        state.update(execution_mode=mode, evidence=copy.deepcopy(self.sources),
                     artifact=copy.deepcopy(self.original) if artifact else None,
                     stop_reason="decision_unavailable")
        state["budget"].update(steps_used=5, rag_queries_used=2, drafts_used=1, elapsed_seconds=23)
        if teacher:
            state.update(lesson_draft={**copy.deepcopy(self.original), "title": "教师亲自保存的修改", "teacher_edited": True},
                         draft_revision=3)
        if trajectory:
            state["trajectory"] = [{"id": "action-before-restart", "step": 5, "action": "write_draft",
                                    "status": "completed", "summary": "已保存生成产物"}]
        # A retry has already moved the failed run back to pending. Runtime v3
        # artifacts deliberately lack the old workflow's artifact_input_signature.
        self.assertNotIn("artifact_input_signature", state)
        with self.sessions() as db:
            db.add(Job(id="recovery-job", course_id="recovery-course", type="course_agent", status="pending",
                       payload=copy.deepcopy(self.payload), result=state))
            db.commit()
        return state

    def assert_preserved_without_fallback(self, before):
        with patch.object(lesson, "_process_lesson_workflow", side_effect=AssertionError("must not re-enter old workflow")), \
             patch.object(runtime, "process_agent_loop", side_effect=AssertionError("model unavailable")):
            lesson.process_course_agent("recovery-job")
        with self.sessions() as db:
            job = db.get(Job, "recovery-job")
            result = job.result
            self.assertEqual(job.status, "failed")
            self.assertEqual(result["stop_reason"], "model_not_configured")
            for key in ("artifact", "lesson_draft", "draft_revision", "evidence", "budget", "trajectory"):
                self.assertEqual(result.get(key), before.get(key), key)

    def test_teacher_saved_draft_without_trajectory_survives_no_key_retry(self):
        self.assert_preserved_without_fallback(self.make_job(teacher=True, trajectory=False))

    def test_prior_model_artifact_without_trajectory_is_not_regenerated_as_fallback(self):
        self.assert_preserved_without_fallback(self.make_job(teacher=False, trajectory=False))

    def test_actual_trajectory_and_spent_budgets_survive_no_key_retry(self):
        self.assert_preserved_without_fallback(self.make_job(teacher=True, trajectory=True))

    def test_saved_teacher_revision_is_protected_even_in_evidence_workflow_mode(self):
        self.assert_preserved_without_fallback(self.make_job(teacher=True, trajectory=False, mode="evidence_workflow"))

    def test_fresh_unconfigured_job_can_still_use_explicit_evidence_workflow(self):
        state = lesson.initial_agent_result(self.payload)
        with self.sessions() as db:
            db.add(Job(id="fresh-job", course_id="recovery-course", type="course_agent", status="pending",
                       payload=self.payload, result=state))
            db.commit()
        with patch.object(lesson, "_process_lesson_workflow") as workflow, patch.object(runtime, "process_agent_loop") as loop:
            lesson.process_course_agent("fresh-job")
        workflow.assert_called_once_with("fresh-job")
        loop.assert_not_called()
        with self.sessions() as db:
            result = db.get(Job, "fresh-job").result
            self.assertEqual(result["execution_mode"], "evidence_workflow")
            self.assertEqual(result["stop_reason"], "model_not_configured")
            self.assertIsNone(result["lesson_draft"])


if __name__ == "__main__":
    unittest.main()
