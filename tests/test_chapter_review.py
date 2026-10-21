"""Chapter corrections, source preservation and API transaction safety, fully offline.

Every test owns a separate in-memory database. The API session factory and cache
invalidation are patched, so no project database, PDF, vector store or model is used.
"""
import copy
import hashlib
import os
import re
import unittest
from unittest.mock import patch

with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}), patch("dotenv.load_dotenv", return_value=False):
    from backend.api import textbooks as textbook_api
    from backend.database import (
        Base, Chapter, Chunk, Course, Job, KnowledgeNode, RagIndexState, Textbook,
        TextbookPage,
    )
    from backend.services.chapter_review import range_capability

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class ChapterReviewTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def enable_constraints(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.pages = {number: f"第 {number} 页的独立教材正文，帮助核对来源。" * 8 for number in range(1, 6)}
        with self.sessions() as db:
            db.add(Course(id="review_course", title="目录校对回归课程"))
            db.flush()
            db.add_all([
                Textbook(id="review_book", course_id="review_course", title="待核对教材", filename="review.pdf", format="pdf", total_pages=5, parse_status="completed", graph_status="pending", index_status="completed", structure_status="review"),
                Textbook(id="foreign_book", course_id="review_course", title="另一教材", filename="foreign.pdf", format="pdf", total_pages=1, parse_status="completed"),
            ])
            db.flush()
            for number, content in self.pages.items():
                db.add(TextbookPage(id=f"review_page_{number}", textbook_id="review_book", page_number=number, text=content, char_count=len(content), has_text=True))
            db.add_all([
                self.chapter("chapter_a", "第一章", 1, 2, 0),
                self.chapter("chapter_b", "第二章", 3, 5, 1),
                Chapter(id="foreign_chapter", textbook_id="foreign_book", title="外部目录", page_start=1, page_end=1, order_index=0, level=1),
            ])
            db.flush()
            for chapter_id, title, start, end in (("chapter_a", "第一章", 1, 2), ("chapter_b", "第二章", 3, 5)):
                content = "\n\n".join(self.pages[number] for number in range(start, end + 1))
                db.add(Chunk(id=f"old_{chapter_id}", textbook_id="review_book", chapter_id=chapter_id, textbook_title="待核对教材", chapter_title=title, section_path=[title, "原有小节"], content=content, char_count=len(content), page_start=start, page_end=end, content_hash=hashlib.sha256(content.encode()).hexdigest()))
            db.add(RagIndexState(course_id="review_course", status="ready", chunk_count=2, content_signature="old-signature"))
            db.commit()
        app = FastAPI()
        app.include_router(textbook_api.router)
        self.api_sessions = patch.object(textbook_api, "SessionLocal", self.sessions)
        self.api_sessions.start()
        self.cache_patch = patch("backend.services.retrieval_service.invalidate_course_cache")
        self.invalidate = self.cache_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.cache_patch.stop()
        self.api_sessions.stop()
        self.engine.dispose()

    def chapter(self, chapter_id, title, start, end, order):
        parts, spans, offset = [], [], 0
        for number in range(start, end + 1):
            text = self.pages[number]
            if parts:
                offset += 2
            parts.append(text)
            spans.append({"page_number": number, "chapter_start": offset, "chapter_end": offset + len(text)})
            offset += len(text)
        content = "\n\n".join(parts)
        return Chapter(id=chapter_id, textbook_id="review_book", title=title, page_start=start, page_end=end, content=content, char_count=len(content), order_index=order, level=1, parent_id="", source_spans=spans)

    def payload(self, **overrides):
        result = {
            "confirmed": True,
            "chapters": [
                {"id": "chapter_a", "title": "第一章", "order_index": 0, "parent_id": "", "level": 1, "page_start": 1, "page_end": 2},
                {"id": "chapter_b", "title": "第二章", "order_index": 1, "parent_id": "", "level": 1, "page_start": 3, "page_end": 5},
            ],
        }
        result.update(overrides)
        return result

    def update(self, payload):
        return self.client.patch("/api/textbooks/review_book/chapters", json=payload)

    def snapshot(self):
        with self.sessions() as db:
            return {
                "chapters": [(row.id, row.title, row.order_index, row.level, row.parent_id, row.page_start, row.page_end, row.content, copy.deepcopy(row.source_spans), row.review_status) for row in db.query(Chapter).order_by(Chapter.id)],
                "chunks": [(row.id, row.chapter_title, row.content, row.page_start, row.page_end, copy.deepcopy(row.section_path), row.content_hash) for row in db.query(Chunk).order_by(Chunk.id)],
                "index": db.get(RagIndexState, "review_course").status,
                "structure": db.get(Textbook, "review_book").structure_status,
            }

    def add_reference(self, kind):
        with self.sessions() as db:
            if kind == "knowledge_node":
                db.add(KnowledgeNode(id="review_node", name="已引用知识点", course_id="review_course", textbook_id="review_book", source_chunk_id="old_chapter_a", page_start=1, page_end=2))
            else:
                db.add(Job(id=f"reference_{kind}", type=kind, status="completed", course_id="review_course", payload={"textbook_ids": ["review_book"]}, result={"artifact": {"citations": [{"textbook_id": "review_book", "page_start": 1}]}}))
            db.commit()

    def test_unused_pdf_range_correction_rebuilds_text_offsets_chunks_and_stales_index(self):
        with self.sessions() as db:
            self.assertTrue(range_capability(db, db.get(Textbook, "review_book"))[0])
        payload = self.payload()
        payload["chapters"][0].update(title="修订后的第一章", page_end=3)
        payload["chapters"][1]["page_start"] = 4
        response = self.update(payload)
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            for chapter_id, start, end in (("chapter_a", 1, 3), ("chapter_b", 4, 5)):
                chapter = db.get(Chapter, chapter_id)
                self.assertEqual((chapter.page_start, chapter.page_end), (start, end))
                self.assertEqual(chapter.content, "\n\n".join(self.pages[number] for number in range(start, end + 1)))
                self.assertEqual(chapter.char_count, len(chapter.content))
                self.assertEqual(chapter.review_status, "confirmed")
                self.assertEqual(chapter.extraction_status, "pending")
                self.assertEqual([span["page_number"] for span in chapter.source_spans], list(range(start, end + 1)))
                for span in chapter.source_spans:
                    self.assertEqual(chapter.content[span["chapter_start"]:span["chapter_end"]], self.pages[span["page_number"]])
                chunks = db.query(Chunk).filter(Chunk.chapter_id == chapter_id).order_by(Chunk.chunk_index).all()
                self.assertTrue(chunks)
                self.assertNotIn(f"old_{chapter_id}", [chunk.id for chunk in chunks])
                self.assertEqual(min(chunk.page_start for chunk in chunks), start)
                self.assertEqual(max(chunk.page_end for chunk in chunks), end)
                for chunk in chunks:
                    self.assertTrue(start <= chunk.page_start <= chunk.page_end <= end)
                    # The semantic splitter inserts sentence newlines, but must
                    # preserve the actual source text and its page boundaries.
                    self.assertIn(re.sub(r"\s+", "", chunk.content), re.sub(r"\s+", "", chapter.content))
                    self.assertEqual(chunk.chapter_title, chapter.title)
                    self.assertEqual(chunk.section_path[0], chapter.title)
                    self.assertEqual(chunk.content_hash, hashlib.sha256(chunk.content.encode()).hexdigest())
            self.assertEqual(db.get(RagIndexState, "review_course").status, "stale")
            self.assertEqual(db.get(Textbook, "review_book").structure_status, "confirmed")
        self.invalidate.assert_called_once_with("review_course")

    def test_knowledge_nodes_agent_runs_and_boards_lock_ranges_but_allow_title_only_edits(self):
        for kind in ("knowledge_node", "course_agent", "teaching_board"):
            with self.subTest(reference=kind):
                self.add_reference(kind)
                with self.sessions() as db:
                    editable, reason = range_capability(db, db.get(Textbook, "review_book"))
                self.assertFalse(editable)
                self.assertTrue(reason)
                before = self.snapshot()
                changed = self.payload()
                changed["chapters"][0]["page_end"] = 3
                response = self.update(changed)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.snapshot(), before)
                renamed = self.payload()
                renamed["chapters"][0]["title"] = f"第一章 · {kind} 后仍可改名"
                response = self.update(renamed)
                self.assertEqual(response.status_code, 200, response.text)
                after = self.snapshot()
                self.assertEqual(after["chapters"][0][7:9], before["chapters"][0][7:9])
                self.assertEqual(after["chunks"][0][2:5], before["chunks"][0][2:5])
                with self.sessions() as db:
                    self.assertEqual(db.get(Chunk, "old_chapter_a").chapter_title, renamed["chapters"][0]["title"])
                    self.assertEqual(db.get(Chunk, "old_chapter_a").section_path, [renamed["chapters"][0]["title"], "原有小节"])
                    db.query(KnowledgeNode).delete()
                    db.query(Job).delete()
                    db.commit()

    def test_empty_incomplete_duplicate_and_foreign_chapter_lists_are_atomic_rejections(self):
        complete = self.payload()["chapters"]
        variants = [[], complete[:1], [complete[0], complete[0]], [complete[0], {**complete[1], "id": "foreign_chapter"}]]
        for chapters in variants:
            with self.subTest(chapters=chapters):
                before = self.snapshot()
                response = self.update(self.payload(chapters=chapters))
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(self.snapshot(), before)
        self.invalidate.assert_not_called()

    def test_title_edit_updates_only_nodes_directly_linked_to_that_chapters_chunks(self):
        with self.sessions() as db:
            for node_id, chunk_id in (("matched_node", "old_chapter_a"),
                                      ("same_title_other_chapter", "old_chapter_b"),
                                      ("unlocated_legacy_node", "")):
                db.add(KnowledgeNode(id=node_id, name=node_id, course_id="review_course",
                                     textbook_id="review_book", chapter_title="第一章",
                                     source_chunk_id=chunk_id, source_paragraph="原文证据不得改变。",
                                     page_start=1, page_end=2))
            db.commit()
        changed = self.payload()
        changed["chapters"][0]["title"] = "第一章 · 新标题"
        response = self.update(changed)
        self.assertEqual(response.status_code, 200, response.text)
        with self.sessions() as db:
            self.assertEqual(db.get(KnowledgeNode, "matched_node").chapter_title, "第一章 · 新标题")
            # A stale same-title label is not a direct link to chapter A.
            self.assertEqual(db.get(KnowledgeNode, "same_title_other_chapter").chapter_title, "第一章")
            self.assertEqual(db.get(KnowledgeNode, "unlocated_legacy_node").chapter_title, "第一章")
            for node_id in ("matched_node", "same_title_other_chapter", "unlocated_legacy_node"):
                node = db.get(KnowledgeNode, node_id)
                self.assertEqual(node.source_paragraph, "原文证据不得改变。")
                self.assertEqual((node.page_start, node.page_end), (1, 2))

    def test_invalid_hierarchy_bounds_and_foreign_parent_reject_without_partial_title_save(self):
        cases = [
            ({"level": 3, "parent_id": "chapter_a"}, 400),
            ({"level": 2, "parent_id": "foreign_chapter"}, 400),
            ({"page_end": 6}, 400),
            ({"page_start": 5, "page_end": 4}, 400),
            ({"level": 2, "parent_id": "chapter_a"}, 400),
            ({"order_index": 0}, 400),
            ({"level": 7}, 422),
            ({"page_start": 0}, 422),
            ({"page_start": 3.5}, 422),
            ({"title": "   "}, 400),
        ]
        for changes, status in cases:
            with self.subTest(changes=changes):
                payload = self.payload()
                payload["chapters"][0]["title"] = "不应被部分保存的标题"
                payload["chapters"][1].update(changes)
                before = self.snapshot()
                response = self.update(payload)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(self.snapshot(), before)
        self.invalidate.assert_not_called()

    def test_page_order_and_first_item_hierarchy_are_checked(self):
        for case in ("reversed_pages", "missing_root"):
            with self.subTest(case=case):
                payload = self.payload()
                if case == "reversed_pages":
                    payload["chapters"][0]["page_start"] = 2
                    payload["chapters"][1]["page_start"] = 1
                else:
                    payload["chapters"][0]["level"] = 2
                before = self.snapshot()
                response = self.update(payload)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(self.snapshot(), before)

    def test_missing_page_late_in_update_rolls_back_previously_rebuilt_chapter(self):
        with self.sessions() as db:
            db.delete(db.get(TextbookPage, "review_page_5"))
            db.commit()
        before = self.snapshot()
        payload = self.payload()
        payload["chapters"][0].update(title="不应保存的第一章", page_end=3)
        payload["chapters"][1].update(title="不应保存的第二章", page_start=4)
        response = self.update(payload)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("缺少页面正文", response.json()["detail"])
        self.assertEqual(self.snapshot(), before)
        self.invalidate.assert_not_called()

    def test_list_exposes_server_range_capability_and_reasons(self):
        response = self.client.get("/api/textbooks", params={"course_id": "review_course"})
        self.assertEqual(response.status_code, 200, response.text)
        current = next(book for book in response.json() if book["id"] == "review_book")
        self.assertIs(current["chapter_range_editable"], True)
        self.assertIn("整页", current["chapter_range_edit_reason"])
        self.add_reference("teaching_board")
        response = self.client.get("/api/textbooks", params={"course_id": "review_course"})
        current = next(book for book in response.json() if book["id"] == "review_book")
        self.assertIs(current["chapter_range_editable"], False)
        self.assertIn("备课材料", current["chapter_range_edit_reason"])


if __name__ == "__main__":
    unittest.main()
