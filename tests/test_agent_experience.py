"""Agent request, source merging and printable saved-draft contracts, offline."""
import copy
from html.parser import HTMLParser
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
with patch("dotenv.load_dotenv", return_value=False):
    from backend.api import agent as api
    from backend.database import Base, Chapter, Chunk, Course, Job, Textbook
    from backend.services.teaching_board import create_teaching_board

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class MainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.active = True

    def handle_endtag(self, tag):
        if tag == "main":
            self.active = False

    def handle_data(self, text):
        if self.active:
            self.parts.append(text)


class AgentExperienceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([Course(id="experience_course", title="备课课程"), Course(id="experience_other", title="其他课程")])
            db.flush()
            for suffix in ("a", "b", "c", "other"):
                db.add(Textbook(id=f"experience_book_{suffix}",
                                course_id="experience_other" if suffix == "other" else "experience_course",
                                title=f"教材{suffix}", filename=f"{suffix}.txt", format="txt"))
            db.flush()
            for suffix in ("a", "b", "c", "other"):
                db.add(Chapter(id=f"experience_chapter_{suffix}", textbook_id=f"experience_book_{suffix}", title="第一章"))
            db.flush()
            for suffix in ("a", "b", "c", "other"):
                db.add(Chunk(id=f"experience_chunk_{suffix}", textbook_id=f"experience_book_{suffix}",
                             chapter_id=f"experience_chapter_{suffix}", textbook_title=f"教材{suffix}",
                             chapter_title="第一章", content=f"教材{suffix}的真实原文。", page_start=5, page_end=5))
            db.commit()
            self.board = create_teaching_board(db, "experience_course", {
                "topic": "本课对照", "textbook_ids": ["experience_book_a", "experience_book_b"],
                "selections": [
                    {"chunk_id": "experience_chunk_a", "teaching_title": "先建立概念", "note": "保留教师的原始备注"},
                    {"chunk_id": "experience_chunk_b", "teaching_title": "再看另一教材"},
                ], "connections": [{"source_chunk_id": "experience_chunk_a", "target_chunk_id": "experience_chunk_b",
                                    "relation_type": "extends", "reason": "教师指定的讲授过渡"}],
            })
        self.patches = [patch.object(api, "SessionLocal", self.sessions),
                        patch("backend.agents.orchestrator.SessionLocal", self.sessions),
                        patch.object(api, "enqueue_job")]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()

    def request(self, **changes):
        values = {
            "course_id": "experience_course", "topic": "本课对照", "goal": "围绕教材原文组织课堂教学",
            "textbook_ids": ["experience_book_a", "experience_book_b", "experience_book_c"],
            "audience": "二年级学生", "prior_knowledge": "已学基础结构",
            "context": {"board_id": self.board["id"],
                        "selected_chunk_ids": ["experience_chunk_a", "experience_chunk_b"],
                        "supplemental_chunk_ids": ["experience_chunk_c"]},
        }
        values.update(changes)
        return api.AgentRunCreate(**values)

    def test_supplemental_material_and_copied_request_preserve_board_context(self):
        original = api.create_agent_run(self.request())
        copied = api.create_agent_run(api.AgentRunCreate.model_validate(copy.deepcopy(original["payload"])))
        for job in (original, copied):
            context = job["payload"]["context"]
            self.assertEqual(context["selected_chunk_ids"], ["experience_chunk_a", "experience_chunk_b", "experience_chunk_c"])
            self.assertEqual([row["chunk_id"] for row in context["selections"]], ["experience_chunk_a", "experience_chunk_b"])
            self.assertEqual(context["selections"][0]["note"], "保留教师的原始备注")
            self.assertEqual(len(context["connections"]), 1)
            self.assertEqual(job["result"]["request"]["audience"], "二年级学生")
            self.assertEqual(job["result"]["request"]["prior_knowledge"], "已学基础结构")

    def test_readding_board_source_as_supplement_keeps_teacher_notes_order_and_links(self):
        request = self.request()
        request.context.supplemental_chunk_ids = ["experience_chunk_a", "experience_chunk_c"]
        job = api.create_agent_run(request)
        context = job["payload"]["context"]
        self.assertEqual(context["selected_chunk_ids"], ["experience_chunk_a", "experience_chunk_b", "experience_chunk_c"])
        self.assertEqual([row["chunk_id"] for row in context["selections"]], ["experience_chunk_a", "experience_chunk_b"])
        self.assertEqual(context["selections"][0]["teaching_title"], "先建立概念")
        self.assertEqual(len(context["connections"]), 1)

    def test_supplements_cannot_expand_course_or_selected_textbook_scope(self):
        for chunk_id, books in (
            ("experience_chunk_other", ["experience_book_a", "experience_book_b", "experience_book_c"]),
            ("experience_chunk_c", ["experience_book_a", "experience_book_b"]),
        ):
            with self.subTest(chunk_id=chunk_id):
                request = self.request(textbook_ids=books)
                request.context.supplemental_chunk_ids = [chunk_id]
                with self.assertRaises(HTTPException) as error:
                    api.create_agent_run(request)
                self.assertEqual(error.exception.status_code, 400)
        with self.sessions() as db:
            self.assertEqual(db.query(Job).filter(Job.type == "course_agent").count(), 0)

    def test_combined_source_limit_and_learner_context_limits_are_enforced(self):
        request = self.request(context={"selected_chunk_ids": [f"chunk_{index}" for index in range(48)],
                                        "supplemental_chunk_ids": ["extra_chunk"]})
        with self.assertRaises(HTTPException) as error:
            api.create_agent_run(request)
        self.assertEqual(error.exception.status_code, 422)
        for change in ({"audience": "学" * 161}, {"prior_knowledge": "学" * 501}):
            with self.assertRaises(ValidationError):
                self.request(**change)

    def test_print_export_prefers_saved_draft_and_keeps_offline_safe_markup(self):
        job = api.create_agent_run(self.request())
        with self.sessions() as db:
            row = db.get(Job, job["id"])
            state = copy.deepcopy(row.result)
            state["artifact"] = {"title": "旧生成稿", "executive_summary": "旧摘要"}
            state["lesson_draft"] = {"title": "教师保存稿", "teacher_edited": True,
                                      "executive_summary": "需要保留的摘要。<script>alert(1)</script>",
                                      "knowledge_sequence": [{"title": "讲解", "explanation": "教学内容", "source_ids": ["S1"]}],
                                      "citations": [{"source_id": "S1", "textbook": "教材a", "page_start": 5, "quote": "真实原文"}]}
            row.result = state
            db.commit()
        response = api.export_lesson(job["id"], format="html")
        text = response.body.decode()
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("教师保存稿", text)
        self.assertNotIn("旧生成稿", text)
        self.assertNotIn("<script>", text)
        self.assertIn("default-src 'none'", text)
        self.assertIn("真实原文", text)

    def test_printed_comparison_symbols_match_saved_teacher_text(self):
        job = api.create_agent_run(self.request())
        summary = "浓度 < 5，与 A & B 对照。"
        with self.sessions() as db:
            row = db.get(Job, job["id"])
            state = copy.deepcopy(row.result)
            state["lesson_draft"] = {"title": "比较符号", "executive_summary": summary, "teacher_edited": True}
            row.result = state
            db.commit()
        document = api.export_lesson(job["id"], format="html").body.decode()
        parser = MainText()
        parser.feed(document)
        self.assertIn(summary, "".join(parser.parts))


if __name__ == "__main__":
    unittest.main()
