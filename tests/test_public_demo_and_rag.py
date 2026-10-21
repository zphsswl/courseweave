import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from unittest.mock import MagicMock


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.responses import JSONResponse  # noqa: E402
from starlette.requests import Request  # noqa: E402

from backend.agents.rag_agent import _has_valid_source_citations, query_node_rag, query_rag  # noqa: E402
from backend.database import (  # noqa: E402
    AlignmentCandidate,
    CanonicalConcept,
    Chapter,
    Chunk,
    Course,
    Job,
    KnowledgeEdge,
    KnowledgeNode,
    RagIndexState,
    RelationEvidence,
    SessionLocal,
    Textbook,
    TextbookPage,
    init_db,
)
from backend.main import protect_public_demo  # noqa: E402
from backend.services.demo_seed import DEMO_AGENT_JOB_ID, DEMO_COURSE_ID, seed_demo_course  # noqa: E402
from backend.services.retrieval_service import get_index_status, invalidate_course_cache  # noqa: E402


def _request(path: str, method: str = "POST") -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 10000),
        "server": ("testserver", 443),
    })


def _retrieval(items):
    return {"results": items, "trace": {"strategy": "test", "candidate_count": len(items)}}


class PublicDemoProtectionTest(unittest.TestCase):
    def test_public_demo_blocks_mutations_but_keeps_evidence_query_available(self):
        call_next = AsyncMock(return_value=JSONResponse({"ok": True}, status_code=202))
        with patch("backend.main.PUBLIC_DEMO_READ_ONLY", True):
            blocked = asyncio.run(protect_public_demo(_request("/api/textbooks/upload"), call_next))
            allowed = asyncio.run(protect_public_demo(_request("/api/rag/query"), call_next))

        self.assertEqual(blocked.status_code, 403)
        self.assertIn("只读演示", json.loads(blocked.body)["detail"])
        self.assertEqual(allowed.status_code, 202)
        call_next.assert_awaited_once()


class RagAnswerTest(unittest.TestCase):
    def test_each_fact_sentence_and_list_item_needs_a_known_citation(self):
        for answer in (
            "无引用的结论。第二条结论 [S1]。",
            "- 第一条结论\n- 第二条结论 [S1]",
            "结论 [S0]。",
            "结论 [N1]。",
            "An uncited fact. Another fact [S1].",
        ):
            with self.subTest(answer=answer):
                self.assertFalse(_has_valid_source_citations(answer, 1))
        for answer in (
            "结论 [S1]。第二条结论。[S2]",
            "## 共同结论\n- 第一条 [S1]\n- 第二条 [S2]",
            "The value is 3.5 [S1]. Another fact.[S2]",
        ):
            with self.subTest(answer=answer):
                self.assertTrue(_has_valid_source_citations(answer, 2))
        self.assertTrue(_has_valid_source_citations("节点原文 [N1]。", 0, allow_node=True))

    def test_uncited_fact_forces_evidence_fallback_without_claiming_semantic_review(self):
        items = [{"id": "c1", "content": "可核对的教材原文。", "page_start": 1}]
        with (
            patch("backend.agents.rag_agent.retrieve", return_value=_retrieval(items)),
            patch("backend.agents.rag_agent._call_llm", return_value="第一条没有引用。第二条有引用 [S1]。"),
        ):
            result = query_rag("教材问题")
        self.assertEqual(result["answer_method"], "evidence_fallback")
        self.assertFalse(result["semantic_reviewed"])

    def test_covered_model_answer_still_requires_teacher_semantic_review(self):
        items = [{"id": "c1", "content": "教材原文。", "page_start": 1}]
        with (
            patch("backend.agents.rag_agent.retrieve", return_value=_retrieval(items)),
            patch("backend.agents.rag_agent._call_llm", return_value="教材结论 [S1]。"),
        ):
            result = query_rag("教材问题")
        self.assertEqual(result["answer_method"], "llm_grounded")
        self.assertFalse(result["citation_check"]["semantic_reviewed"])

    def test_node_answer_rejects_unknown_citations_and_falls_back_to_quote_not_generated_definition(self):
        node = SimpleNamespace(id="node1", course_id="course1", name="测试概念", evidence_status="verified",
                               source_paragraph="这是真实教材的原句。", definition="未经语义审核的模型定义。",
                               textbook_id="book1", textbook_title="教材", chapter_title="章节", page=5, page_start=5)
        db = MagicMock()
        db.query.return_value.filter.return_value.filter.return_value = db.query.return_value.filter.return_value
        db.query.return_value.filter.return_value.first.return_value = node
        db.query.return_value.filter.return_value.limit.return_value.all.return_value = []
        with (
            patch("backend.agents.rag_agent.SessionLocal", return_value=db),
            patch("backend.agents.rag_agent.retrieve", return_value=_retrieval([])),
            patch("backend.agents.rag_agent._call_llm", return_value="引用不存在的来源 [S1]。"),
        ):
            result = query_node_rag("node1", "请解释", "course1")
        self.assertEqual(result["answer_method"], "evidence_fallback")
        self.assertIn(node.source_paragraph, result["answer"])
        self.assertNotIn(node.definition, result["answer"])
        self.assertFalse(result["semantic_reviewed"])

    def test_unverified_node_without_retrieved_evidence_does_not_call_model(self):
        node = SimpleNamespace(id="node1", course_id="course1", name="测试概念", evidence_status="invalid",
                               source_paragraph="未核验的引文", definition="未核验定义")
        db = MagicMock()
        db.query.return_value.filter.return_value.filter.return_value = db.query.return_value.filter.return_value
        db.query.return_value.filter.return_value.first.return_value = node
        db.query.return_value.filter.return_value.limit.return_value.all.return_value = []
        with (
            patch("backend.agents.rag_agent.SessionLocal", return_value=db),
            patch("backend.agents.rag_agent.retrieve", return_value=_retrieval([])),
            patch("backend.agents.rag_agent._call_llm") as call_model,
        ):
            result = query_node_rag("node1", "请解释", "course1")
        self.assertEqual(result["answer_method"], "no_evidence")
        call_model.assert_not_called()

    def test_query_refuses_to_answer_without_course_evidence(self):
        with patch("backend.agents.rag_agent.retrieve", return_value=_retrieval([])):
            result = query_rag("教材没有覆盖的问题")

        self.assertEqual(result["answer_method"], "no_evidence")
        self.assertEqual(result["citations"], [])
        self.assertIn("未找到足够证据", result["answer"])

    def test_query_degrades_to_cited_evidence_when_model_fails(self):
        items = [{
            "id": "chunk_1",
            "textbook_id": "book_1",
            "textbook": "生理学",
            "chapter": "第一章",
            "section_path": ["第一章", "细胞功能"],
            "page_start": 12,
            "page_end": 12,
            "content": "细胞膜通过选择性通透维持细胞内环境稳定。",
            "score": 0.91,
            "retrievers": ["bm25"],
        }]
        with (
            patch("backend.agents.rag_agent.retrieve", return_value=_retrieval(items)),
            patch("backend.agents.rag_agent._call_llm", side_effect=RuntimeError("model unavailable")),
        ):
            result = query_rag("细胞膜有什么作用？")

        self.assertEqual(result["answer_method"], "evidence_fallback")
        self.assertIn("[S1]", result["answer"])
        self.assertEqual(result["citations"][0]["source_id"], "S1")
        self.assertEqual(result["citations"][0]["page"], 12)

    def test_query_rejects_model_answer_with_unknown_citation(self):
        items = [{
            "id": "chunk_1", "textbook_id": "book_1", "textbook": "生理学",
            "chapter": "第一章", "section_path": ["第一章"], "page_start": 3,
            "page_end": 3, "content": "教材中的可核验原文。", "score": 0.8,
            "retrievers": ["bm25"],
        }]
        with (
            patch("backend.agents.rag_agent.retrieve", return_value=_retrieval(items)),
            patch("backend.agents.rag_agent._call_llm", return_value="模型给出了一条没有来源的结论 [S99]"),
        ):
            result = query_rag("请回答问题")

        self.assertEqual(result["answer_method"], "evidence_fallback")
        self.assertIn("[S1]", result["answer"])


class DemoSeedContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def _clear_demo(self):
        db = SessionLocal()
        try:
            book_ids = ["demo_book_design", "demo_book_assessment"]
            edge_ids = [row[0] for row in db.query(KnowledgeEdge.id).filter(KnowledgeEdge.course_id == DEMO_COURSE_ID).all()]
            if edge_ids:
                db.query(RelationEvidence).filter(RelationEvidence.edge_id.in_(edge_ids)).delete(synchronize_session=False)
            db.query(Job).filter(Job.course_id == DEMO_COURSE_ID).delete(synchronize_session=False)
            db.query(KnowledgeEdge).filter(KnowledgeEdge.course_id == DEMO_COURSE_ID).delete(synchronize_session=False)
            db.query(AlignmentCandidate).filter(AlignmentCandidate.course_id == DEMO_COURSE_ID).delete(synchronize_session=False)
            db.query(KnowledgeNode).filter(KnowledgeNode.course_id == DEMO_COURSE_ID).delete(synchronize_session=False)
            db.query(CanonicalConcept).filter(CanonicalConcept.course_id == DEMO_COURSE_ID).delete(synchronize_session=False)
            db.query(RagIndexState).filter(RagIndexState.course_id == DEMO_COURSE_ID).delete(synchronize_session=False)
            db.query(Chunk).filter(Chunk.textbook_id.in_(book_ids)).delete(synchronize_session=False)
            db.query(Chapter).filter(Chapter.textbook_id.in_(book_ids)).delete(synchronize_session=False)
            db.query(TextbookPage).filter(TextbookPage.textbook_id.in_(book_ids)).delete(synchronize_session=False)
            db.query(Textbook).filter(Textbook.id.in_(book_ids)).delete(synchronize_session=False)
            db.query(Course).filter(Course.id == DEMO_COURSE_ID).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEMO_COURSE_ID)

    def setUp(self):
        self._clear_demo()

    def tearDown(self):
        self._clear_demo()

    def test_seed_is_query_ready_and_repairs_agent_demo_idempotently(self):
        seed_demo_course()
        self.assertEqual(get_index_status(DEMO_COURSE_ID)["status"], "ready")

        db = SessionLocal()
        try:
            state = db.get(RagIndexState, DEMO_COURSE_ID)
            state.content_signature = "stale-signature"
            db.query(Job).filter(Job.id == DEMO_AGENT_JOB_ID).delete()
            db.commit()
        finally:
            db.close()

        seed_demo_course()
        self.assertEqual(get_index_status(DEMO_COURSE_ID)["status"], "ready")
        db = SessionLocal()
        try:
            job = db.get(Job, DEMO_AGENT_JOB_ID)
            self.assertIsNotNone(job)
            self.assertEqual(job.status, "completed")
            self.assertEqual(job.result["artifact"]["citations"][0]["source_id"], "S1")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
