"""Offline bridge contract tests against an isolated, in-memory database."""
import os
import unittest
from unittest.mock import patch


# Do not read local credentials or create a live database while importing models.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
with patch("dotenv.load_dotenv", return_value=False):
    from backend.database import (
        AlignmentCandidate, Base, Chapter, Chunk, Course, Job, KnowledgeEdge,
        KnowledgeNode, RelationEvidence, Textbook,
    )
    from backend.api.teaching_bridge import router
    from backend.services.teaching_bridge import get_bridge_diagnostics, get_teaching_bridge
    from backend.services.source_titles import passage_concept_metadata

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class TeachingBridgeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.db.add_all([Course(id="course_a", title="植物课程"), Course(id="course_b", title="其他课程")])
        self.db.add_all([
            Textbook(id="book_a", course_id="course_a", filename="a.pdf", title="教材 A", format="pdf", total_pages=30),
            Textbook(id="book_b", course_id="course_a", filename="b.txt", title="教材 B", format="txt"),
            Textbook(id="book_c", course_id="course_a", filename="c.txt", title="未选教材", format="txt"),
            Textbook(id="book_other", course_id="course_b", filename="other.pdf", title="其他课程", format="pdf"),
        ])
        self.db.flush()
        for book_id in ("book_a", "book_b", "book_c", "book_other"):
            self.db.add(Chapter(id=f"chapter_{book_id}", textbook_id=book_id, title="第一章"))
        self.db.flush()
        for chunk_id, book_id, content, page in (
            ("chunk_a", "book_a", "叶绿体吸收光能。叶绿体内存在类囊体。", 5),
            ("chunk_b", "book_b", "叶绿体的类囊体膜为能量转换提供场所。", 7),
            ("chunk_c", "book_c", "叶绿体的原文来自未选教材。", 8),
            ("chunk_other", "book_other", "叶绿体的原文来自其他课程。", 9),
        ):
            self.db.add(Chunk(
                id=chunk_id, textbook_id=book_id, chapter_id=f"chapter_{book_id}",
                chapter_title="第一章", section_path=["第一章", "叶绿体"],
                content=content, page_start=page, page_end=page,
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_passages_are_balanced_scoped_and_have_source_links(self):
        with patch("backend.services.retrieval_service.embed_text", side_effect=AssertionError("no vector path")), patch(
            "backend.services.retrieval_service.embeddings_available", side_effect=AssertionError("no model path")
        ):
            result = get_teaching_bridge(self.db, "course_a", ["book_a", "book_b"], "叶绿体")
        self.assertEqual([group["textbook_id"] for group in result["groups"]], ["book_a", "book_b"])
        self.assertEqual([group["status"] for group in result["groups"]], ["evidence_found", "evidence_found"])
        first, second = [group["items"][0] for group in result["groups"]]
        self.assertEqual(first["id"], "chunk_a")
        self.assertEqual(second["id"], "chunk_b")
        self.assertEqual(first["section_path"], ["第一章", "叶绿体"])
        self.assertEqual(first["title"], "叶绿体")
        self.assertEqual(first["source_heading"], "叶绿体")
        self.assertEqual(first["display_title"], "叶绿体")
        self.assertEqual(first["title_origin"], "source_heading")
        self.assertEqual(first["match_kind"], "topic_heading")
        self.assertEqual(first["page_image_url"], "/api/textbooks/book_a/teaching/pages/5/image")
        self.assertIsNone(second["page_image_url"])
        self.assertEqual(first["review_status"], "unreviewed")
        self.assertEqual(result["method"], "lexical_only")
        self.assertEqual(result["confirmed_relations"], [])

    def test_unknown_or_foreign_book_is_rejected_instead_of_silently_dropped(self):
        for book_id in ("missing", "book_other"):
            with self.assertRaises(ValueError):
                get_teaching_bridge(self.db, "course_a", ["book_a", book_id], "叶绿体")
        with self.assertRaises(LookupError):
            get_teaching_bridge(self.db, "missing_course", ["book_a"], "叶绿体")

    def test_empty_recall_explains_uncertainty_without_claiming_absence_of_relation(self):
        result = get_teaching_bridge(self.db, "course_a", ["book_a", "book_b"], "岩浆冷却")
        self.assertTrue(all(group["status"] == "no_evidence" and not group["items"] for group in result["groups"]))
        self.assertIn("不代表两本教材没有关联", result["message"])
        self.assertTrue(all("不代表" in group["message"] for group in result["groups"]))

    def test_limits_deduplicate_and_preserve_literal_source_excerpt(self):
        long_content = "背景说明。" * 400 + "叶绿体吸收光能。" + "随后说明。" * 400
        self.db.add_all([
            Chunk(id="long", textbook_id="book_a", chapter_id="chapter_book_a", content=long_content, chunk_index=1),
            Chunk(id="duplicate", textbook_id="book_a", chapter_id="chapter_book_a", content=long_content, chunk_index=2),
        ])
        self.db.commit()
        result = get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体", limit_per_book=8)
        items = result["groups"][0]["items"]
        self.assertEqual(len(items), 2)
        excerpt = next(item for item in items if item["id"] == "long")
        self.assertTrue(excerpt["quote_truncated"])
        self.assertIn("叶绿体", excerpt["quote"])
        self.assertEqual(excerpt["quote"], long_content[excerpt["quote_start"]:excerpt["quote_end"]])
        self.assertLessEqual(len(excerpt["quote"]), 1400)
        limited = get_teaching_bridge(self.db, "course_a", ["book_a", "book_b"], "叶绿体", 1)
        self.assertTrue(all(len(group["items"]) <= 1 for group in limited["groups"]))
        for value in (0, 9):
            with self.assertRaises(ValueError):
                get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体", value)

    def test_read_only_does_not_write_jobs_candidates_or_index(self):
        from sqlalchemy import event
        writes = []

        def record_write(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP"}:
                writes.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_write)
        get_teaching_bridge(self.db, "course_a", ["book_a", "book_b"], "叶绿体")
        get_bridge_diagnostics(self.db, "course_a", ["book_a", "book_b"])
        self.assertEqual(writes, [])

    def test_concept_lookup_starts_with_its_overview_before_procedure_and_continuation(self):
        self.db.query(Chunk).filter(Chunk.textbook_id == "book_a").delete()
        self.db.add_all([
            Chunk(id="overview", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "一、叶绿体"], content="一、叶绿体\n叶绿体（chloroplast）是一类细胞器，内部具有膜系统。", chunk_index=0, page_start=10),
            Chunk(id="continuation", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "一、叶绿体"], content="叶绿体内的反应涉及多种分子。" * 10, chunk_index=1, page_start=11),
            Chunk(id="procedure", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "实验操作"], content="叶绿体实验操作：观察叶绿体，记录叶绿体形态。" * 12, chunk_index=2, page_start=20),
            Chunk(id="exercise", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "复习习题"], content="请描述叶绿体，比较叶绿体的形态和叶绿体的作用。" * 12, chunk_index=3, page_start=25),
        ])
        self.db.commit()
        result = get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体")
        self.assertEqual(result["groups"][0]["items"][0]["id"], "overview")
        self.assertEqual({item["id"] for item in result["groups"][0]["items"]}, {"overview", "continuation", "procedure", "exercise"})
        procedure = get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体实验操作")
        self.assertEqual(procedure["groups"][0]["items"][0]["id"], "procedure")

    def test_body_topic_heading_can_identify_overview_when_section_path_is_coarse(self):
        self.db.query(Chunk).filter(Chunk.textbook_id == "book_a").delete()
        self.db.add_all([
            Chunk(id="coarse_overview", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "结构"], content="图 1-1 结构\n（1）叶绿体 chloroplast\n叶绿体具有双层膜，其内部存在类囊体。", chunk_index=0),
            Chunk(id="detailed_continuation", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "结构"], content="叶绿体中的分子运动涉及叶绿体膜的改变，叶绿体膜上的反应参与物质合成。" * 8, chunk_index=1),
        ])
        self.db.commit()
        result = get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体")
        self.assertEqual(result["groups"][0]["items"][0]["id"], "coarse_overview")

    def test_generic_directory_uses_the_actual_numbered_topic_subheading(self):
        chunk = self.db.get(Chunk, "chunk_a")
        chunk.section_path = ["第二章 颈部", "（二）肌三角", "2. 内容"]
        chunk.content = "图 2-11 二腹肌后腹的毗邻关系\n图 2-12 颈前区结构\n（1）甲状腺thyroid gland\n1）形态与被膜：甲状腺呈H形。"
        metadata = passage_concept_metadata(chunk, "book_a", "甲状腺")
        self.assertEqual(metadata["source_heading"], "2. 内容")
        self.assertEqual(metadata["display_title"], "甲状腺thyroid gland")
        self.assertEqual(metadata["title_origin"], "source_subheading")
        self.db.commit()
        item = get_teaching_bridge(self.db, "course_a", ["book_a"], "甲状腺")["groups"][0]["items"][0]
        self.assertEqual(item["title"], "2. 内容")
        self.assertEqual(item["display_title"], metadata["display_title"])
        self.assertEqual(item["concept_key"], metadata["concept_key"])

    def test_numbered_source_headings_group_only_the_same_book_chapter_and_path(self):
        chunk = self.db.get(Chunk, "chunk_a")
        chunk.section_path = ["第二章 颈部", "（1）甲状腺"]
        intro = passage_concept_metadata(chunk, "book_a", "甲状腺")
        self.assertEqual(intro["display_title"], "甲状腺")
        self.assertEqual(intro["title_origin"], "source_heading")
        continuation = Chunk(id="continued", chapter_id=chunk.chapter_id, chapter_title=chunk.chapter_title,
                             section_path=chunk.section_path, content="两侧叶邻近气管。")
        self.assertEqual(passage_concept_metadata(continuation, "book_a", "甲状腺")["concept_key"], intro["concept_key"])
        self.assertNotEqual(passage_concept_metadata(continuation, "book_b", "甲状腺")["concept_key"], intro["concept_key"])
        continuation.chapter_id = "different_chapter"
        self.assertNotEqual(passage_concept_metadata(continuation, "book_a", "甲状腺")["concept_key"], intro["concept_key"])
        continuation.chapter_id = chunk.chapter_id
        continuation.section_path = ["第三节 另一位置", "（1）甲状腺"]
        self.assertNotEqual(passage_concept_metadata(continuation, "book_a", "甲状腺")["concept_key"], intro["concept_key"])

    def test_generic_continuations_and_similar_mentions_are_not_merged_as_concepts(self):
        chunk = self.db.get(Chunk, "chunk_a")
        chunk.section_path = ["第二章 颈部", "2. 内容"]
        chunk.content = "甲状腺的前面由浅入深有皮肤、浅筋膜；\n左右两侧叶与气管相邻。"
        first = passage_concept_metadata(chunk, "book_a", "甲状腺")
        other = Chunk(id="similar_mention", chapter_id=chunk.chapter_id, chapter_title=chunk.chapter_title,
                      section_path=chunk.section_path, content="甲状腺的前面还包括气管前筋膜。")
        second = passage_concept_metadata(other, "book_a", "甲状腺")
        self.assertEqual(first["display_title"], "甲状腺 · 原文片段")
        self.assertEqual(first["title_origin"], "topic_excerpt")
        self.assertEqual(second["title_origin"], "topic_excerpt")
        self.assertNotEqual(first["concept_key"], second["concept_key"])

    def test_unrelated_headings_captions_and_inline_prose_do_not_name_a_concept(self):
        chunk = self.db.get(Chunk, "chunk_a")
        chunk.section_path = ["第一章", "颈动脉三角"]
        for content in ("图2-13 甲状腺的形态\n颈动脉的分支经过甲状腺附近。",
                        "（1）甲状腺位于颈前区。", "甲状腺：位于颈前区，分为两侧叶。"):
            with self.subTest(content=content):
                chunk.content = content
                metadata = passage_concept_metadata(chunk, "book_a", "甲状腺")
                self.assertEqual(metadata["title_origin"], "topic_excerpt")
                self.assertEqual(metadata["source_heading"], "颈动脉三角")

    def test_short_body_facet_titles_and_long_queries_keep_source_provenance(self):
        chunk = self.db.get(Chunk, "chunk_a")
        chunk.section_path = ["第一章", "结构"]
        for heading, expected in (("3）甲状腺的动脉和喉的神经（图2-14）", "甲状腺的动脉和喉的神经(图2-14)"),
                                  ("2.3. 甲状腺的结构", "甲状腺的结构"),
                                  ("甲状腺的功能：", "甲状腺的功能")):
            with self.subTest(heading=heading):
                chunk.content = heading + "\n甲状腺的教材原文。"
                metadata = passage_concept_metadata(chunk, "book_a", "甲状腺的组成和功能是什么？")
                self.assertEqual(metadata["display_title"], expected)
                self.assertEqual(metadata["title_origin"], "source_subheading")
        chunk.content = "甲状腺的前面由浅入深有皮肤、浅筋膜。"
        query = "请结合甲状腺的教材原文说明本次课堂中的不同讲授重点，" * 5
        metadata = passage_concept_metadata(chunk, "book_a", query)
        self.assertEqual(metadata["title_origin"], "topic_excerpt")
        self.assertLessEqual(len(metadata["display_title"]), 70)
        self.assertTrue(metadata["display_title"].endswith("… · 原文片段"))

    def test_topic_section_introduction_precedes_deeper_facet_for_bare_concept_query(self):
        self.db.query(Chunk).filter(Chunk.textbook_id == "book_a").delete()
        self.db.add_all([
            Chunk(id="section_intro", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "第三节 | 叶绿体的光能转换"], content="第三节 | 叶绿体的光能转换\n叶绿体是细胞进行光合作用的场所，具有内部膜系统。", chunk_index=0),
            Chunk(id="deep_facet", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "第三节 | 叶绿体的光能转换", "三、叶绿体的调节"], content="叶绿体的反应随条件改变而变化。" * 8 + "\n（四）叶绿体的反馈调节\n叶绿体内的代谢产物参与调节。", chunk_index=1),
        ])
        self.db.commit()
        result = get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体")
        self.assertEqual(result["groups"][0]["items"][0]["id"], "section_intro")
        self.assertEqual(len(result["groups"][0]["items"]), 2)

    def test_pagination_ranks_complete_deduplicated_candidates_before_slicing(self):
        for index in range(10):
            self.db.add(Chunk(id=f"page_{index}", textbook_id="book_a", chapter_id="chapter_book_a", chapter_title="第一章", section_path=["第一章", "细胞器"], content=f"叶绿体原文材料 {index}。", chunk_index=index + 1))
        self.db.add(Chunk(id="duplicate_page", textbook_id="book_a", chapter_id="chapter_book_a", content="叶绿体原文材料 0。", chunk_index=15))
        self.db.commit()
        pages = [get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体", 3, offset)["groups"][0] for offset in (0, 3, 6, 9)]
        ids = [item["id"] for page in pages for item in page["items"]]
        self.assertEqual(len(ids), 11)
        self.assertEqual(len(set(ids)), 11)
        self.assertTrue(all(page["total_matches"] == 11 for page in pages))
        self.assertEqual([page["has_more"] for page in pages], [True, True, True, False])
        self.assertEqual([page["offset"] for page in pages], [0, 3, 6, 9])
        smaller = get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体", 2)["groups"][0]
        self.assertEqual([item["id"] for item in smaller["items"]], ids[:2])
        self.assertEqual(next(item for page in pages for item in page["items"] if item["quote"] == "叶绿体原文材料 0。")["match_kind"], "mention")
        beyond = get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体", 3, 10000)["groups"][0]
        self.assertEqual(beyond["items"], [])
        self.assertEqual(beyond["total_matches"], 11)
        self.assertEqual(beyond["status"], "evidence_found")
        self.assertFalse(beyond["has_more"])
        for offset in (-1, 10001):
            with self.assertRaises(ValueError):
                get_teaching_bridge(self.db, "course_a", ["book_a"], "叶绿体", 3, offset)

    def test_only_teacher_approved_scoped_topic_relations_are_exposed(self):
        for suffix, book_id, name in (("a", "book_a", "叶绿体"), ("b", "book_b", "叶绿体"), ("c", "book_c", "叶绿体"), ("other", "book_other", "叶绿体")):
            self.db.add(KnowledgeNode(
                id=f"node_{suffix}", course_id="course_b" if suffix == "other" else "course_a",
                textbook_id=book_id, name=name, source_paragraph="叶绿体吸收光能。", evidence_status="verified", page_start=5,
            ))
        self.db.flush()
        for edge_id, target, status in (("approved", "node_b", "approved"), ("suggested", "node_b", "unreviewed"), ("auto", "node_b", "auto_verified"), ("unselected", "node_c", "approved"), ("foreign", "node_other", "approved")):
            self.db.add(KnowledgeEdge(
                id=edge_id, course_id="course_a", source="node_a", target=target,
                relation_type="related_to", is_cross_textbook=True, review_status=status,
            ))
        self.db.flush()
        self.db.add(RelationEvidence(id="evidence", edge_id="approved", textbook_id="book_a", chunk_id="chunk_a", page_number=5, source_quote="叶绿体吸收光能。", evidence_role="source", quote_verified=True))
        self.db.commit()
        result = get_teaching_bridge(self.db, "course_a", ["book_a", "book_b"], "叶绿体")
        self.assertEqual([edge["id"] for edge in result["confirmed_relations"]], ["approved"])
        self.assertTrue(result["confirmed_relations"][0]["source_evidence"]["verified"])
        unrelated = get_teaching_bridge(self.db, "course_a", ["book_a", "book_b"], "岩浆冷却")
        self.assertEqual(unrelated["confirmed_relations"], [])

    def test_diagnostics_use_exact_selected_pair_and_unknown_metrics_are_null(self):
        self.db.add_all([
            Job(id="selected_run", course_id="course_a", type="integrate", status="completed", payload={"textbook_ids": ["book_b", "book_a"]}, result={"eligible_nodes": 2, "candidate_pairs": 0, "qualified_pairs": 0, "judged": 0, "candidates_created": 0}),
            Job(id="whole_course_run", course_id="course_a", type="integrate", status="completed", payload={"textbook_ids": ["book_a", "book_b", "book_c"]}, result={"eligible_nodes": 14}),
        ])
        self.db.commit()
        diagnostics = get_bridge_diagnostics(self.db, "course_a", ["book_a", "book_b"])
        self.assertEqual(diagnostics["latest_run"]["id"], "selected_run")
        self.assertEqual(diagnostics["latest_run"]["eligible_nodes"], 2)
        self.assertEqual(diagnostics["latest_run"]["qualified_pairs"], 0)
        self.assertIsNone(get_bridge_diagnostics(self.db, "course_a", ["book_a", "book_c"])["latest_run"])

    def test_http_supports_csv_and_repeated_keys_and_rejects_invalid_limits(self):
        app = FastAPI()
        app.include_router(router)
        with patch("backend.api.teaching_bridge.SessionLocal", self.sessions):
            client = TestClient(app)
            for scope in ("textbook_ids=book_a,book_b", "textbook_ids=book_a&textbook_ids=book_b"):
                response = client.get(f"/api/courses/course_a/teaching/bridge?{scope}&q=叶绿体")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["textbook_ids"], ["book_a", "book_b"])
            self.assertEqual(client.get("/api/courses/course_a/teaching/bridge?textbook_ids=book_a&q=叶绿体&limit_per_book=9").status_code, 422)
            self.assertEqual(client.get("/api/courses/course_a/teaching/bridge?textbook_ids=book_a&q=叶绿体&offset_per_book=10001").status_code, 422)
            self.assertEqual(client.get("/api/courses/course_a/teaching/bridge?textbook_ids=book_other&q=叶绿体").status_code, 400)
            self.assertEqual(client.get("/api/courses/missing/teaching/bridge?textbook_ids=book_a&q=叶绿体").status_code, 404)
            self.assertEqual(client.get("/api/courses/course_a/teaching/bridge?textbook_ids=book_a&q=%20%20").status_code, 400)


if __name__ == "__main__":
    unittest.main()
