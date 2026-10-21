"""Lesson board persistence, source boundaries and revision safety, entirely offline."""
import copy
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
with patch("dotenv.load_dotenv", return_value=False):
    from backend.database import Base, Chapter, Chunk, Course, Job, KnowledgeEdge, Textbook
    from backend.services.teaching_board import (
        BoardConflict, create_teaching_board, get_board_agent_context,
        get_teaching_board, get_teaching_sources, list_teaching_boards, update_teaching_board,
    )
    from backend.api.teaching_board import router

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class TeachingBoardTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.db.add_all([Course(id="course_a", title="课程 A"), Course(id="course_b", title="课程 B")])
        for index, course_id in (("a", "course_a"), ("b", "course_a"), ("c", "course_a"), ("other", "course_b")):
            self.db.add(Textbook(id=f"book_{index}", course_id=course_id, filename=f"{index}.pdf", title=f"教材 {index}", format="pdf", total_pages=20))
        self.db.flush()
        for index in ("a", "b", "c", "other"):
            self.db.add(Chapter(id=f"chapter_{index}", textbook_id=f"book_{index}", title="第一章"))
        self.db.flush()
        for index in ("a", "b", "c", "other"):
            self.db.add(Chunk(id=f"chunk_{index}", textbook_id=f"book_{index}", chapter_id=f"chapter_{index}", chapter_title="第一章", section_path=["第一章", "能量转换"], content=f"教材 {index} 的真实原文，不能由浏览器伪造。", page_start=5, page_end=6))
        self.db.commit()
        self.payload = {
            "topic": "能量转换", "textbook_ids": ["book_a", "book_b"],
            "selections": [{"chunk_id": "chunk_a", "dimension": "基本概念", "note": "本课先讲"}, {"chunk_id": "chunk_b", "dimension": "应用"}],
            "connections": [{"id": "connection_a", "source_chunk_id": "chunk_a", "target_chunk_id": "chunk_b", "relation_type": "extends", "reason": "待核验的补充解释"}],
        }

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_create_restores_server_sources_and_never_creates_graph_relation(self):
        self.payload["selections"][0]["quote"] = "伪造原文"
        board = create_teaching_board(self.db, "course_a", self.payload)
        self.assertEqual(board["revision"], 1)
        self.assertEqual(board["scope"], "lesson")
        self.assertEqual(board["selection_counts"], {"book_a": 1, "book_b": 1})
        self.assertEqual(board["connections"][0]["status"], "draft")
        self.assertEqual(board["confirmed_count"], 0)
        self.assertEqual(board["draft_count"], 1)
        source = board["selections"][0]
        self.assertEqual(source["quote"], "教材 a 的真实原文，不能由浏览器伪造。")
        self.assertEqual(source["page_image_url"], "/api/textbooks/book_a/teaching/pages/5/image")
        self.assertEqual(source["section_path"], ["第一章", "能量转换"])
        self.assertEqual(self.db.query(KnowledgeEdge).count(), 0)
        job = self.db.get(Job, board["id"])
        self.assertEqual(job.status, "completed")
        self.assertNotIn("quote", job.payload["selections"][0])
        self.assertEqual(get_teaching_board(self.db, "course_a", board["id"])["id"], board["id"])

    def test_selected_original_is_refreshed_and_long_excerpt_is_identified(self):
        board = create_teaching_board(self.db, "course_a", self.payload)
        chunk = self.db.get(Chunk, "chunk_a")
        chunk.content = "原文背景。" * 400 + "能量转换的真实定义。" + "原文后续。" * 400
        self.db.commit()
        loaded = get_teaching_board(self.db, "course_a", board["id"])["selections"][0]
        self.assertTrue(loaded["quote_truncated"])
        self.assertLessEqual(len(loaded["quote"]), 1400)
        self.assertEqual(loaded["quote"], chunk.content[loaded["quote_start"]:loaded["quote_end"]])
        context = get_board_agent_context(self.db, "course_a", board["id"])
        self.assertEqual(context["selections"][0]["content"], chunk.content)

    def test_teaching_titles_and_teacher_order_survive_crud_and_agent_subset(self):
        self.payload["selections"][0]["teaching_title"] = "  先建立共同概念  "
        self.payload["selections"][1]["teaching_title"] = "再看另一教材的应用"
        created = create_teaching_board(self.db, "course_a", self.payload)
        self.assertEqual(created["selections"][0]["teaching_title"], "先建立共同概念")
        update = copy.deepcopy(self.payload)
        update["selections"].reverse()
        update["selections"][0]["teaching_title"] = "从问题进入，随后讲概念"
        saved = update_teaching_board(self.db, "course_a", created["id"], update, 1)
        self.assertEqual(saved["revision"], 2)
        loaded = get_teaching_board(self.db, "course_a", created["id"])
        self.assertEqual([row["chunk_id"] for row in loaded["selections"]], ["chunk_b", "chunk_a"])
        self.assertEqual([row["teaching_title"] for row in loaded["selections"]], ["从问题进入，随后讲概念", "先建立共同概念"])
        for selected_ids in (None, [], ["chunk_a", "chunk_b"]):
            context = get_board_agent_context(self.db, "course_a", created["id"], selected_ids)
            self.assertEqual(context["selected_chunk_ids"], ["chunk_b", "chunk_a"])
            self.assertEqual([row["chunk_id"] for row in context["selections"]], ["chunk_b", "chunk_a"])
            self.assertEqual(context["selections"][0]["teaching_title"], "从问题进入，随后讲概念")
            self.assertEqual(context["selections"][0]["content"], "教材 b 的真实原文，不能由浏览器伪造。")
        subset = get_board_agent_context(self.db, "course_a", created["id"], ["chunk_a"])
        self.assertEqual(subset["selections"][0]["teaching_title"], "先建立共同概念")
        self.assertEqual(loaded["selections"][0]["section_path"], ["第一章", "能量转换"])
        self.assertEqual(loaded["selections"][0]["quote"], "教材 b 的真实原文，不能由浏览器伪造。")

    def test_legacy_board_without_teaching_titles_loads_and_updates_with_empty_titles(self):
        created = create_teaching_board(self.db, "course_a", self.payload)
        job = self.db.get(Job, created["id"])
        # Reproduce the JSON persisted before the optional title field existed.
        job.payload = copy.deepcopy(self.payload)
        self.db.commit()
        loaded = get_teaching_board(self.db, "course_a", created["id"])
        self.assertEqual([row["teaching_title"] for row in loaded["selections"]], ["", ""])
        context = get_board_agent_context(self.db, "course_a", created["id"])
        self.assertEqual([row["teaching_title"] for row in context["selections"]], ["", ""])
        updated = update_teaching_board(self.db, "course_a", created["id"], self.payload, 1)
        self.assertEqual([row["teaching_title"] for row in updated["selections"]], ["", ""])

    def test_invalid_teaching_titles_are_rejected_without_partial_save(self):
        for invalid_title in ("字" * 101, 42, None, []):
            invalid = copy.deepcopy(self.payload)
            invalid["selections"][0]["teaching_title"] = invalid_title
            with self.assertRaises(ValueError):
                create_teaching_board(self.db, "course_a", invalid)
        self.assertEqual(self.db.query(Job).count(), 0)
        valid = copy.deepcopy(self.payload)
        valid["selections"][0]["teaching_title"] = "字" * 100
        created = create_teaching_board(self.db, "course_a", valid)
        invalid = copy.deepcopy(valid)
        invalid["selections"][0]["teaching_title"] += "字"
        with self.assertRaises(ValueError):
            update_teaching_board(self.db, "course_a", created["id"], invalid, 1)
        current = get_teaching_board(self.db, "course_a", created["id"])
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current["selections"][0]["teaching_title"], "字" * 100)

    def test_source_heading_groups_remain_stable_after_reload_title_edits_and_reordering(self):
        self.db.add_all([
            Chunk(id="chunk_a_next", textbook_id="book_a", chapter_id="chapter_a", chapter_title="第一章", section_path=["第一章", "能量转换"], content="另一段能量转换原文，仍属于同一明确小节。", page_start=7),
            Chunk(id="unheaded_1", textbook_id="book_a", chapter_id="chapter_a", chapter_title="第一章", section_path=["第一章", "2. 内容"], content="教材这里讨论能量转换，但这只是一句正文。", page_start=8),
            Chunk(id="unheaded_2", textbook_id="book_a", chapter_id="chapter_a", chapter_title="第一章", section_path=["第一章", "2. 内容"], content="另一个段落提到能量转换，没有提供具体的原文标题。", page_start=9),
        ])
        self.db.commit()
        for chunk_id in ("chunk_a_next", "unheaded_1", "unheaded_2"):
            self.payload["selections"].append({"chunk_id": chunk_id})
        created = create_teaching_board(self.db, "course_a", self.payload)
        metadata_keys = ("source_heading", "display_title", "title_origin", "concept_key")
        metadata = {row["chunk_id"]: {key: row[key] for key in metadata_keys} for row in created["selections"]}
        self.assertEqual(metadata["chunk_a"]["concept_key"], metadata["chunk_a_next"]["concept_key"])
        self.assertNotEqual(metadata["chunk_a"]["concept_key"], metadata["chunk_b"]["concept_key"])
        self.assertNotEqual(metadata["unheaded_1"]["concept_key"], metadata["unheaded_2"]["concept_key"])
        self.assertEqual(metadata["unheaded_1"]["title_origin"], "topic_excerpt")
        self.assertEqual(metadata["unheaded_1"]["source_heading"], "2. 内容")
        update = copy.deepcopy(self.payload)
        update["selections"].reverse()
        for row in update["selections"]:
            row["teaching_title"] = "教师用同一个名称组织讲授"
        update_teaching_board(self.db, "course_a", created["id"], update, 1)
        reloaded = get_teaching_board(self.db, "course_a", created["id"])
        context = get_board_agent_context(self.db, "course_a", created["id"])
        for rows in (reloaded["selections"], context["selections"]):
            self.assertEqual([row["chunk_id"] for row in rows], [row["chunk_id"] for row in update["selections"]])
            self.assertEqual({row["chunk_id"]: {key: row[key] for key in metadata_keys} for row in rows}, metadata)
            self.assertTrue(all(row["teaching_title"] == "教师用同一个名称组织讲授" for row in rows))
        self.assertEqual(reloaded["selections"][0]["title"], "2. 内容")
        self.assertEqual(reloaded["selections"][0]["quote"], "另一个段落提到能量转换，没有提供具体的原文标题。")

    def test_legacy_source_hydration_preserves_requested_order_and_never_writes(self):
        from sqlalchemy import event
        board = create_teaching_board(self.db, "course_a", self.payload)
        writes = []

        def record_write(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP"}:
                writes.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_write)
        hydrated = get_teaching_sources(self.db, "course_a", ["book_a", "book_b"], ["chunk_b", "chunk_a"], "能量转换")
        self.assertEqual([row["chunk_id"] for row in hydrated["items"]], ["chunk_b", "chunk_a"])
        self.assertEqual(hydrated["items"][0]["quote"], "教材 b 的真实原文，不能由浏览器伪造。")
        self.assertEqual(hydrated["items"][0]["teaching_title"], "")
        self.assertEqual(hydrated["items"][0]["dimension"], "未归类")
        self.assertEqual(hydrated["items"][0]["note"], "")
        source_keys = ("source_heading", "display_title", "title_origin", "concept_key", "quote", "section_path")
        original = get_teaching_board(self.db, "course_a", board["id"])
        original_b = next(row for row in original["selections"] if row["chunk_id"] == "chunk_b")
        self.assertEqual({key: hydrated["items"][0][key] for key in source_keys}, {key: original_b[key] for key in source_keys})
        self.assertEqual(original["revision"], 1)
        self.assertEqual(self.db.query(Job).count(), 1)
        self.assertEqual(writes, [])

    def test_legacy_source_hydration_rejects_scope_missing_sources_and_invalid_limits(self):
        for chunk_ids in ([], ["missing"], ["chunk_c"], ["chunk_other"], ["chunk_a"] * 81):
            with self.assertRaises(ValueError):
                get_teaching_sources(self.db, "course_a", ["book_a", "book_b"], chunk_ids, "能量转换")
        for query in ("", "   ", "字" * 161):
            with self.assertRaises(ValueError):
                get_teaching_sources(self.db, "course_a", ["book_a"], ["chunk_a"], query)
        for books in ([], ["book_a", "book_other"], ["book_a"] * 13):
            with self.assertRaises(ValueError):
                get_teaching_sources(self.db, "course_a", books, ["chunk_a"], "能量转换")
        with self.assertRaises(LookupError):
            get_teaching_sources(self.db, "missing_course", ["book_a"], ["chunk_a"], "能量转换")
        self.db.get(Chunk, "chunk_a").content = "   "
        self.db.commit()
        with self.assertRaises(ValueError):
            get_teaching_sources(self.db, "course_a", ["book_a"], ["chunk_a"], "能量转换")
        self.assertEqual(self.db.query(Job).count(), 0)

    def test_source_hydration_http_route_precedes_board_id_and_supports_csv_and_repeated_keys(self):
        app = FastAPI()
        app.include_router(router)
        with patch("backend.api.teaching_board.SessionLocal", self.sessions):
            client = TestClient(app)
            base = "/api/courses/course_a/teaching/boards/sources"
            for params in (
                "textbook_ids=book_a,book_b&chunk_ids=chunk_b,chunk_a",
                "textbook_ids=book_a&textbook_ids=book_b&chunk_ids=chunk_b&chunk_ids=chunk_a",
            ):
                response = client.get(f"{base}?{params}&q=能量转换")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual([item["chunk_id"] for item in response.json()["items"]], ["chunk_b", "chunk_a"])
            self.assertEqual(client.get(base).status_code, 400)
            self.assertEqual(client.get(base, params={"textbook_ids": "book_a", "chunk_ids": "missing", "q": "能量转换"}).status_code, 400)
            self.assertEqual(client.get(base, params={"textbook_ids": "book_a", "chunk_ids": "chunk_other", "q": "能量转换"}).status_code, 400)
            self.assertEqual(client.get(base, params={"textbook_ids": "book_a", "chunk_ids": "chunk_a", "q": "字" * 161}).status_code, 400)
            self.assertEqual(client.get("/api/courses/missing/teaching/boards/sources", params={"textbook_ids": "book_a", "chunk_ids": "chunk_a", "q": "能量转换"}).status_code, 404)

    def test_scope_and_relation_validation_leave_database_unchanged(self):
        invalid_payloads = []
        for chunk_id in ("missing", "chunk_c", "chunk_other"):
            item = copy.deepcopy(self.payload)
            item["selections"][0]["chunk_id"] = chunk_id
            invalid_payloads.append(item)
        for property_name, value in (("target_chunk_id", "chunk_c"), ("target_chunk_id", "chunk_a"), ("relation_type", "fabricated"), ("status", "auto_verified")):
            item = copy.deepcopy(self.payload)
            item["connections"][0][property_name] = value
            invalid_payloads.append(item)
        item = copy.deepcopy(self.payload)
        item["textbook_ids"].append("book_other")
        invalid_payloads.append(item)
        item = copy.deepcopy(self.payload)
        item["selections"].append(item["selections"][0])
        invalid_payloads.append(item)
        for item in invalid_payloads:
            with self.assertRaises(ValueError):
                create_teaching_board(self.db, "course_a", item)
        self.assertEqual(self.db.query(Job).count(), 0)
        self.assertEqual(self.db.query(KnowledgeEdge).count(), 0)

    def test_confirmation_requires_explicit_status_and_reason(self):
        self.payload["connections"][0]["status"] = "confirmed"
        self.payload["connections"][0]["reason"] = "  "
        with self.assertRaises(ValueError):
            create_teaching_board(self.db, "course_a", self.payload)
        self.payload["connections"][0]["reason"] = "教师核对双方材料后确认这条本课教学补充"
        board = create_teaching_board(self.db, "course_a", self.payload)
        self.assertEqual(board["confirmed_count"], 1)
        self.assertEqual(self.db.query(KnowledgeEdge).count(), 0)

    def test_revision_updates_and_stale_writes_cannot_overwrite(self):
        board = create_teaching_board(self.db, "course_a", self.payload)
        updated = copy.deepcopy(self.payload)
        updated["topic"] = "修改后的课题"
        saved = update_teaching_board(self.db, "course_a", board["id"], updated, expected_revision=1)
        self.assertEqual(saved["revision"], 2)
        with self.assertRaises(BoardConflict):
            update_teaching_board(self.db, "course_a", board["id"], self.payload, expected_revision=1)
        current = get_teaching_board(self.db, "course_a", board["id"])
        self.assertEqual(current["topic"], "修改后的课题")
        invalid = copy.deepcopy(updated)
        invalid["connections"][0]["target_chunk_id"] = "missing"
        with self.assertRaises(ValueError):
            update_teaching_board(self.db, "course_a", board["id"], invalid, expected_revision=2)
        self.assertEqual(get_teaching_board(self.db, "course_a", board["id"])["revision"], 2)

    def test_atomic_compare_and_swap_detects_revision_changed_during_validation(self):
        import backend.services.teaching_board as service
        board = create_teaching_board(self.db, "course_a", self.payload)
        original = service._normalize_payload

        def concurrent_update(*args):
            result = original(*args)
            self.db.query(Job).filter(Job.id == board["id"]).update({Job.result: {"revision": 2, "scope": "lesson"}}, synchronize_session=False)
            self.db.commit()
            return result

        with patch.object(service, "_normalize_payload", side_effect=concurrent_update), self.assertRaises(BoardConflict):
            update_teaching_board(self.db, "course_a", board["id"], self.payload, 1)
        self.assertEqual(get_teaching_board(self.db, "course_a", board["id"])["revision"], 2)

    def test_active_and_foreign_or_other_job_types_are_not_editable(self):
        board = create_teaching_board(self.db, "course_a", self.payload)
        with self.assertRaises(LookupError):
            get_teaching_board(self.db, "course_b", board["id"])
        job = self.db.get(Job, board["id"])
        job.status = "processing"
        self.db.commit()
        with self.assertRaises(BoardConflict):
            update_teaching_board(self.db, "course_a", board["id"], self.payload, 1)
        job.status = "completed"
        job.type = "course_agent"
        self.db.commit()
        with self.assertRaises(LookupError):
            update_teaching_board(self.db, "course_a", board["id"], self.payload, 1)

    def test_history_summary_and_agent_subset_are_course_scoped(self):
        board = create_teaching_board(self.db, "course_a", self.payload)
        items = list_teaching_boards(self.db, "course_a")
        self.assertEqual(items["total"], 1)
        self.assertEqual(items["items"][0]["selection_counts"], {"book_a": 1, "book_b": 1})
        self.assertEqual(list_teaching_boards(self.db, "course_b")["items"], [])
        context = get_board_agent_context(self.db, "course_a", board["id"], [])
        self.assertEqual(context["board_revision"], 1)
        self.assertEqual(len(context["selections"]), 2)
        subset = get_board_agent_context(self.db, "course_a", board["id"], ["chunk_a"])
        self.assertEqual(subset["textbook_ids"], ["book_a"])
        self.assertEqual(subset["connections"], [])
        for ids in (["chunk_c"], ["chunk_other"], ["missing"], [[]]):
            with self.assertRaises(ValueError):
                get_board_agent_context(self.db, "course_a", board["id"], ids)
        empty = create_teaching_board(self.db, "course_a", {"topic": "空板", "textbook_ids": ["book_a"]})
        with self.assertRaises(ValueError):
            get_board_agent_context(self.db, "course_a", empty["id"])

    def test_http_roundtrip_conflicts_and_client_forgery_rejection(self):
        app = FastAPI()
        app.include_router(router)
        with patch("backend.api.teaching_board.SessionLocal", self.sessions):
            client = TestClient(app)
            base = "/api/courses/course_a/teaching/boards"
            response = client.post(base, json=self.payload)
            self.assertEqual(response.status_code, 201, response.text)
            board_id = response.json()["id"]
            self.assertEqual(client.get(f"{base}/{board_id}").status_code, 200)
            self.assertEqual(client.get(base).json()["items"][0]["selection_count"], 2)
            updated = {**self.payload, "expected_revision": 1}
            self.assertEqual(client.patch(f"{base}/{board_id}", json=updated).json()["revision"], 2)
            self.assertEqual(client.patch(f"{base}/{board_id}", json=updated).status_code, 409)
            self.assertEqual(client.get(f"/api/courses/course_b/teaching/boards/{board_id}").status_code, 404)
            forged = copy.deepcopy(self.payload)
            forged["selections"][0]["quote"] = "伪造引文"
            self.assertEqual(client.post(base, json=forged).status_code, 422)
            self.assertEqual(client.post(base, json={**self.payload, "topic": "   "}).status_code, 400)
            titled = copy.deepcopy(self.payload)
            titled["selections"][0]["teaching_title"] = "教师自定的讲授标题"
            self.assertEqual(client.post(base, json=titled).json()["selections"][0]["teaching_title"], "教师自定的讲授标题")
            titled["selections"][0]["teaching_title"] = "字" * 101
            self.assertEqual(client.post(base, json=titled).status_code, 422)
            titled["selections"][0]["teaching_title"] = None
            self.assertEqual(client.post(base, json=titled).status_code, 422)


if __name__ == "__main__":
    unittest.main()
