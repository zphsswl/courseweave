"""Idempotent, copyright-safe sample course for a public portfolio deployment."""
import hashlib

from backend.database import (
    SessionLocal,
    Course,
    Textbook,
    TextbookPage,
    Chapter,
    Chunk,
    CanonicalConcept,
    KnowledgeNode,
    KnowledgeEdge,
    RelationEvidence,
    AlignmentCandidate,
    RagIndexState,
    Job,
)


DEMO_COURSE_ID = "course_portfolio_demo"
DEMO_AGENT_JOB_ID = "job_portfolio_agent_demo"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _demo_agent_result() -> dict:
    plan = [
        ("inspect", "理解任务与检查课程", "inspect_course", "已确认 2 本教材、章节与知识树均可复用"),
        ("prepare", "准备教材证据", "parse_textbook", "教材已解析，跳过重复处理"),
        ("graph", "补齐知识结构", "extract_knowledge_tree", "知识树已存在，直接复用"),
        ("connections", "读取跨教材连接", "align_textbooks", "读取到学习目标的双侧证据连接"),
        ("index", "确认检索底座", "build_rag_index", "BM25 索引状态正常"),
        ("retrieve", "检索教材原文", "retrieve_evidence", "从两本教材召回 2 条核心证据"),
        ("generate", "生成备课知识包", "generate_lesson_package", "在公开演示中使用原文证据模式生成"),
        ("verify", "核验引用与覆盖", "verify_result", "引用编号、教材覆盖与页码核验通过"),
    ]
    citations = [
        {
            "source_id": "S1", "textbook_id": "demo_book_design",
            "textbook": "教学设计基础（原创示例）", "chapter": "目标与评价",
            "section_path": ["目标与评价"], "page_start": 1, "page_end": 1,
            "quote": "学习目标描述学习结束后学生应能表现出的可观察行为。",
            "retrievers": ["bm25", "knowledge_graph"],
        },
        {
            "source_id": "S2", "textbook_id": "demo_book_assessment",
            "textbook": "课堂评价方法（原创示例）", "chapter": "认知与反馈",
            "section_path": ["认知与反馈"], "page_start": 2, "page_end": 2,
            "quote": "清晰的学习目标为评价标准提供依据，评价结果应反馈到后续教学决策。",
            "retrievers": ["bm25", "knowledge_graph"],
        },
    ]
    return {
        "agent_version": "lesson_agent_v1",
        "goal": "用两本教材的原文证据，生成学习目标与课堂评价的备课知识包。",
        "topic": "学习目标如何连接课堂评价",
        "requirements": ["核心概念", "教材差异", "课堂提问"],
        "textbook_ids": ["demo_book_design", "demo_book_assessment"],
        "plan": [
            {"id": step_id, "title": title, "description": message, "tool": tool,
             "status": "completed", "message": message}
            for step_id, title, tool, message in plan
        ],
        "approval": None,
        "observations": {
            "textbooks": [
                {"id": "demo_book_design", "title": "教学设计基础（原创示例）", "parse_status": "completed", "structure_status": "confirmed", "graph_status": "completed", "pages": 2},
                {"id": "demo_book_assessment", "title": "课堂评价方法（原创示例）", "parse_status": "completed", "structure_status": "confirmed", "graph_status": "completed", "pages": 2},
            ],
            "evidence_count": 2,
            "model": "公开演示 · 证据模式",
            "retrieval_mode": "跨教材均衡检索",
        },
        "artifact": {
            "title": "学习目标与课堂评价 · 可核验备课知识包",
            "executive_summary": "两本教材共同表明：学习目标既描述可观察的学习结果，也为评价标准提供依据。[S1][S2]",
            "teaching_objectives": ["能用可观察行为表述学习目标", "能说明学习目标与评价标准之间的关系"],
            "knowledge_sequence": [
                {"title": "先明确学习结果", "explanation": "把目标写成学生学习后可观察的行为。", "source_ids": ["S1"]},
                {"title": "再设计评价依据", "explanation": "用清晰目标约束评价标准，并将结果反馈到教学决策。", "source_ids": ["S2"]},
            ],
            "common_ground": [{"claim": "学习目标是连接教学活动与评价的共同依据。", "source_ids": ["S1", "S2"]}],
            "textbook_differences": [
                {"textbook": "教学设计基础（原创示例）", "perspective": "侧重目标的可观察行为表述。", "source_ids": ["S1"]},
                {"textbook": "课堂评价方法（原创示例）", "perspective": "侧重目标对评价标准和后续教学决策的约束。", "source_ids": ["S2"]},
            ],
            "misconceptions": [{"issue": "把学习目标写成教师活动", "guidance": "应改写为学生学习后能够表现的可观察行为。", "source_ids": ["S1"]}],
            "classroom_questions": ["如果目标无法观察，评价标准会遇到什么困难？", "评价结果如何反向影响下一步教学？"],
            "unresolved_questions": ["示例教材未给出不同学科目标的具体评价量表，需要教师补充。"],
            "citations": citations,
            "generation_method": "evidence_fallback",
            "generated_at": "2026-08-30T12:00:00+00:00",
        },
        "quality": {
            "score": 96, "status": "passed", "message": "双教材覆盖、引用编号与页码核验通过。",
            "used_source_ids": ["S1", "S2"], "covered_textbook_ids": ["demo_book_design", "demo_book_assessment"],
            "checks": [
                {"id": "citations", "label": "引用可追溯", "passed": True, "value": "2/2"},
                {"id": "coverage", "label": "教材覆盖", "passed": True, "value": "2 本"},
                {"id": "pages", "label": "页码有效", "passed": True, "value": "2/2"},
            ],
        },
        "retry_count": 0,
        "tools_used": ["inspect_course", "align_textbooks", "retrieve_evidence", "verify_result"],
        "created_at": "2026-08-30T12:00:00+00:00",
        "completed_at": "2026-08-30T12:00:08+00:00",
    }


