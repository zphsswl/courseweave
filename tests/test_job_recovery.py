import os
import unittest
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.api.jobs import list_textbook_jobs
from backend.database import Course, Job, SessionLocal, Textbook, init_db


class TextbookJobRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.add_all([Course(id="recovery_course", title="任务恢复课程"),
                        Course(id="recovery_other", title="其他课程")])
            db.flush()
            db.add_all([
                Textbook(id="recovery_book", course_id="recovery_course", title="教材", filename="book.txt", format="txt"),
                Textbook(id="recovery_second", course_id="recovery_course", title="教材二", filename="second.txt", format="txt"),
                Textbook(id="recovery_other_book", course_id="recovery_other", title="其他教材", filename="other.txt", format="txt"),
            ])
            db.flush()
            now = datetime(2026, 10, 20, 10)
            for index, (job_id, book_id, job_type, status, retries, course_id) in enumerate([
                ("recovery_old_parse", "recovery_book", "parse", "completed", 0, None),
                ("recovery_latest_graph", "recovery_book", "extract_graph", "processing", 0, "recovery_course"),
                ("recovery_legacy_failed", "recovery_second", "parse", "failed", 2, None),
                ("recovery_foreign", "recovery_other_book", "parse", "pending", 0, "recovery_other"),
                ("recovery_non_book", "recovery_book", "course_agent", "pending", 0, "recovery_course"),
            ]):
                db.add(Job(id=job_id, type=job_type, status=status, retry_count=retries,
                           course_id=course_id, payload={"textbook_id": book_id},
                           created_at=now + timedelta(seconds=index), progress=20, total=100))
            db.commit()
        finally:
            db.close()

    def tearDown(self):
        db = SessionLocal()
        try:
            db.query(Job).filter(Job.id.like("recovery_%")).delete(synchronize_session=False)
            db.query(Textbook).filter(Textbook.id.like("recovery_%")).delete(synchronize_session=False)
            db.query(Course).filter(Course.id.like("recovery_%")).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def test_recovery_returns_latest_attempt_per_book_with_hook_payload_and_progress(self):
        jobs = list_textbook_jobs("recovery_course")
        self.assertEqual({job["id"] for job in jobs}, {"recovery_latest_graph", "recovery_legacy_failed"})
        for job in jobs:
            self.assertIsInstance(job["payload"]["textbook_id"], str)
            self.assertIn(job["status"], {"processing", "failed"})
            self.assertEqual((job["progress"], job["total"]), (20, 100))
        failed = next(job for job in jobs if job["status"] == "failed")
        self.assertTrue(failed["recoverable"])
        self.assertEqual(failed["retry_count"], 2)

    def test_legacy_null_course_jobs_follow_their_textbooks_course(self):
        jobs = list_textbook_jobs("recovery_other")
        self.assertEqual([job["id"] for job in jobs], ["recovery_foreign"])
        self.assertEqual(list_textbook_jobs("recovery_missing"), [])


if __name__ == "__main__":
    unittest.main()
