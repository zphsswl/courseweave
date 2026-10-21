import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Imports must not inspect a developer's .env, and this test owns its own DB.
with patch("dotenv.load_dotenv", return_value=False):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from backend.database import Base, Chapter, Chunk, Course, KnowledgeNode, Textbook, TextbookPage, get_db
    from backend.api.teaching import router
    from backend.services import teaching_service as teaching


class TeachingContentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([Course(id="course_a", title="课堂课程"), Course(id="course_b", title="其他课程")])
        self.db.flush()
        self.book = Textbook(id="book_a", course_id="course_a", filename="book_a.pdf", title="局部解剖学", format="pdf", total_pages=12)
        self.db.add_all([self.book, Textbook(id="book_b", course_id="course_b", filename="book_b.txt", title="另一教材", format="txt")])
        self.db.flush()
        self.directory = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(teaching, "TEXTBOOK_ROOT", Path(self.directory.name))
        self.root_patch.start()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()
        teaching._render_page.cache_clear()
        self.root_patch.stop()
        self.directory.cleanup()

    def chapter(self, text, chapter_id="chapter_a", **kwargs):
        chapter = Chapter(id=chapter_id, textbook_id="book_a", title="第七章 上肢", page_start=1, page_end=12, content=text, **kwargs)
        self.db.add(chapter)
        self.db.flush()
        return chapter

    def test_full_chapter_is_not_cut_at_6000_characters_or_eight_sections(self):
        text = "\n".join(f"第{number}节 主题{number}\n" + "原始教材正文。" * 170 for number in range(1, 13))
        text += "\n第十三节 臂丛\n臂丛由多个部分构成，详细内容保留在全书后半段。"
        self.chapter(text)
        result = self.client.get("/api/textbooks/book_a/teaching").json()
        sections = result["chapters"][0]["sections"]
        self.assertEqual(len(sections), 13)
        self.assertIn("详细内容保留", sections[-1]["content"])
        self.assertGreater(sum(len(section["content"]) for section in sections), 6000)
        search = self.client.get("/api/textbooks/book_a/teaching/search", params={"q": "臂丛"}).json()
        self.assertEqual(search["items"][0]["section_id"], sections[-1]["id"])

    def test_subsection_hierarchy_and_parent_bodies_are_not_duplicated(self):
        self.chapter("第一节 肩部\n肩部总述。\n一、腋区\n腋区总述。\n（一）臂丛\n臂丛正文。\n（二）血管\n血管正文。\n第二节 手部\n手部正文。")
        sections = teaching.get_teaching_content(self.db, "book_a")["chapters"][0]["sections"]
        self.assertEqual([row["level"] for row in sections], [2, 3, 4, 4, 2])
        self.assertEqual(sections[2]["parent_id"], sections[1]["id"])
        self.assertEqual(sections[3]["parent_id"], sections[1]["id"])
        self.assertEqual(sections[-1]["parent_id"], "")
        self.assertEqual(sections[0]["content"], "肩部总述。")
        self.assertNotIn("臂丛正文", sections[0]["content"])

    def test_formal_section_markers_support_complete_aggregate_reading(self):
        self.chapter("第一节\u2002 |\u2002 肩部\n一、腋区\n腋区总述。\n（一）臂丛\n臂丛全部正文。\n（二）血管\n血管全部正文。\n第二节 手部\n手部正文。")
        result = teaching.get_teaching_content(self.db, "book_a")
        sections = result["chapters"][0]["sections"]
        self.assertEqual([section["formal_section"] for section in sections], [True, False, False, False, True])
        self.assertEqual(result["readiness"]["formal_section_count"], 2)
        first_formal = next(index for index, section in enumerate(sections) if section["formal_section"])
        next_formal = next(index for index in range(first_formal + 1, len(sections)) if sections[index]["formal_section"])
        # The frontend reads this whole source-ordered range, not only the parent body.
        reading = "\n".join(section["content"] for section in sections[first_formal:next_formal])
        self.assertEqual(sections[first_formal]["content"], "")
        self.assertIn("腋区总述", reading)
        self.assertEqual(reading.count("臂丛全部正文"), 1)
        self.assertEqual(reading.count("血管全部正文"), 1)
        self.assertNotIn("手部正文", reading)
        self.assertTrue(all(section["source_kind"] == "chapter" for section in sections))

    def test_chapter_without_formal_sections_uses_intro_and_top_level_topics(self):
        intro = "原教材独立导读说明细胞、组织、器官的结构及相互联系，正文仍然保留原有的来源，不把分组名称伪造为正式节。"
        self.chapter(intro + "\n一、\u2002研究内容\n研究内容正文。\n（一）细胞\n细胞正文。\n二、\u2002学习方法\n学习方法正文。")
        result = teaching.get_teaching_content(self.db, "book_a")
        sections = result["chapters"][0]["sections"]
        units = [row for row in sections if row["navigation_unit"]]
        self.assertEqual([row["title"] for row in units], ["本章正文", "一、 研究内容", "二、 学习方法"])
        self.assertFalse(any(row["formal_section"] for row in sections))
        self.assertEqual(result["readiness"]["navigation_unit_count"], 3)
        self.assertFalse(next(row for row in sections if "细胞" in row["title"])["navigation_unit"])

    def test_stored_pages_recover_earlier_opening_without_mutating_chapter(self):
        original = "第二节 手部\n手部晚页正文。"
        chapter = self.chapter(original, source_spans=[{"page_number": 3, "chapter_start": 0, "chapter_end": len(original)}])
        chapter.page_start = 3
        chapter.page_end = 5
        self.db.add_all([
            TextbookPage(id="toc", textbook_id="book_a", page_number=1, text="第七章 上肢\n第一节 肩部 . . . . . 2\n第二节 手部 . . . . . 3"),
            TextbookPage(id="opening", textbook_id="book_a", page_number=2, text="第七章\u2003上肢\n第一节 肩部\n补回本章开头的肩部正文。"),
            TextbookPage(id="running", textbook_id="book_a", page_number=3, text="第七章 上肢\n" + original),
        ])
        self.db.commit()
        result = teaching.get_teaching_content(self.db, "book_a")
        self.assertEqual(result["chapters"][0]["page_start"], 2)
        self.assertEqual(result["readiness"]["formal_section_count"], 2)
        self.assertEqual(result["readiness"]["recovered_openings"], [{"chapter_id": chapter.id, "original_page_start": 3, "page_start": 2}])
        self.assertEqual(teaching.search_teaching_content(self.db, "book_a", "补回")["items"][0]["page_start"], 2)
        self.assertEqual(teaching.search_teaching_content(self.db, "book_a", "晚页")["items"][0]["page_start"], 3)
        self.assertEqual(chapter.page_start, 3)
        self.assertEqual(chapter.content, original)
        self.assertFalse(self.db.dirty)

    def test_appendix_is_separate_unit_and_overprinted_reference_heading_stops_tail(self):
        self.chapter("第一节 主体\n真实医学主体必须保留。\n附录一\u2002 |\u2002 预防资料\n附录的医学内容也必须保留。\n一、具体方法\n具体方法正文。\n推荐阅读推荐阅读\n不属于课堂正文的参考书目。")
        result = teaching.get_teaching_content(self.db, "book_a")
        sections = result["chapters"][0]["sections"]
        units = [row for row in sections if row["navigation_unit"]]
        self.assertEqual(len(units), 2)
        self.assertTrue(units[0]["formal_section"])
        self.assertFalse(units[1]["formal_section"])
        self.assertTrue(units[1]["title"].startswith("附录一"))
        full = "\n".join(row["content"] for row in sections)
        self.assertIn("真实医学主体", full)
        self.assertIn("附录的医学内容", full)
        self.assertIn("具体方法正文", full)
        self.assertNotIn("参考书目", full)

    def test_exact_chapter_topic_intro_ranks_above_earlier_partial_heading(self):
        earlier = self.chapter("（一）热休克反应\n热休克反应属于前章内容。")
        earlier.title = "第六章 应激"
        later = self.chapter("休克是后章开头需要优先读取的主题。\n第一节 分类\n休克的分类正文。", "chapter_later", order_index=1)
        later.title = "第十三章 休克"
        result = teaching.search_teaching_content(self.db, "book_a", "休克")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["items"][0]["chapter_id"], later.id)
        self.assertEqual(result["items"][0]["title"], "本章正文")
        self.assertIn("热休克反应", result["items"][-1]["title"])

    def test_chapter_intro_precedes_same_named_bilingual_section_in_other_chapter(self):
        earlier = self.chapter("（一）热休克反应\n相关休克反应。\n（二）休克（shock）\n休克的精确小节正文。")
        earlier.title = "第六章 应激"
        later = self.chapter("休克章节导言。", "chapter_later", order_index=1)
        later.title = "第13章 休克"
        result = teaching.search_teaching_content(self.db, "book_a", "休克")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["items"][0]["chapter_id"], later.id)
        self.assertEqual(result["items"][0]["title"], "本章正文")
        self.assertIn("休克（shock）", result["items"][1]["title"])
        self.assertNotEqual(teaching._topic_key("维生素C"), teaching._topic_key("维生素"))

    def test_exact_chapter_first_navigation_unit_precedes_foreign_exact_section(self):
        earlier = self.chapter("（三）休克\n其他章同名小节的休克正文。")
        earlier.title = "第十四章 凝血与抗凝血平衡紊乱"
        later = self.chapter("第一节 概述\n休克专章的完整主题概述。\n第二节 分类\n休克的分类资料。", "chapter_later", order_index=1)
        later.title = "第十三章 休克"
        result = teaching.search_teaching_content(self.db, "book_a", "休克")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["items"][0]["chapter_id"], later.id)
        self.assertEqual(result["items"][0]["title"], "第一节 概述")
        self.assertEqual(result["items"][1]["chapter_id"], earlier.id)
        self.assertEqual(result["items"][2]["title"], "第二节 分类")

    def test_headingless_and_missing_chapters_have_stable_sections(self):
        self.chapter("没有小标题的原教材。\n\n第二段仍须保留。")
        self.chapter("", "chapter_empty", order_index=1)
        first = teaching.get_teaching_content(self.db, "book_a")
        second = teaching.get_teaching_content(self.db, "book_a")
        self.assertEqual(first, second)
        self.assertEqual(len(first["chapters"][1]["sections"]), 1)
        self.assertFalse(first["chapters"][1]["sections"][0]["formal_section"])
        self.assertIn("\n\n", first["chapters"][0]["sections"][0]["content"])
        self.assertEqual(first["readiness"]["missing_chapter_ids"], ["chapter_empty"])

    def test_exact_page_mapping_caption_location_and_noise_cleaning(self):
        page_one = "第一节 肩部\n肩部正文见图 7-2。\n局部解剖学\n88\n第二节 手部…………90\n"
        page_two = "第二节 臂丛\n臂丛正文不应丢失。\n"
        self.chapter(page_one + page_two, source_spans=[
            {"page_number": 8, "chapter_start": 0, "chapter_end": len(page_one)},
            {"page_number": 9, "chapter_start": len(page_one), "chapter_end": len(page_one + page_two)},
        ])
        self.db.add(TextbookPage(id="p10", textbook_id="book_a", page_number=10, text="图 7-2 肩部结构示意图"))
        result = teaching.get_teaching_content(self.db, "book_a")
        sections = result["chapters"][0]["sections"]
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["figure_refs"], [{"label": "图 7-2", "page_number": 10, "location": "caption"}])
        self.assertNotIn("局部解剖学", sections[0]["content"])
        search = teaching.search_teaching_content(self.db, "book_a", "臂丛")
        self.assertEqual((search["items"][0]["page_start"], search["items"][0]["page_end"]), (9, 9))

    def test_all_chunks_fallback_and_no_cross_book_content(self):
        self.chapter("")
        self.db.add(Chapter(id="other_chapter", textbook_id="book_b", title="其他章", content="外书独有臂丛正文"))
        for number in range(12):
            self.db.add(Chunk(id=f"chunk_{number}", chapter_id="chapter_a", textbook_id="book_a", content=f"第{number}段正文。" + ("末尾臂丛资料。" if number == 11 else ""), chunk_index=number, page_start=number + 1, page_end=number + 1, section_path=["第七章 上肢", "第一节 肩部"]))
        self.db.flush()
        result = teaching.get_teaching_content(self.db, "book_a")
        body = "".join(section["content"] for section in result["chapters"][0]["sections"])
        self.assertIn("末尾臂丛资料", body)
        self.assertNotIn("外书独有", body)
        hits = teaching.search_teaching_content(self.db, "book_a", "臂丛")
        self.assertEqual(hits["items"][0]["page_start"], 12)
        self.assertEqual(teaching.search_teaching_content(self.db, "book_a", "外书独有")["total"], 0)

    def test_stored_pages_fallback_and_wrapped_word_search(self):
        self.chapter("")
        self.db.add_all([
            TextbookPage(id="p1", textbook_id="book_a", page_number=1, text="第七章 上肢\n第一节 肩部\n臂\n丛的组成。"),
            TextbookPage(id="p2", textbook_id="book_a", page_number=2, text="第二节 手部\n手部正文。"),
        ])
        self.db.flush()
        result = teaching.get_teaching_content(self.db, "book_a")
        self.assertEqual(result["chapters"][0]["sections"][0]["source_kind"], "pages")
        self.assertEqual(teaching.search_teaching_content(self.db, "book_a", "臂丛")["total"], 1)

    def test_reading_does_not_mutate_teacher_nodes_or_chapters(self):
        chapter = self.chapter("第一节 肩部\n臂丛资料。")
        self.db.add(KnowledgeNode(id="teacher_node", name="教师术语", textbook_id="book_a", course_id="course_a", teacher_locked=True, definition="教师确认的定义"))
        self.db.commit()
        before = (chapter.content, self.db.get(KnowledgeNode, "teacher_node").definition)
        teaching.get_teaching_content(self.db, "book_a")
        teaching.search_teaching_content(self.db, "book_a", "臂丛")
        self.assertFalse(self.db.dirty)
        self.assertFalse(self.db.new)
        self.assertEqual(before, (chapter.content, self.db.get(KnowledgeNode, "teacher_node").definition))

    def test_pdf_spacing_and_inline_bilingual_subheading_keep_subject_and_body(self):
        self.chapter("本章数字资源\n第一节\u2002 |\u2002 概\u2003 述\n\n概述正文。\n一、腋窝\n3. 臂丛brachial plexus 臂丛的组成和主要分支有详细记载，不能只按前八个标题截断。\n" + "后续说明。" * 20)
        sections = teaching.get_teaching_content(self.db, "book_a")["chapters"][0]["sections"]
        self.assertEqual(sections[0]["title"], "第一节 概述")
        self.assertNotIn("本章数字资源", "".join(row["content"] for row in sections))
        hit = teaching.search_teaching_content(self.db, "book_a", "臂丛")["items"][0]
        self.assertIn("臂丛", hit["title"])
        self.assertEqual(hit["section_id"], sections[-1]["id"])
        self.assertIn("组成和主要分支", sections[-1]["content"])

    def test_api_validation_empty_search_missing_book_and_missing_pdf(self):
        self.assertEqual(self.client.get("/api/textbooks/missing/teaching").status_code, 404)
        self.assertEqual(self.client.get("/api/textbooks/book_a/teaching/search", params={"q": "  "}).status_code, 422)
        self.assertEqual(self.client.get("/api/textbooks/book_a/teaching/search", params={"q": "a", "limit": 51}).status_code, 422)
        self.assertEqual(self.client.get("/api/textbooks/book_a/teaching/pages/0/image").status_code, 422)
        self.assertEqual(self.client.get("/api/textbooks/book_a/teaching/pages/1/image").status_code, 404)

    def test_pdf_preview_is_physical_page_bounded_and_cached(self):
        import fitz
        path = Path(self.directory.name) / "book_a.pdf"
        with fitz.open() as document:
            document.new_page(width=300, height=500).insert_text((40, 40), "PAGE ONE")
            document.new_page(width=600, height=300).insert_text((40, 40), "PAGE TWO")
            document.save(path)
        response = self.client.get("/api/textbooks/book_a/teaching/pages/2/image")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        image = fitz.Pixmap(response.content)
        self.assertGreater(image.width, image.height)
        self.assertLessEqual(max(image.width, image.height), teaching.MAX_IMAGE_SIDE)
        self.assertLessEqual(image.width * image.height, teaching.MAX_IMAGE_PIXELS)
        self.assertLessEqual(len(response.content), teaching.MAX_IMAGE_BYTES)
        again = self.client.get("/api/textbooks/book_a/teaching/pages/2/image")
        self.assertEqual(response.headers["etag"], again.headers["etag"])
        self.assertGreater(teaching._render_page.cache_info().hits, 0)
        self.assertEqual(self.client.get("/api/textbooks/book_a/teaching/pages/3/image").status_code, 404)

    def test_unsafe_path_wrong_content_and_pdf_size_limit(self):
        outside = Path(self.directory.name).parent / "outside.pdf"
        for filename in ("../outside.pdf", str(outside), "..\\outside.pdf", "C:outside.pdf"):
            self.book.filename = filename
            with self.assertRaises(teaching.TeachingSourceError) as error:
                teaching.resolve_pdf_path(self.book)
            self.assertEqual(error.exception.status_code, 404)
        self.book.filename = "book_a.pdf"
        path = Path(self.directory.name) / "book_a.pdf"
        path.write_text("not a PDF", encoding="utf-8")
        self.assertEqual(self.client.get("/api/textbooks/book_a/teaching/pages/1/image").status_code, 422)
        with patch.object(teaching, "MAX_PDF_BYTES", 4):
            self.assertEqual(self.client.get("/api/textbooks/book_a/teaching/pages/1/image").status_code, 413)


if __name__ == "__main__":
    unittest.main()
