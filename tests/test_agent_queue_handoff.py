"""Run one real queue-consumption cycle and inject API replies before release.

No worker thread is started. A queue sentinel exits the production worker loop
at its second get, leaving any required continuation observable in the queue.
"""
import copy
import os
import queue
import threading
import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import patch

with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
    from backend.api import agent as api
    from backend.agents import orchestrator
    from backend.database import Base, Course, Job, Textbook
    from backend.services import job_queue as jobs

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class StopAfterOneCycle(BaseException):
    pass


class OneCycleQueue(queue.Queue):
    def __init__(self):
        super().__init__()
        self.get_count = 0

    def get(self, *args, **kwargs):
        if self.get_count:
            raise StopAfterOneCycle()
        self.get_count += 1
        return super().get(block=False)


class AgentQueueHandoffTests(unittest.TestCase):
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
        for module in (api, orchestrator, jobs):
            self.patches.enter_context(patch.object(module, "SessionLocal", self.sessions))
        with self.sessions() as db:
            db.add(Course(id="handoff_course", title="队列交接回归"))
            db.flush()
            db.add(Textbook(id="handoff_book", course_id="handoff_course", title="测试教材", filename="handoff.txt", format="txt",
                            parse_status="completed", structure_status="confirmed"))
            db.commit()

    def job(self):
        job_id = "handoff_" + uuid.uuid4().hex[:12]
        payload = {"course_id": "handoff_course", "topic": "模块", "goal": "据教材安排一堂课", "textbook_ids": ["handoff_book"]}
        with self.sessions() as db:
            db.add(Job(id=job_id, course_id="handoff_course", type="course_agent", status="pending", payload=payload,
                       result={"agent_version": "lesson_agent_v3", "teacher_answers": [], "approval": None}))
            db.commit()
        return job_id

    def checkpoint(self, job_id, status, approval=None):
        with self.sessions() as db:
            job = db.get(Job, job_id)
            state = copy.deepcopy(job.result)
            state["approval"] = approval
            state["checkpoint_marker"] = "saved_before_worker_return"
            job.status, job.result = status, state
            db.commit()

    def saved(self, job_id):
        with self.sessions() as db:
            job = db.get(Job, job_id)
            return {"status": job.status, "retry_count": job.retry_count or 0, "result": copy.deepcopy(job.result)}

    def run_one_cycle(self, job_id, dispatch):
        controlled = OneCycleQueue()
        with patch.object(jobs, "_job_ids", controlled), patch.object(jobs, "_enqueued", set()), \
             patch.object(jobs, "_state_lock", threading.Lock()), patch.object(jobs, "_dispatch_job", side_effect=dispatch) as called:
            self.assertTrue(jobs.enqueue_job(job_id))
            with self.assertRaises(StopAfterOneCycle):
                jobs._worker_loop()
            with controlled.mutex:
                queued = list(controlled.queue)
            return {"queued": queued, "enqueued": set(jobs._enqueued),
                    "unfinished_tasks": controlled.unfinished_tasks, "dispatch_count": called.call_count}

    def assert_continuation_is_scheduled_once(self, job_id, cycle):
        self.assertEqual(self.saved(job_id)["status"], "pending")
        self.assertEqual(cycle["queued"], [job_id], "API accepted a continuation, but the worker release left a pending job without a queue item")
        self.assertEqual(cycle["enqueued"], {job_id})
        self.assertEqual(cycle["unfinished_tasks"], 1)
        self.assertEqual(cycle["dispatch_count"], 1)

    def test_teacher_reply_during_dispatch_return_is_not_lost(self):
        job_id = self.job()

        def dispatch(current):
            self.assertEqual(current, job_id)
            self.checkpoint(job_id, "waiting_user", {"type": "teacher_question", "request_id": "question_a", "question": "学生是否已学先修模块？"})
            response = api.respond_to_agent(job_id, api.AgentTeacherResponse(request_id="question_a", answer="已学过"))
            self.assertEqual(response["status"], "pending")

        cycle = self.run_one_cycle(job_id, dispatch)
        self.assert_continuation_is_scheduled_once(job_id, cycle)
        self.assertEqual(self.saved(job_id)["result"]["teacher_answers"][0]["answer"], "已学过")
        self.assertIsNone(self.saved(job_id)["result"]["approval"])

    def test_retry_during_failed_dispatch_return_is_not_lost(self):
        job_id = self.job()

        def dispatch(current):
            self.assertEqual(current, job_id)
            self.checkpoint(job_id, "failed")
            response = api.retry_agent_run(job_id)
            self.assertEqual(response["status"], "pending")

        cycle = self.run_one_cycle(job_id, dispatch)
        self.assert_continuation_is_scheduled_once(job_id, cycle)
        self.assertEqual(self.saved(job_id)["retry_count"], 1)

    def test_confirmed_chapter_resume_during_dispatch_return_is_not_lost(self):
        job_id = self.job()

        def dispatch(current):
            self.assertEqual(current, job_id)
            self.checkpoint(job_id, "waiting_user", {"type": "chapter_review", "question": "核对章节"})
            response = api.resume_agent_run(job_id)
            self.assertEqual(response["status"], "pending")

        cycle = self.run_one_cycle(job_id, dispatch)
        self.assert_continuation_is_scheduled_once(job_id, cycle)

    def test_unacknowledged_wait_or_terminal_status_does_not_busy_requeue(self):
        for status in ("waiting_user", "failed", "completed", "cancelled"):
            with self.subTest(status=status):
                job_id = self.job()
                cycle = self.run_one_cycle(job_id, lambda current: self.checkpoint(current, status))
                self.assertEqual(self.saved(job_id)["status"], status)
                self.assertEqual(cycle["queued"], [])
                self.assertEqual(cycle["enqueued"], set())
                self.assertEqual(cycle["unfinished_tasks"], 0)
                self.assertEqual(cycle["dispatch_count"], 1)


if __name__ == "__main__":
    unittest.main()
