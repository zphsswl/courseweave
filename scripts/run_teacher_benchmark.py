"""Run the fixed teacher-question benchmark and export an auditable report."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.benchmark import (  # noqa: E402
    TEACHER_SUITE_PATH,
    evaluate_teacher_questions,
    load_teacher_suite,
)
from backend.database import DEFAULT_COURSE_ID, Chapter, Chunk, SessionLocal, Textbook  # noqa: E402


def _corpus_summary(course_id: str) -> dict:
    db = SessionLocal()
    try:
        textbook_count = db.query(Textbook).filter(Textbook.course_id == course_id).count()
        chunks = (
            db.query(Chunk)
            .join(Textbook, Textbook.id == Chunk.textbook_id)
            .filter(Textbook.course_id == course_id)
            .order_by(Chunk.textbook_id, Chunk.chapter_id, Chunk.chunk_index, Chunk.id)
            .all()
        )
        corpus_digest = hashlib.sha256()
        for chunk in chunks:
            corpus_digest.update((chunk.id or "").encode("utf-8"))
            corpus_digest.update(b"\0")
            corpus_digest.update((chunk.content or "").encode("utf-8"))
            corpus_digest.update(b"\0")
        chapter_count = (
            db.query(Chapter)
            .join(Textbook, Textbook.id == Chapter.textbook_id)
            .filter(Textbook.course_id == course_id)
            .count()
        )
        return {
            "textbook_count": textbook_count,
            "chapter_count": chapter_count,
            "chunk_count": len(chunks),
            "corpus_sha256": corpus_digest.hexdigest(),
        }
    finally:
        db.close()


def _category_summary(details: list[dict]) -> list[dict]:
    groups = defaultdict(lambda: {
        "question_count": 0,
        "answerable_count": 0,
        "retrieval_hits": 0,
        "citation_hits": 0,
        "citation_count": 0,
        "rejection_hits": 0,
        "rejection_count": 0,
    })
    for detail in details:
        group = groups[detail["category"]]
        group["question_count"] += 1
        if detail["answerable"]:
            group["answerable_count"] += 1
            group["retrieval_hits"] += int(detail["retrieval_hit"])
            group["citation_hits"] += detail["citation_hits"]
            group["citation_count"] += detail["citation_count"]
        else:
            group["rejection_count"] += 1
            group["rejection_hits"] += int(detail["rejected"])
    return [{"category": category, **values} for category, values in sorted(groups.items())]


def _dimension_summary(details: list[dict], field: str) -> list[dict]:
    groups = defaultdict(lambda: {
        "question_count": 0,
        "answerable_count": 0,
        "retrieval_hits": 0,
        "rejection_hits": 0,
        "rejection_count": 0,
        "chapter_hits": 0,
        "chapter_count": 0,
    })
    for detail in details:
        group = groups[detail.get(field, "unknown")]
        group["question_count"] += 1
        if detail["answerable"]:
            group["answerable_count"] += 1
            group["retrieval_hits"] += int(detail["retrieval_hit"])
            if detail.get("chapter_hit") is not None:
                group["chapter_count"] += 1
                group["chapter_hits"] += int(detail["chapter_hit"])
        else:
            group["rejection_count"] += 1
            group["rejection_hits"] += int(detail["rejected"])
    return [{field: name, **values} for name, values in sorted(groups.items())]


def _percent(metric: dict) -> str:
    return f'{metric["score"] * 100:.2f}% ({metric["numerator"]}/{metric["denominator"]})'


def _ratio(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}" if denominator else "—"


def _markdown(report: dict) -> str:
    metrics = {item["metric"]: item for item in report["metrics"]}
    failed_retrieval = [item["id"] for item in report["details"] if item.get("retrieval_hit") is False]
    failed_rejection = [item["id"] for item in report["details"] if item.get("rejected") is False]
    group_rows = "\n".join(
        f"| {item['suite_group']} | {item['question_count']} | "
        f"{_ratio(item['retrieval_hits'], item['answerable_count'])} | "
        f"{_ratio(item['rejection_hits'], item['rejection_count'])} |"
        for item in report["groups"]
    )
    type_rows = "\n".join(
        f"| {item['question_type']} | {item['question_count']} | "
        f"{_ratio(item['retrieval_hits'], item['answerable_count'])} |"
        for item in report["question_types"]
    )
    return f"""# CourseWeave RAG 教师问题评测报告

评测版本：`{report['suite']['version']}`

评测日期：{report['run']['date']}

数据范围：{report['corpus']['textbook_count']} 本教材、{report['corpus']['chapter_count']} 章、{report['corpus']['chunk_count']:,} 个可检索 chunk

语料 SHA-256：`{report['corpus']['corpus_sha256']}`

执行耗时：{report['run']['duration_seconds']:.2f} 秒

## 评测集

