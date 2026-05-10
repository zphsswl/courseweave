import json
import re
import uuid
from backend.config import LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
from backend.database import SessionLocal, Chapter, Chunk, KnowledgeNode, KnowledgeEdge, Textbook, IntegrationDecision

VALID_RELATION_TYPES = {"prerequisite", "parallel", "contains", "applies_to"}
VALID_CATEGORIES = {"核心概念", "结构", "机制", "疾病", "病原体", "表现", "诊断", "治疗"}

# ── Topic extraction prompt ──
TOPIC_PROMPT = """你是医学教材结构化 Agent。请只依据给定章节原文，抽取本章的大类知识结构。

要求：
1. 输出纯 JSON（不要 Markdown 代码块）。
2. 先给出 1 个 chapter_topic（本章核心主题）。
3. 再给出 3-8 个 section_topic（本章下的主要知识大类）。
4. 每个 section_topic 必须说明 scope（教学范围）和 source_quote（原文依据）。
5. 不要抽取细碎事实、孤立数字、目录项。

输出格式：
{"chapter_topic": {"name": "...", "definition": "...", "learning_objective": "..."}, "section_topics": [{"local_id": "s1", "name": "...", "scope": "...", "source_quote": "..."}], "edges": [{"source": "chapter_topic", "target": "s1", "relation_type": "contains", "description": "..."}]}

教材：{textbook}
章节：{chapter}
原文内容（前6000字）：
{content}"""

# ── Concept extraction prompt ──
CONCEPT_PROMPT = """你是医学知识点抽取 Agent。请只在指定的 section_topic 范围内从原文中抽取核心知识点。

关系类型只能为：prerequisite（前置依赖）、parallel（并列）、contains（包含）、applies_to（应用）。

数量：当前 section 至少 3 个、最多 8 个知识点。每个知识点必须有 source_quote。每个核心知识点至少建立 1 条关系。

输出纯 JSON：
{"nodes": [{"local_id": "n1", "name": "...", "aliases": [], "definition": "...", "category": "核心概念|结构|机制|疾病|病原体|表现|诊断|治疗", "importance": 3, "granularity": "core_concept", "source_quote": "...", "quality_reason": "..."}], "edges": [{"source": "n1", "target": "n2", "relation_type": "prerequisite|parallel|contains|applies_to", "description": "...", "source_quote": "..."}], "parent_edges": [{"source": "section_id", "target": "n1", "relation_type": "contains", "description": "..."}]}

教材：{textbook}  章节：{chapter}
当前大类：{section_name}（范围：{section_scope}）
原文内容：
{content}"""


def extract_textbook_graph(textbook_id: str, force: bool = False) -> dict:
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if not book:
            raise ValueError(f"Textbook {textbook_id} not found")

        if force:
            _clean_textbook_graph(db, textbook_id)

        existing_nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.textbook_id == textbook_id
        ).count()
        if existing_nodes > 0:
            return {"textbook_id": textbook_id, "nodes": existing_nodes,
                    "edges": 0, "message": "Already extracted (use force=true to re-extract)"}

        # Pre-extraction check
        chapter_count = db.query(Chapter).filter(Chapter.textbook_id == textbook_id).count()
        chunk_count = db.query(Chunk).filter(Chunk.textbook_id == textbook_id).count()
        if chapter_count == 0:
            return {"textbook_id": textbook_id, "nodes": 0, "edges": 0,
                    "error": "请先解析教材并生成章节，再提取知识图谱。当前章节数为0。"}
        if chunk_count == 0:
            return {"textbook_id": textbook_id, "nodes": 0, "edges": 0,
                    "error": "请先生成教材chunk，再提取知识图谱。当前chunk数为0。"}

        total_nodes, total_edges = _layered_extract(db, book)
        book.graph_status = "completed"
        db.commit()
        return {"textbook_id": textbook_id, "nodes": total_nodes, "edges": total_edges}
    finally:
        db.close()


