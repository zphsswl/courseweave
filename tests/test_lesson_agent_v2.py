import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from backend.agents import course_agent as agent  # noqa: E402
from backend.api.agent import (  # noqa: E402
    AgentRunCreate, LessonDraftUpdate, create_agent_run, export_lesson, save_lesson_draft,
)
from backend.database import Chapter, Chunk, Course, Job, SessionLocal, Textbook, init_db  # noqa: E402


class LessonAgentV2Tests(unittest.TestCase):
    course = "lesson_v2_course"
    book_a = "lesson_v2_anatomy"
    book_b = "lesson_v2_physiology"

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.add(Course(id=self.course, title="备课合同测试"))
            db.flush()
            for book_id, title in ((self.book_a, "局部解剖学"), (self.book_b, "生理学")):
                db.add(Textbook(id=book_id, course_id=self.course, filename=f"{book_id}.txt", title=title,
                                format="txt", total_pages=20, parse_status="completed",
                                structure_status="confirmed", graph_status="pending"))
            db.flush()
            for book_id in (self.book_a, self.book_b):
                db.add(Chapter(id=f"{book_id}_chapter", textbook_id=book_id, title="甲状腺"))
            db.flush()
            for chunk_id, book_id, text in (
                ("lesson_v2_structure", self.book_a, "甲状腺由左右叶和峡部组成，位于颈前区。"),
                ("lesson_v2_injury", self.book_a, "甲状腺周围结构的损伤定位需要核对神经与血管的毗邻。"),
                ("lesson_v2_feedback", self.book_b, "甲状腺激素通过反馈机制调节分泌，甲状腺功能需要结合生理过程理解。"),
            ):
                db.add(Chunk(id=chunk_id, textbook_id=book_id, chapter_id=f"{book_id}_chapter",
                             textbook_title="局部解剖学" if book_id == self.book_a else "生理学",
                             chapter_title="甲状腺", content=text, page_start=10, page_end=10))
            db.commit()
        finally:
            db.close()
        self.payload = {
            "course_id": self.course, "topic": "甲状腺", "goal": "围绕损伤定位安排45分钟教学和3道课堂问题",
            "textbook_ids": [self.book_a, self.book_b], "requirements": ["核心概念", "重点难点", "课堂提问"],
            "duration_minutes": 45, "question_count": 3, "focus_terms": ["损伤定位"], "context": {},
        }

    def tearDown(self):
        db = SessionLocal()
        try:
            db.query(Job).filter(Job.course_id == self.course).delete(synchronize_session=False)
            db.query(Chunk).filter(Chunk.textbook_id.in_([self.book_a, self.book_b])).delete(synchronize_session=False)
            db.query(Chapter).filter(Chapter.textbook_id.in_([self.book_a, self.book_b])).delete(synchronize_session=False)
            db.query(Textbook).filter(Textbook.id.in_([self.book_a, self.book_b])).delete(synchronize_session=False)
            db.query(Course).filter(Course.id == self.course).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def evidence(self):
        db = SessionLocal()
        try:
            return [agent._chunk_item(db.get(Chunk, value), title) for value, title in (
                ("lesson_v2_injury", "局部解剖学"), ("lesson_v2_feedback", "生理学"),
            )]
        finally:
            db.close()

    def artifact(self):
        return agent._normalize_artifact({
            "title": "甲状腺课堂初稿", "executive_summary": "围绕原文组织讲授，需教师审核。",
            "teaching_objectives": ["说明损伤定位与反馈机制"],
            "knowledge_sequence": [{"title": "损伤定位", "explanation": "核对毗邻与功能", "source_ids": ["S1", "S2"]}],
            "lesson_blocks": [
                {"title": "损伤定位", "minutes": 30, "content": "按原文讲解", "source_ids": ["S1"]},
                {"title": "反馈与讨论", "minutes": 15, "content": "核对生理材料", "source_ids": ["S2"]},
            ],
            "teaching_focus": [{"title": "损伤定位", "explanation": "核对结构", "source_ids": ["S1"]}],
            "classroom_questions": ["问题甲", "问题乙", "问题丙"],
        }, "甲状腺", agent._citations(self.evidence()), "llm_grounded")

    def job(self, artifact=None, status="completed", state=None):
        result = state or agent.initial_agent_result(self.payload)
        if artifact is not None:
            result["artifact"] = artifact
        db = SessionLocal()
        try:
            db.add(Job(id="lesson_v2_job", course_id=self.course, type="course_agent", status=status,
                       payload=copy.deepcopy(self.payload), result=result))
            db.commit()
        finally:
            db.close()
        return "lesson_v2_job"

    def test_fallback_is_only_evidence_and_does_not_fabricate_timing_or_questions(self):
        evidence = self.evidence()
        artifact = agent._fallback_artifact("甲状腺", evidence, agent._citations(evidence), "模型不可用")
        quality = agent.verify_artifact(artifact, self.payload["textbook_ids"], self.payload)
        self.assertEqual(quality["task_completion"]["status"], "evidence_only")
        self.assertFalse(artifact["lesson_blocks"])
        self.assertFalse(artifact["classroom_questions"])
        self.assertEqual(quality["score"], 0)
        self.assertFalse(quality["semantic_reviewed"])
        self.assertTrue(quality["task_completion"]["missing_items"])

    def test_single_book_common_claim_moves_to_sequence_without_losing_content(self):
        citations = agent._citations(self.evidence())
        data = {"common_ground": [{"claim": "单本教材中的局部结构说明", "source_ids": ["S1"]}]}
        result = agent._normalize_artifact(data, "甲状腺", citations, "llm_grounded")
        self.assertEqual(result["common_ground"], [])
        self.assertEqual(result["knowledge_sequence"][0]["explanation"], "单本教材中的局部结构说明")
        self.assertEqual(result["knowledge_sequence"][0]["source_ids"], ["S1"])
        self.assertTrue(result["unresolved_questions"])

    def test_common_claim_requires_distinct_books_not_just_distinct_sources(self):
        citations = agent._citations(self.evidence())
        citations.append({**citations[0], "source_id": "S3"})
        result = agent._normalize_artifact({"common_ground": [
            {"claim": "同一教材两段材料", "source_ids": ["S1", "S3"]},
            {"claim": "两本教材支持", "source_ids": ["S1", "S2"]},
        ]}, "甲状腺", citations, "llm_grounded")
        self.assertEqual([row["claim"] for row in result["common_ground"]], ["两本教材支持"])
        artifact = self.artifact()
        artifact["common_ground"] = [{"claim": "待核对的共同结论", "source_ids": ["S1"]}]
        quality = agent.verify_artifact(artifact, self.payload["textbook_ids"], self.payload)
        self.assertFalse(next(row for row in quality["checks"] if row["id"] == "common_ground_sources")["passed"])
        with self.assertRaisesRegex(ValueError, "至少两本不同教材"):
            agent.validate_lesson_draft(artifact, self.artifact(), self.payload)

    def test_contract_ready_still_requires_teacher_semantic_review(self):
        quality = agent.verify_artifact(self.artifact(), self.payload["textbook_ids"], self.payload)
        self.assertEqual(quality["task_completion"]["status"], "draft_ready")
        self.assertEqual(quality["status"], "needs_review")
        self.assertFalse(quality["semantic_reviewed"])

    def test_model_prompt_receives_teacher_notes_dimensions_and_mapped_sources(self):
        items = self.evidence()
        self.payload.update(audience="医学生二年级", prior_knowledge="已学习颈部基本结构")
        self.payload["context"] = {
            "board_id": "lesson_board", "board_revision": 3,
            "selected_chunk_ids": [row["id"] for row in items],
            "selections": [
                {"chunk_id": items[0]["id"], "dimension": "临床毗邻", "note": "先请学生定位神经，再讨论损伤。",
                 "content": "DO_NOT_REPEAT_CONTEXT_CONTENT", "quote": "DO_NOT_REPEAT_CONTEXT_QUOTE"},
                {"chunk_id": items[1]["id"], "dimension": "生理反馈", "note": "与第一条原文对照讲解。"},
            ],
            "connections": [{"source_chunk_id": items[0]["id"], "target_chunk_id": items[1]["id"],
                             "relation_type": "extends", "reason": "用于本课从结构过渡到功能，尚需核验", "status": "draft"}],
        }
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.artifact(), ensure_ascii=False)))])
        with patch.object(agent, "LLM_API_KEY", "offline_test"), \
             patch.object(agent, "create_openai_client", return_value=client), \
             patch.object(agent, "record_model_success"), \
             patch.object(agent, "record_model_failure"), \
             patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            artifact = agent._generate_artifact(self.payload, [SimpleNamespace(title="局部解剖学"), SimpleNamespace(title="生理学")], items)
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("教学对象：医学生二年级", prompt)
        self.assertIn("先修知识：已学习颈部基本结构", prompt)
        self.assertEqual(agent.initial_agent_result(self.payload)["request"]["audience"], "医学生二年级")
        context = json.loads(prompt.split("<UNTRUSTED_TEACHER_CONTEXT>", 1)[1].split("</UNTRUSTED_TEACHER_CONTEXT>", 1)[0])
        self.assertEqual(context["selections"][0], {"source_id": "S1", "chunk_id": items[0]["id"],
                                                  "teaching_title": "",
                                                  "dimension": "临床毗邻", "note": "先请学生定位神经，再讨论损伤。"})
        self.assertEqual(context["selections"][1]["source_id"], "S2")
        self.assertEqual(context["links"][0], {"source_id": "S1", "target_source_id": "S2", "type": "extends",
                                             "reason": "用于本课从结构过渡到功能，尚需核验", "status": "draft"})
        self.assertNotIn("DO_NOT_REPEAT_CONTEXT_CONTENT", prompt)
        self.assertNotIn("DO_NOT_REPEAT_CONTEXT_QUOTE", prompt)
        self.assertFalse(any(context["omitted"].values()))
        self.assertEqual(artifact["teacher_context_trace"]["selection_count"], 2)

    def test_long_teacher_annotations_are_budgeted_as_valid_json_with_visible_notice(self):
        items = [{**self.evidence()[0], "id": f"context_{index}"} for index in range(12)]
        self.payload["context"] = {
            "selected_chunk_ids": [row["id"] for row in items] + ["missing_source"],
            "selections": [{"chunk_id": row["id"], "dimension": "讲解维度", "note": "备注" * 500} for row in items],
            "connections": [{"source_chunk_id": items[index]["id"], "target_chunk_id": items[index + 1]["id"],
                             "relation_type": "extends", "reason": "说明" * 500, "status": "confirmed"} for index in range(6)],
        }
        context = json.loads(json.dumps(agent._teacher_context(self.payload, items), ensure_ascii=False))
        self.assertLessEqual(sum(len(row["note"]) for row in context["selections"]), 8000)
        self.assertLessEqual(sum(len(row["reason"]) for row in context["links"]), 4000)
        self.assertEqual(context["omitted"]["selections"], 1)
        self.assertEqual(context["omitted"]["truncated_notes"], 12)
        self.assertEqual(context["omitted"]["truncated_reasons"], 6)
        self.assertTrue(all(row["status"] == "confirmed" for row in context["links"]))
        with patch.object(agent, "LLM_API_KEY", ""):
            artifact = agent._generate_artifact(self.payload, [], items)
        self.assertTrue(any("维度 0 条" in text and "备注 12 条" in text for text in artifact["unresolved_questions"]))
        self.assertEqual(artifact["teacher_context_trace"]["omitted"], context["omitted"])

    def test_teacher_context_keeps_teacher_titles_and_selected_teaching_order(self):
        items = self.evidence()
        self.payload["context"] = {
            "selected_chunk_ids": [items[1]["id"], items[0]["id"]],
            "selections": [
                {"chunk_id": items[0]["id"], "teaching_title": "  结构与损伤定位  "},
                {"chunk_id": items[1]["id"], "teaching_title": "从反馈机制导入课堂"},
            ],
        }
        original = copy.deepcopy(self.payload)
        context = agent._teacher_context(self.payload, items)
        self.assertEqual([row["chunk_id"] for row in context["selections"]], [items[1]["id"], items[0]["id"]])
        self.assertEqual([row["source_id"] for row in context["selections"]], ["S2", "S1"])
        self.assertEqual([row["teaching_title"] for row in context["selections"]], ["从反馈机制导入课堂", "结构与损伤定位"])
        self.assertFalse(context["omitted"]["truncated_titles"])
        self.assertEqual(self.payload, original)

    def test_duration_question_count_focus_and_requirements_are_independent_checks(self):
        artifact = self.artifact()
        artifact["lesson_blocks"][0]["minutes"] = 10
        artifact["classroom_questions"] = ["仅一道问题"]
        artifact["teaching_focus"] = []
        quality = agent.verify_artifact(artifact, self.payload["textbook_ids"], self.payload)
        by_id = {row["id"]: row for row in quality["task_completion"]["checks"]}
        for key in ("duration_minutes", "question_count", "requirement:teaching_focus"):
            self.assertFalse(by_id[key]["passed"])
        self.assertEqual(quality["task_completion"]["status"], "needs_work")

    def test_missing_citations_cannot_be_offset_by_other_structure(self):
        artifact = self.artifact()
        artifact["knowledge_sequence"].append({"title": "无引用", "explanation": "需补依据", "source_ids": []})
        quality = agent.verify_artifact(artifact, self.payload["textbook_ids"], self.payload)
        self.assertFalse(next(row for row in quality["checks"] if row["id"] == "grounding")["passed"])
        self.assertEqual(quality["task_completion"]["status"], "needs_work")

    def test_all_selected_books_are_checked_not_only_two_of_seven(self):
        quality = agent.verify_artifact(self.artifact(), [self.book_a, self.book_b, "third_book"], self.payload)
        self.assertFalse(next(row for row in quality["checks"] if row["id"] == "book_coverage")["passed"])

    def test_retrieval_balances_books_and_uses_focus_without_goal_scope_rejection(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            items, trace = agent._retrieve_lesson_evidence(self.payload)
        self.assertEqual({row["textbook_id"] for row in items}, {self.book_a, self.book_b})
        self.assertIn("lesson_v2_injury", {row["id"] for row in items})
        self.assertEqual(trace["channel"], "lexical_bridge")
        self.assertIn("甲状腺 损伤定位", trace["queries"])
        self.assertTrue(trace["goal_used_for_ranking"])
        self.assertNotIn(self.payload["goal"], trace["queries"])

    def test_explicit_context_evidence_is_preserved_even_without_literal_topic(self):
        db = SessionLocal()
        try:
            db.get(Chunk, "lesson_v2_structure").content = "教师选中的具体材料，即使术语没有逐字出现也必须保留。"
            db.commit()
        finally:
            db.close()
        self.payload["context"] = {"selected_chunk_ids": ["lesson_v2_structure"]}
        items, _ = agent._retrieve_lesson_evidence(self.payload)
        self.assertIn("lesson_v2_structure", {row["id"] for row in items})

    def test_explicit_selections_are_not_truncated_to_the_per_book_quota(self):
        selected = [f"lesson_v2_selected_{index}" for index in range(9)]
        db = SessionLocal()
        try:
            for index, chunk_id in enumerate(selected):
                db.add(Chunk(id=chunk_id, textbook_id=self.book_a, chapter_id=f"{self.book_a}_chapter",
                             chapter_title="甲状腺", content=f"教师选定的原文材料 {index}",
                             page_start=10, page_end=10, chunk_index=100 + index))
            db.commit()
        finally:
            db.close()
        self.payload["context"] = {"selected_chunk_ids": selected}
        items, trace = agent._retrieve_lesson_evidence(self.payload)
        self.assertTrue(set(selected).issubset({row["id"] for row in items}))
        self.assertIn(self.book_b, {row["textbook_id"] for row in items})
        self.assertLessEqual(len(items), 48)
        fallback = agent._fallback_artifact("甲状腺", items, agent._citations(items), "模型不可用")
        quality = agent.verify_artifact(fallback, self.payload["textbook_ids"], self.payload)
        self.assertTrue(next(row for row in quality["task_completion"]["checks"] if row["id"] == "selected_sources")["passed"])
        self.assertEqual(trace["per_book_counts"][self.book_a], 9)

    def test_goal_changes_source_ranking_without_becoming_a_required_topic(self):
        self.payload["focus_terms"] = []
        self.payload["goal"] = "讲清甲状腺组成"
        structure, _ = agent._retrieve_lesson_evidence(self.payload)
        self.payload["goal"] = "讲清甲状腺损伤定位"
        injury, _ = agent._retrieve_lesson_evidence(self.payload)
        self.assertEqual(structure[0]["id"], "lesson_v2_structure")
        self.assertEqual(injury[0]["id"], "lesson_v2_injury")

    def test_source_ready_task_does_not_build_graph_alignments_or_indexes(self):
        job_id = self.job(status="pending")
        with patch.object(agent, "LLM_API_KEY", ""), \
             patch("backend.agents.kg_extraction_agent.extract_textbook_graph", side_effect=AssertionError("graph forbidden")), \
             patch("backend.services.alignment_service.generate_alignment_candidates", side_effect=AssertionError("alignment forbidden")), \
             patch("backend.services.retrieval_service.build_course_index", side_effect=AssertionError("index forbidden")), \
             patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            agent.process_course_agent(job_id)
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            self.assertEqual(job.status, "completed")
            self.assertEqual(job.result["delivery"]["status"], "evidence_only")
            self.assertEqual(job.result["artifact"]["generation_method"], "evidence_fallback")
            self.assertEqual(job.result["draft_revision"], 0)
            self.assertEqual(db.get(Textbook, self.book_a).graph_status, "pending")
        finally:
            db.close()

    def test_generated_artifact_survives_verification_interruption_without_regeneration(self):
        job_id = self.job(status="pending")
        persist = agent._persist
        interrupted = []
        def interrupt_after_checkpoint(*args, **kwargs):
            persist(*args, **kwargs)
            if kwargs.get("stage") == "verify" and not interrupted:
                interrupted.append(True)
                raise RuntimeError("simulated interruption")
        with patch.object(agent, "_persist", side_effect=interrupt_after_checkpoint), \
             patch.object(agent, "_generate_artifact", return_value=self.artifact()) as generate:
            agent.process_course_agent(job_id)
            self.assertEqual(generate.call_count, 1)
        with patch.object(agent, "_generate_artifact", side_effect=AssertionError("duplicate generation")) as generate:
            agent.process_course_agent(job_id)
            generate.assert_not_called()
        db = SessionLocal()
        try:
            self.assertEqual(db.get(Job, job_id).status, "completed")
            self.assertTrue(db.get(Job, job_id).result["artifact_input_signature"])
        finally:
            db.close()

    def test_teacher_save_preserves_generated_artifact_and_uses_revision_conflicts(self):
        original = self.artifact()
        job_id = self.job(original)
        draft = copy.deepcopy(original)
        draft["title"] = "教师调整后的教案"
        result = save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=draft))
        self.assertEqual(result["result"]["draft_revision"], 1)
        self.assertEqual(result["result"]["lesson_draft"]["title"], draft["title"])
        self.assertEqual(result["result"]["artifact"], original)
        self.assertEqual(result["result"]["delivery"]["status"], "draft_ready")
        with self.assertRaises(HTTPException) as error:
            save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=draft))
        self.assertEqual(error.exception.status_code, 409)

    def test_teacher_can_complete_a_fallback_without_rewriting_its_provenance(self):
        items = self.evidence()
        original = agent._fallback_artifact("甲状腺", items, agent._citations(items), "模型不可用")
        job_id = self.job(original)
        draft = self.artifact()
        draft["generation_method"] = "forged_verified_method"
        draft["teacher_edited"] = False
        response = save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=draft))
        state = response["result"]
        self.assertEqual(state["artifact"], original)
        self.assertEqual(state["lesson_draft"]["generation_method"], "evidence_fallback")
        self.assertTrue(state["lesson_draft"]["teacher_edited"])
        self.assertEqual(state["delivery"]["status"], "draft_ready")
        self.assertFalse(state["quality"]["semantic_reviewed"])
        draft["lesson_blocks"] = []
        draft["classroom_questions"] = []
        response = save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=1, artifact=draft))
        self.assertEqual(response["result"]["delivery"]["status"], "needs_work")

    def test_board_source_changes_return_a_conflict_instead_of_an_internal_error(self):
        from backend.services.teaching_board import BoardConflict
        payload = AgentRunCreate(**{**self.payload, "context": {"board_id": "changed_board"}})
        with patch("backend.services.teaching_board.get_board_agent_context", side_effect=BoardConflict("选定原文已变化")), \
             patch("backend.api.agent.enqueue_job") as enqueue, self.assertRaises(HTTPException) as error:
            create_agent_run(payload)
        self.assertEqual(error.exception.status_code, 409)
        enqueue.assert_not_called()

    def test_teacher_cannot_forge_sources_or_save_while_job_is_active(self):
        original = self.artifact()
        job_id = self.job(original)
        draft = copy.deepcopy(original)
        draft["knowledge_sequence"][0]["source_ids"] = ["S99"]
        with self.assertRaises(HTTPException) as error:
            save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=draft))
        self.assertEqual(error.exception.status_code, 422)
        draft = copy.deepcopy(original)
        draft["citations"][0]["textbook_id"] = "outside_course"
        with self.assertRaises(HTTPException) as error:
            save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=draft))
        self.assertEqual(error.exception.status_code, 422)
        db = SessionLocal()
        try:
            db.get(Job, job_id).status = "processing"
            db.commit()
        finally:
            db.close()
        with self.assertRaises(HTTPException) as error:
            save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=original))
        self.assertEqual(error.exception.status_code, 409)

    def test_legacy_run_without_revision_can_be_edited_without_a_schema_migration(self):
        original = self.artifact()
        job_id = self.job(state={"artifact": original})
        response = save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=original))
        self.assertEqual(response["result"]["draft_revision"], 1)
        self.assertEqual(response["result"]["artifact"], original)

    def test_export_uses_saved_draft_and_non_pdf_locations_without_unsafe_markup(self):
        original = self.artifact()
        job_id = self.job(original)
        draft = copy.deepcopy(original)
        draft["title"] = "教师版本"
        draft["executive_summary"] = '<script>alert(1)</script> ![tracking](https://example.invalid/image.png)'
        save_lesson_draft(job_id, LessonDraftUpdate(expected_revision=0, artifact=draft))
        response = export_lesson(job_id)
        content = response.body.decode("utf-8")
        self.assertIn("教师版本", content)
        self.assertNotIn("<script>", content)
        self.assertNotIn("![tracking]", content)
        # Both source books are TXT fixtures: stored location numbers cannot
        # establish PDF provenance in either downloadable or printable output.
        self.assertEqual(content.count(" · 原文位置 10–10"), 2)
        self.assertNotIn(" · PDF ", content)
        self.assertIn("attachment", response.headers["content-disposition"])
        printed = export_lesson(job_id, format="html").body.decode("utf-8")
        self.assertIn("教师版本", printed)
        self.assertEqual(printed.count(" · 原文位置 10–10"), 2)
        self.assertNotIn(" · PDF ", printed)

    def test_create_context_and_scope_are_validated_before_enqueuing(self):
        payload = AgentRunCreate(**{**self.payload, "context": {"source_book_id": "outside", "selected_chunk_ids": []}})
        with patch("backend.api.agent.enqueue_job") as enqueue, self.assertRaises(HTTPException) as error:
            create_agent_run(payload)
        self.assertEqual(error.exception.status_code, 400)
        enqueue.assert_not_called()
        payload = AgentRunCreate(**{**self.payload, "context": {"selected_chunk_ids": ["missing_chunk"]}})
        with self.assertRaises(HTTPException) as error:
            create_agent_run(payload)
        self.assertEqual(error.exception.status_code, 400)

    def test_request_supports_seven_books_and_bounds_duration_questions_and_focus(self):
        payload = AgentRunCreate(topic="甲状腺", goal="安排课堂教学", textbook_ids=[f"book_{i}" for i in range(7)])
        self.assertEqual(payload.duration_minutes, 45)
        self.assertEqual(payload.question_count, 3)
        for values in ({"duration_minutes": 0}, {"question_count": 13}, {"duration_minutes": True}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                AgentRunCreate(topic="甲状腺", goal="安排课堂教学", textbook_ids=[self.book_a], **values)


if __name__ == "__main__":
    unittest.main()
