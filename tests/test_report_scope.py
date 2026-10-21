import os
import unittest

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.agents.report_agent import export_report_markdown, generate_report
from backend.api.report import report_export, report_summary
from backend.database import (
    Chapter, Chunk, Course, IntegrationDecision, KnowledgeEdge,
    KnowledgeNode, SessionLocal, Textbook, init_db,
)


class CourseReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            for suffix in ("a", "b"):
                course_id, book_id = f"report_course_{suffix}", f"report_book_{suffix}"
                db.add(Course(id=course_id, title=f"独立课程{suffix}"))
                db.flush()
                db.add(Textbook(id=book_id, course_id=course_id, filename=f"{suffix}.txt",
                                title=f"专属教材{suffix}", format="txt", total_pages=10, total_chars=100))
                db.flush()
                db.add(Chapter(id=f"report_chapter_{suffix}", textbook_id=book_id, title="章节"))
                db.flush()
                db.add(Chunk(id=f"report_chunk_{suffix}", textbook_id=book_id,
                             chapter_id=f"report_chapter_{suffix}", content="课程原文"))
                db.add(KnowledgeNode(id=f"report_node_{suffix}", name=f"概念{suffix}",
                                     course_id=course_id, textbook_id=book_id))
            db.flush()
            db.add_all([
                IntegrationDecision(id="report_decision_a", action="keep", affected_nodes=["report_node_a"]),
                IntegrationDecision(id="report_decision_b", action="keep", affected_nodes=["report_node_b"]),
                IntegrationDecision(id="report_decision_mixed", action="merge", affected_nodes=["report_node_a", "report_node_b"]),
                IntegrationDecision(id="report_decision_unknown", action="merge", affected_nodes=[]),
            ])
            db.commit()
        finally:
            db.close()

    def tearDown(self):
        db = SessionLocal()
        try:
            db.query(IntegrationDecision).filter(IntegrationDecision.id.like("report_decision_%")).delete(synchronize_session=False)
            db.query(KnowledgeNode).filter(KnowledgeNode.id.like("report_node_%")).delete(synchronize_session=False)
            db.query(Chunk).filter(Chunk.id.like("report_chunk_%")).delete(synchronize_session=False)
            db.query(Chapter).filter(Chapter.id.like("report_chapter_%")).delete(synchronize_session=False)
            db.query(Textbook).filter(Textbook.id.like("report_book_%")).delete(synchronize_session=False)
            db.query(Course).filter(Course.id.like("report_course_%")).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def test_report_contains_only_current_course_data_and_real_index_status(self):
        report = report_summary("report_course_a")
        self.assertEqual(report["textbooks"]["count"], 1)
        self.assertEqual(report["textbooks"]["list"][0]["title"], "专属教材a")
        self.assertEqual(report["knowledge_graph"]["total_nodes"], 1)
        self.assertEqual(report["decisions"]["total"], 1)
        self.assertEqual(report["decisions"]["merge"], 0)
        self.assertFalse(report["rag"]["indexed"])
        self.assertEqual(report["rag"]["total_chunks"], 1)

    def test_export_uses_selected_course_without_static_medical_examples(self):
        text = export_report_markdown("report_course_a")
        self.assertIn("专属教材a", text)
        self.assertNotIn("专属教材b", text)
        self.assertNotIn("炎症", text)
        self.assertNotIn("向量检索 + 语义匹配", text)
        response = report_export({"course_id": "report_course_b"})
        self.assertIn("专属教材b", response.body.decode())
        self.assertNotIn("专属教材a", response.body.decode())

    def test_unknown_course_never_falls_back_to_global_data(self):
        report = generate_report("report_missing")
        self.assertEqual(report["textbooks"]["count"], 0)
        self.assertEqual(report["decisions"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
