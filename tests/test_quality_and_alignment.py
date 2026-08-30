import os
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.database import (  # noqa: E402
    init_db,
    SessionLocal,
    DEFAULT_COURSE_ID,
    Textbook,
    TextbookPage,
    Chapter,
    Chunk,
    KnowledgeNode,
    AlignmentCandidate,
    KnowledgeEdge,
    RelationEvidence,
    IntegrationDecision,
    RagIndexState,
)
from backend.services.quality_gate import (  # noqa: E402
    validate_node_candidate,
    validate_edge_candidate,
    has_broken_text,
)
from backend.services.alignment_service import (  # noqa: E402
    _parse_json,
    generate_alignment_candidates,
    is_meaningful_alignment_node,
    run_alignment,
)
from backend.api.alignment import get_alignment_graph  # noqa: E402
from backend.agents.ingestion_agent import _invalidate_textbook_derivatives  # noqa: E402


class QualityAndAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(RelationEvidence).delete()
            db.query(KnowledgeEdge).delete()
            db.query(AlignmentCandidate).delete()
            db.query(KnowledgeNode).delete()
            db.query(IntegrationDecision).delete()
            db.query(Chunk).delete()
            db.query(Chapter).delete()
            db.query(TextbookPage).delete()
            db.query(RagIndexState).delete()
            db.query(Textbook).delete()
            db.commit()
        finally:
            db.close()

    def test_alignment_model_output_requires_scalar_explanations(self):
        with self.assertRaisesRegex(ValueError, "reason must be a string"):
            _parse_json(
                '{"relation_type":"related_to","confidence":0.8,'
                '"reason":{"unexpected":"object"},"differences":""}'
            )

        parsed = _parse_json(
            '{"relation_type":"equivalent_to","confidence":0.93,'
            '"reason":"定义与教学边界一致","differences":"教材侧重点不同"}'
        )
        self.assertEqual(parsed["relation_type"], "equivalent_to")
        self.assertEqual(parsed["reason"], "定义与教学边界一致")

    def test_high_confidence_model_alignment_stays_pending_for_teacher_review(self):
        db = SessionLocal()
        try:
            db.add_all([
                Textbook(id="trust_book_a", course_id=DEFAULT_COURSE_ID, filename="a.txt", title="教材 A", format="txt", graph_status="completed"),
                Textbook(id="trust_book_b", course_id=DEFAULT_COURSE_ID, filename="b.txt", title="教材 B", format="txt", graph_status="completed"),
            ])
            db.flush()
            db.add_all([
                KnowledgeNode(
                    id="trust_node_a", course_id=DEFAULT_COURSE_ID, name="动脉粥样硬化斑块形成机制",
                    definition="脂质沉积与炎症反应共同促进动脉粥样硬化斑块形成", textbook_id="trust_book_a", textbook_title="教材 A",
                    chapter_title="第一章", page_start=1, page_end=1, granularity="core_concept",
                    source_paragraph="脂质沉积与炎症反应共同促进动脉粥样硬化斑块形成。", evidence_status="verified",
                    importance=5, quality_score=.95,
                ),
                KnowledgeNode(
                    id="trust_node_b", course_id=DEFAULT_COURSE_ID, name="动脉粥样硬化斑块形成机制",
                    definition="脂质沉积和慢性炎症参与动脉粥样硬化斑块的形成", textbook_id="trust_book_b", textbook_title="教材 B",
                    chapter_title="第二章", page_start=2, page_end=2, granularity="core_concept",
                    source_paragraph="脂质沉积和慢性炎症参与动脉粥样硬化斑块的形成。", evidence_status="verified",
                    importance=5, quality_score=.95,
                ),
            ])
            db.commit()
        finally:
            db.close()

        with patch("backend.services.alignment_service.judge_alignment_candidate", return_value={
            "relation_type": "equivalent_to", "confidence": .99, "reason": "模型认为相同",
            "differences": "", "method": "llm",
        }):
            result = run_alignment(DEFAULT_COURSE_ID, textbook_ids=["trust_book_a", "trust_book_b"])

        self.assertGreaterEqual(result["judged"], 1)
        self.assertEqual(result["auto_approved"], 0)
        db = SessionLocal()
        try:
            candidate = db.query(AlignmentCandidate).filter(
                AlignmentCandidate.source_node_id == "trust_node_a",
                AlignmentCandidate.target_node_id == "trust_node_b",
            ).first()
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.status, "pending")
            self.assertEqual(db.query(KnowledgeEdge).filter(KnowledgeEdge.is_cross_textbook.is_(True)).count(), 0)
        finally:
            db.close()

    def tearDown(self):
        db = SessionLocal()
        try:
            db.query(RelationEvidence).delete()
            db.query(KnowledgeEdge).delete()
            db.query(AlignmentCandidate).delete()
            db.query(KnowledgeNode).delete()
            db.query(IntegrationDecision).delete()
            db.query(Chunk).delete()
            db.query(Chapter).delete()
            db.query(TextbookPage).delete()
            db.query(RagIndexState).delete()
            db.query(Textbook).delete()
            db.commit()
        finally:
            db.close()

    def test_node_quote_must_be_grounded_in_source(self):
        source = "肺泡通气量是每分钟进入肺泡并参与气体交换的新鲜气体量。"
        valid = validate_node_candidate({
            "name": "肺泡通气量",
            "definition": "衡量有效肺通气的生理指标。",
            "concept_type": "concept",
            "source_quote": source,
        }, source)
        invalid = validate_node_candidate({
            "name": "肺泡通气量",
            "definition": "衡量有效肺通气的生理指标。",
            "concept_type": "concept",
            "source_quote": "教材中不存在的引用内容。",
        }, source)

        self.assertTrue(valid.accepted)
        self.assertTrue(valid.evidence_verified)
        self.assertFalse(invalid.evidence_verified)
        self.assertIn("source_quote_not_found", invalid.flags)

    def test_semantic_edge_without_evidence_is_rejected(self):
        result = validate_edge_candidate({
            "source": "n1",
            "target": "n2",
            "relation_type": "prerequisite",
            "source_quote": "",
        }, "原文", {"n1", "n2"})
        self.assertFalse(result.accepted)
        self.assertIn("missing_relation_evidence", result.flags)

    def test_sentence_and_toc_lines_are_not_usable_concept_names(self):
        noisy = KnowledgeNode(
            id="noise", course_id=DEFAULT_COURSE_ID,
            name="一、组织细胞肿瘤概述................", definition="目录项目不是概念定义",
            textbook_id="book", textbook_title="教材", source_paragraph="目录项目不是概念证据。",
            granularity="section_topic", evidence_status="verified",
        )
        sentence = KnowledgeNode(
            id="sentence", course_id=DEFAULT_COURSE_ID,
            name="肺淤血由左心衰竭引起，左心压力升高，阻碍肺静脉回流。",
            definition="肺静脉回流受阻所形成的病理改变",
            textbook_id="book", textbook_title="教材", source_paragraph="肺淤血由左心衰竭引起。",
            granularity="core_concept", evidence_status="verified",
        )
        self.assertFalse(is_meaningful_alignment_node(noisy))
        self.assertFalse(is_meaningful_alignment_node(sentence))

    def test_front_matter_and_broken_quotes_never_enter_alignment(self):
        front_matter = KnowledgeNode(
            id="front", course_id=DEFAULT_COURSE_ID,
            name="课程学习方法", definition="说明本教材的学习顺序与使用方法",
            textbook_id="book", textbook_title="教材", chapter_title="绪论/前言",
            source_paragraph="本教材供相关专业师生使用。", granularity="core_concept",
            evidence_status="verified",
        )
        broken = KnowledgeNode(
            id="broken", course_id=DEFAULT_COURSE_ID,
            name="炎症反应", definition="机体针对损伤产生的防御反应",
            textbook_id="book", textbook_title="教材", chapter_title="炎症",
            source_paragraph="炎症是防御反应。\x08\ufffd\ufffd", granularity="core_concept",
            evidence_status="verified",
        )
        self.assertFalse(is_meaningful_alignment_node(front_matter))
        self.assertFalse(is_meaningful_alignment_node(broken))
        self.assertTrue(has_broken_text(broken.source_paragraph))

    def test_generic_structure_titles_never_enter_alignment(self):
        for index, name in enumerate(("概述", "分类", "病因和发病机制", "炎症的分类")):
            node = KnowledgeNode(
                id=f"generic_{index}", course_id=DEFAULT_COURSE_ID,
                name=name, definition="这是一段足够长但只描述教材结构的文字",
                textbook_id="book", textbook_title="教材", chapter_title="第四章 炎症",
                source_paragraph="教材原文中包含一段足够长的结构性说明。",
                granularity="section_topic", evidence_status="verified",
            )
            self.assertFalse(is_meaningful_alignment_node(node), name)

    def test_cross_textbook_candidates_are_course_scoped_and_evidence_scoped(self):
        db = SessionLocal()
        try:
            db.add_all([
                Textbook(
                    id="align_book_a",
                    course_id=DEFAULT_COURSE_ID,
                    filename="a.pdf",
                    title="教材 A",
                    format="pdf",
                ),
                Textbook(
                    id="align_book_b",
                    course_id=DEFAULT_COURSE_ID,
                    filename="b.pdf",
                    title="教材 B",
                    format="pdf",
                ),
            ])
            db.flush()
            for node_id, textbook_id, title in (
                ("align_node_a", "align_book_a", "教材 A"),
                ("align_node_b", "align_book_b", "教材 B"),
            ):
                db.add(KnowledgeNode(
                    id=node_id,
                    course_id=DEFAULT_COURSE_ID,
                    name="肺泡通气量",
                    definition="每分钟进入肺泡参与交换的新鲜气体量",
                    textbook_id=textbook_id,
                    textbook_title=title,
                    granularity="core_concept",
                    source_paragraph="肺泡通气量是每分钟进入肺泡并参与交换的新鲜气体量。",
                    evidence_status="verified",
                ))
            db.commit()
        finally:
            db.close()

        result = generate_alignment_candidates(DEFAULT_COURSE_ID)
        self.assertEqual(result["candidates_created"], 1, result)
        db = SessionLocal()
        try:
            candidate = db.query(AlignmentCandidate).one()
            self.assertEqual(candidate.course_id, DEFAULT_COURSE_ID)
            self.assertEqual(candidate.status, "pending")
        finally:
            db.close()

    def test_alignment_candidates_only_use_selected_textbooks(self):
        db = SessionLocal()
        try:
            books = [
                Textbook(id=f"selected_book_{suffix}", course_id=DEFAULT_COURSE_ID,
                         filename=f"{suffix}.pdf", title=f"教材 {suffix}", format="pdf")
                for suffix in ("a", "b", "c")
            ]
            db.add_all(books)
            db.flush()
            db.add_all([
                KnowledgeNode(
                    id=f"selected_node_{suffix}", course_id=DEFAULT_COURSE_ID,
                    name="炎症反应", definition="机体针对组织损伤产生的防御性反应",
                    textbook_id=f"selected_book_{suffix}", textbook_title=f"教材 {suffix}",
                    granularity="core_concept", source_paragraph="炎症是机体针对损伤产生的防御反应。",
                    evidence_status="verified",
                )
                for suffix in ("a", "b", "c")
            ])
            db.commit()
        finally:
            db.close()

        result = generate_alignment_candidates(
            DEFAULT_COURSE_ID,
            textbook_ids=["selected_book_a", "selected_book_b"],
        )
        self.assertEqual(result["candidates_created"], 1)
        db = SessionLocal()
        try:
            candidate = db.query(AlignmentCandidate).one()
            node_ids = {candidate.source_node_id, candidate.target_node_id}
            self.assertEqual(node_ids, {"selected_node_a", "selected_node_b"})
        finally:
            db.close()

    def test_specific_related_concepts_can_link_without_exact_names(self):
        db = SessionLocal()
        try:
            db.add_all([
                Textbook(id="specific_book_a", course_id=DEFAULT_COURSE_ID,
                         filename="a.pdf", title="组织学", format="pdf"),
                Textbook(id="specific_book_b", course_id=DEFAULT_COURSE_ID,
                         filename="b.pdf", title="病理学", format="pdf"),
            ])
            db.flush()
            db.add_all([
                KnowledgeNode(
                    id="specific_node_a", course_id=DEFAULT_COURSE_ID, name="甲状腺",
                    definition="甲状腺由滤泡和滤泡旁细胞构成并分泌甲状腺激素",
                    textbook_id="specific_book_a", textbook_title="组织学",
                    chapter_title="内分泌系统", granularity="core_concept",
                    source_paragraph="甲状腺由滤泡和滤泡旁细胞构成。",
                    evidence_status="verified",
                ),
                KnowledgeNode(
                    id="specific_node_b", course_id=DEFAULT_COURSE_ID, name="甲状腺肿",
                    definition="甲状腺肿是甲状腺滤泡增生导致的甲状腺体积增大",
                    textbook_id="specific_book_b", textbook_title="病理学",
                    chapter_title="内分泌系统疾病", granularity="core_concept",
                    source_paragraph="甲状腺滤泡增生可导致甲状腺体积增大。",
                    evidence_status="verified",
                ),
            ])
            db.commit()
        finally:
            db.close()

        result = generate_alignment_candidates(
            DEFAULT_COURSE_ID,
            textbook_ids=["specific_book_a", "specific_book_b"],
        )
        self.assertEqual(result["candidates_created"], 1, result)

    def test_shared_generic_suffix_does_not_create_false_alignment(self):
        db = SessionLocal()
        try:
            db.add_all([
                Textbook(id="suffix_book_a", course_id=DEFAULT_COURSE_ID,
                         filename="a.pdf", title="教材 A", format="pdf"),
                Textbook(id="suffix_book_b", course_id=DEFAULT_COURSE_ID,
                         filename="b.pdf", title="教材 B", format="pdf"),
            ])
            db.flush()
            db.add_all([
                KnowledgeNode(
                    id="suffix_node_a", course_id=DEFAULT_COURSE_ID, name="免疫性疾病",
                    definition="免疫调节异常造成组织损伤并引起机体功能改变",
                    textbook_id="suffix_book_a", textbook_title="教材 A",
                    chapter_title="免疫", granularity="core_concept",
                    source_paragraph="免疫调节异常可以造成组织损伤。",
                    evidence_status="verified",
                ),
                KnowledgeNode(
                    id="suffix_node_b", course_id=DEFAULT_COURSE_ID, name="传染性疾病",
                    definition="病原体进入机体造成组织损伤并引起机体功能改变",
                    textbook_id="suffix_book_b", textbook_title="教材 B",
                    chapter_title="感染", granularity="core_concept",
                    source_paragraph="病原体进入机体后可以造成组织损伤。",
                    evidence_status="verified",
                ),
            ])
            db.commit()
        finally:
            db.close()

        result = generate_alignment_candidates(
            DEFAULT_COURSE_ID,
            textbook_ids=["suffix_book_a", "suffix_book_b"],
        )
        self.assertEqual(result["candidates_created"], 0, result)

    def test_current_topic_nodes_are_available_before_and_after_alignment(self):
        db = SessionLocal()
        try:
            db.add_all([
                Textbook(id="topic_book_a", course_id=DEFAULT_COURSE_ID,
                         filename="a.pdf", title="主题教材 A", format="pdf", graph_status="review"),
                Textbook(id="topic_book_b", course_id=DEFAULT_COURSE_ID,
                         filename="b.pdf", title="主题教材 B", format="pdf", graph_status="review"),
            ])
            db.flush()
            db.add_all([
                KnowledgeNode(
                    id="topic_node_a", course_id=DEFAULT_COURSE_ID, name="炎症反应",
                    definition="机体针对损伤产生的防御反应", textbook_id="topic_book_a",
                    textbook_title="主题教材 A", chapter_title="第四章 炎症",
                    granularity="section_topic", source_paragraph="炎症是机体对损伤的防御反应。",
                    evidence_status="verified", importance=4, quality_score=1.0,
                ),
                KnowledgeNode(
                    id="topic_node_b", course_id=DEFAULT_COURSE_ID, name="炎症反应",
                    definition="血管和细胞共同参与的防御过程", textbook_id="topic_book_b",
                    textbook_title="主题教材 B", chapter_title="第五章 免疫",
                    granularity="section_topic", source_paragraph="炎症反应包含血管和细胞反应。",
                    evidence_status="verified", importance=4, quality_score=1.0,
                ),
            ])
            db.commit()
        finally:
            db.close()

        before = get_alignment_graph(
            DEFAULT_COURSE_ID,
            textbook_ids=["topic_book_a", "topic_book_b"],
            limit=240,
        )
        self.assertEqual([group["node_count"] for group in before["groups"]], [1, 1])
        self.assertEqual([group["linked_node_count"] for group in before["groups"]], [0, 0])
        self.assertEqual(before["total_nodes"], 0)

        result = generate_alignment_candidates(
            DEFAULT_COURSE_ID,
            textbook_ids=["topic_book_a", "topic_book_b"],
        )
        self.assertEqual(result["eligible_nodes"], 2)
        self.assertEqual(result["candidates_created"], 1)

        after = get_alignment_graph(
            DEFAULT_COURSE_ID,
            textbook_ids=["topic_book_a", "topic_book_b"],
            limit=240,
        )
        self.assertEqual([group["linked_node_count"] for group in after["groups"]], [1, 1])
        self.assertEqual(after["total_nodes"], 2)
        self.assertEqual(after["total_edges"], 1)
        edge = after["edges"][0]
        self.assertEqual(edge["relation_type"], "related_to")
        self.assertGreater(edge["confidence"], 0)
        self.assertTrue(edge["why"])
        self.assertEqual(edge["source_evidence"]["textbook"], "主题教材 A")
        self.assertEqual(edge["target_evidence"]["textbook"], "主题教材 B")
        self.assertTrue(edge["source_evidence"]["quote"])
        self.assertIn("page_start", edge["target_evidence"])

    def test_unverified_legacy_nodes_are_excluded_from_cross_textbook_graph(self):
        db = SessionLocal()
        try:
            db.add_all([
                Textbook(id="legacy_book_a", course_id=DEFAULT_COURSE_ID,
                         filename="a.pdf", title="旧教材 A", format="pdf", graph_status="completed"),
                Textbook(id="legacy_book_b", course_id=DEFAULT_COURSE_ID,
                         filename="b.pdf", title="旧教材 B", format="pdf", graph_status="completed"),
            ])
            db.flush()
            db.add_all([
                KnowledgeNode(
                    id="legacy_node_a", course_id=DEFAULT_COURSE_ID, name="细胞适应",
                    definition="细胞应对环境变化的反应", textbook_id="legacy_book_a",
                    textbook_title="旧教材 A", chapter_title="第一章", granularity="core_concept",
                    source_paragraph="细胞适应是细胞应对环境变化的反应。", evidence_status="unverified",
                    importance=4, quality_score=.8,
                ),
                KnowledgeNode(
                    id="legacy_node_b", course_id=DEFAULT_COURSE_ID, name="细胞适应",
                    definition="细胞针对刺激产生的适应性改变", textbook_id="legacy_book_b",
                    textbook_title="旧教材 B", chapter_title="第二章", granularity="core_concept",
                    source_paragraph="细胞可针对刺激产生适应性改变。", evidence_status="unverified",
                    importance=4, quality_score=.8,
                ),
            ])
            db.commit()
        finally:
            db.close()

        result = generate_alignment_candidates(
            DEFAULT_COURSE_ID,
            textbook_ids=["legacy_book_a", "legacy_book_b"],
        )
        self.assertEqual(result["candidates_created"], 0, result)

        graph = get_alignment_graph(
            DEFAULT_COURSE_ID,
            textbook_ids=["legacy_book_a", "legacy_book_b"],
            limit=240,
        )
        self.assertEqual(len(graph["groups"]), 2)
        self.assertEqual(graph["total_nodes"], 0)
        self.assertEqual(graph["total_edges"], 0)

    def test_force_reparse_invalidates_stale_graph_chunks_and_rag_index(self):
        db = SessionLocal()
        try:
            book = Textbook(
                id="reparse_book", course_id=DEFAULT_COURSE_ID,
                filename="book.pdf", title="待重解析教材", format="pdf",
                parse_status="completed", graph_status="completed", index_status="completed",
            )
            db.add(book)
            db.flush()
            db.add(TextbookPage(
                id="reparse_page", textbook_id=book.id, page_number=1,
                text="旧原文", char_count=3, has_text=True, extraction_method="native",
            ))
            db.add(Chapter(
                id="reparse_chapter", textbook_id=book.id, title="第一章",
                content="旧章节原文" * 30, char_count=150, page_start=1, page_end=1,
            ))
            db.add(Chunk(
                id="reparse_chunk", textbook_id=book.id, chapter_id="reparse_chapter",
                textbook_title=book.title, chapter_title="第一章", content="旧 chunk",
                char_count=7, page_start=1, page_end=1,
            ))
            db.add(KnowledgeNode(
                id="reparse_node", course_id=DEFAULT_COURSE_ID, name="旧知识点",
                definition="旧知识点定义", textbook_id=book.id, textbook_title=book.title,
                chapter_title="第一章", source_paragraph="旧教材证据原文。",
                granularity="core_concept", evidence_status="verified",
            ))
            db.add(IntegrationDecision(
                id="reparse_decision", action="keep", affected_nodes=["reparse_node"],
            ))
            db.add(RagIndexState(
                course_id=DEFAULT_COURSE_ID, status="ready", chunk_count=1,
            ))
            db.commit()

            _invalidate_textbook_derivatives(db, book)
            db.commit()

            self.assertEqual(db.query(TextbookPage).filter_by(textbook_id=book.id).count(), 0)
            self.assertEqual(db.query(Chapter).filter_by(textbook_id=book.id).count(), 0)
            self.assertEqual(db.query(Chunk).filter_by(textbook_id=book.id).count(), 0)
            self.assertEqual(db.query(KnowledgeNode).filter_by(textbook_id=book.id).count(), 0)
            self.assertIsNone(db.query(IntegrationDecision).filter_by(id="reparse_decision").first())
            self.assertEqual(db.query(RagIndexState).filter_by(course_id=DEFAULT_COURSE_ID).one().status, "stale")
            self.assertEqual(book.graph_status, "pending")
        finally:
            db.query(RagIndexState).filter_by(course_id=DEFAULT_COURSE_ID).delete()
            db.query(Textbook).filter_by(id="reparse_book").delete()
            db.commit()
            db.close()

if __name__ == "__main__":
    unittest.main()
