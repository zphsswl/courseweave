import os
import unittest


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.database import (  # noqa: E402
    Chapter,
    Chunk,
    Course,
    SessionLocal,
    Textbook,
    init_db,
)
from backend.services.retrieval_service import invalidate_course_cache, retrieve  # noqa: E402


class TeacherQueryConstraintTests(unittest.TestCase):
    course_id = "teacher_query_constraints"
    other_course_id = "teacher_query_constraints_other"
    anatomy_id = "teacher_query_anatomy"
    physiology_id = "teacher_query_physiology"
    other_book_id = "teacher_query_other"
    long_question = (
        "仅依据《局部解剖学》，列出臂丛的组成、主要分支和相关页码；"
        "不要补充教材中没有依据的内容。"
    )

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.add_all([
                Course(id=self.course_id, title="解剖课"),
                Course(id=self.other_course_id, title="另一门课"),
            ])
            db.flush()
            for book_id, course_id, title in (
                (self.anatomy_id, self.course_id, "局部解剖学"),
                (self.physiology_id, self.course_id, "生理学"),
                (self.other_book_id, self.other_course_id, "另一课程专属教材"),
            ):
                db.add(Textbook(
                    id=book_id, course_id=course_id, filename=f"{book_id}.txt",
                    title=title, format="txt",
                ))
            db.flush()
            for book_id in (self.anatomy_id, self.physiology_id, self.other_book_id):
                db.add(Chapter(id=f"{book_id}_chapter", textbook_id=book_id, title="上肢"))
            db.flush()
            for chunk_id, book_id, title, page, content in (
                ("teacher_anatomy_roots", self.anatomy_id, "局部解剖学", 76,
                 "臂丛由第5至第8颈神经和第1胸神经前支组成，经斜角肌间隙进入颈外侧区。"),
                ("teacher_anatomy_thyroid", self.anatomy_id, "局部解剖学", 65,
                 "甲状腺的形态呈H形，由左右叶及峡部组成。甲状腺的位置在颈前区，左右叶位于喉和气管的前外侧。"),
                ("teacher_anatomy_branches", self.anatomy_id, "局部解剖学", 229,
                 "臂丛的主要分支包括肌皮神经、正中神经、尺神经、桡神经和腋神经。"),
                ("teacher_anatomy_skin", self.anatomy_id, "局部解剖学", 57,
                 "颈部皮肤较薄，皮纹呈横向分布，浅筋膜内有颈阔肌。"),
                ("teacher_anatomy_chest", self.anatomy_id, "局部解剖学", 82,
                 "胸壁由皮肤、浅筋膜、肌层、胸廓和胸内筋膜等构成。"),
                ("teacher_anatomy_pelvis", self.anatomy_id, "局部解剖学", 173,
                 "盆部与会阴位于躯干下部，骨盆由髋骨、骶骨和尾骨围成。"),
                ("teacher_anatomy_leg", self.anatomy_id, "局部解剖学", 262,
                 "下肢具有行走、运动和支持体重的功能，与躯干直接相连。"),
                ("teacher_physiology", self.physiology_id, "生理学", 10,
                 "臂丛的组成和分支将神经冲动传递至上肢，臂丛的分支参与运动控制。"),
                ("teacher_other_course", self.other_book_id, "另一课程专属教材", 1,
                 "臂丛的组成和分支属于另一课程的资料，不应进入本课程回答。"),
            ):
                db.add(Chunk(
                    id=chunk_id, textbook_id=book_id, chapter_id=f"{book_id}_chapter",
                    textbook_title=title, chapter_title="上肢", page_start=page,
                    page_end=page, content=content, chunk_index=page,
                ))
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(self.course_id)
        invalidate_course_cache(self.other_course_id)

    def tearDown(self):
        db = SessionLocal()
        book_ids = [self.anatomy_id, self.physiology_id, self.other_book_id]
        try:
            db.query(Chunk).filter(Chunk.textbook_id.in_(book_ids)).delete(synchronize_session=False)
            db.query(Chapter).filter(Chapter.textbook_id.in_(book_ids)).delete(synchronize_session=False)
            db.query(Textbook).filter(Textbook.id.in_(book_ids)).delete(synchronize_session=False)
            db.query(Course).filter(Course.id.in_([self.course_id, self.other_course_id])).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(self.course_id)
        invalidate_course_cache(self.other_course_id)

    def ask(self, question, textbook_ids=None):
        return retrieve(question, course_id=self.course_id, textbook_ids=textbook_ids, top_k=8)

    def test_observed_long_request_recovers_the_same_evidence_as_short_request(self):
        short = self.ask("臂丛的组成和分支是什么？", [self.anatomy_id])
        long = self.ask(self.long_question, [self.anatomy_id])
        self.assertTrue(short["results"])
        self.assertEqual({item["id"] for item in long["results"]}, {item["id"] for item in short["results"]})
        self.assertTrue({76, 229}.issubset({item["page_start"] for item in long["results"]}))

    def test_explicit_only_book_request_restricts_the_course_wide_search(self):
        result = self.ask(self.long_question)
        self.assertTrue(result["results"])
        self.assertEqual({item["textbook_id"] for item in result["results"]}, {self.anatomy_id})

    def test_explicit_book_scope_does_not_expand_the_ui_selection(self):
        result = self.ask(self.long_question, [self.physiology_id])
        self.assertEqual(result["results"], [])
        self.assertEqual(result["trace"]["reason"], "requested_textbooks_outside_scope")

    def test_unknown_or_other_course_source_does_not_fall_back_to_current_books(self):
        for title in ("不存在的教材", "另一课程专属教材"):
            with self.subTest(title=title):
                result = self.ask(f"仅依据《{title}》，列出臂丛的组成和分支。")
                self.assertEqual(result["results"], [])
                self.assertEqual(result["trace"]["reason"], "requested_textbook_not_available")

    def test_format_and_evidence_constraints_are_not_retrieval_topics(self):
        for question in (
            "请列出臂丛的组成和分支，并给出页码；不要编造内容。",
            "请用表格列出臂丛的组成和分支；不要补充教材之外的内容。",
            "只根据本书原文，说明臂丛的组成和分支，标注相关页码。",
            "请列出臂丛的组成和分支；不要补充书中没有依据的内容。",
        ):
            with self.subTest(question=question):
                result = self.ask(question, [self.anatomy_id])
                self.assertTrue(result["results"])
                self.assertEqual({item["textbook_id"] for item in result["results"]}, {self.anatomy_id})

    def test_multiple_explicit_source_books_are_kept_within_selected_scope(self):
        result = self.ask("仅依据《局部解剖学》和《生理学》，列出臂丛的组成和分支。")
        self.assertEqual({item["textbook_id"] for item in result["results"]}, {self.anatomy_id, self.physiology_id})

    def test_natural_location_and_source_requests_keep_the_same_topic_evidence(self):
        for question in (
            "甲状腺的位置与形态",
            "甲状腺的位置和形态是什么",
            "请解释甲状腺在什么位置，有什么形态特点",
            "甲状腺的位置与形态，给出教材原文依据",
            "甲状腺在哪里，提供本书原文证据",
        ):
            with self.subTest(question=question):
                result = self.ask(question, [self.anatomy_id])
                self.assertIn("teacher_anatomy_thyroid", {item["id"] for item in result["results"]})

    def test_natural_location_request_keeps_mixed_unknown_subjects(self):
        for question in (
            "甲状腺在什么位置，同时解释量子计算机的组成",
            "甲状腺的位置与形态和区块链共识算法，给出教材原文依据",
        ):
            with self.subTest(question=question):
                result = self.ask(question, [self.anatomy_id])
                self.assertEqual(result["results"], [])
                self.assertEqual(result["trace"]["reason"], "unsupported_query_topics")

    def test_unknown_topics_are_not_discarded_as_output_constraints(self):
        for question in (
            "仅依据《局部解剖学》，列出区块链共识算法的组成和分支；不要补充教材中没有依据的内容。",
            "仅依据《局部解剖学》，列出臂丛和区块链共识算法的组成；不要编造内容。",
            "仅依据《局部解剖学》，列出臂丛的组成和分支；同时解释区块链共识算法。",
            "请列出臂丛和量子计算机的组成，并给出页码。",
            "请列出臂丛的组成；不要补充区块链算法内容。",
        ):
            with self.subTest(question=question):
                result = self.ask(question, [self.anatomy_id])
                self.assertEqual(result["results"], [])
                self.assertEqual(result["trace"]["reason"], "unsupported_query_topics")

    def test_constraints_without_a_subject_do_not_return_arbitrary_evidence(self):
        result = self.ask("仅依据《局部解剖学》，标注页码；不要编造内容。")
        self.assertEqual(result["results"], [])


if __name__ == "__main__":
    unittest.main()
