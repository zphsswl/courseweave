import os
import unittest
from unittest.mock import patch


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.database import (  # noqa: E402
    init_db,
    SessionLocal,
    DEFAULT_COURSE_ID,
    Course,
    Textbook,
    Chapter,
    Chunk,
    RagIndexState,
)
from backend.services.retrieval_service import (  # noqa: E402
    _content_signature,
    _prepare_query,
    get_index_status,
    invalidate_course_cache,
    retrieve,
)


class RetrievalServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(RagIndexState).delete()
            db.query(Chunk).delete()
            db.query(Chapter).delete()
            db.query(Textbook).delete()
            db.query(Course).filter(Course.id != DEFAULT_COURSE_ID).delete()
            db.commit()
            db.add(Course(id="course_other", owner_id="demo_user", title="其他课程"))
            books = [
                Textbook(id="rag_book_a", course_id=DEFAULT_COURSE_ID, filename="a.txt", title="生理学", format="txt"),
                Textbook(id="rag_book_b", course_id=DEFAULT_COURSE_ID, filename="b.txt", title="病理生理学", format="txt"),
                Textbook(id="rag_book_other", course_id="course_other", filename="c.txt", title="其他课程教材", format="txt"),
            ]
            db.add_all(books)
            db.flush()
            for book in books:
                db.add(Chapter(id=f"chapter_{book.id}", textbook_id=book.id, title="第一章"))
            db.flush()
            contents = [
                ("a1", "rag_book_a", "叶绿体吸收光能并驱动后续反应。"),
                ("b1", "rag_book_b", "叶绿体吸收光能是能量转换的起点。"),
                ("a2", "rag_book_a", "根系从土壤中吸收水和无机盐。"),
                ("b2", "rag_book_b", "细胞膜具有选择透过性。"),
                ("b3", "rag_book_b", "遗传信息储存在核酸序列中。"),
                ("a3", "rag_book_a", "Grant anatomy for students. Lippincott Williams and Wilkins."),
                ("o1", "rag_book_other", "叶绿体吸收光能，但这属于另一门课程。"),
            ]
            title_map = {book.id: book.title for book in books}
            for index, (chunk_id, book_id, content) in enumerate(contents):
                db.add(Chunk(
                    id=chunk_id,
                    textbook_id=book_id,
                    chapter_id=f"chapter_{book_id}",
                    textbook_title=title_map[book_id],
                    chapter_title="第一章",
                    page_start=index + 1,
                    page_end=index + 1,
                    content=content,
                    content_hash=chunk_id,
                    chunk_index=index,
                ))
            db.commit()
        finally:
            db.close()

    def test_index_status_is_not_ready_before_build(self):
        status = get_index_status(DEFAULT_COURSE_ID)
        self.assertFalse(status["indexed"])
        self.assertEqual(status["status"], "not_built")

    def test_content_signature_changes_when_retrieval_title_changes(self):
        db = SessionLocal()
        try:
            chunk = db.get(Chunk, "a1")
            before = _content_signature([chunk])
            chunk.textbook_title = "重命名后的生理学"
            after = _content_signature([chunk])
        finally:
            db.close()

        self.assertNotEqual(before, after)

    def test_stage_query_splits_endpoint_topics_and_suppresses_type_intent(self):
        features = _prepare_query("从受精到胚泡形成经历哪些阶段？")
        self.assertIn("受精", features["topics"])
        self.assertIn("胚泡", features["topics"])
        self.assertIn("分期", features["intent_terms"])
        self.assertNotIn("类型", features["intent_terms"])

    def test_retrieval_is_course_scoped(self):
        result = retrieve("叶绿体吸收光能", course_id=DEFAULT_COURSE_ID, top_k=5)
        self.assertTrue(result["results"])
        self.assertNotIn("rag_book_other", {item["textbook_id"] for item in result["results"]})
        self.assertEqual(result["trace"]["course_id"], DEFAULT_COURSE_ID)

    def test_compare_mode_keeps_evidence_from_both_textbooks(self):
        result = retrieve(
            "叶绿体吸收光能",
            course_id=DEFAULT_COURSE_ID,
            textbook_ids=["rag_book_a", "rag_book_b"],
            mode="compare",
            top_k=4,
        )
        books = {item["textbook_id"] for item in result["results"]}
        self.assertEqual(books, {"rag_book_a", "rag_book_b"})

    def test_compare_question_uses_named_textbooks_and_medical_anchor(self):
        result = retrieve(
            "生理学的叶绿体吸收光能与病理生理学如何衔接？",
            course_id=DEFAULT_COURSE_ID,
            mode="compare",
            top_k=4,
        )
        self.assertEqual(result["trace"]["requested_textbook_ids"], ["rag_book_b", "rag_book_a"])
        self.assertEqual(
            {item["textbook_id"] for item in result["results"][:2]},
            {"rag_book_a", "rag_book_b"},
        )
        self.assertTrue(all("叶绿体吸收光能" in item["content"] for item in result["results"][:2]))

    def test_compare_question_recovers_a_named_book_missing_from_global_top_sixty(self):
        db = SessionLocal()
        try:
            for index in range(70):
                db.add(Chunk(
                    id=f"dominant_{index}",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="第一章",
                    page_start=index + 30,
                    page_end=index + 30,
                    content=f"叶绿体吸收光能的病理变化资料 {index}。",
                    section_path=["第一章", "叶绿体吸收光能"],
                    content_hash=f"dominant_{index}",
                    chunk_index=index + 30,
                ))
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve(
            "生理学与病理生理学如何比较叶绿体吸收光能？",
            course_id=DEFAULT_COURSE_ID,
            mode="compare",
            top_k=4,
        )

        self.assertEqual(
            {item["textbook_id"] for item in result["results"][:2]},
            {"rag_book_a", "rag_book_b"},
        )

    def test_out_of_domain_english_question_is_not_matched_by_bibliography_stopwords(self):
        result = retrieve(
            "How does a compiler perform register allocation for SSA form?",
            course_id=DEFAULT_COURSE_ID,
            top_k=5,
        )
        self.assertEqual(result["results"], [])

    def test_out_of_domain_chinese_question_requires_a_specific_anchor(self):
        result = retrieve(
            "如何用细胞自动机生成迷宫游戏？",
            course_id=DEFAULT_COURSE_ID,
            top_k=5,
        )
        self.assertEqual(result["results"], [])

    def test_chinese_out_of_domain_query_cannot_mix_unrelated_course_terms(self):
        result = retrieve(
            "神经网络如何进行图像分类？",
            course_id=DEFAULT_COURSE_ID,
            top_k=5,
        )
        self.assertEqual(result["results"], [])
        self.assertEqual(result["trace"]["reason"], "unsupported_query_topics")

    def test_stale_vector_index_is_not_used(self):
        db = SessionLocal()
        try:
            db.add(RagIndexState(
                course_id=DEFAULT_COURSE_ID,
                status="ready",
                embedding_available=True,
                content_signature="stale-signature",
            ))
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        with patch("backend.services.retrieval_service.embed_text") as embed_mock, patch(
            "backend.services.retrieval_service.search_index"
        ) as search_mock:
            result = retrieve("叶绿体吸收光能", course_id=DEFAULT_COURSE_ID, top_k=3)

        embed_mock.assert_not_called()
        search_mock.assert_not_called()
        self.assertFalse(result["trace"]["vector_used"])

    def test_partial_textbook_scope_uses_course_signature_for_vector_freshness(self):
        db = SessionLocal()
        try:
            course_chunks = db.query(Chunk).join(Textbook, Textbook.id == Chunk.textbook_id).filter(
                Textbook.course_id == DEFAULT_COURSE_ID,
            ).order_by(Chunk.textbook_id, Chunk.chapter_id, Chunk.chunk_index, Chunk.id).all()
            db.add(RagIndexState(
                course_id=DEFAULT_COURSE_ID,
                status="ready",
                embedding_available=True,
                content_signature=_content_signature(course_chunks),
            ))
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        with patch("backend.services.retrieval_service.embed_text", return_value=[0.1, 0.2]), patch(
            "backend.services.retrieval_service.search_index",
            return_value=[{"id": "a1", "distance": 0.1}],
        ):
            result = retrieve(
                "叶绿体吸收光能",
                course_id=DEFAULT_COURSE_ID,
                textbook_ids=["rag_book_a"],
                top_k=3,
            )

        self.assertTrue(result["trace"]["vector_used"])
        self.assertIn("vector", result["trace"]["retrievers"])

    def test_zero_score_structural_decoys_do_not_exhaust_candidate_limit(self):
        db = SessionLocal()
        try:
            for index in range(70):
                db.add(Chunk(
                    id=f"intent_decoy_{index}",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="第一章",
                    page_start=index + 100,
                    page_end=index + 100,
                    content="完全无关的占位资料。",
                    section_path=["第一章", "类型 分类 分期 机制 结构"],
                    content_hash=f"intent_decoy_{index}",
                    chunk_index=index + 100,
                ))
            db.add(Chunk(
                id="late_positive",
                textbook_id="rag_book_a",
                chapter_id="chapter_rag_book_a",
                textbook_title="生理学",
                chapter_title="第二章",
                page_start=999,
                page_end=999,
                content="肾小球滤过率由有效滤过压决定。",
                section_path=["第二章", "肾功能"],
                content_hash="late_positive",
                chunk_index=999,
            ))
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve(
            "肾小球滤过率的基本机制是什么？",
            course_id=DEFAULT_COURSE_ID,
            top_k=5,
        )

        self.assertIn("late_positive", {item["id"] for item in result["results"]})

    def test_topic_overview_beats_a_generic_intent_match(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="adaptation_overview",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="细胞和组织的适应与损伤",
                    page_start=201,
                    page_end=201,
                    content="适应包括萎缩、肥大、增生和化生四种基本类型。",
                    section_path=["细胞和组织的适应与损伤", "适应"],
                    content_hash="adaptation_overview",
                    chunk_index=201,
                ),
                Chunk(
                    id="adaptation_decoy",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="细胞和组织的适应与损伤",
                    page_start=202,
                    page_end=202,
                    content="细胞可逆性损伤的形态变化表现为变性，并可按结构分类。",
                    section_path=["细胞和组织的适应与损伤", "细胞可逆性损伤"],
                    content_hash="adaptation_decoy",
                    chunk_index=202,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("细胞适应包括哪些基本类型？", course_id=DEFAULT_COURSE_ID, top_k=1)

        self.assertEqual(result["results"][0]["id"], "adaptation_overview")

    def test_stage_intent_prefers_the_matching_section(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="shock_stages",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="第十三章 休克",
                    page_start=210,
                    page_end=210,
                    content="休克依次经历缺血缺氧期、淤血缺氧期和衰竭期。",
                    section_path=["第十三章 休克", "分期及发生发展机制"],
                    content_hash="shock_stages",
                    chunk_index=210,
                ),
                Chunk(
                    id="shock_decoy",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="第十三章 休克",
                    page_start=211,
                    page_end=211,
                    content="常见休克包括脓毒症休克和心源性休克，各有不同特点。",
                    section_path=["第十三章 休克", "几种常见休克的特点"],
                    content_hash="shock_decoy",
                    chunk_index=211,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("休克的发生发展可分为哪些阶段？", course_id=DEFAULT_COURSE_ID, top_k=1)

        self.assertEqual(result["results"][0]["id"], "shock_stages")

    def test_explicit_stage_evidence_beats_a_high_frequency_disease_overview(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="pneumonia_stages",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="呼吸系统疾病",
                    page_start=220,
                    page_end=221,
                    content=(
                        "大叶性肺炎的演变分为以下四期。\n"
                        "（1）充血水肿期：肺泡腔出现浆液。\n"
                        "（2）红色肝样变期：肺泡腔出现纤维蛋白。"
                    ),
                    section_path=["呼吸系统疾病", "肺炎", "病理变化"],
                    content_hash="pneumonia_stages",
                    chunk_index=220,
                ),
                Chunk(
                    id="pneumonia_overview_noise",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="呼吸系统疾病",
                    page_start=222,
                    page_end=222,
                    content="大叶性肺炎是肺炎的一种。大叶性肺炎可出现并发症，大叶性肺炎需要治疗。",
                    section_path=["呼吸系统疾病", "肺炎", "概述"],
                    content_hash="pneumonia_overview_noise",
                    chunk_index=222,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("大叶性肺炎各期如何演变？", course_id=DEFAULT_COURSE_ID, top_k=1)

        self.assertEqual(result["results"][0]["id"], "pneumonia_stages")

    def test_stage_continuation_inherits_subject_only_from_the_same_section(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="pneumonia_subject",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="呼吸系统疾病",
                    page_start=223,
                    page_end=223,
                    content="大叶性肺炎的病理变化可分为四期。（1）充血水肿期：肺泡充血。",
                    section_path=["呼吸系统疾病", "大叶性肺炎", "病理变化"],
                    content_hash="pneumonia_subject",
                    chunk_index=223,
                ),
                Chunk(
                    id="pneumonia_red_stage_continuation",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="呼吸系统疾病",
                    page_start=224,
                    page_end=224,
                    content="（2）红色肝样变期：肺泡腔内充满纤维蛋白和大量红细胞。",
                    section_path=["呼吸系统疾病", "大叶性肺炎", "病理变化"],
                    content_hash="pneumonia_red_stage_continuation",
                    chunk_index=224,
                ),
                Chunk(
                    id="unrelated_stage_continuation",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="呼吸系统疾病",
                    page_start=225,
                    page_end=225,
                    content="（2）症状期：其他疾病进入症状期。",
                    section_path=["呼吸系统疾病", "其他疾病", "病理变化"],
                    content_hash="unrelated_stage_continuation",
                    chunk_index=225,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("大叶性肺炎各期的病理变化如何演变？", course_id=DEFAULT_COURSE_ID, top_k=3)

        result_ids = [item["id"] for item in result["results"]]
        self.assertIn("pneumonia_red_stage_continuation", result_ids)
        self.assertNotIn("unrelated_stage_continuation", result_ids)

    def test_primary_gland_context_beats_host_cell_substring_noise(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="fundic_gland_cells",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="消化管",
                    page_start=230,
                    page_end=230,
                    content="主细胞、壁细胞、颈黏液细胞、干细胞和内分泌细胞组成胃底腺。",
                    section_path=["消化管", "胃", "胃底腺"],
                    content_hash="fundic_gland_cells",
                    chunk_index=230,
                ),
                Chunk(
                    id="host_cell_noise",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="病毒的基本性状",
                    page_start=231,
                    page_end=231,
                    content="病毒蛋白在宿主细胞中表达，包括结构蛋白和非结构蛋白。",
                    section_path=["病毒的基本性状", "病毒的化学组成"],
                    content_hash="host_cell_noise",
                    chunk_index=231,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("胃底腺主要包含哪些细胞？", course_id=DEFAULT_COURSE_ID, top_k=3)

        self.assertEqual(result["results"][0]["id"], "fundic_gland_cells")
        self.assertNotIn("host_cell_noise", {item["id"] for item in result["results"]})

    def test_basic_pathology_overview_beats_deep_organ_complications(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="atherosclerosis_overview",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="心血管系统疾病",
                    page_start=240,
                    page_end=240,
                    content="基本病理变化包括脂纹、纤维斑块和粥样斑块。",
                    section_path=["心血管系统疾病", "动脉粥样硬化"],
                    content_hash="atherosclerosis_overview",
                    chunk_index=240,
                ),
                Chunk(
                    id="coronary_complication_noise",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="心血管系统疾病",
                    page_start=241,
                    page_end=241,
                    content="冠状动脉粥样硬化可造成心肌缺血。动脉粥样硬化需要长期治疗。",
                    section_path=[
                        "心血管系统疾病", "动脉粥样硬化", "病理变化",
                        "主要动脉的病理变化", "冠状动脉粥样硬化性心脏病",
                    ],
                    content_hash="coronary_complication_noise",
                    chunk_index=241,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("动脉粥样硬化的基本病理变化是什么？", course_id=DEFAULT_COURSE_ID, top_k=1)

        self.assertEqual(result["results"][0]["id"], "atherosclerosis_overview")

    def test_subject_chapter_overview_beats_same_words_in_a_tumour_section(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="epithelium_overview",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="上皮组织",
                    page_start=250,
                    page_end=250,
                    content="上皮组织的共同结构特点如下：细胞排列紧密，具有明显极性，基底面附着于基膜。",
                    section_path=["上皮组织"],
                    content_hash="epithelium_overview",
                    chunk_index=250,
                ),
                Chunk(
                    id="epithelial_tumour_noise",
                    textbook_id="rag_book_b",
                    chapter_id="chapter_rag_book_b",
                    textbook_title="病理生理学",
                    chapter_title="肿瘤",
                    page_start=251,
                    page_end=251,
                    content="上皮组织肿瘤很常见，上皮组织恶性肿瘤称为癌。",
                    section_path=["肿瘤", "常见肿瘤举例", "上皮组织肿瘤"],
                    content_hash="epithelial_tumour_noise",
                    chunk_index=251,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("上皮组织有哪些共同结构特点？", course_id=DEFAULT_COURSE_ID, top_k=1)

        self.assertEqual(result["results"][0]["id"], "epithelium_overview")

    def test_section_path_participates_in_retrieval_and_is_returned(self):
        db = SessionLocal()
        try:
            db.add_all([
                Chunk(
                    id="gastric_target",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="第一章",
                    page_start=20,
                    page_end=20,
                    content="壁细胞、主细胞和颈黏液细胞共同组成此腺体。",
                    section_path=["第一章", "胃底腺"],
                    content_hash="gastric_target",
                    chunk_index=20,
                ),
                Chunk(
                    id="gastric_noise",
                    textbook_id="rag_book_a",
                    chapter_id="chapter_rag_book_a",
                    textbook_title="生理学",
                    chapter_title="第一章",
                    page_start=21,
                    page_end=21,
                    content="胃底腺一词出现在目录标题中，但这里没有介绍其组成。",
                    section_path=["第一章", "目录说明"],
                    content_hash="gastric_noise",
                    chunk_index=21,
                ),
            ])
            db.commit()
        finally:
            db.close()
        invalidate_course_cache(DEFAULT_COURSE_ID)

        result = retrieve("胃底腺由哪些细胞组成？", course_id=DEFAULT_COURSE_ID, top_k=1)

        self.assertEqual(result["results"][0]["id"], "gastric_target")
        self.assertEqual(result["results"][0]["section_path"], ["第一章", "胃底腺"])


if __name__ == "__main__":
    unittest.main()
