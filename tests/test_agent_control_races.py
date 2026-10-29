"""Inject a real checkpoint between control API read and conditional SQL write.

No threads or timing guesses: the production Query.update is preceded by one
committed competing state transition in the isolated database. The old request
must fail its compare-and-swap rather than overwrite that newer result.
"""
import copy
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
with patch("dotenv.load_dotenv", return_value=False):
    from backend.api import agent as api
    from backend.agents import orchestrator
    from backend.database import Base, Course, Job, Textbook

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Query, sessionmaker
from sqlalchemy.pool import StaticPool


class AgentControlRaceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.patches = ExitStack()
        for module in (api, orchestrator):
            self.patches.enter_context(patch.object(module, "SessionLocal", self.sessions))
        self.enqueue = self.patches.enter_context(patch.object(api, "enqueue_job"))
        with self.sessions() as db:
            db.add(Course(id="control-course", title="控制接口竞态测试"))
            db.flush()
            db.add(Textbook(id="control-book", course_id="control-course", filename="book.txt", title="当前教材",
                            format="txt", parse_status="completed", structure_status="confirmed"))
            db.commit()

    def tearDown(self):
        self.patches.close()
        self.engine.dispose()

    def make_job(self, status, approval=None):
        state = {"agent_version": "lesson_agent_v3", "artifact": None, "lesson_draft": None,
                 "approval": approval, "teacher_answers": [], "trajectory": [],
                 "budget": {"steps_used": 1, "rag_queries_used": 0, "drafts_used": 0}}
        with self.sessions() as db:
            db.add(Job(id="control-job", type="course_agent", course_id="control-course", status=status,
                       payload={"course_id": "control-course", "textbook_ids": ["control-book"]}, result=state))
            db.commit()

    def race(self, mutate):
        original_update = Query.update
        calls, committed = [], {}

        def interleave(query, values, *args, **kwargs):
            if not calls:
                calls.append(True)
                with self.sessions() as db:
                    job = db.get(Job, "control-job")
                    state = copy.deepcopy(job.result)
                    mutate(job, state)
                    job.result = state
                    db.commit()
                    committed.update(status=job.status, result=copy.deepcopy(job.result))
            return original_update(query, values, *args, **kwargs)

        return patch.object(Query, "update", interleave), calls, committed

    def assert_conflict_preserves(self, call, mutate):
        injection, calls, committed = self.race(mutate)
        with injection, self.assertRaises(HTTPException) as error:
            call()
        self.assertEqual(error.exception.status_code, 409)
        self.assertTrue(calls, "the competing transition must happen at the real conditional write")
        self.enqueue.assert_not_called()
        with self.sessions() as db:
            job = db.get(Job, "control-job")
            self.assertEqual(job.status, committed["status"])
            self.assertEqual(job.result, committed["result"])

    def test_cancel_cannot_erase_a_tool_checkpoint_saved_after_its_read(self):
        self.make_job("processing")

        def tool_finished(job, state):
            state["artifact"] = {"title": "工具刚保存的新稿件", "citations": [{"source_id": "S1"}]}
            state["budget"].update(steps_used=2, drafts_used=1)
            state["trajectory"].append({"id": "new-action", "action": "write_draft", "status": "completed"})

        self.assert_conflict_preserves(lambda: api.cancel_agent_run("control-job"), tool_finished)

    def test_old_question_response_cannot_overwrite_a_new_waiting_question(self):
        self.make_job("waiting_user", {"type": "teacher_question", "request_id": "question-1", "question": "先讲哪部分？"})

        def another_tab_already_answered_and_agent_asked_again(job, state):
            # Status returned to waiting_user: a status-only predicate cannot
            # distinguish this newer checkpoint from the original question.
            state["teacher_answers"] = [{"request_id": "question-1", "question": "先讲哪部分？", "answer": "另一标签已提交"}]
            state["approval"] = {"type": "teacher_question", "request_id": "question-2", "question": "学生先修条件是什么？"}
            state["budget"].update(steps_used=3, rag_queries_used=1)
            state["trajectory"] = [{"id": "new-action", "action": "ask_teacher", "status": "completed"}]

        self.assert_conflict_preserves(
            lambda: api.respond_to_agent("control-job", api.AgentTeacherResponse(request_id="question-1", answer="过期请求中的回答")),
            another_tab_already_answered_and_agent_asked_again,
        )

    def test_old_chapter_resume_cannot_revive_a_concurrently_cancelled_run(self):
        self.make_job("waiting_user", {"type": "chapter_review", "textbooks": [{"id": "control-book", "title": "当前教材"}]})

        def teacher_cancelled(job, state):
            job.status = "cancelled"
            state.update(stop_reason="user_cancelled", approval=None)
            state["artifact"] = {"title": "取消时保留的原成果"}

        self.assert_conflict_preserves(lambda: api.resume_agent_run("control-job"), teacher_cancelled)


if __name__ == "__main__":
    unittest.main()
