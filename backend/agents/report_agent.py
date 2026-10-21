"""Course-scoped reports derived only from persisted course data."""
from collections import Counter

from backend.database import (
    DEFAULT_COURSE_ID, Chapter, Chunk, Course, IntegrationDecision,
    KnowledgeEdge, KnowledgeNode, SessionLocal, Textbook,
)
from backend.services.retrieval_service import get_index_status


def generate_report(course_id: str = DEFAULT_COURSE_ID) -> dict:
    db = SessionLocal()
    try:
        course = db.get(Course, course_id)
        textbooks = db.query(Textbook).filter(Textbook.course_id == course_id).all()
        book_ids = [book.id for book in textbooks]
        chapters = db.query(Chapter).filter(Chapter.textbook_id.in_(book_ids)).all() if book_ids else []
        chunks = db.query(Chunk).filter(Chunk.textbook_id.in_(book_ids)).all() if book_ids else []
        nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.course_id == course_id, KnowledgeNode.textbook_id.in_(book_ids),
        ).all() if book_ids else []
        node_ids = {node.id for node in nodes}
        edges = db.query(KnowledgeEdge).filter(
            KnowledgeEdge.course_id == course_id,
            KnowledgeEdge.source.in_(node_ids), KnowledgeEdge.target.in_(node_ids),
        ).all() if node_ids else []
        # Legacy decisions have no course_id. Include only decisions whose
        # complete affected-node set is known to belong to this course.
        decisions = [decision for decision in db.query(IntegrationDecision).all()
                     if decision.affected_nodes
                     and set(decision.affected_nodes).issubset(node_ids)
                     and (not decision.result_node or decision.result_node in node_ids)]
        actions = Counter(decision.action for decision in decisions)
        index = get_index_status(course_id)
        return {
            "course_id": course_id, "course_title": course.title if course else "未找到课程",
            "textbooks": {
                "count": len(textbooks), "total_pages": sum(book.total_pages or 0 for book in textbooks),
                "total_chars": sum(book.total_chars or 0 for book in textbooks),
                "list": [{"title": book.title, "filename": book.filename, "format": book.format,
                          "pages": book.total_pages, "chars": book.total_chars, "parse_status": book.parse_status}
                         for book in textbooks],
            },
            "chapters": {"total": len(chapters)},
            "knowledge_graph": {
                "total_nodes": len(nodes), "non_merged_nodes": sum(not node.is_merged for node in nodes),
                "merged_nodes_count": sum(bool(node.is_merged) for node in nodes),
                "total_edges": len(edges), "edge_types": dict(Counter(edge.relation_type for edge in edges)),
                "chapter_topics": sum(node.granularity == "chapter_topic" for node in nodes),
                "section_topics": sum(node.granularity == "section_topic" for node in nodes),
                "core_concepts": sum(node.granularity == "core_concept" for node in nodes),
                "quote_matched_nodes": sum(node.evidence_status == "verified" for node in nodes),
                "teacher_reviewed_edges": sum(edge.review_status == "approved" for edge in edges),
            },
            "decisions": {
                "total": len(decisions), "merge": actions["merge"], "keep": actions["keep"],
                "remove": actions["remove"], "split": actions["split"],
                "teacher_overrides": sum(bool(decision.teacher_override) for decision in decisions),
            },
            "rag": {"total_chunks": len(chunks), "indexed": index["indexed"],
                    "status": index["status"], "method": index["method"]},
        }
    finally:
        db.close()


def _markdown(value) -> str:
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def export_report_markdown(course_id: str = DEFAULT_COURSE_ID) -> str:
    data = generate_report(course_id)
    books, graph, decisions, rag = (data[key] for key in ("textbooks", "knowledge_graph", "decisions", "rag"))
    rows = [
        f"# {_markdown(data['course_title'])} · 课程资料报告", "",
        f"课程编号：{_markdown(course_id)}", "",
        "## 教材与来源", "", "| 指标 | 数值 |", "|---|---:|",
        f"| 教材数量 | {books['count']} |", f"| 教材页数 | {books['total_pages']} |",
        f"| 已解析字符数 | {books['total_chars']} |", f"| 章节数量 | {data['chapters']['total']} |",
        f"| 可检索知识块 | {rag['total_chunks']} |", "",
        "| 教材 | 格式 | 页数 | 解析状态 |", "|---|---|---:|---|",
    ]
    rows.extend(f"| {_markdown(book['title'])} | {_markdown(book['format'])} | {book['pages'] or 0} | {_markdown(book['parse_status'])} |"
                for book in books["list"])
    rows.extend([
        "", "## 知识结构与审核", "",
        f"- 知识点：{graph['total_nodes']}；关系：{graph['total_edges']}。",
        f"- 原文匹配节点：{graph['quote_matched_nodes']}；教师已审核关系：{graph['teacher_reviewed_edges']}。",
        f"- 当前课程可归属的整合决策：{decisions['total']}；教师修改：{decisions['teacher_overrides']}。",
        "- 旧整合决策没有课程编号，仅统计全部关联节点都属于本课程的记录。", "",
        "## 检索状态", "",
        f"- 索引状态：{_markdown(rag['status'])}；索引方法：{_markdown(rag['method'])}。",
        "- 索引状态与来源数量不代表回答正确率；本报告未执行教学语义评测。",
        "- 原文匹配仅说明引文存在，教学结论与关系含义仍需教师核验。", "",
    ])
    return "\n".join(rows)
