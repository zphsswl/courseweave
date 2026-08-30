"""Course-specific, domain-neutral quality scorecard."""
import json
from pathlib import Path

from fastapi import APIRouter, Query

from backend.database import (
    SessionLocal,
    DEFAULT_COURSE_ID,
    Textbook,
    Chapter,
    Chunk,
    KnowledgeNode,
    KnowledgeEdge,
    RelationEvidence,
    AlignmentCandidate,
)
from backend.services.retrieval_service import retrieve


router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])
_result_cache = {}
STRUCTURAL_RELATIONS = {"contains", "part_of", "example_of"}
TEACHER_SUITE_PATH = Path(__file__).resolve().parents[1] / "evals" / "teacher_questions.json"


def _metric(name: str, numerator: int, denominator: int, detail: str, category: str = "system"):
    score = numerator / denominator if denominator else 0.0
    return {
        "metric": name,
        "score": round(score, 4),
        "description": f"{detail}（{numerator}/{denominator}）" if denominator else f"{detail}（暂无可评估数据）",
        "numerator": numerator,
        "denominator": denominator,
        "category": category,
    }


def load_teacher_suite() -> dict:
    return json.loads(TEACHER_SUITE_PATH.read_text(encoding="utf-8"))


@router.get("/suite")
def get_benchmark_suite():
    suite = load_teacher_suite()
    questions = suite["questions"]
    return {
        "version": suite["version"],
        "description": suite["description"],
        "question_count": len(questions),
        "answerable_count": sum(1 for item in questions if item["answerable"]),
        "compare_count": sum(1 for item in questions if item["mode"] == "compare"),
        "rejection_count": sum(1 for item in questions if not item["answerable"]),
        "questions": [
            {key: item[key] for key in ("id", "category", "question", "mode", "answerable")}
            for item in questions
        ],
    }


@router.get("")
def get_benchmark(course_id: str = Query(DEFAULT_COURSE_ID)):
    return _result_cache.get(course_id, [])


@router.post("/run")
def run_benchmark(payload: dict | None = None):
    course_id = (payload or {}).get("course_id") or DEFAULT_COURSE_ID
    results = _evaluate_course(course_id)
    _result_cache[course_id] = results
    return results


def _evaluate_course(course_id: str):
    teacher_metrics = _evaluate_teacher_questions(course_id)
    db = SessionLocal()
    try:
        book_ids = [row[0] for row in db.query(Textbook.id).filter(Textbook.course_id == course_id).all()]
        chunks = db.query(Chunk).filter(Chunk.textbook_id.in_(book_ids)).all() if book_ids else []
        page_addressable = sum(1 for chunk in chunks if (chunk.page_start or 0) > 0 and (chunk.page_end or 0) >= (chunk.page_start or 0))

        core_nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.course_id == course_id,
            KnowledgeNode.granularity == "core_concept",
        ).all()
        verified_nodes = [node for node in core_nodes if node.evidence_status == "verified" and node.source_paragraph]

        semantic_edges = db.query(KnowledgeEdge).filter(
            KnowledgeEdge.course_id == course_id,
            KnowledgeEdge.relation_type.notin_(STRUCTURAL_RELATIONS),
        ).all()
        edge_ids = [edge.id for edge in semantic_edges]
        verified_edge_ids = {
            row[0]
            for row in db.query(RelationEvidence.edge_id).filter(
                RelationEvidence.edge_id.in_(edge_ids),
                RelationEvidence.quote_verified.is_(True),
            ).distinct().all()
        } if edge_ids else set()

        candidates = db.query(AlignmentCandidate).filter(AlignmentCandidate.course_id == course_id).all()
        reviewed = sum(1 for item in candidates if item.status in {"approved", "rejected"})

        samples = verified_nodes[:5]
        retrieval_hits = 0
        for node in samples:
            retrieved = retrieve(node.name, course_id=course_id, top_k=5)["results"]
            if any(
                item["id"] == node.source_chunk_id or item["textbook_id"] == node.textbook_id
                for item in retrieved
            ):
                retrieval_hits += 1

        confirmed_chapters = db.query(Chapter).join(Textbook, Textbook.id == Chapter.textbook_id).filter(
            Textbook.course_id == course_id,
            Chapter.review_status == "confirmed",
        ).count()
        all_chapters = db.query(Chapter).join(Textbook, Textbook.id == Chapter.textbook_id).filter(
            Textbook.course_id == course_id,
        ).count()

        return teacher_metrics + [
            _metric("章节人工确认率", confirmed_chapters, all_chapters, "已由教师确认的章节结构"),
            _metric("页码可追溯率", page_addressable, len(chunks), "可定位到有效物理页范围的知识块"),
            _metric("核心节点证据覆盖率", len(verified_nodes), len(core_nodes), "带可核验原文的核心概念"),
            _metric("语义关系证据有效率", len(verified_edge_ids), len(semantic_edges), "至少有一条已核验关系证据的语义边"),
            _metric("跨教材候选审核完成率", reviewed, len(candidates), "已经教师通过或驳回的关联候选"),
            _metric("检索来源命中率@5", retrieval_hits, len(samples), "以已验证概念抽样，原来源进入前五的比例"),
        ]
    finally:
        db.close()


