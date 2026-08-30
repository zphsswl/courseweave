import os
import sys
import types
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.services.pdf_parser import _clean_text, _parse_pdf, _split_by_headings_with_pages  # noqa: E402
from backend.services.chunker import (  # noqa: E402
    _pages_for_range,
    _split_semantic_text_with_offsets,
    _split_text_with_offsets,
)


class PageAwareIngestionTest(unittest.TestCase):
    def test_pdf_control_characters_are_removed_before_chunking(self):
        raw = "炎症是机体的防御反应。\x08\x0c\ufffd\ufffd\n\n后续原文。"
        cleaned = _clean_text(raw)
        self.assertEqual(cleaned, "炎症是机体的防御反应。\n\n后续原文。")
        self.assertNotIn("\ufffd", cleaned)

    def test_chapter_boundaries_keep_real_page_numbers(self):
        pages = [
            {
                "page_number": 1,
                "text": "前言内容" * 60 + "\n第1章 基础概念\n" + "第一页正文" * 20,
                "printed_page_number": "",
                "extraction_method": "native",
            },
            {
                "page_number": 2,
                "text": "上一节延续内容" * 40 + "\n第2章 进阶内容\n" + "进阶正文" * 20,
                "printed_page_number": "",
                "extraction_method": "native",
            },
            {
                "page_number": 3,
                "text": "后续知识内容" * 60,
                "printed_page_number": "",
                "extraction_method": "native",
            },
        ]

        chapters = _split_by_headings_with_pages(pages)

        self.assertEqual([chapter["title"] for chapter in chapters], [
            "绪论/前言",
            "第1章 基础概念",
            "第2章 进阶内容",
        ])
        self.assertEqual((chapters[1]["page_start"], chapters[1]["page_end"]), (1, 2))
        self.assertEqual((chapters[2]["page_start"], chapters[2]["page_end"]), (2, 3))
        self.assertEqual(
            [span["page_number"] for span in chapters[2]["source_spans"]],
            [2, 3],
        )

    def test_chunk_offsets_map_to_only_overlapping_pages(self):
        text = "A" * 300 + "。" + "B" * 300 + "。" + "C" * 300
        chunks = _split_text_with_offsets(text, chunk_size=420, overlap=40)
        spans = [
            {"page_number": 10, "chapter_start": 0, "chapter_end": 301},
            {"page_number": 11, "chapter_start": 301, "chapter_end": 602},
            {"page_number": 12, "chapter_start": 602, "chapter_end": len(text)},
        ]

        first_start, first_end, _ = chunks[0]
        last_start, last_end, _ = chunks[-1]

        self.assertEqual(_pages_for_range(spans, first_start, first_end, 10, 12), (10, 10))
        self.assertEqual(_pages_for_range(spans, last_start, last_end, 10, 12)[1], 12)
        self.assertTrue(all(chunk_text for _, _, chunk_text in chunks))

    def test_pdf_parser_requests_visual_reading_order(self):
        class FakePage:
            def __init__(self):
                self.sort_values = []

            def get_text(self, mode, sort=False):
                self.sort_values.append(sort)
                if sort:
                    return "第一章 基础概念\n" + "正文内容。" * 80
                return "正文内容。" * 80 + "\n第一章 基础概念"

        class FakeDocument(list):
            def close(self):
                return None

        page = FakePage()
        fake_fitz = types.SimpleNamespace(open=lambda _: FakeDocument([page]))
        with patch.dict(sys.modules, {"fitz": fake_fitz}):
            parsed = _parse_pdf("visual-order.pdf", "book_visual")

        self.assertEqual(page.sort_values, [True])
        self.assertEqual(parsed["chapters"][0]["title"], "第一章 基础概念")

    def test_semantic_chunks_do_not_cross_sections_and_keep_hierarchy(self):
        text = (
            "第一节 基础概念\n"
            + "炎症是机体对损伤的防御反应。" * 12
            + "\n第二节 临床表现\n"
            + "局部表现包括红、肿、热、痛。" * 12
        )

        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第四章 炎症",
            textbook_title="病理学",
        )

        self.assertTrue(chunks)
        self.assertTrue(all(not ("防御反应" in content and "局部表现" in content) for _, _, content, _ in chunks))
        self.assertTrue(any(path[-1] == "第一节 基础概念" for _, _, _, path in chunks))
        self.assertTrue(any(path[-1] == "第二节 临床表现" for _, _, _, path in chunks))

    def test_semantic_overlap_restarts_at_a_complete_unit(self):
        text = "第一节 机制\n" + "甲机制维持稳态。乙机制参与调节。丙机制负责反馈。" * 12
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=120,
            overlap=40,
            chapter_title="第一章 总论",
        )

        for start, _, _, _ in chunks[1:]:
            self.assertTrue(start == 0 or text[start - 1] in "。！？；!?;\n")

    def test_reference_and_index_tail_are_not_retrieval_chunks(self):
        text = (
            "第一节 正文\n" + "有效医学正文。" * 40
            + "\n参考文献\n[1] Example textbook.\n"
            + "中英文名词对照索引\nA anatomy 解剖学\n"
        )

        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第一章 总论",
        )
        combined = "\n".join(content for _, _, content, _ in chunks)

        self.assertIn("有效医学正文", combined)
        self.assertNotIn("Example textbook", combined)
        self.assertNotIn("中英文名词对照索引", combined)

    def test_reference_phrase_in_ordinary_prose_does_not_truncate_chapter(self):
        text = (
            "第一节 正文\n"
            "参考文献显示该机制还与免疫调节有关。\n"
            + "这部分章末正文必须继续保留。" * 20
        )

        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第一章 总论",
        )
        combined = "\n".join(content for _, _, content, _ in chunks)

        self.assertIn("参考文献显示", combined)
        self.assertIn("章末正文必须继续保留", combined)

    def test_short_final_units_are_folded_into_previous_chunk(self):
        text = "第一节 机制\n" + "甲机制维持稳态。" * 31 + "末尾结论。"
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=240,
            overlap=30,
            chapter_title="第一章 总论",
        )

        self.assertGreater(len(chunks), 1)
        self.assertGreaterEqual(len(chunks[-1][2]), 80)
        self.assertLessEqual(max(len(content) for _, _, content, _ in chunks), 300)

    def test_overlap_never_creates_nested_suffix_only_chunks(self):
        text = (
            "第一节 机制\n"
            + "短句甲。短句乙。短句丙。短句丁。短句戊。" * 8
            + ("超长完整语义单元，" * 38) + "结束。"
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=240,
            overlap=55,
            chapter_title="第一章 总论",
        )
        ends = [end for _, end, _, _ in chunks]

        self.assertEqual(len(ends), len(set(ends)))
        self.assertTrue(all(len(content) >= 55 for _, _, content, _ in chunks[:-1]))

    def test_wrapped_numbered_prose_is_not_promoted_to_a_section_title(self):
        text = (
            "第一节 表面解剖\n"
            "1. 眉弓位于眶上缘上方并与额窦位置关系密切，这是一行被 PDF 换行的正文\n"
            "延续说明其临床定位意义。\n"
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第一章 头部",
        )

        self.assertTrue(chunks)
        self.assertTrue(all(len(path) == 2 for _, _, _, path in chunks))

    def test_chinese_enumeration_prose_with_sentence_punctuation_is_not_a_heading(self):
        text = (
            "第一节 抗菌药物\n"
            "第一、二代头孢菌素差异明显。前者对革兰阳性菌作用较强。\n"
            "后续正文继续说明临床选择。\n"
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第十章 抗菌治疗",
        )

        self.assertTrue(chunks)
        self.assertTrue(all("头孢菌素差异" not in " ".join(path) for _, _, _, path in chunks))
        self.assertIn("第一、二代头孢菌素差异明显", "\n".join(item[2] for item in chunks))

    def test_inline_numbered_heading_keeps_body_after_em_space(self):
        text = "第一节 栓塞\n1.\u2002 肺动脉栓塞\u2003 造成肺动脉栓塞的栓子多来自下肢深静脉。\n"
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第三章 局部血液循环障碍",
        )

        self.assertIn("第一节 栓塞", chunks[0][3])
        normalized_content = " ".join(chunks[0][2].split())
        self.assertIn("肺动脉栓塞", normalized_content)
        self.assertIn("造成肺动脉栓塞", chunks[0][2])

    def test_inline_numbered_heading_keeps_body_after_en_space(self):
        text = "第一节 被膜\n1.\u2002 纤维膜\u2002 纤维膜主要由致密结缔组织构成并具有保护作用。\n"
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第三章 器官",
        )

        combined = "\n".join(content for _, _, content, _ in chunks)
        self.assertIn("纤维膜主要由致密结缔组织构成", combined)
        self.assertTrue(any(path[-1].startswith("1. 纤维膜") for _, _, _, path in chunks))
        self.assertTrue(all("主要由" not in " ".join(path) for _, _, _, path in chunks))

    def test_inline_heading_whitespace_normalization_never_drops_source_line(self):
        text = (
            "第一节 栓塞\n"
            "1.\u2002 肺动脉栓塞\u2003 造成  肺动脉栓塞的栓子多来自下肢深静脉。\n"
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第三章 局部血液循环障碍",
        )

        combined = "\n".join(content for _, _, content, _ in chunks)
        self.assertIn("造成  肺动脉栓塞的栓子", combined)
        self.assertTrue(all(text[start:end].strip() for start, end, _, _ in chunks))

    def test_numbered_prose_with_predicate_is_not_promoted_to_path(self):
        text = "第一节 血液\n1. 红细胞的生理特征 红细胞具有可塑变形性并参与气体运输。\n"
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第五章 血液",
        )

        combined = "\n".join(content for _, _, content, _ in chunks)
        self.assertIn("红细胞具有可塑变形性", combined)
        self.assertTrue(all("红细胞具有" not in " ".join(path) for _, _, _, path in chunks))

    def test_parenthetical_inline_subheading_carries_subject_into_following_chunks(self):
        text = (
            "四、胃\n"
            "（1）胃底腺（fundic gland）：又称泌酸腺，胃底腺由主细胞、壁细胞和颈黏液细胞组成。\n"
            + "1）主细胞数量最多并分泌胃蛋白酶原。" * 18
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=30,
            chapter_title="第十四章 消化管",
        )

        gland_chunks = [item for item in chunks if "主细胞" in item[2]]
        self.assertTrue(gland_chunks)
        self.assertTrue(all(any("胃底腺" in label for label in path) for _, _, _, path in gland_chunks))
        self.assertTrue(any("由主细胞、壁细胞和颈黏液细胞组成" in content for _, _, content, _ in chunks))

    def test_arabic_parenthetical_stage_keeps_numeric_parent_topic(self):
        text = (
            "四、肺炎\n"
            "（一）细菌性肺炎\n"
            "1.\u2002 大叶性肺炎（lobar pneumonia）\u2003 是肺泡内的急性纤维蛋白性炎症。\n"
            "【病理变化及临床病理联系】\n"
            "（1）\u2002 充血水肿期：发病第1～2天，肺泡壁毛细血管扩张充血。\n"
            + "该期肺泡腔内可见浆液性渗出物。" * 12
            + "\n（2）\u2002 红色肝样变期：发病第3～4天，肺泡腔内充满红细胞和纤维蛋白。\n"
            + "红色肝样变期的病理变化继续发展。" * 12
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=30,
            chapter_title="第十章 呼吸系统疾病",
        )

        stage_chunks = [item for item in chunks if "充血水肿期" in item[2] or "红色肝样变期" in item[2]]
        self.assertTrue(stage_chunks)
        self.assertTrue(all(
            any("1. 大叶性肺炎" in label for label in path)
            for _, _, _, path in stage_chunks
        ))

    def test_ambiguous_prose_and_broken_compound_titles_stay_out_of_path(self):
        cases = [
            ("了解", "2.\u2002 了解感染病原菌种类与对抗菌药物的敏感性，正确选择抗菌药物\u2003 对于感染性疾病应先留取标本。", "了解感染病原菌", "先留取标本"),
            ("棘突", "2. 棘突spinous process 在后正中线上可摸到大\n部分椎骨的棘突。", "棘突spinous process 在", "部分椎骨"),
            ("熟悉", "3.\u2002 熟悉抗菌药物的药学特征和不良反应，制订合理的治疗方案\u2003 临床医师必须充分了解药效学。", "熟悉抗菌药物", "药效学"),
            ("锻炼", "3.\u2002 早日进行全身和局部功能锻炼，保持局部良好的血液供应\u2003 骨折后常需复位固定。", "早日进行", "复位固定"),
            ("儿童诊断", "（2）\u2002 18 月龄及以下儿童，符合下列1 项者即可诊断感染：①两次核酸检测阳性。", "18 月龄及以下儿童", "核酸检测阳性"),
            ("神经纤维瘤", "（二）\u2002神经纤维瘤 肿瘤呈束状型和网状型两种组织构象，束状型构象中\n瘤细胞平行排列。", "神经纤维瘤 肿瘤呈", "瘤细胞平行排列"),
            ("继发性肺结核", "（二）\u2002继发性肺结核病 发病灶，肺门部见肿大的淋巴结，二\n者之间以淋巴管炎相连。", "继发性肺结核病 发病灶", "淋巴管炎相连"),
            ("GH-IGF", "1.\u2002 生长激素（GH）-\u2002胰岛素样生长因子-1轴 GH促进骨骼生长。", "生长激素（GH）-", "促进骨骼生长"),
            ("压力容积", "2.\u2003 应用心室压力-\u2003容积环评价心功能 通过心导管检查绘制曲线。", "应用心室压力-", "心导管检查"),
            ("2,3-DPG", "3.\u2003 红细胞内2,3-\u2003二磷酸甘油酸的影响 该物质可降低血红蛋白亲和力。", "红细胞内2,3-", "降低血红蛋白"),
            ("下丘脑轴", "1.\u2002 下丘脑-\u2002垂体-\u2002卵巢轴的功能联系 月经周期由三者共同调节。", "下丘脑-", "月经周期"),
            ("兴奋收缩", "2.\u2003 兴奋-\u2003收缩耦联的基本步骤 动作电位沿横管传导。", "兴奋-", "动作电位"),
            ("黑质纹状体", "2.\u2002 黑质-\u2002纹状体投射系统 新纹状体含投射神经元。", "黑质-", "投射神经元"),
            ("电化学", "1.\u2003 电-\u2003化学驱动力及其变化 平衡电位决定驱动力。", "电-", "平衡电位"),
            ("触压感受器", "1.\u2003 触-\u2003压觉感受器 皮肤机械刺激引起触觉。", "触-", "机械刺激"),
            ("触压阈", "2.\u2003 触-\u2003压觉敏感性指标 不同部位的触觉阈不同。", "触-", "触觉阈"),
        ]

        for name, source, forbidden_path_text, expected_evidence in cases:
            with self.subTest(name=name):
                text = "第一节 示例\n" + source + "\n后续证据必须保留。\n"
                chunks = _split_semantic_text_with_offsets(
                    text,
                    chunk_size=180,
                    overlap=30,
                    chapter_title="第一章 示例",
                )
                combined = "\n".join(content for _, _, content, _ in chunks)
                labels = [label for _, _, _, path in chunks for label in path]
                self.assertIn(expected_evidence, combined)
                self.assertFalse(any(forbidden_path_text in label for label in labels), labels)

    def test_textbook_name_inside_a_valid_sentence_is_not_removed_as_a_running_header(self):
        text = (
            "第一节 实验室安全\n"
            "实验室条件应避免人员和环境受到不可接受的损害。医学微生物学\n"
            "领域涉及病原微生物实验室的生物安全。\n"
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=30,
            chapter_title="第三章 实验室安全",
            textbook_title="医学微生物学",
        )
        combined = "\n".join(content for _, _, content, _ in chunks)

        self.assertIn("医学微生物学\n领域涉及", combined)
        self.assertIn("避免人员和环境受到不可接受的损害", combined)
        self.assertIn("领域涉及病原微生物实验室的生物安全", combined)

    def test_parent_level_prose_is_not_misattributed_to_only_child(self):
        text = (
            "第一节 总论\n"
            "一、上位主题\n"
            "这是一段只属于上位主题的总述正文。\n"
            "（一）下位主题\n"
            "下位主题的具体说明。\n"
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=220,
            overlap=20,
            chapter_title="第一章 层级",
        )

        mixed = next(path for _, _, content, path in chunks if "总述正文" in content and "具体说明" in content)
        self.assertEqual(mixed[-1], "一、上位主题")

    def test_short_body_after_heading_is_not_swallowed_into_path(self):
        text = "第一节 概述\n炎症是防御反应\n后续正文说明。\n"
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第四章 炎症",
        )

        combined = "\n".join(content for _, _, content, _ in chunks)
        self.assertIn("炎症是防御反应", combined)
        self.assertTrue(all("炎症是防御反应" not in path for _, _, _, path in chunks))

    def test_ambiguous_numbered_prose_remains_citable_source(self):
        text = "第一节 乳房\n1. 位置 乳房 breast 是皮肤特殊分化的器官，位于胸前区。\n"
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=180,
            overlap=40,
            chapter_title="第三章 胸部",
        )

        combined = "\n".join(content for _, _, content, _ in chunks)
        self.assertIn("乳房 breast 是皮肤特殊分化的器官", combined)
        self.assertTrue(all("乳房 breast 是" not in " ".join(path) for _, _, _, path in chunks))

    def test_short_child_items_are_packed_inside_the_same_hard_section(self):
        text = (
            "第一节 适应\n"
            "一、萎缩\n萎缩是细胞体积缩小。\n"
            "二、肥大\n肥大是细胞体积增大。\n"
            "三、增生\n增生是细胞数目增多。\n"
            "第二节 损伤\n损伤是稳态破坏。\n"
        )
        chunks = _split_semantic_text_with_offsets(
            text,
            chunk_size=220,
            overlap=20,
            chapter_title="第一章 适应与损伤",
        )

        adaptation = [content for _, _, content, path in chunks if "第一节 适应" in path]
        self.assertEqual(len(adaptation), 1)
        self.assertIn("一、萎缩", adaptation[0])
        self.assertIn("三、增生", adaptation[0])
        self.assertTrue(all(not ("增生" in content and "第二节 损伤" in content) for _, _, content, _ in chunks))

    def test_chapter_heading_whitespace_does_not_consume_next_line(self):
        pages = [{
            "page_number": 1,
            "text": "第一章\n炎症反应包括血管反应和细胞反应。\n后续正文。" * 20,
            "printed_page_number": "",
            "extraction_method": "native",
        }]
        chapters = _split_by_headings_with_pages(pages)

        self.assertEqual(chapters[0]["title"], "第一章")
        self.assertIn("炎症反应包括血管反应和细胞反应", chapters[0]["content"])

    def test_partial_fitz_failure_restarts_cleanly_with_pypdf(self):
        class NativePage:
            def __init__(self, fail=False):
                self.fail = fail

            def get_text(self, mode, sort=False):
                if self.fail:
                    raise RuntimeError("native extraction failed")
                return "第一章 基础\n" + "原生正文。" * 30

        class NativeDocument(list):
            closed = False

            def close(self):
                self.closed = True

        class FallbackPage:
            def __init__(self, text):
                self.text = text

            def extract_text(self):
                return self.text

        native_document = NativeDocument([NativePage(), NativePage(fail=True)])
        fake_fitz = types.SimpleNamespace(open=lambda _: native_document)
        fake_pypdf = types.SimpleNamespace(PdfReader=lambda _: types.SimpleNamespace(pages=[
            FallbackPage("第一章 基础\n" + "回退正文。" * 30),
            FallbackPage("第二页正文。" * 30),
        ]))
        with patch.dict(sys.modules, {"fitz": fake_fitz, "pypdf": fake_pypdf}):
            parsed = _parse_pdf("fallback.pdf", "book_fallback")

        self.assertTrue(native_document.closed)
        self.assertEqual(parsed["total_pages"], 2)
        self.assertEqual([page["page_number"] for page in parsed["pages"]], [1, 2])
        self.assertTrue(all(page["extraction_method"] == "pypdf" for page in parsed["pages"]))

    def test_toc_and_repeated_running_headers_do_not_create_fake_chapters(self):
        pages = [
            {"page_number": 1, "text": "目录\n第1章 基础概念\n第2章 进阶内容\n第3章 临床应用", "printed_page_number": "", "extraction_method": "native"},
            {"page_number": 2, "text": "第1章 基础概念\n" + "基础正文。" * 80, "printed_page_number": "", "extraction_method": "native"},
            {"page_number": 3, "text": "第1章 基础概念\n" + "基础延续。" * 80, "printed_page_number": "", "extraction_method": "native"},
            {"page_number": 4, "text": "第2章 进阶内容\n" + "进阶正文。" * 80, "printed_page_number": "", "extraction_method": "native"},
            {"page_number": 5, "text": "第2章 进阶内容\n" + "进阶延续。" * 80, "printed_page_number": "", "extraction_method": "native"},
            {"page_number": 6, "text": "第3章 临床应用\n" + "临床正文。" * 80, "printed_page_number": "", "extraction_method": "native"},
        ]

        chapters = _split_by_headings_with_pages(pages)

        self.assertEqual([chapter["title"] for chapter in chapters], [
            "第1章 基础概念", "第2章 进阶内容", "第3章 临床应用",
        ])
        self.assertEqual((chapters[0]["page_start"], chapters[0]["page_end"]), (2, 3))
        self.assertEqual((chapters[1]["page_start"], chapters[1]["page_end"]), (4, 5))

    def test_two_chapter_toc_is_not_mistaken_for_real_content(self):
        pages = [
            {"page_number": 1, "text": "目录\n第1章 基础概念\n第2章 进阶内容", "printed_page_number": "", "extraction_method": "native"},
            {"page_number": 2, "text": "第1章 基础概念\n" + "第一章真实正文。" * 60, "printed_page_number": "", "extraction_method": "native"},
            {"page_number": 3, "text": "第2章 进阶内容\n" + "第二章真实正文。" * 60, "printed_page_number": "", "extraction_method": "native"},
        ]

        chapters = _split_by_headings_with_pages(pages)

        self.assertEqual([chapter["title"] for chapter in chapters], ["第1章 基础概念", "第2章 进阶内容"])
        self.assertEqual(chapters[0]["page_start"], 2)
        self.assertIn("第一章真实正文", chapters[0]["content"])
        self.assertNotIn("目录", chapters[0]["content"])

    def test_chapter_heading_allows_spacing_and_fullwidth_digits(self):
        pages = [
            {"page_number": 1, "text": "第１章 组织学绪论\n" + "绪论内容。" * 30},
            {"page_number": 2, "text": "第2 章 上皮组织\n" + "上皮组织内容。" * 30},
            {"page_number": 3, "text": "第 3 章 结缔组织\n" + "结缔组织内容。" * 30},
        ]
        chapters = _split_by_headings_with_pages(pages)
        self.assertEqual(len(chapters), 3)
        self.assertEqual([chapter["page_start"] for chapter in chapters], [1, 2, 3])
        self.assertIn("组织学绪论", chapters[0]["title"])
        self.assertIn("上皮组织", chapters[1]["title"])
        self.assertIn("结缔组织", chapters[2]["title"])

    def test_line_initial_chapter_reference_is_not_a_heading(self):
        pages = [
            {"page_number": 1, "text": "第1章 基础\n" + "基础内容。" * 30},
            {"page_number": 2, "text": "第3章）。这里只是正文中的引用。\n" + "延续内容。" * 30},
            {"page_number": 3, "text": "第2 章 进阶\n" + "进阶内容。" * 30},
            {"page_number": 4, "text": "第3章 应用\n" + "应用内容。" * 30},
        ]
        chapters = _split_by_headings_with_pages(pages)
        self.assertEqual([chapter["title"] for chapter in chapters], [
            "第1章 基础", "第2 章 进阶", "第3章 应用",
        ])
        self.assertEqual(chapters[2]["page_start"], 4)


if __name__ == "__main__":
    unittest.main()