def _sync_demo_runtime(db) -> None:
    """Repair derived demo state on every startup so old persistent disks stay usable."""
    from backend.services.retrieval_service import _content_signature

    chunks = db.query(Chunk).join(Textbook, Textbook.id == Chunk.textbook_id).filter(
        Textbook.course_id == DEMO_COURSE_ID,
    ).order_by(Chunk.textbook_id, Chunk.chapter_id, Chunk.chunk_index, Chunk.id).all()
    state = db.query(RagIndexState).filter(RagIndexState.course_id == DEMO_COURSE_ID).first()
    if state is None:
        state = RagIndexState(course_id=DEMO_COURSE_ID)
        db.add(state)
    state.status = "ready" if chunks else "not_built"
    state.chunk_count = len(chunks)
    state.index_method = "bm25" if chunks else ""
    state.embedding_available = False
    state.content_signature = _content_signature(chunks) if chunks else ""
    state.error = ""

    if chunks and not db.query(Job).filter(Job.id == DEMO_AGENT_JOB_ID).first():
        db.add(Job(
            id=DEMO_AGENT_JOB_ID,
            course_id=DEMO_COURSE_ID,
            type="course_agent",
            status="completed",
            progress=100,
            total=100,
            message="公开示例已完成，可查看 Agent 执行轨迹、交付物与证据。",
            payload={
                "course_id": DEMO_COURSE_ID,
                "topic": "学习目标如何连接课堂评价",
                "goal": "生成可核验的跨教材备课知识包",
                "textbook_ids": ["demo_book_design", "demo_book_assessment"],
                "requirements": ["核心概念", "教材差异", "课堂提问"],
            },
            result=_demo_agent_result(),
            stage="completed",
        ))