def _clean_textbook_graph(db, textbook_id: str):
    """Remove all graph data for a textbook before re-extraction."""
    node_ids = [r[0] for r in db.query(KnowledgeNode.id).filter(
        KnowledgeNode.textbook_id == textbook_id).all()]
    db.query(KnowledgeEdge).filter(
        (KnowledgeEdge.source.in_(node_ids)) |
        (KnowledgeEdge.target.in_(node_ids))
    ).delete(synchronize_session=False)
    db.query(KnowledgeNode).filter(
        KnowledgeNode.textbook_id == textbook_id).delete(synchronize_session=False)
    db.query(IntegrationDecision).filter(
        IntegrationDecision.affected_nodes.contains([textbook_id])
    ).delete(synchronize_session=False)
    db.flush()


def _layered_extract(db, book) -> tuple:
    """Phase 1: topic extraction → Phase 2: concept extraction per section."""
    chapters = db.query(Chapter).filter(Chapter.textbook_id == book.id).all()
    total_nodes, total_edges = 0, 0

    for ch in chapters:
        if len(ch.content) < 200:
            continue

        content = ch.content[:6000]
        topics = _call_llm_topic(book.title, ch.title, content)
        if not topics:
            continue

        ct = topics.get("chapter_topic", {})
        sections = topics.get("section_topics", [])

        # Create chapter_topic node
        ct_id = f"{book.id}_{ch.id}_topic"
        ct_node = KnowledgeNode(
            id=ct_id, name=ct.get("name", ch.title),
            aliases=[], definition=ct.get("definition", ""),
            category="核心概念", importance=4,
            textbook_id=book.id, textbook_title=book.title,
            chapter_title=ch.title,
            page=ch.page_start, page_start=ch.page_start, page_end=ch.page_end,
            source_paragraph=ct.get("definition", ""),
            source_sentences=[ct.get("definition", "")],
            granularity="chapter_topic",
            learning_objective=ct.get("learning_objective", ""),
            quality_score=0.85, confidence=0.85,
            quality_flags=[],
        )
        db.merge(ct_node)
        total_nodes += 1

        # Create section_topic nodes
        section_nodes = []
        for s in sections[:8]:  # max 8 sections per chapter
            sid = f"{book.id}_{ch.id}_sec_{s.get('local_id', '')}"
            sn = KnowledgeNode(
                id=sid, name=s.get("name", ""),
                aliases=[], definition=s.get("scope", ""),
                category="核心概念", importance=3,
                textbook_id=book.id, textbook_title=book.title,
                chapter_title=ch.title,
                page=ch.page_start, page_start=ch.page_start, page_end=ch.page_end,
                source_paragraph=s.get("source_quote", ""),
                source_sentences=[s.get("source_quote", "")],
                granularity="section_topic",
                learning_objective=s.get("scope", ""),
                quality_score=0.80, confidence=0.80,
                quality_flags=[],
            )
            db.merge(sn)
            total_nodes += 1
            section_nodes.append(sn)

            # Chapter contains section
            db.add(KnowledgeEdge(
                id=f"edge_{uuid.uuid4().hex[:10]}",
                source=ct_id, target=sid,
                relation_type="contains",
                description=f"「{ch.title}」包含「{s.get('name', '')}」",
                confidence=0.95,
                created_by="topic_extraction",
            ))
            total_edges += 1

        # Phase 2: Extract core concepts per section
        chunks = db.query(Chunk).filter(Chunk.chapter_id == ch.id).order_by(Chunk.chunk_index).all()

        for sn in section_nodes:
            # Gather relevant content for this section
            section_content = _gather_section_content(chunks, sn.name, sn.definition)
            if len(section_content) < 100:
                section_content = ch.content[:(len(ch.content) // max(len(section_nodes), 1))]

            concepts = _call_llm_concept(
                book.title, ch.title,
                sn.name, sn.definition or "",
                section_content[:4000]
            )
            if not concepts:
                continue

            local_to_id = {}
            for c in concepts.get("nodes", [])[:8]:  # max 8 per section
                cid = f"{book.id}_{ch.id}_c_{uuid.uuid4().hex[:6]}"
                node = KnowledgeNode(
                    id=cid, name=c.get("name", ""),
                    aliases=c.get("aliases", []),
                    definition=c.get("definition", ""),
                    category=c.get("category", "核心概念"),
                    importance=c.get("importance", 3),
                    textbook_id=book.id, textbook_title=book.title,
                    chapter_title=ch.title,
                    page=ch.page_start, page_start=ch.page_start, page_end=ch.page_end,
                    source_paragraph=c.get("source_quote", ""),
                    source_sentences=[c.get("source_quote", "")],
                    granularity="core_concept",
                    learning_objective=c.get("quality_reason", ""),
                    quality_score=_quick_quality(c),
                    confidence=0.75,
                    quality_flags=[],
                )
                db.merge(node)
                total_nodes += 1
                local_to_id[c.get("local_id", "")] = cid

                # Section contains concept
                db.add(KnowledgeEdge(
                    id=f"edge_{uuid.uuid4().hex[:10]}",
                    source=sn.id, target=cid,
                    relation_type="contains",
                    description=f"「{sn.name}」包含知识点「{c.get('name', '')}」",
                    confidence=0.90,
                    created_by="concept_extraction",
                ))
                total_edges += 1

            # Concept-to-concept edges
            for e in concepts.get("edges", []):
                src = local_to_id.get(e.get("source", ""))
                tgt = local_to_id.get(e.get("target", ""))
                rt = e.get("relation_type", "")
                if src and tgt and rt in VALID_RELATION_TYPES:
                    db.add(KnowledgeEdge(
                        id=f"edge_{uuid.uuid4().hex[:10]}",
                        source=src, target=tgt,
                        relation_type=rt,
                        description=e.get("description", ""),
                        source_quote=e.get("source_quote", ""),
                        confidence=e.get("confidence", 0.7),
                        created_by="concept_extraction",
                    ))
                    total_edges += 1

        # Cross-section relations within chapter
        db.flush()

    # Post-processing: generate cross-concept relations
    total_edges += _generate_cross_relations(db, book)

    return total_nodes, total_edges


def _gather_section_content(chunks, section_name: str, section_scope: str) -> str:
    """Gather content relevant to a section from chunks."""
    relevant = []
    keywords = set(section_name) | set(section_scope or "")
    for ck in chunks[:20]:
        score = sum(1 for ch in ck.content if ch in keywords)
        if score > 5 or section_name[:2] in ck.content:
            relevant.append(ck.content)
        if sum(len(r) for r in relevant) > 4000:
            break
    return "\n".join(relevant) if relevant else ""


def _generate_cross_relations(db, book) -> int:
    """Generate prerequisite and applies_to edges across concepts within a book."""
    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.textbook_id == book.id,
        KnowledgeNode.granularity == "core_concept"
    ).all()
    if len(nodes) < 2:
        return 0

    added = 0
    # Prerequisite: 结构 → 机制 → 疾病
    cat_order = {"结构": 1, "机制": 2, "疾病": 3, "表现": 4, "诊断": 5, "治疗": 6}
    for i, na in enumerate(nodes):
        for nb in nodes[i+1:]:
            oa = cat_order.get(na.category, 3)
            ob = cat_order.get(nb.category, 3)
            if oa < ob and (ob - oa) <= 2:
                existing = db.query(KnowledgeEdge).filter(
                    KnowledgeEdge.source == na.id,
                    KnowledgeEdge.target == nb.id,
                ).count()
                if existing == 0:
                    db.add(KnowledgeEdge(
                        id=f"edge_{uuid.uuid4().hex[:10]}",
                        source=na.id, target=nb.id,
                        relation_type="prerequisite",
                        description=f"「{na.name}」({na.category})是理解「{nb.name}」({nb.category})的基础",
                        confidence=0.6,
                        created_by="cross_relation_gen",
                    ))
                    added += 1

    # Parallel: same category, same chapter
    by_chapter = {}
    for n in nodes:
        by_chapter.setdefault(n.chapter_title, []).append(n)
    for ch, ch_nodes in by_chapter.items():
        for i in range(len(ch_nodes)):
            for j in range(i+1, len(ch_nodes)):
                if ch_nodes[i].category == ch_nodes[j].category:
                    existing = db.query(KnowledgeEdge).filter(
                        ((KnowledgeEdge.source == ch_nodes[i].id) & (KnowledgeEdge.target == ch_nodes[j].id)) |
                        ((KnowledgeEdge.source == ch_nodes[j].id) & (KnowledgeEdge.target == ch_nodes[i].id))
                    ).count()
                    if existing == 0:
                        db.add(KnowledgeEdge(
                            id=f"edge_{uuid.uuid4().hex[:10]}",
                            source=ch_nodes[i].id, target=ch_nodes[j].id,
                            relation_type="parallel",
                            description=f"「{ch_nodes[i].name}」与「{ch_nodes[j].name}」同属{ch_nodes[i].category}类概念",
                            confidence=0.65,
                            created_by="cross_relation_gen",
                        ))
                        added += 1
                        if added > 100:
                            break
    db.flush()
    return added


def _call_llm_topic(book_title: str, chapter_title: str, content: str) -> dict | None:
    """Call LLM for chapter/section topic extraction."""
    try:
        import openai
        client = openai.OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        prompt = TOPIC_PROMPT.format(textbook=book_title, chapter=chapter_title, content=content[:6000])
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=2000,
        )
        return _parse_json_safely(resp.choices[0].message.content)
    except Exception:
        return _rule_topic(chapter_title, content)


