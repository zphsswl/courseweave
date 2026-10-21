import os
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.api.benchmark import (  # noqa: E402
    _evaluate_teacher_questions,
    load_teacher_suite,
)


class TeacherBenchmarkTests(unittest.TestCase):
    def test_suite_contains_420_questions_covering_all_137_chapters(self):
        suite = load_teacher_suite()
        questions = suite["questions"]
        chapter_questions = [item for item in questions if item.get("target_chapter_id")]
        self.assertEqual(suite["version"], "medical-teacher-v3")
        self.assertEqual(len(questions), 420)
        self.assertEqual(sum(1 for item in questions if item["answerable"]), 380)
        self.assertEqual(sum(1 for item in questions if item["mode"] == "compare"), 41)
        self.assertEqual(sum(1 for item in questions if not item["answerable"]), 40)
        self.assertEqual(len(chapter_questions), 274)
        self.assertEqual(len({item["target_chapter_id"] for item in chapter_questions}), 137)
        self.assertEqual({
            sum(1 for item in chapter_questions if item["target_chapter_id"] == chapter_id)
            for chapter_id in {item["target_chapter_id"] for item in chapter_questions}
        }, {2})
        self.assertEqual(len({item["id"] for item in questions}), len(questions))
        self.assertTrue(all(
            not item["answerable"] or item.get("expected_terms") or item.get("expected_concepts")
            for item in questions
        ))
        forbidden_source_fields = {"content", "source_paragraph", "source_quote", "source_sentences"}
        self.assertTrue(all(forbidden_source_fields.isdisjoint(item) for item in questions))

    def test_four_teacher_metrics_are_computed_from_retrieval_results(self):
        questions = [
            {"question": "炎症是什么", "mode": "all", "answerable": True, "expected_terms": ["炎症"]},
            {"question": "比较缺氧", "mode": "compare", "answerable": True, "expected_terms": ["缺氧"], "min_textbooks": 2},
            {"question": "quantum compiler", "mode": "all", "answerable": False, "expected_terms": []},
        ]
        responses = [
            {"results": [{"id": "c1", "content": "炎症是防御反应", "page_start": 10, "page_end": 10, "textbook_id": "a"}]},
            {"results": [
                {"id": "c2", "content": "缺氧的生理基础", "page_start": 20, "page_end": 20, "textbook_id": "a"},
                {"id": "c3", "content": "缺氧的病理变化", "page_start": 30, "page_end": 30, "textbook_id": "b"},
            ]},
            {"results": []},
        ]
        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertTrue({"检索召回率", "引用准确率", "跨教材覆盖率", "无答案拒答率"}.issubset(by_name))
        self.assertTrue(all(by_name[name]["score"] == 1.0 for name in ("检索召回率", "引用准确率", "跨教材覆盖率", "无答案拒答率")))

    def test_chapter_questions_require_the_expected_chapter(self):
        questions = [{
            "id": "chapter_case",
            "question": "解释静息电位",
            "mode": "all",
            "answerable": True,
            "expected_terms": ["静息电位"],
            "textbook_ids": ["book_a"],
            "target_chapter_id": "chapter_a",
            "target_chapter_title": "第二章",
        }]
        responses = [{"results": [
            {"id": "wrong", "content": "静息电位", "page_start": 5, "page_end": 5, "textbook_id": "book_a", "chapter_id": "chapter_b", "chapter": "第三章"},
            {"id": "right", "content": "静息电位", "page_start": 8, "page_end": 8, "textbook_id": "book_a", "chapter_id": "chapter_a", "chapter": "第二章"},
        ]}]

        with patch("backend.api.benchmark.retrieve", side_effect=responses) as mocked_retrieve:
            metrics = _evaluate_teacher_questions("course_test", questions)

        mocked_retrieve.assert_called_once_with(
            "解释静息电位", course_id="course_test", textbook_ids=["book_a"], mode="all", top_k=8,
        )
        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["章节题命中率"]["score"], 1.0)
        self.assertEqual(by_name["章节覆盖率"]["score"], 1.0)
        self.assertEqual(by_name["引用准确率"]["numerator"], 1)
        self.assertEqual(by_name["引用准确率"]["denominator"], 2)

    def test_chapter_questions_reject_wrong_chapter_only(self):
        questions = [{
            "id": "chapter_case",
            "question": "解释静息电位",
            "mode": "all",
            "answerable": True,
            "expected_terms": ["静息电位"],
            "textbook_ids": ["book_a"],
            "target_chapter_id": "chapter_a",
            "target_chapter_title": "第二章",
        }]
        responses = [{"results": [{
            "id": "wrong",
            "content": "静息电位",
            "page_start": 5,
            "page_end": 5,
            "textbook_id": "book_a",
            "chapter_id": "chapter_b",
            "chapter": "第三章",
        }]}]

        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["章节题命中率"]["score"], 0.0)
        self.assertEqual(by_name["章节覆盖率"]["score"], 0.0)

    def test_chapter_title_alone_does_not_match_expected_concept(self):
        questions = [{
            "id": "chapter_title_only",
            "question": "传染病是什么",
            "mode": "all",
            "answerable": True,
            "expected_terms": ["传染病"],
        }]
        responses = [{"results": [{
            "id": "chapter_title_only_result",
            "content": "本章介绍学习目标。",
            "section_path": ["学习目标"],
            "chapter": "传染病学总论",
            "page_start": 5,
            "page_end": 5,
        }]}]

        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["检索召回率"]["score"], 0.0)
        self.assertEqual(by_name["引用准确率"]["score"], 0.0)

    def test_citation_requires_a_valid_full_page_range(self):
        questions = [{
            "question": "炎症是什么",
            "mode": "all",
            "answerable": True,
            "expected_terms": ["炎症"],
        }]
        responses = [{"results": [{
            "id": "broken_page_range",
            "content": "炎症是防御反应",
            "page_start": 10,
            "page_end": 0,
        }]}]

        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["检索召回率"]["score"], 1.0)
        self.assertEqual(by_name["引用准确率"]["score"], 0.0)

    def test_multi_part_questions_require_coverage_but_single_concepts_do_not_change(self):
        questions = [
            {
                "question": "四期如何演变",
                "mode": "all",
                "answerable": True,
                "expected_terms": ["一期", "二期", "三期", "四期"],
            },
            {
                "question": "三类细胞",
                "mode": "all",
                "answerable": True,
                "expected_terms": ["甲细胞", "乙细胞", "丙细胞"],
            },
            {
                "question": "炎症是什么",
                "mode": "all",
                "answerable": True,
                "expected_terms": ["炎症"],
            },
        ]
        responses = [
            {"results": [{"id": "one_phase", "content": "仅提到一期", "page_start": 1, "page_end": 1}]},
            {"results": [
                {"id": "cell_a", "content": "甲细胞", "page_start": 2, "page_end": 2},
                {"id": "cell_b", "content": "乙细胞", "page_start": 3, "page_end": 3},
            ]},
            {"results": [{"id": "single", "content": "炎症", "page_start": 4, "page_end": 4}]},
        ]

        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["检索召回率"]["numerator"], 2)
        self.assertEqual(by_name["检索召回率"]["denominator"], 3)
        self.assertEqual(by_name["引用准确率"]["numerator"], 4)
        self.assertEqual(by_name["引用准确率"]["denominator"], 4)

    def test_aliases_match_one_concept_without_increasing_the_coverage_denominator(self):
        questions = [{
            "question": "休克分期",
            "mode": "all",
            "answerable": True,
            "expected_terms": ["微循环缺血期", "微循环淤血期", "微循环衰竭期"],
            "expected_concepts": [
                {"canonical": "微循环缺血期", "aliases": ["微循环缺血期", "缺血缺氧期"]},
                {"canonical": "微循环淤血期", "aliases": ["微循环淤血期", "淤血缺氧期"]},
                {"canonical": "微循环衰竭期", "aliases": ["微循环衰竭期", "衰竭期"]},
            ],
        }]
        responses = [{"results": [{
            "id": "stages",
            "content": "休克分为缺血缺氧期、淤血缺氧期和衰竭期。",
            "page_start": 10,
            "page_end": 10,
        }]}]

        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["检索召回率"]["numerator"], 1)
        self.assertEqual(by_name["引用准确率"]["numerator"], 1)


if __name__ == "__main__":
    unittest.main()
