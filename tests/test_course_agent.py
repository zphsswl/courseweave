import os
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.agents.course_agent import initial_agent_result, verify_artifact  # noqa: E402
from backend.api.agent import AgentRunCreate, create_agent_run, resume_agent_run  # noqa: E402
from backend.database import DEFAULT_COURSE_ID, Job, SessionLocal, Textbook, init_db  # noqa: E402


class CourseAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(Job).delete()
            db.query(Textbook).delete()
            db.add_all([
                Textbook(
                    id="agent_book_a",
                    course_id=DEFAULT_COURSE_ID,
                    filename="a.pdf",
                    title="教材 A",
                    format="pdf",
                    parse_status="completed",
                    structure_status="confirmed",
                    graph_status="completed",
                ),
                Textbook(
                    id="agent_book_b",
                    course_id=DEFAULT_COURSE_ID,
                    filename="b.pdf",
                    title="教材 B",
                    format="pdf",
                    parse_status="completed",
                    structure_status="confirmed",
                    graph_status="completed",
                ),
            ])
            db.commit()
        finally:
            db.close()

    def test_initial_result_exposes_a_goal_driven_tool_plan(self):
        state = initial_agent_result({
            "topic": "炎症",
            "goal": "生成炎症备课知识包",
            "textbook_ids": ["agent_book_a", "agent_book_b"],
            "requirements": ["教材差异"],
        })
        self.assertEqual(state["topic"], "炎症")
        self.assertEqual(state["plan"][0]["tool"], "inspect_course")
        self.assertEqual(state["plan"][-1]["tool"], "verify_result")
        self.assertGreaterEqual(len(state["plan"]), 7)

    def test_verifier_checks_book_page_grounding_and_structure(self):
        artifact = {
            "executive_summary": "概览",
            "teaching_objectives": ["目标"],
            "knowledge_sequence": [
                {"title": "定义", "explanation": "解释", "source_ids": ["S1"]},
            ],
            "common_ground": [
                {"claim": "共同点", "source_ids": ["S1", "S2"]},
            ],
            "textbook_differences": [],
            "misconceptions": [],
            "classroom_questions": ["问题"],
            "citations": [
                {"source_id": "S1", "textbook_id": "agent_book_a", "page_start": 10},
                {"source_id": "S2", "textbook_id": "agent_book_b", "page_start": 20},
            ],
        }
        quality = verify_artifact(artifact, ["agent_book_a", "agent_book_b"])
        self.assertEqual(quality["status"], "passed")
        self.assertEqual(quality["score"], 100)
        self.assertEqual(quality["covered_textbook_ids"], ["agent_book_a", "agent_book_b"])

    def test_agent_run_reuses_the_durable_job_queue(self):
        payload = AgentRunCreate(
            course_id=DEFAULT_COURSE_ID,
            topic="炎症",
            goal="生成炎症跨教材备课知识包",
            textbook_ids=["agent_book_a", "agent_book_b"],
            requirements=["教材差异"],
        )
        with patch("backend.api.agent.enqueue_job") as enqueue:
            job = create_agent_run(payload)
        self.assertEqual(job["type"], "course_agent")
        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["result"]["topic"], "炎症")
        enqueue.assert_called_once_with(job["id"])

    def test_waiting_agent_resumes_only_after_chapter_confirmation(self):
        db = SessionLocal()
        try:
            book = db.query(Textbook).filter(Textbook.id == "agent_book_a").one()
            book.structure_status = "confirmed"
            db.add(Job(
                id="agent_waiting",
                course_id=DEFAULT_COURSE_ID,
                type="course_agent",
                status="waiting_user",
                payload={"textbook_ids": [book.id]},
                result=initial_agent_result({"topic": "炎症", "goal": "生成备课方案", "textbook_ids": [book.id]}),
            ))
            db.commit()
        finally:
            db.close()
        with patch("backend.api.agent.enqueue_job") as enqueue:
            resumed = resume_agent_run("agent_waiting")
        self.assertEqual(resumed["status"], "pending")
        enqueue.assert_called_once_with("agent_waiting")


if __name__ == "__main__":
    unittest.main()