def _call_llm_concept(book_title: str, chapter_title: str,
                      section_name: str, section_scope: str,
                      content: str) -> dict | None:
    """Call LLM for concept extraction within a section."""
    try:
        import openai
        client = openai.OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        prompt = CONCEPT_PROMPT.format(
            textbook=book_title, chapter=chapter_title,
            section_name=section_name, section_scope=section_scope,
            content=content[:4000],
        )
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=2500,
        )
        return _parse_json_safely(resp.choices[0].message.content)
    except Exception:
        return _rule_concepts(content, section_name)


def _rule_topic(chapter_title: str, content: str) -> dict:
    """Rule-based topic extraction fallback."""
    # Split by common medical section patterns
    patterns = re.findall(r'(?:[一二三四五六七八九十\d]+[、．.)]\s*[^\n]{4,40})', content)
    sections = []
    for i, p in enumerate(patterns[:8]):
        sections.append({
            "local_id": f"s{i+1}",
            "name": p.strip(),
            "scope": p.strip(),
            "source_quote": p.strip(),
        })
    return {
        "chapter_topic": {
            "name": chapter_title,
            "definition": f"本章围绕{chapter_title}展开教学内容",
            "learning_objective": f"掌握{chapter_title}相关核心知识",
        },
        "section_topics": sections,
        "edges": [],
    }


