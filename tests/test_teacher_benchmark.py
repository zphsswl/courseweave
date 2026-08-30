import os
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.api.benchmark import (  # noqa: E402
    _evaluate_teacher_questions,
    load_teacher_suite,
)


class TeacherBenchmarkTests(unittest.TestCase):
    def test_suite_contains_30_to_50_realistic_teacher_questions(self):
        questions = load_teacher_suite()["questions"]
        self.assertGreaterEqual(len(questions), 30)
        self.assertLessEqual(len(questions), 50)
        self.assertGreaterEqual(sum(1 for item in questions if item["mode"] == "compare"), 5)
        self.assertGreaterEqual(sum(1 for item in questions if not item["answerable"]), 5)
        self.assertEqual(len({item["id"] for item in questions}), len(questions))

    def test_four_teacher_metrics_are_computed_from_retrieval_results(self):
        questions = [
            {"question": "炎症是什么", "mode": "all", "answerable": True, "expected_terms": ["炎症"]},
            {"question": "比较缺氧", "mode": "compare", "answerable": True, "expected_terms": ["缺氧"], "min_textbooks": 2},
            {"question": "quantum compiler", "mode": "all", "answerable": False, "expected_terms": []},
        ]
        responses = [
            {"results": [{"id": "c1", "content": "炎症是防御反应", "page_start": 10, "textbook_id": "a"}]},
            {"results": [
                {"id": "c2", "content": "缺氧的生理基础", "page_start": 20, "textbook_id": "a"},
                {"id": "c3", "content": "缺氧的病理变化", "page_start": 30, "textbook_id": "b"},
            ]},
            {"results": []},
        ]
        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(set(by_name), {"检索召回率", "引用准确率", "跨教材覆盖率", "无答案拒答率"})
        self.assertTrue(all(item["score"] == 1.0 for item in metrics))

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
            {"results": [{"id": "one_phase", "content": "仅提到一期", "page_start": 1}]},
            {"results": [
                {"id": "cell_a", "content": "甲细胞", "page_start": 2},
                {"id": "cell_b", "content": "乙细胞", "page_start": 3},
            ]},
            {"results": [{"id": "single", "content": "炎症", "page_start": 4}]},
        ]

        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["检索召回率"]["numerator"], 2)
        self.assertEqual(by_name["检索召回率"]["denominator"], 3)
        self.assertEqual(by_name["引用准确率"]["numerator"], 3)
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
        }]}]

        with patch("backend.api.benchmark.retrieve", side_effect=responses):
            metrics = _evaluate_teacher_questions("course_test", questions)

        by_name = {item["metric"]: item for item in metrics}
        self.assertEqual(by_name["检索召回率"]["numerator"], 1)
        self.assertEqual(by_name["引用准确率"]["numerator"], 1)


if __name__ == "__main__":
    unittest.main()
