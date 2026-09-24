"""Build the 420-question chapter-coverage benchmark from the local corpus.

The generated suite stores headings, concept labels, identifiers and page ranges,
but never copies textbook paragraphs.  Generation is deterministic so reviewers
can reproduce the exact suite from the same parsed corpus.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import (  # noqa: E402
    DEFAULT_COURSE_ID,
    Chapter,
    Chunk,
    KnowledgeNode,
    SessionLocal,
    Textbook,
)


CORE_SUITE_PATH = ROOT / "backend" / "evals" / "teacher_questions.json"
DEFAULT_OUTPUT = ROOT / "backend" / "evals" / "teacher_questions_chapter_v3.json"
GENERIC_LABELS = {
    "概述", "总论", "绪论", "本章小结", "小结", "思考题", "复习题", "参考文献",
    "生物学性状", "致病性", "致病性与免疫性", "致病性和免疫性", "防治原则",
    "微生物学检查", "微生物学检查法", "临床表现", "诊断", "治疗", "分类",
    "感染与免疫", "病原学", "发病机制与病理", "病因和发病机制", "病因",
    "形态与结构", "表面解剖", "细胞", "病毒的感染与复制", "基本概念和组成",
}


CROSS_CASES = [
    ("炎症反应", "炎症", ["病理学", "病理生理学"]),
    ("缺氧与氧运输", "缺氧", ["生理学", "病理生理学"]),
    ("体液平衡与水肿", "水肿", ["病理学", "病理生理学"]),
    ("血栓形成与凝血平衡", "血栓", ["病理学", "病理生理学"]),
    ("休克时循环功能变化", "休克", ["生理学", "病理生理学"]),
    ("发热与体温调节", "发热", ["生理学", "病理生理学"]),
    ("酸碱平衡与酸碱紊乱", "酸碱", ["生理学", "病理生理学"]),
    ("心脏泵血与心功能不全", "心功能", ["生理学", "病理生理学"]),
    ("肺通气与肺功能不全", "肺功能", ["生理学", "病理生理学"]),
    ("尿生成与肾功能不全", "肾功能", ["生理学", "病理生理学"]),
    ("肝脏结构与肝功能不全", "肝", ["组织学与胚胎学", "病理生理学"]),
    ("细胞死亡与组织损伤", "细胞死亡", ["病理学", "病理生理学"]),
    ("组织再生与损伤修复", "再生", ["组织学与胚胎学", "病理学"]),
    ("免疫防御与免疫性损伤", "免疫", ["医学微生物学", "病理学"]),
    ("细菌致病与细菌性疾病", "细菌", ["医学微生物学", "传染病学"]),
    ("病毒感染与病毒性疾病", "病毒", ["医学微生物学", "传染病学"]),
    ("结核分枝杆菌与结核病", "结核", ["医学微生物学", "传染病学"]),
    ("肝炎病毒与病毒性肝炎", "肝炎", ["医学微生物学", "传染病学"]),
    ("螺旋体与螺旋体病", "螺旋体", ["医学微生物学", "传染病学"]),
    ("真菌致病与深部真菌病", "真菌", ["医学微生物学", "传染病学"]),
    ("感染过程与传染病流行", "感染", ["医学微生物学", "传染病学"]),
    ("血液组成与血液循环", "血液", ["组织学与胚胎学", "生理学"]),
    ("呼吸系统结构与呼吸功能", "呼吸", ["组织学与胚胎学", "生理学"]),
    ("泌尿系统结构与尿生成", "泌尿", ["组织学与胚胎学", "生理学"]),
    ("生殖系统结构与生殖功能", "生殖", ["组织学与胚胎学", "生理学"]),
    ("胚胎发育与先天畸形", "发育", ["组织学与胚胎学", "病理学"]),
]


REJECTION_CASES = [
    "如何证明黎曼猜想？", "区块链共识算法如何容错？", "明代海禁政策经历了哪些变化？",
    "怎样设计一台量子计算机？", "Transformer 的位置编码有哪些实现？", "火星土壤适合种植什么作物？",
    "怎样计算桥梁抗震荷载？", "文艺复兴油画如何使用明暗法？", "宏观经济中的菲利普斯曲线是什么？",
    "如何编写 Rust 异步运行时？", "解释航空发动机涡扇比的设计取舍。", "什么是椭圆曲线数字签名？",
    "古典音乐中的奏鸣曲式如何分析？", "太阳耀斑如何影响地球磁层？", "怎样训练自动驾驶感知模型？",
    "欧盟数字市场法有哪些核心义务？", "如何估算商业卫星的轨道衰减？", "唐诗格律中的拗救规则是什么？",
    "数据库分布式事务如何保证一致性？", "芯片光刻中的数值孔径有什么作用？",
]


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _clean_label(value: str) -> str:
    value = re.sub(r"\([^)]*[A-Za-z][^)]*\)", "", value or "")
    value = re.sub(r"（[^）]*[A-Za-z][^）]*）", "", value)
    value = re.sub(r"^(?:第[一二三四五六七八九十百0-9]+(?:章|节)\s*[|｜]?\s*)", "", value)
    value = re.sub(r"^[一二三四五六七八九十]+、\s*", "", value)
    value = re.sub(r"^[（(][一二三四五六七八九十0-9]+[）)]\s*", "", value)
    value = re.sub(r"^[0-9]+[.、]\s*", "", value)
    return re.sub(r"\s+", "", value).strip("|｜：:。【】[]")


def _is_usable_label(value: str, chapter_title: str) -> bool:
    compact = _compact(value)
    return (
        2 <= len(compact) <= 32
        and compact != _compact(_clean_label(chapter_title))
        and value not in GENERIC_LABELS
        and not re.search(r"[。；;]{1}", value)
        and not re.match(r"^(图|表)\s*\d", value)
    )


def _question_type(label: str, chapter_title: str) -> str:
    text = f"{label}{chapter_title}"
    rules = [
        ("structure", r"结构|形态|境界|组成|分支|解剖|组织"),
        ("mechanism", r"机制|调节|病因|致病|损伤|紊乱|耐药"),
        ("process", r"过程|发生|发育|周期|阶段|循环|代谢"),
        ("classification", r"分类|分型|类型|种类"),
        ("function", r"功能|作用|意义|任务"),
        ("diagnosis", r"诊断|检查|染色|技术|实验|研究方法"),
        ("prevention", r"防治|预防|治疗|消毒|灭菌"),
        ("clinical", r"疾病|病$|炎|癌|肿瘤|休克|发热|缺氧"),
    ]
    return next((kind for kind, pattern in rules if re.search(pattern, text)), "definition")


def _question_text(book: str, chapter: str, label: str, kind: str, variant: int) -> str:
    prompts = {
        "structure": "“{label}”的主要结构和组成是什么",
        "mechanism": "“{label}”的发生机制或调节链路是什么",
        "process": "“{label}”经历哪些关键过程或阶段",
        "classification": "“{label}”可分为哪些类型",
        "function": "“{label}”的主要功能和作用是什么",
        "diagnosis": "“{label}”的原理、步骤或判定要点是什么",
        "prevention": "“{label}”的防治原则和关键措施是什么",
        "clinical": "“{label}”的核心表现和鉴别要点是什么",
        "definition": "什么是“{label}”",
    }
    if variant == 0:
        return f"{prompts[kind].format(label=label)}？"
    return f"请概括“{label}”的核心要点，并给出教材页码依据。"


def _chapter_candidates(db, chapter: Chapter) -> list[dict]:
    chunks = db.query(Chunk).filter(Chunk.chapter_id == chapter.id).order_by(Chunk.chunk_index).all()
    chunk_by_id = {item.id: item for item in chunks}
    candidates: list[dict] = []
    seen: set[str] = set()

    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.textbook_id == chapter.textbook_id,
        KnowledgeNode.chapter_title == chapter.title,
    ).order_by(KnowledgeNode.quality_score.desc(), KnowledgeNode.page_start, KnowledgeNode.name).all()
    def add_node(node: KnowledgeNode) -> None:
        label = _clean_label(node.name)
        chunk = chunk_by_id.get(node.source_chunk_id)
        if not chunk or not _is_usable_label(label, chapter.title):
            return
        key = _compact(label)
        searchable = _compact((chunk.content or "") + "".join(chunk.section_path or []))
        if key in seen or key not in searchable:
            return
        seen.add(key)
        candidates.append({"label": label, "chunk": chunk})

    # Prefer section-level concepts: they are more representative of a chapter
    # than short, repeated terms such as “传染” or an isolated drug trade name.
    for node in nodes:
        if node.granularity == "section_topic":
            add_node(node)

    for chunk in chunks:
        for raw_label in reversed(chunk.section_path or []):
            label = _clean_label(raw_label)
            key = _compact(label)
            if key in seen or not _is_usable_label(label, chapter.title):
                continue
            if key not in _compact((chunk.content or "") + raw_label):
                continue
            seen.add(key)
            candidates.append({"label": label, "chunk": chunk})

    for node in nodes:
        if node.granularity not in {"section_topic", "chapter_topic"}:
            add_node(node)

    if len(candidates) < 2:
        chapter_label = _clean_label(chapter.title)
        for chunk in chunks:
            words = re.findall(r"[\u4e00-\u9fff]{2,10}", chunk.content or "")
            for label in words:
                key = _compact(label)
                if key in seen or label in {"本章", "教材", "学习", "内容"}:
                    continue
                seen.add(key)
                candidates.append({"label": label, "chunk": chunk})
                if len(candidates) >= 2:
                    break
            if len(candidates) >= 2:
                break
        if not candidates and chunks:
            candidates.append({"label": chapter_label, "chunk": chunks[0]})
    return candidates[:2]


def build_suite(course_id: str) -> dict:
    core = json.loads(CORE_SUITE_PATH.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        books = db.query(Textbook).filter(Textbook.course_id == course_id).order_by(Textbook.title).all()
        book_by_title = {item.title: item for item in books}
        chapters = (
            db.query(Chapter)
            .join(Textbook, Textbook.id == Chapter.textbook_id)
            .filter(Textbook.course_id == course_id)
            .order_by(Textbook.title, Chapter.order_index, Chapter.id)
            .all()
        )
        chapter_questions = []
        type_counts = defaultdict(int)
        for index, chapter in enumerate(chapters, start=1):
            book = next(item for item in books if item.id == chapter.textbook_id)
            candidates = _chapter_candidates(db, chapter)
            if len(candidates) < 2:
                raise RuntimeError(f"章节无法生成两道可核验题：{book.title} / {chapter.title}")
            for variant, candidate in enumerate(candidates):
                label = candidate["label"]
                chunk = candidate["chunk"]
                kind = _question_type(label, chapter.title)
                type_counts[kind] += 1
                chapter_questions.append({
                    "id": f"C{index:03d}{'A' if variant == 0 else 'B'}",
                    "suite_group": "chapter_coverage",
                    "category": book.title,
                    "question_type": kind,
                    "question": _question_text(book.title, chapter.title, label, kind, variant),
                    "mode": "all",
                    "answerable": True,
                    "expected_terms": [label],
                    "textbook_ids": [book.id],
                    "target_textbook_id": book.id,
                    "target_chapter_id": chapter.id,
                    "target_chapter_title": chapter.title,
                    "target_page_start": chunk.page_start,
                    "target_page_end": chunk.page_end,
                })

        if len(chapters) != 137 or len(chapter_questions) != 274:
            raise RuntimeError(f"预期 137 章 / 274 题，实际 {len(chapters)} 章 / {len(chapter_questions)} 题")

        core_questions = []
        for item in core["questions"]:
            copied = dict(item)
            copied.setdefault("suite_group", "core_manual")
            copied.setdefault("question_type", "comparison" if copied["mode"] == "compare" else ("rejection" if not copied["answerable"] else "knowledge"))
            core_questions.append(copied)

        cross_questions = []
        for index, (_theme, term, titles) in enumerate(CROSS_CASES, start=1):
            missing = [title for title in titles if title not in book_by_title]
            if missing:
                raise RuntimeError(f"跨教材题缺少教材：{missing}")
            cross_questions.append({
                "id": f"X{index:03d}",
                "suite_group": "cross_textbook_extension",
                "category": "跨教材",
                "question_type": "comparison",
                "question": f"《{'》与《'.join(titles)}》中的“{term}”知识有什么联系？",
                "mode": "compare",
                "answerable": True,
                "expected_terms": [term],
                "textbook_ids": [book_by_title[title].id for title in titles],
                "min_textbooks": 2,
            })

        rejection_questions = [{
            "id": f"N{index:03d}",
            "suite_group": "rejection_extension",
            "category": "拒答",
            "question_type": "rejection",
            "question": question,
            "mode": "all",
            "answerable": False,
            "expected_terms": [],
        } for index, question in enumerate(REJECTION_CASES, start=1)]

        questions = core_questions + chapter_questions + cross_questions + rejection_questions
        if len(questions) != 420:
            raise RuntimeError(f"预期 420 题，实际 {len(questions)} 题")
        return {
            "version": "medical-teacher-v3",
            "description": "420 道医学教材 RAG 固定评测题：保留 100 道人工核心题，新增覆盖全部 137 章的 274 道章节题、26 道跨教材题和 20 道域外拒答题；不包含教材原文。",
            "generation": {
                "course_id": course_id,
                "chapter_count": len(chapters),
                "questions_per_chapter": 2,
                "chapter_question_count": len(chapter_questions),
                "core_question_count": len(core_questions),
                "cross_extension_count": len(cross_questions),
                "rejection_extension_count": len(rejection_questions),
                "question_type_counts": dict(sorted(type_counts.items())),
            },
            "questions": questions,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", default=DEFAULT_COURSE_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    suite = build_suite(args.course_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "version": suite["version"],
        "question_count": len(suite["questions"]),
        "generation": suite["generation"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