def _rule_concepts(content: str, section_name: str) -> dict:
    """Rule-based concept extraction fallback."""
    nodes = []
    edges = []
    # Extract medical terms
    patterns = [
        r'([一-鿿]{2,8}(?:病|症|炎|癌|瘤|反应|机制|系统|细胞|菌|病毒|蛋白|因子|受体|通路|途径|介质|抗原|抗体|应答|调节|修复|再生|坏死|凋亡|变性|渗出|增生|血栓|栓塞|梗死|休克|发热|免疫|感染|炎症|肿瘤))',
        r'([一-鿿]{3,12}(?:障碍|异常|低下|亢进|减退|增生|萎缩|化生|变性|坏死|损伤|衰竭|中毒|过敏|缺陷))',
    ]
    seen = set()
    count = 0
    for pat in patterns:
        for m in re.finditer(pat, content):
            kw = m.group()
            if kw not in seen and len(kw) >= 2:
                seen.add(kw)
                nodes.append({
                    "local_id": f"n{count}", "name": kw,
                    "aliases": [], "definition": kw,
                    "category": "核心概念", "importance": 3,
                    "granularity": "core_concept",
                    "source_quote": content[m.start():m.start()+100].strip(),
                    "quality_reason": "规则兜底抽取",
                })
                count += 1
                if count >= 6:
                    break
        if count >= 6:
            break
    # Add one parent edge per concept
    for n in nodes:
        edges.append({
            "source": "section_id", "target": n["local_id"],
            "relation_type": "contains",
            "description": f"包含{n['name']}",
            "source_quote": "",
        })
    return {"nodes": nodes, "edges": [], "parent_edges": edges}


def _quick_quality(concept: dict) -> float:
    """Quick quality score for a concept."""
    score = 0.5
    if concept.get("source_quote") and len(concept.get("source_quote", "")) > 10:
        score += 0.15
    if concept.get("definition") and len(concept.get("definition", "")) > 10:
        score += 0.15
    if concept.get("category") in ("疾病", "病原体", "机制", "核心概念"):
        score += 0.10
    if concept.get("importance", 3) >= 4:
        score += 0.10
    return min(score, 0.95)


def _parse_json_safely(text: str) -> dict:
    """Parse JSON from LLM output."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}
