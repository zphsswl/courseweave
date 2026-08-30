import os
import unittest
from unittest.mock import patch

from sqlalchemy.exc import OperationalError


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.database import (  # noqa: E402
    Job,
    SessionLocal,
    _recover_interrupted_jobs,
    init_db,
)
from backend.agents.orchestrator import _write_with_retry  # noqa: E402


class DurableJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(Job).delete()
            db.commit()
        finally:
            db.close()

    def test_interrupted_jobs_are_requeued_instead_of_failed(self):
        db = SessionLocal()
        try:
            db.add(Job(
                id="resume_me",
                type="extract_graph",
                status="processing",
                progress=73,
                retry_count=0,
                payload={"textbook_id": "book_1"},
            ))
            db.commit()
        finally:
            db.close()

        _recover_interrupted_jobs()

        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == "resume_me").one()
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.progress, 73)
            self.assertEqual(job.retry_count, 1)
            self.assertIn("重新排队", job.message)
            self.assertEqual(job.error, "")
        finally:
            db.close()

    def test_short_job_writes_retry_transient_sqlite_locks(self):
        commit_calls = []

        class FakeSession:
            def commit(self):
                commit_calls.append(1)
                if len(commit_calls) < 3:
                    raise OperationalError("UPDATE jobs", {}, Exception("database is locked"))

            def rollback(self):
                pass

            def close(self):
                pass

        with patch("backend.agents.orchestrator.SessionLocal", side_effect=FakeSession), \
             patch("backend.agents.orchestrator.time.sleep"):
            result = _write_with_retry(lambda _db: "saved", attempts=3)

        self.assertEqual(result, "saved")
        self.assertEqual(len(commit_calls), 3)


if __name__ == "__main__":
    unittest.main()
