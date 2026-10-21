"""Conservative display labels for retrieved sources, never concept equivalence.

Only an actual source heading can group multiple passages. A shared query or a
similar sentence does not establish that two passages describe the same concept.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import re
import unicodedata


_NUMBERING = re.compile(
    r"^(?:第[一二三四五六七八九十百零〇\d]+[章节篇部]\s*[|｜:：]?\s*|"
    r"\([一二三四五六七八九十百零〇\d]+\)\s*|"
    r"[一二三四五六七八九十百零〇]+[、.)]\s*|"
    r"\d+(?:\.\d+)*[.、)]\s*|\d+(?:\.\d+)+\s+|"
    r"[ivxlcdm]+[.、)]\s*)", re.I,
)
_GENERIC = {
    "内容", "结构", "功能", "概述", "概论", "总论", "小结", "概要", "应用", "意义", "特点",
    "组成", "分类", "位置", "境界", "毗邻", "形态", "定义", "作用", "调节", "总结", "练习",
    "习题", "复习习题", "复习思考题", "思考题", "临床应用", "病例", "内容及其毗邻", "结构与功能",
    "位置与毗邻", "形态与结构", "形态与被膜", "概念", "简介", "前言", "本章要点", "学习目标",
}
_PROSE = re.compile(r"位于|是指|是一|是由|分为|具有|包括|含有|称为|又称|用于|可以|可使|"
                    r"受到|通过|参与|产生|分布|发生|进行|导致|上端|下端|前面|后面|侧叶|左叶|右叶|"
                    r"由.+(?:组成|构成)")
_FIGURE = re.compile(r"^(?:图|表|fig(?:ure)?\.?|table)\s*[一二三四五六七八九十\d]", re.I)


def _label(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    value = _NUMBERING.sub("", value, count=1).strip(" |｜:：、. ")
    return re.sub(r"\s+", " ", value)


def _identity(value: str) -> str:
    return re.sub(r"\s+", "", _label(value)).lower()


@lru_cache(maxsize=128)
def _topic_terms(query: str) -> tuple[str, ...]:
    # Reuse the existing lexical question parser, without vector/model paths.
    # Both bridge and restored boards call this helper with the same query.
    from backend.services.retrieval_service import _prepare_query
    features = _prepare_query(query, [])
    return tuple(dict.fromkeys(_identity(value) for value in features["anchors"]
                               if 2 <= len(_identity(value)) <= 40 and _identity(value) not in _GENERIC))


def _reliable(value: str, topics: tuple[str, ...]) -> bool:
    label = _label(value)
    compact = _identity(label)
    return bool(
        2 <= len(label) <= 64 and compact not in _GENERIC
        and not _FIGURE.match(label)
        and not re.search(r"[。；;，!?！？:：]", label)
        and not _PROSE.search(label)
        and any(topic in compact for topic in topics)
    )


def _body_heading(line: str, topics: tuple[str, ...]) -> str | None:
    raw = unicodedata.normalize("NFKC", line).strip()
    if not raw or _FIGURE.match(raw):
        return None
    numbered = bool(_NUMBERING.match(raw))
    # A numbered inline title may precede a definition after a colon. Without
    # numbering, a prose prefix before a colon is not assumed to be a heading.
    if numbered and re.search(r"[:：]", raw):
        raw = re.split(r"[:：]", raw, maxsplit=1)[0]
    elif raw.endswith((":", "：")):
        raw = raw[:-1]
    label = _label(raw)
    if not _reliable(label, topics):
        return None
    compact = _identity(label)
    # Unnumbered lines qualify only as an explicit, concise topic title or a
    # title followed by a translation, not any short sentence mentioning it.
    if not numbered and not any(
        compact == topic or re.fullmatch(re.escape(topic) + r"[a-z][a-z0-9()（）,\-/]*", compact)
        or (compact.startswith(topic + "的") and len(compact) - len(topic) <= 18)
        for topic in topics
    ):
        return None
    return label


def passage_concept_metadata(chunk, book_id: str, query: str) -> dict:
    """Describe an original passage; keys group identical source headings only.

    The legacy ``title`` is deliberately outside this metadata. ``source_heading``
    always preserves the last original directory label even when it is generic.
    An excerpt without a reliable heading remains unique to its chunk.
    """
    path = [str(value) for value in chunk.section_path] if isinstance(chunk.section_path, list) else []
    chapter = str(chunk.chapter_title or "")
    source_heading = path[-1] if path else chapter
    topics = _topic_terms(query)
    display = None
    origin = "topic_excerpt"
    heading_path = None
    labels = path or ([chapter] if chapter else [])
    for index in range(len(labels) - 1, -1, -1):
        if _reliable(labels[index], topics):
            display, origin = _label(labels[index]), "source_heading"
            heading_path = [_identity(value) for value in labels[:index + 1]]
            break
    if display is None:
        for line in (chunk.content or "").splitlines():
            heading = _body_heading(line, topics)
            if heading:
                display, origin = heading, "source_subheading"
                heading_path = [*[_identity(value) for value in labels], _identity(heading)]
                break
    if display is None:
        # Keep a long question readable without presenting it as source wording.
        topic_label = re.sub(r"\s+", " ", (query or "").strip())
        display = f"{topic_label[:60]}{'…' if len(topic_label) > 60 else ''} · 原文片段"
    identity = {
        "book": book_id, "chapter": chunk.chapter_id or chapter,
        "heading": heading_path,
        "chunk": None if heading_path else chunk.id,
    }
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return {"source_heading": source_heading, "display_title": display, "title_origin": origin,
            "concept_key": f"{'heading' if heading_path else 'excerpt'}:{digest}"}