def seed_demo_course():
    db = SessionLocal()
    try:
        if db.query(Course).filter(Course.id == DEMO_COURSE_ID).first():
            _sync_demo_runtime(db)
            db.commit()
            return {"seeded": False, "course_id": DEMO_COURSE_ID}

        course = Course(
            id=DEMO_COURSE_ID,
            owner_id="demo_user",
            title="AI 教学设计 · 示例课程",
            subject="教育技术",
            description="由原创短文本构成的公开演示数据，用于展示跨教材知识连接与证据问答。",
            status="review",
            default_granularity="core",
        )
        books = [
            Textbook(
                id="demo_book_design",
                course_id=DEMO_COURSE_ID,
                filename="demo_design.md",
                original_filename="教学设计基础（原创示例）.md",
                title="教学设计基础（原创示例）",
                format="md",
                total_pages=2,
                total_chars=128,
                parse_status="completed",
                graph_status="completed",
                index_status="completed",
                structure_status="confirmed",
                parse_warnings=[],
                content_hash=_hash("demo_design"),
            ),
            Textbook(
                id="demo_book_assessment",
                course_id=DEMO_COURSE_ID,
                filename="demo_assessment.md",
                original_filename="课堂评价方法（原创示例）.md",
                title="课堂评价方法（原创示例）",
                format="md",
                total_pages=2,
                total_chars=132,
                parse_status="completed",
                graph_status="completed",
                index_status="completed",
                structure_status="confirmed",
                parse_warnings=[],
                content_hash=_hash("demo_assessment"),
            ),
        ]
        db.add(course)
        db.add_all(books)
        db.flush()

        page_text = {
            "demo_book_design": [
                "学习目标描述学习结束后学生应能表现出的可观察行为。形成性评价发生在教学过程中，用于发现理解偏差并调整教学活动。",
                "认知负荷是学习任务对工作记忆资源的占用。教学材料应减少无关信息造成的外在认知负荷。",
            ],
            "demo_book_assessment": [
                "过程性评价是在学习活动进行期间持续收集证据，并据此改进教与学的评价方式。",
                "清晰的学习目标为评价标准提供依据，评价结果应反馈到后续教学决策。",
            ],
        }
        chapters = []
        chunks = []
        for book in books:
            for index, text_value in enumerate(page_text[book.id], 1):
                chapter_id = f"demo_chapter_{book.id}_{index}"
                chunk_id = f"demo_chunk_{book.id}_{index}"
                db.add(TextbookPage(
                    id=f"demo_page_{book.id}_{index}",
                    textbook_id=book.id,
                    page_number=index,
                    text=text_value,
                    char_count=len(text_value),
                    content_hash=_hash(text_value),
                    has_text=True,
                    extraction_method="text",
                ))
                chapters.append(Chapter(
                    id=chapter_id,
                    textbook_id=book.id,
                    title="目标与评价" if index == 1 else "认知与反馈",
                    page_start=index,
                    page_end=index,
                    content=text_value,
                    char_count=len(text_value),
                    order_index=index - 1,
                    level=1,
                    review_status="confirmed",
                    source_spans=[{"page_number": index, "start": 0, "end": len(text_value)}],
                ))
                chunks.append(Chunk(
                    id=chunk_id,
                    textbook_id=book.id,
                    chapter_id=chapter_id,
                    textbook_title=book.title,
                    chapter_title="目标与评价" if index == 1 else "认知与反馈",
                    page_start=index,
                    page_end=index,
                    content=text_value,
                    char_count=len(text_value),
                    chunk_index=index - 1,
                    section_path=["目标与评价" if index == 1 else "认知与反馈"],
                    content_hash=_hash(text_value),
                ))
        db.add_all(chapters + chunks)
        db.flush()

        canonical = CanonicalConcept(
            id="demo_concept_learning_objective",
            course_id=DEMO_COURSE_ID,
            canonical_name="学习目标",
            concept_type="concept",
            definition_summary="描述预期学习结果，并为评价标准提供依据。",
            status="published",
            teacher_locked=True,
            created_by="demo_seed",
        )
        db.add(canonical)
        nodes = [
            KnowledgeNode(
                id="demo_node_objective_design", course_id=DEMO_COURSE_ID,
                canonical_concept_id=canonical.id, name="学习目标",
                definition="学习结束后学生应能表现出的可观察行为。",
                category="concept", importance=5, textbook_id=books[0].id,
                textbook_title=books[0].title, chapter_title="目标与评价",
                page=1, page_start=1, page_end=1,
                source_chunk_id="demo_chunk_demo_book_design_1",
                source_paragraph="学习目标描述学习结束后学生应能表现出的可观察行为。",
                granularity="core_concept", is_essence=True, review_status="approved",
                evidence_status="verified", confidence=.98, quality_score=.96,
                created_by="demo_seed", source_type="demo_seed", parent_id="demo_topic_design_1",
            ),
            KnowledgeNode(
                id="demo_node_formative", course_id=DEMO_COURSE_ID, name="形成性评价",
                definition="教学过程中用于发现偏差并调整活动的评价。",
                category="concept", importance=5, textbook_id=books[0].id,
                textbook_title=books[0].title, chapter_title="目标与评价",
                page=1, page_start=1, page_end=1,
                source_chunk_id="demo_chunk_demo_book_design_1",
                source_paragraph="形成性评价发生在教学过程中，用于发现理解偏差并调整教学活动。",
                granularity="core_concept", is_essence=True, review_status="review",
                evidence_status="verified", confidence=.94, quality_score=.93,
                created_by="demo_seed", source_type="demo_seed", parent_id="demo_topic_design_1",
            ),
            KnowledgeNode(
                id="demo_node_load", course_id=DEMO_COURSE_ID, name="认知负荷",
                definition="学习任务对工作记忆资源的占用。",
                category="concept", importance=4, textbook_id=books[0].id,
                textbook_title=books[0].title, chapter_title="认知与反馈",
                page=2, page_start=2, page_end=2,
                source_chunk_id="demo_chunk_demo_book_design_2",
                source_paragraph="认知负荷是学习任务对工作记忆资源的占用。",
                granularity="core_concept", is_essence=True, review_status="approved",
                evidence_status="verified", confidence=.96, quality_score=.95,
                created_by="demo_seed", source_type="demo_seed", parent_id="demo_topic_design_2",
            ),
            KnowledgeNode(
                id="demo_node_process_assessment", course_id=DEMO_COURSE_ID, name="过程性评价",
                definition="学习活动期间持续收集证据并改进教与学的评价。",
                category="concept", importance=5, textbook_id=books[1].id,
                textbook_title=books[1].title, chapter_title="目标与评价",
                page=1, page_start=1, page_end=1,
                source_chunk_id="demo_chunk_demo_book_assessment_1",
                source_paragraph="过程性评价是在学习活动进行期间持续收集证据，并据此改进教与学的评价方式。",
                granularity="core_concept", is_essence=True, review_status="review",
                evidence_status="verified", confidence=.93, quality_score=.92,
                created_by="demo_seed", source_type="demo_seed", parent_id="demo_topic_assessment_1",
            ),
            KnowledgeNode(
                id="demo_node_objective_assessment", course_id=DEMO_COURSE_ID,
                canonical_concept_id=canonical.id, name="学习目标",
                definition="为评价标准提供依据的预期学习结果。",
                category="concept", importance=5, textbook_id=books[1].id,
                textbook_title=books[1].title, chapter_title="认知与反馈",
                page=2, page_start=2, page_end=2,
                source_chunk_id="demo_chunk_demo_book_assessment_2",
                source_paragraph="清晰的学习目标为评价标准提供依据，评价结果应反馈到后续教学决策。",
                granularity="core_concept", is_essence=True, review_status="approved",
                evidence_status="verified", confidence=.97, quality_score=.94,
                created_by="demo_seed", source_type="demo_seed", parent_id="demo_topic_assessment_2",
            ),
        ]
        for topic_id, book, page, title, chunk_id, text_value in (
            ("demo_topic_design_1", books[0], 1, "目标与评价", "demo_chunk_demo_book_design_1", page_text[books[0].id][0]),
            ("demo_topic_design_2", books[0], 2, "认知与反馈", "demo_chunk_demo_book_design_2", page_text[books[0].id][1]),
            ("demo_topic_assessment_1", books[1], 1, "目标与评价", "demo_chunk_demo_book_assessment_1", page_text[books[1].id][0]),
            ("demo_topic_assessment_2", books[1], 2, "认知与反馈", "demo_chunk_demo_book_assessment_2", page_text[books[1].id][1]),
        ):
            nodes.append(KnowledgeNode(
                id=topic_id, course_id=DEMO_COURSE_ID, name=title,
                definition=f"《{book.title}》中的章节主题。",
                category="topic", importance=5, textbook_id=book.id,
                textbook_title=book.title, chapter_title=title,
                page=page, page_start=page, page_end=page,
                source_chunk_id=chunk_id, source_paragraph=text_value,
                granularity="chapter_topic", node_role="chapter", display_level="overview",
                is_essence=True, review_status="approved", evidence_status="verified",
                confidence=1.0, quality_score=1.0, created_by="demo_seed", source_type="demo_seed",
            ))
        db.add_all(nodes)
        db.flush()

        edge = KnowledgeEdge(
            id="demo_edge_objectives", course_id=DEMO_COURSE_ID,
            source="demo_node_objective_design", target="demo_node_objective_assessment",
            relation_type="equivalent_to", description="两本教材从行为描述与评价依据两个角度表述学习目标。",
            confidence=.98, is_cross_textbook=True, review_status="approved",
            created_by="demo_seed", source_quote=nodes[0].source_paragraph,
            source_chunk_id=nodes[0].source_chunk_id,
        )
        db.add(edge)
        db.add_all([
            KnowledgeEdge(
                id=f"demo_contains_{index}", course_id=DEMO_COURSE_ID,
                source=node.parent_id, target=node.id, relation_type="contains",
                description="章节包含知识点", confidence=1.0,
                review_status="approved", created_by="demo_seed",
            )
            for index, node in enumerate(nodes[:5], 1)
        ])
        db.flush()
        db.add_all([
            RelationEvidence(
                id="demo_evidence_objective_a", edge_id=edge.id, textbook_id=books[0].id,
                chunk_id=nodes[0].source_chunk_id, page_number=1,
                source_quote=nodes[0].source_paragraph, evidence_role="source", quote_verified=True,
            ),
            RelationEvidence(
                id="demo_evidence_objective_b", edge_id=edge.id, textbook_id=books[1].id,
                chunk_id=nodes[4].source_chunk_id, page_number=2,
                source_quote=nodes[4].source_paragraph, evidence_role="target", quote_verified=True,
            ),
            AlignmentCandidate(
                id="demo_alignment_formative", course_id=DEMO_COURSE_ID,
                source_node_id="demo_node_formative", target_node_id="demo_node_process_assessment",
                proposed_relation="equivalent_to", confidence=.91,
                name_similarity=.72, definition_similarity=.94, context_similarity=.91,
                reason="两者都发生在教学过程中，并以收集证据和改进教学为目的。",
                differences="“形成性评价”强调诊断偏差，“过程性评价”强调持续收集学习证据。",
                evidence=[nodes[1].source_paragraph, nodes[3].source_paragraph],
                status="pending", model_version="demo", prompt_version="demo-v1",
            ),
        ])

        _sync_demo_runtime(db)
        db.commit()
        return {"seeded": True, "course_id": DEMO_COURSE_ID}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
