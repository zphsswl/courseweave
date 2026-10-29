"""RAG tool transport/scope contracts; no original DB, network, or model calls."""
import copy
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
with patch("dotenv.load_dotenv", return_value=False):
    from backend.agents import rag_tool as tool
    from backend.database import Base, Chapter, Chunk, Course, Textbook

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class AgentRagToolTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([Course(id="course-a", title="当前课"), Course(id="course-b", title="别的课")])
            db.flush()
            for suffix in ("a", "b", "c", "other"):
                db.add(Textbook(id="book-" + suffix, course_id="course-b" if suffix == "other" else "course-a",
                                title="真实教材" + suffix, filename=suffix + ".txt", format="txt"))
            db.flush()
            for suffix in ("a", "b", "c", "other"):
                db.add(Chapter(id="chapter-" + suffix, textbook_id="book-" + suffix, title="真实章节" + suffix))
            db.flush()
            for suffix in ("a", "b", "c", "other"):
                db.add(Chunk(id="chunk-" + suffix, textbook_id="book-" + suffix, chapter_id="chapter-" + suffix,
                             textbook_title="过时书名", chapter_title="过时章节", page_start=3, page_end=4,
                             section_path=["真实章节" + suffix, "来源小节"], content=("真实完整原文" + suffix) * 100))
            db.add(Chunk(id="broken-chapter", textbook_id="book-a", chapter_id="chapter-other", content="不一致的章节归属"))
            db.add(Chunk(id="empty", textbook_id="book-a", chapter_id="chapter-a", content="  "))
            db.commit()
        self.raw = {
            "answer": "上游回答 [S1]", "citations": [{"chunk_id": "chunk-a", "textbook_id": "book-a",
                "quote": "外部伪造节选", "textbook": "伪造书名", "page_start": 999, "retrievers": ["bm25"]}],
            "retrieval_trace": {"retrievers": ["bm25"], "vector_used": False}, "answer_method": "llm_grounded",
            "semantic_reviewed": True,
        }
        self.scope_patch = patch.object(tool, "SessionLocal", self.sessions)
        self.scope_patch.start()
        self.env_patch = patch.dict(os.environ, {"AGENT_RAG_URL": ""})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.scope_patch.stop()
        self.engine.dispose()

    def query(self, **changes):
        request = {"question": "教材证据", "course_id": "course-a", "textbook_ids": ["book-a", "book-b"]}
        request.update(changes)
        return tool.query_rag_tool(**request)

    def http_client(self, handler):
        client_type = httpx.Client
        return patch.object(tool.httpx, "Client", side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs))

    def test_default_internal_proxy_keeps_arguments_and_rehydrates_local_full_text(self):
        original = copy.deepcopy(self.raw)
        with patch.object(tool, "query_rag", return_value=self.raw) as query:
            result = self.query(question="  教材证据  ", textbook_ids=["book-a", "book-b", "book-a"], mode="compare", top_k=2)
        query.assert_called_once_with(question="教材证据", course_id="course-a", textbook_ids=["book-a", "book-b"], mode="compare", top_k=2)
        self.assertEqual(result["transport"], "internal")
        self.assertEqual(result["answer_method"], "llm_grounded")
        self.assertFalse(result["semantic_reviewed"])
        item = result["items"][0]
        self.assertGreater(len(item["content"]), 500)
        self.assertEqual(item["textbook"], "真实教材a")
        self.assertEqual(item["chapter"], "真实章节a")
        self.assertEqual(item["chapter_id"], "chapter-a")
        self.assertEqual((item["page_start"], item["page_end"]), (3, 4))
        self.assertEqual(item["section_path"], ["真实章节a", "来源小节"])
        self.assertNotIn("外部伪造", item["content"])
        self.assertEqual(result["retrieval_trace"], self.raw["retrieval_trace"])
        self.assertEqual(self.raw, original)

    def test_scope_must_validate_every_selected_textbook_before_retrieval(self):
        with patch.object(tool, "query_rag") as query, patch.object(tool.httpx, "Client") as client:
            for changes in ({"textbook_ids": ["book-a", "book-other"]}, {"textbook_ids": ["book-a", "missing"]}, {"course_id": "missing"}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.query(endpoint="http://rag.test/api/rag/query", **changes)
            query.assert_not_called()
            client.assert_not_called()

    def test_input_limits_reject_ambiguous_or_unbounded_requests(self):
        invalid = [
            {"question": ""}, {"question": "x"}, {"question": "x" * 2001}, {"question": 123},
            {"textbook_ids": None}, {"textbook_ids": []}, {"textbook_ids": "book-a"}, {"textbook_ids": [None]},
            {"textbook_ids": ["book-a"] * 13}, {"mode": "node"}, {"mode": {}}, {"mode": "compare", "textbook_ids": ["book-a", "book-a"]},
            {"top_k": 0}, {"top_k": 16}, {"top_k": True}, {"top_k": "8"}, {"top_k": 2.5},
            {"timeout": 0}, {"timeout": float("inf")}, {"timeout": True}, {"course_id": ""},
        ]
        with patch.object(tool, "query_rag") as query:
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.query(**changes)
            query.assert_not_called()

    def test_forged_unselected_cross_course_and_broken_chapter_citations_are_excluded(self):
        bad = [
            {"chunk_id": "missing"}, {"chunk_id": "chunk-other"}, {"chunk_id": "chunk-c"},
            {"chunk_id": "chunk-a", "textbook_id": "book-other"},
            {"chunk_id": "chunk-a", "chapter_id": "chapter-other"},
            {"chunk_id": "chunk-a", "course_id": "course-b"},
            {"chunk_id": "broken-chapter"}, {"chunk_id": 5}, "chunk-a", {},
        ]
        for citation in bad:
            with self.subTest(citation=citation), patch.object(tool, "query_rag", return_value={**self.raw, "citations": [citation]}):
                result = self.query()
                self.assertEqual(result["items"], [])
                self.assertEqual(result["answer_method"], "no_evidence")
                self.assertNotIn("上游回答", result["answer"])
                self.assertIn("rag_citation_rejected", result["warnings"])

    def test_partial_rejection_discards_answer_with_now_dangling_source_numbers(self):
        raw = {**self.raw, "answer": "错误结论 [S2]", "citations": [self.raw["citations"][0], {"chunk_id": "chunk-other"}]}
        with patch.object(tool, "query_rag", return_value=raw):
            result = self.query()
        self.assertEqual([item["id"] for item in result["items"]], ["chunk-a"])
        self.assertNotIn("错误结论", result["answer"])
        self.assertNotIn("[S2]", result["answer"])
        self.assertEqual(result["answer_method"], "evidence_fallback")

    def test_duplicates_top_k_and_empty_chunks_cannot_leave_inconsistent_answers(self):
        cases = [
            ([{"chunk_id": "chunk-a"}, {"chunk_id": "chunk-a"}], 8, "rag_duplicate_citation"),
            ([{"chunk_id": "chunk-a"}, {"chunk_id": "chunk-b"}], 1, "rag_citations_trimmed"),
            ([{"chunk_id": "empty"}, {"chunk_id": "chunk-a"}], 8, "rag_empty_chunk_rejected"),
        ]
        for citations, count, warning in cases:
            with self.subTest(warning=warning), patch.object(tool, "query_rag", return_value={**self.raw, "citations": citations}):
                result = self.query(top_k=count)
                self.assertEqual([item["id"] for item in result["items"]], ["chunk-a"])
                self.assertEqual(result["answer_method"], "evidence_fallback")
                self.assertIn(warning, result["warnings"])

    def test_no_evidence_ignores_unsubstantiated_answer(self):
        with patch.object(tool, "query_rag", return_value={**self.raw, "citations": []}):
            result = self.query()
        self.assertEqual(result["items"], [])
        self.assertEqual(result["answer_method"], "no_evidence")
        self.assertNotIn("上游回答", result["answer"])
        self.assertEqual(result["warnings"], [])

    def test_malformed_optional_fields_cannot_promote_or_crash_evidence_results(self):
        for method, answer in (([], "claim"), ("semantic_reviewed", "claim"), ("no_evidence", "claim"), ("llm_grounded", None)):
            raw = {**self.raw, "answer_method": method, "answer": answer, "retrieval_trace": "invalid"}
            raw["citations"] = [{"chunk_id": "chunk-a", "retrievers": [{"unexpected": "value"}]}]
            with self.subTest(method=method), patch.object(tool, "query_rag", return_value=raw):
                result = self.query()
            self.assertEqual(result["answer_method"], "evidence_fallback")
            self.assertFalse(result["semantic_reviewed"])
            self.assertEqual(result["items"][0]["retrievers"], [])
            self.assertEqual(result["retrieval_trace"], {})

    def test_http_uses_complete_server_endpoint_post_payload_and_bounded_timeout(self):
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=self.raw)
        endpoint = "https://rag.test/custom/query?deployment=teacher"
        with self.http_client(handler) as client, patch.object(tool, "query_rag") as internal:
            result = self.query(endpoint=endpoint, timeout=300)
        self.assertEqual(result["transport"], "http")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(str(seen[0].url), endpoint)
        self.assertEqual(seen[0].method, "POST")
        self.assertEqual(json.loads(seen[0].content), {"question": "教材证据", "course_id": "course-a", "textbook_ids": ["book-a", "book-b"], "mode": "all", "top_k": 8})
        self.assertFalse(client.call_args.kwargs["follow_redirects"])
        self.assertFalse(client.call_args.kwargs["trust_env"])
        self.assertEqual(client.call_args.kwargs["timeout"].read, 30)
        internal.assert_not_called()

    def test_environment_endpoint_is_server_config_and_explicit_empty_uses_internal(self):
        with patch.dict(os.environ, {"AGENT_RAG_URL": "http://rag.test/configured/path"}), self.http_client(lambda request: httpx.Response(200, json=self.raw)):
            self.assertEqual(self.query()["transport"], "http")
            with patch.object(tool, "query_rag", return_value=self.raw) as internal:
                self.assertEqual(self.query(endpoint="")["transport"], "internal")
                internal.assert_called_once()

    def test_redirects_are_not_followed(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(307, headers={"Location": "http://other.test/private"})
        with self.http_client(handler):
            result = self.query(endpoint="http://rag.test/query")
        self.assertEqual(len(requests), 1)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["warnings"], ["rag_http_redirect_refused"])

    def test_invalid_endpoint_cannot_be_interpreted_as_a_new_target(self):
        for endpoint in ("file:///private", "ftp://rag.test/query", "http://user:secret@rag.test/query", "http://rag.test/query#token", "http://rag.test:bad/query", 7):
            with self.subTest(endpoint=endpoint), patch.object(tool.httpx, "Client") as client, self.assertRaises(ValueError):
                self.query(endpoint=endpoint)
            client.assert_not_called()

    def test_http_errors_empty_and_invalid_responses_do_not_expose_body(self):
        cases = [
            (httpx.Response(500, text="secret-token-and-private-url"), "rag_http_error"),
            (httpx.Response(200, content=b""), "rag_empty_response"),
            (httpx.Response(200, text="not-json-secret"), "rag_invalid_response"),
            (httpx.Response(200, json=[]), "rag_invalid_response"),
            (httpx.Response(200, json={"citations": {}}), "rag_invalid_response"),
        ]
        for response, warning in cases:
            with self.subTest(warning=warning), self.http_client(lambda request: response):
                result = self.query(endpoint="http://rag.test/query")
            self.assertEqual(result["warnings"], [warning])
            self.assertEqual(result["items"], [])
            self.assertNotIn("secret", json.dumps(result))

    def test_http_body_limit_applies_with_and_without_content_length(self):
        class LargeBody(httpx.SyncByteStream):
            def __iter__(self):
                for _ in range(17):
                    yield b"x" * 65536
        for response in (
            httpx.Response(200, headers={"Content-Length": str(tool.MAX_RESPONSE_BYTES + 1)}, content=b"{}"),
            httpx.Response(200, stream=LargeBody()),
        ):
            with self.subTest(headers=response.headers), self.http_client(lambda request: response):
                result = self.query(endpoint="http://rag.test/query")
            self.assertEqual(result["warnings"], ["rag_response_too_large"])
            self.assertEqual(result["items"], [])

    def test_network_and_internal_exception_messages_are_never_returned(self):
        def unavailable(request):
            raise httpx.ReadTimeout("secret-token in http://private.test/query", request=request)
        with self.http_client(unavailable):
            result = self.query(endpoint="http://rag.test/query")
        self.assertEqual(result["warnings"], ["rag_http_unavailable"])
        self.assertNotIn("secret-token", json.dumps(result))
        with patch.object(tool, "query_rag", side_effect=RuntimeError("secret-token")):
            result = self.query()
        self.assertEqual(result["warnings"], ["rag_internal_unavailable"])
        self.assertNotIn("secret-token", json.dumps(result))

    def test_scope_is_rechecked_after_upstream_response(self):
        def changed_scope(**kwargs):
            with self.sessions() as db:
                db.get(Textbook, "book-a").course_id = "course-b"
                db.commit()
            return self.raw
        with patch.object(tool, "query_rag", side_effect=changed_scope), self.assertRaises(ValueError):
            self.query()


if __name__ == "__main__":
    unittest.main()