def _contains_expected_term(item: dict, expected_terms: list[str]) -> bool:
    content = "".join((item.get("content") or "").lower().split())
    return any("".join(term.lower().split()) in content for term in expected_terms if term)


def _expected_concept_groups(
    expected_terms: list[str] | None = None,
    expected_concepts: list[dict] | None = None,
) -> list[tuple[str, list[str]]]:
    if expected_concepts:
        groups = []
        for concept in expected_concepts:
            canonical = str(concept.get("canonical") or "").strip()
            aliases = [str(value).strip() for value in concept.get("aliases", []) if str(value).strip()]
            if canonical and canonical not in aliases:
                aliases.insert(0, canonical)
            if canonical and aliases:
                groups.append((canonical, aliases))
        return groups
    return [(term, [term]) for term in dict.fromkeys(expected_terms or []) if term]


def _matched_expected_terms(
    items: list[dict],
    expected_terms: list[str] | None = None,
    expected_concepts: list[dict] | None = None,
) -> set[str]:
    """Return distinct rubric concepts covered by an evidence set."""
    normalized_contents = ["".join((item.get("content") or "").lower().split()) for item in items]
    return {
        canonical
        for canonical, aliases in _expected_concept_groups(expected_terms, expected_concepts)
        if any(
            "".join(alias.lower().split()) in content
            for alias in aliases
            for content in normalized_contents
        )
    }


def _required_expected_matches(
    expected_terms: list[str] | None = None,
    expected_concepts: list[dict] | None = None,
) -> int:
    """Require broad coverage for multi-part questions without changing single concepts."""
    term_count = len(_expected_concept_groups(expected_terms, expected_concepts))
    if term_count <= 1:
        return term_count
    # Two-part comparisons need both sides. Longer enumerations accept a
    # teaching-useful majority because page-aware evidence may split one list
    # over neighbouring chunks (for example the four phases of pneumonia).
    if term_count == 2:
        return 2
    return max(2, (term_count * 3 + 4) // 5)  # ceil(60%)


def _has_expected_coverage(
    items: list[dict],
    expected_terms: list[str] | None = None,
    expected_concepts: list[dict] | None = None,
) -> bool:
    required = _required_expected_matches(expected_terms, expected_concepts)
    return required == 0 or len(_matched_expected_terms(items, expected_terms, expected_concepts)) >= required


def _evaluate_teacher_questions(course_id: str, questions: list[dict] | None = None):
    suite = load_teacher_suite()
    questions = questions or suite["questions"]
    retrieval_hits = 0
    answerable_count = 0
    citation_hits = 0
    citation_count = 0
    compare_hits = 0
    compare_count = 0
    rejection_hits = 0
    rejection_count = 0

    for question in questions:
        result = retrieve(
            question["question"],
            course_id=course_id,
            mode=question.get("mode", "all"),
            top_k=8,
        )
        items = result["results"]
        if not question.get("answerable", True):
            rejection_count += 1
            rejection_hits += int(not items)
            continue

        answerable_count += 1
        expected_terms = question.get("expected_terms") or []
        expected_concepts = question.get("expected_concepts") or []
        relevant_items = [
            item for item in items
            if _matched_expected_terms([item], expected_terms, expected_concepts)
        ]
        retrieval_hits += int(_has_expected_coverage(items, expected_terms, expected_concepts))

        citation_items = items[:3]
        citation_set_has_coverage = _has_expected_coverage(citation_items, expected_terms, expected_concepts)
        for item in citation_items:
            citation_count += 1
            citation_hits += int(
                bool(item.get("id"))
                and (item.get("page_start") or 0) > 0
                and citation_set_has_coverage
                and bool(_matched_expected_terms([item], expected_terms, expected_concepts))
            )

        if question.get("mode") == "compare":
            compare_count += 1
            covered_books = {item.get("textbook_id") for item in relevant_items if item.get("textbook_id")}
            compare_hits += int(len(covered_books) >= int(question.get("min_textbooks", 2)))

    return [
        _metric("检索召回率", retrieval_hits, answerable_count, "前 8 条结果覆盖单概念全部、双概念全部或多项知识至少 60%", "teacher_questions"),
        _metric("引用准确率", citation_hits, citation_count, "前 3 条引用整体达到知识覆盖门槛，且单条含预期知识与有效页码", "teacher_questions"),
        _metric("跨教材覆盖率", compare_hits, compare_count, "对比问题召回至少两本教材的相关证据", "teacher_questions"),
        _metric("无答案拒答率", rejection_hits, rejection_count, "超出课程范围的问题未返回伪相关证据", "teacher_questions"),
    ]