- 共 {report['suite']['question_count']} 题：{report['suite']['answerable_count']} 道教材内可回答题（其中 {report['suite']['compare_count']} 道跨教材题），另有 {report['suite']['rejection_count']} 道课程外拒答题。
- 章节覆盖集为 {report['suite']['chapter_question_count']} 题，覆盖 {report['suite']['chapter_count']}/{report['corpus']['chapter_count']} 个一级章节，每章固定 2 道可追溯问题。
- 题集文件：`backend/evals/teacher_questions_chapter_v3.json`（由 `scripts/build_chapter_benchmark.py` 生成）
- 题集 SHA-256：`{report['suite']['sha256']}`
- 评测集只保存问题、知识点 rubric 与别名，不包含教材原文。

## 核心结果

| 指标 | 结果 | 口径 |
|---|---:|---|
| 检索召回率@8 | {_percent(metrics['检索召回率'])} | 单概念全部命中、双概念两侧命中、多项知识至少覆盖 60% |
| 引用准确率@3 | {_percent(metrics['引用准确率'])} | 每条引用的正文或章节路径包含预期知识且具有有效物理页码 |
| 跨教材覆盖率@8 | {_percent(metrics['跨教材覆盖率'])} | 对比题至少召回两本教材的相关证据 |
| 无答案拒答率 | {_percent(metrics['无答案拒答率'])} | 课程外问题不返回伪相关证据 |
| 章节题命中率@8 | {_percent(metrics['章节题命中率'])} | 章节题同时命中指定教材、章节与知识点 |
| 章节覆盖率@8 | {_percent(metrics['章节覆盖率'])} | 137 章中至少有一道题成功命中的比例 |

六项指标均值为 {sum(item['score'] for item in report['metrics']) / len(report['metrics']) * 100:.2f} 分。召回率与引用准确率分开统计：一个问题少覆盖一项知识只影响召回，不会把其余正确引用重复判错。

## 分层结果

| 子集 | 题数 | Recall 命中 | 拒答命中 |
|---|---:|---:|---:|
{group_rows}

| 题型 | 题数 | Recall 命中 |
|---|---:|---:|
{type_rows}

## 可复现方法

```powershell
$env:PYTHONPATH = (Get-Location).Path
./.venv/Scripts/python.exe ./scripts/run_teacher_benchmark.py `
  --json-out ./docs/evaluation/teacher-benchmark-v3.json `
  --markdown-out ./docs/evaluation/teacher-benchmark-v3.md
```

本次评测直接调用生产检索函数，未调用付费大模型；因此结果衡量的是切分、范围判断、检索排序、页码追溯和拒答能力，不把语言流畅度混入检索分数。

## 失败观察

- 未达到 Recall@8 覆盖门槛：{', '.join(failed_retrieval) if failed_retrieval else '无'}。
- 未正确拒答：{', '.join(failed_rejection) if failed_rejection else '无'}。
- 引用准确率未达到 100% 的主要原因是：枚举答案往往集中在一个 chunk，Top 3 中的相邻背景段虽与主题相关，但未逐字包含 rubric 知识点；后续应继续优化段落级重排与引用数量自适应。

## 适用边界

这是当前 7 本本地医学教材语料上的固定回归集，不代表所有学科或任意 PDF 的泛化效果。100 道核心题由人工整理，320 道扩展题由可复现脚本从章节元数据和知识节点生成；章节题适合检验覆盖面，但不能替代独立教师盲标。正式产品化仍需多课程数据、双人标注一致性与真实课堂任务完成率。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", default=DEFAULT_COURSE_ID)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()

    suite = load_teacher_suite()
    started = time.perf_counter()
    def progress(completed: int, total: int, _question: dict) -> None:
        if completed == 1 or completed % 25 == 0 or completed == total:
            print(f"[benchmark] {completed}/{total}", file=sys.stderr, flush=True)

    evaluation = evaluate_teacher_questions(args.course_id, progress_callback=progress)
    duration = time.perf_counter() - started
    questions = suite["questions"]
    report = {
        "suite": {
            "version": suite["version"],
            "description": suite["description"],
            "question_count": len(questions),
            "answerable_count": sum(1 for item in questions if item["answerable"]),
            "compare_count": sum(1 for item in questions if item["mode"] == "compare"),
            "rejection_count": sum(1 for item in questions if not item["answerable"]),
            "chapter_question_count": sum(1 for item in questions if item.get("target_chapter_id")),
            "chapter_count": len({item["target_chapter_id"] for item in questions if item.get("target_chapter_id")}),
            "sha256": hashlib.sha256(TEACHER_SUITE_PATH.read_bytes()).hexdigest(),
        },
        "corpus": {"course_id": args.course_id, **_corpus_summary(args.course_id)},
        "run": {"date": date.today().isoformat(), "duration_seconds": round(duration, 2)},
        "metrics": evaluation["metrics"],
        "categories": _category_summary(evaluation["details"]),
        "groups": _dimension_summary(evaluation["details"], "suite_group"),
        "question_types": _dimension_summary(evaluation["details"], "question_type"),
        "details": evaluation["details"],
    }

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(_markdown(report), encoding="utf-8")

    print(json.dumps({
        "suite": report["suite"],
        "corpus": report["corpus"],
        "run": report["run"],
        "metrics": report["metrics"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
