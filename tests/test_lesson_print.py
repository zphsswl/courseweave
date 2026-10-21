import unittest
from backend.services.lesson_print import lesson_print_html


class LessonPrintTests(unittest.TestCase):
    def test_saved_document_content_and_layout_survive_export(self):
        result = lesson_print_html("# 本课\n\n## 教学目标\n- 解释甲概念 [S1]\n\n|环节|分钟|\n|---|---|\n|讨论|5|", "本课")
        self.assertIn("<h1>本课</h1>", result)
        self.assertIn("<li>解释甲概念 [S1]</li>", result)
        self.assertIn("<th>环节</th>", result)
        self.assertIn("<td>5</td>", result)
        self.assertIn("@page{size:A4", result)
        self.assertIn("保存为 PDF", result)

    def test_untrusted_source_html_cannot_execute(self):
        result = lesson_print_html('<script>alert(1)</script>\n<img src="https://example.com/pixel">', '<script>title</script>')
        self.assertNotIn("<script>", result)
        self.assertNotIn("<img ", result)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", result)
        self.assertIn("default-src 'none'", result)


if __name__ == "__main__":
    unittest.main()
