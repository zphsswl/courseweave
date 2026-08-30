import os
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.database import (  # noqa: E402
    init_db,
    SessionLocal,
    DEFAULT_COURSE_ID,
    Chapter,
    Chunk,
    Job,
    KnowledgeEdge,
    KnowledgeNode,
    RelationEvidence,
    Textbook,
)
from backend.agents.kg_extraction_agent import (  # noqa: E402
    CONCEPT_PROMPT,
    TOPIC_PROMPT,
    _rule_concepts,
    extract_textbook_graph,
)
from backend.agents.orchestrator import update_job  # noqa: E402


class GraphExtractionProgressTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(RelationEvidence).delete()
            db.query(KnowledgeEdge).delete()
            db.query(KnowledgeNode).delete()
            db.query(Chunk).delete()
            db.query(Chapter).delete()
            db.query(Job).delete()
            db.query(Textbook).delete()
            db.commit()
        finally:
            db.close()

    def tearDown(self):
        self.setUp()

    def test_extraction_reports_fine_grained_progress_through_separate_job_writes(self):
        source = "肺泡通气量是每分钟进入肺泡并参与气体交换的新鲜气体量。"
        content = source * 12
        db = SessionLocal()
        try:
            db.add(Textbook(
                id="progress_book", course_id=DEFAULT_COURSE_ID,
                filename="progress.txt", title="生理学", format="txt",
                structure_status="confirmed",
            ))
            db.commit()
            db.add(Chapter(
                id="progress_chapter", textbook_id="progress_book", title="肺通气",
                content=content, char_count=len(content), order_index=1,
            ))
            db.commit()
            db.add(Chunk(
                id="progress_chunk", textbook_id="progress_book", chapter_id="progress_chapter",
                textbook_title="生理学", chapter_title="肺通气", content=content,
                char_count=len(content), chunk_index=0,
            ))
            db.add(Job(id="progress_job", course_id=DEFAULT_COURSE_ID, type="extract_graph"))
            db.commit()
        finally:
            db.close()

        topic_result = {
            "chapter_topic": {
                "name": "肺通气", "definition": "肺泡气体更新过程",
                "learning_objective": "理解有效通气", "source_quote": source,
            },
            "section_topics": [
                {"local_id": "s1", "name": "肺泡通气量", "scope": "有效通气指标", "source_quote": source},
            ],
            "_meta": {"method": "llm"},
        }
        concept_result = {
            "nodes": [
                {
                    "local_id": "n1", "name": "肺泡通气量", "definition": "有效通气指标",
                    "concept_type": "concept", "importance": 4, "source_quote": source,
                    "quality_reason": "核心生理指标",
                },
            ],
            "edges": [],
            "_meta": {"method": "llm"},
        }
        progress_events = []

        def report(progress, total, message):
            progress_events.append((progress, total, message))
            update_job("progress_job", progress=progress, total=total, message=message)

        with patch("backend.agents.kg_extraction_agent._call_llm_topic", return_value=topic_result), \
             patch("backend.agents.kg_extraction_agent._call_llm_concept", return_value=concept_result):
            result = extract_textbook_graph("progress_book", progress_callback=report)

        self.assertGreaterEqual(len(progress_events), 5)
        self.assertTrue(all(total == 100 for _, total, _ in progress_events))
        self.assertGreater(max(progress for progress, _, _ in progress_events), 90)
        self.assertEqual(result["graph_status"], "completed")

        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == "progress_job").one()
            self.assertGreater(job.progress, 90)
            self.assertIn("整理知识树", job.message)
        finally:
            db.close()

    def test_extraction_prompts_format_json_examples_without_key_errors(self):
        topic = TOPIC_PROMPT.format(textbook="生理学", chapter="第一章", content="原文")
        concept = CONCEPT_PROMPT.format(
            textbook="生理学", chapter="第一章", section_name="肺通气",
            section_scope="气体更新", content="原文",
        )
        self.assertIn('{"chapter_topic":', topic)
        self.assertIn('{"nodes":', concept)

    def test_interrupted_graph_resumes_without_duplicating_completed_chapter(self):
        source = "肺泡通气量是每分钟进入肺泡并参与气体交换的新鲜气体量。"
        content = source * 12
        db = SessionLocal()
        try:
            db.add(Textbook(
                id="resume_book", course_id=DEFAULT_COURSE_ID,
                filename="resume.txt", title="生理学", format="txt",
                structure_status="confirmed", graph_status="pending",
            ))
            db.commit()
            db.add(Chapter(
                id="resume_chapter", textbook_id="resume_book", title="肺通气",
                content=content, char_count=len(content), order_index=1,
            ))
            db.add(Chunk(
                id="resume_chunk", textbook_id="resume_book", chapter_id="resume_chapter",
                textbook_title="生理学", chapter_title="肺通气", content=content,
                char_count=len(content), chunk_index=0,
            ))
            db.commit()
        finally:
            db.close()

        topic_result = {
            "chapter_topic": {
                "name": "肺通气", "definition": "肺泡气体更新过程",
                "learning_objective": "理解有效通气", "source_quote": source,
            },
            "section_topics": [],
            "_meta": {"method": "llm"},
        }

        def interrupt_after_checkpoint(progress, _total, _message):
            if progress >= 97:
                raise RuntimeError("simulated service restart")

        with patch("backend.agents.kg_extraction_agent._call_llm_topic", return_value=topic_result):
            with self.assertRaisesRegex(RuntimeError, "service restart"):
                extract_textbook_graph("resume_book", progress_callback=interrupt_after_checkpoint)

        db = SessionLocal()
        try:
            count_before = db.query(KnowledgeNode).filter(
                KnowledgeNode.textbook_id == "resume_book"
            ).count()
            chapter = db.query(Chapter).filter(Chapter.id == "resume_chapter").one()
            self.assertEqual(chapter.extraction_status, "completed")
        finally:
            db.close()

        with patch("backend.agents.kg_extraction_agent._call_llm_topic", return_value=topic_result):
            result = extract_textbook_graph("resume_book")

        db = SessionLocal()
        try:
            count_after = db.query(KnowledgeNode).filter(
                KnowledgeNode.textbook_id == "resume_book"
            ).count()
        finally:
            db.close()
        self.assertEqual(count_after, count_before)
        self.assertEqual(result["graph_status"], "completed")

    def test_rule_concepts_uses_term_after_called_marker(self):
        content = (
            "这种对环境变化的应答反应，称为适应（adaptation）。"
            "萎缩（atrophy）是指已发育正常的细胞、组织或器官的体积缩小。"
            "激素受体所致，称为内分泌性肥大（endocrine hypertrophy）或激素性肥大。"
        )
        result = _rule_concepts(content, "细胞适应")
        names = [node["name"] for node in result["nodes"]]
        self.assertIn("适应（adaptation）", names)
        self.assertIn("萎缩（atrophy）", names)
        self.assertIn("内分泌性肥大（endocrine hypertrophy）", names)
        self.assertNotIn("应答反应", names)
        self.assertNotIn("激素受体所致", names)


if __name__ == "__main__":
    unittest.main()
