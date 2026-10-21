"""Read-only teaching views over stored textbook text; never generates knowledge."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from backend.database import Chapter, Chunk, Textbook, TextbookPage
from backend.services.chunker import _is_back_matter_heading, _looks_like_numbered_prose, _section_heading


TEXTBOOK_ROOT = Path(__file__).resolve().parents[2] / "data" / "textbooks"
LEGACY_TEXTBOOK_ROOT = Path(__file__).resolve().parents[2] / "教材"
MAX_PDF_BYTES = 512 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 1600
MAX_IMAGE_PIXELS = 2_000_000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]")
_FIGURE = re.compile(r"图[^\S\r\n]*([0-9０-９]{1,3})[^\S\r\n]*[-－—–][^\S\r\n]*([0-9０-９]{1,3})([A-Za-z]?)")
_FORMAL_SECTION = re.compile(r"^第\s*[一二三四五六七八九十百千\d０-９]+\s*节\s*(?:[|｜]\s*)?(.*)$")
_TOC_LINE = re.compile(r"(?:[.·…]\s*){4,}\d+\s*$|…{2,}\s*\d+\s*$")
_DECORATION = re.compile(r"本章(?:数字资源|思维导图|目标测试)|思考题解题思路|扫描图片|体验\s*AR")
_APPENDIX = re.compile(r"^附录\s*[一二三四五六七八九十百\dA-Z]+\s*(?:[|｜]\s*)?(.+)$")
_RUNNING_BANNER = re.compile(r"^(?:(?:第[一二三四五六七八九十百\d]+|[上中下])篇[^。；]{0,35}|附录[一二三四五六七八九十百\d]*)$")
_INLINE_NUMBERED = re.compile(
    r"^(?P<marker>\d{1,2}[.、]|[（(]\d{1,2}[）)])\s*"
    r"(?P<title>[\u4e00-\u9fff]{1,16})"
    r"(?P<english>\s*[A-Za-z][A-Za-z0-9 /-]{0,60})?\s+(?P<body>.+)$"
)


class TeachingSourceError(ValueError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "")).casefold()


def _clean(value: str) -> str:
    value = _CONTROL.sub("", value or "").replace("\u00ad", "")
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _clean_title(value: str) -> str:
    value = re.sub(r"[\s|｜]+", " ", _clean(value)).strip()
    value = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)
    return re.sub(r"^第\s*([一二三四五六七八九十百千\d０-９]+)\s*([章节])\s*", r"第\1\2 ", value).strip()


def _pages_for(spans: list, start: int, end: int, fallback: tuple[int, int]) -> tuple[int, int]:
    matching = []
    for span in spans:
        try:
            if int(span.get("chapter_end", 0)) > start and int(span.get("chapter_start", 0)) < end:
                first = int(span.get("page_number") or span.get("page_start") or 0)
                last = int(span.get("page_end") or first)
                if first > 0:
                    matching.extend((first, last))
        except (TypeError, ValueError):
            continue
    return (min(matching), max(matching)) if matching else fallback


def _append_part(parts: list[str], spans: list[dict], content: str, first: int, last: int, deduplicate: bool = True) -> None:
    if not content:
        return
    current = "".join(parts)
    # Chunks can overlap; remove only an exact shared suffix, never a semantic guess.
    overlap = 0
    for size in range(min(len(current), len(content), 2000) if deduplicate else 0, 0, -1):
        if current.endswith(content[:size]):
            overlap = size
            break
    content = content[overlap:]
    if not content:
        return
    if parts and not overlap:
        parts.append("\n\n")
    start = sum(map(len, parts))
    parts.append(content)
    spans.append({"chapter_start": start, "chapter_end": start + len(content), "page_start": first, "page_end": last})


def _opening_page_prefixes(chapters: list, pages: list) -> dict:
    """Recover a missed opening from stored pages, without changing chapter records.

    Some older imports selected a running chapter header on a later page. Only
    exact chapter-title lines on non-TOC pages, before the recorded start and
    after the previous chapter start, are accepted as evidence for a prefix.
    """
    known_titles = {_compact(chapter.title) for chapter in chapters}
    occurrences = {}
    for page in pages:
        lines = (page.text or "").splitlines()
        if sum(bool(_TOC_LINE.search(line)) for line in lines) >= 2:
            continue
        for line in lines:
            key = _compact(line)
            if key in known_titles:
                occurrences.setdefault(key, []).append(page.page_number)
    prefixes = {}
    for index, chapter in enumerate(chapters):
        lower = chapters[index - 1].page_start if index else 1
        candidates = [number for number in occurrences.get(_compact(chapter.title), []) if lower <= number < chapter.page_start]
        if candidates:
            start = min(candidates)
            selected = [page for page in pages if start <= page.page_number < chapter.page_start]
            # Do not silently bridge missing stored physical pages.
            if [page.page_number for page in selected] == list(range(start, chapter.page_start)):
                prefixes[chapter.id] = selected
    return prefixes


def _chapter_source(chapter, pages, chunks, next_chapter=None, opening_pages=None) -> tuple[str, list, str]:
    if (chapter.content or "").strip():
        if opening_pages:
            parts, prefix_spans = [], []
            for page in opening_pages:
                content = "\n".join(line for line in (page.text or "").splitlines() if _compact(line) != _compact(chapter.title))
                _append_part(parts, prefix_spans, content, page.page_number, page.page_number, deduplicate=False)
            prefix = "".join(parts)
            if prefix.strip() and _compact(prefix) not in _compact(chapter.content):
                offset = len(prefix) + 2
                spans = list(prefix_spans)
                original_spans = chapter.source_spans or [{
                    "chapter_start": 0, "chapter_end": len(chapter.content),
                    "page_start": chapter.page_start, "page_end": chapter.page_end,
                }]
                spans.extend({**span, "chapter_start": int(span.get("chapter_start", 0)) + offset,
                              "chapter_end": int(span.get("chapter_end", 0)) + offset} for span in original_spans)
                return prefix + "\n\n" + chapter.content, spans, "chapter_and_pages"
        return chapter.content, chapter.source_spans or [], "chapter"
    selected_pages = [page for page in pages if chapter.page_start <= page.page_number <= chapter.page_end]
    if selected_pages:
        parts, spans = [], []
        for index, page in enumerate(selected_pages):
            content = page.text or ""
            if index == 0 and chapter.title in content:
                content = content[content.index(chapter.title) + len(chapter.title):]
            if next_chapter and page.page_number == next_chapter.page_start and next_chapter.title in content:
                content = content[:content.index(next_chapter.title)]
            _append_part(parts, spans, content, page.page_number, page.page_number, deduplicate=False)
        if "".join(parts).strip():
            return "".join(parts), spans, "pages"
    parts, spans = [], []
    previous_path = []
    for chunk in chunks:
        path = [str(item) for item in (chunk.section_path or []) if str(item) != chapter.title]
        content = chunk.content or ""
        if path != previous_path:
            shared = 0
            while shared < min(len(path), len(previous_path)) and path[shared] == previous_path[shared]:
                shared += 1
            headings = [label for label in path[shared:] if _compact(label) not in _compact(content[:150])]
            if headings:
                content = "\n".join(headings) + "\n" + content
        _append_part(parts, spans, content, chunk.page_start, chunk.page_end)
        previous_path = path
    return "".join(parts), spans, "chunks" if parts else "missing"


def _heading(value: str):
    if _TOC_LINE.search(value):
        return None
    appendix = _APPENDIX.fullmatch(value)
    if appendix and appendix.group(1).strip(" |｜"):
        return 2, _clean_title(value), ""
    formal = _FORMAL_SECTION.match(value)
    if formal:
        # Page extraction sometimes puts a short title and its body on one line.
        tail = formal.group(1).strip()
        split = [tail] if len(_compact(tail)) <= 40 and not re.search(r"[。！？；;]", tail) else re.split(r"[\u2002\u2003]|\t| {3,}", tail, maxsplit=1)
        title = split[0].strip()
        if title and len(title) <= 50 and not re.search(r"[。！？；;]", title):
            return 2, _clean_title(value[:formal.start(1)] + title), split[1].strip() if len(split) > 1 else ""
    inline_numbered = _INLINE_NUMBERED.match(value)
    if inline_numbered and not _looks_like_numbered_prose(inline_numbered.group("title")):
        marker = inline_numbered.group("marker")
        label = marker + " " + inline_numbered.group("title") + (inline_numbered.group("english") or "")
        return 6 if marker.startswith(("（", "(")) else 5, _clean_title(label), inline_numbered.group("body").strip()
    found = _section_heading(value)
    if found:
        level, title, inline = found
        return level, _clean_title(title), inline
    return None


def _figure_label(match) -> str:
    return "图 " + unicodedata.normalize("NFKC", match.group(1)) + "-" + unicodedata.normalize("NFKC", match.group(2)) + match.group(3)


def _figure_locations(pages: list) -> dict[str, int]:
    locations = {}
    for page in pages:
        for line in (page.text or "").splitlines():
            value = line.strip()
            match = _FIGURE.match(value)
            if match:
                tail = value[match.end():].strip(" :：")
                # Standalone captions are stronger locations than an inline mention.
                if tail and len(tail) <= 80 and not re.search(r"[，。；、（）()]|所示|见图", tail):
                    locations.setdefault(_figure_label(match), page.page_number)
    return locations


def _is_reference_tail(value: str) -> bool:
    if _is_back_matter_heading(value):
        return True
    # Overprinted PDF headings can occur twice on the same line. Match only a
    # complete repeated bibliography heading, never a phrase inside prose.
    return bool(re.fullmatch(r"(推荐阅读|主要参考文献|参考文献|中英文名词对照索引)\1{1,3}", _compact(value)))


def _mark_navigation_units(records: list[dict]) -> None:
    """Expose real top-level reading units without calling them teaching priorities."""
    formal_indices = [index for index, record in enumerate(records) if record["formal_section"]]
    if formal_indices:
        selected = set(formal_indices)
    else:
        structural = [(index, record) for index, record in enumerate(records) if record["title"] != "本章正文"]
        top_level = min((record["level"] for _, record in structural), default=2)
        selected = {index for index, record in structural if record["level"] == top_level}
    selected.update(index for index, record in enumerate(records) if _APPENDIX.fullmatch(record["title"]))
    if not selected:
        selected.add(0)
    first = min(selected)
    # A chapter's independent introduction/learning objectives precede its first
    # top-level heading. Keep that block accessible as a separate reading unit.
    if first > 0 and sum(len(_compact(record["content"])) for record in records[:first]) >= 40:
        selected.add(0)
    for index, record in enumerate(records):
        record["navigation_unit"] = index in selected


def _section_records(chapter, source: str, spans: list, kind: str, book_title: str, figure_locations: dict) -> list[dict]:
    headers = {_compact(chapter.title), _compact(book_title)}
    records, stack = [], []
    current = None

    def new_record(title, level, offset):
        nonlocal current
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        record = {
            "id": f"{chapter.id}:section:{offset}", "title": title,
            "level": level, "parent_id": stack[-1]["id"] if stack else "",
            "formal_section": bool(_FORMAL_SECTION.fullmatch(title)),
            "_lines": [], "_start": offset, "_end": offset,
            "_source": source, "_spans": spans, "source_kind": kind,
        }
        records.append(record)
        stack.append(record)
        current = record

    lines = list(re.finditer(r"[^\n]+", source))
    for line in lines:
        value = _DECORATION.sub("", _clean(line.group())).strip()
        if not value or _compact(value) in headers or re.fullmatch(r"\d{1,4}", value) or _TOC_LINE.search(value) or _RUNNING_BANNER.fullmatch(_compact(value)):
            continue
        if _compact(value) in {"目录", "目次"}:
            continue
        if _is_reference_tail(value):
            break
        heading = _heading(value)
        if heading:
            level, title, inline = heading
            # Ignore a repeated running section header, retain its subsequent body.
            if not current or _compact(current["title"]) != _compact(title):
                new_record(title, level, line.start())
            if inline:
                at = line.group().find(inline)
                current["_lines"].append((line.start() + max(at, 0), line.end(), inline))
            current["_end"] = line.end()
        else:
            if current is None:
                new_record("本章正文", 2, line.start())
            current["_lines"].append((line.start(), line.end(), value))
            current["_end"] = line.end()

    if not records:
        new_record("本章正文", 2, 0)
    for record in records:
        paragraphs = []
        previous_end = None
        for start, end, text in record["_lines"]:
            if paragraphs:
                gap = source[previous_end:start]
                paragraphs.append("\n\n" if gap.count("\n") >= 2 else "\n")
            paragraphs.append(text)
            previous_end = end
        content = _clean("".join(paragraphs))
        record["content"] = content
        record["excerpt"] = re.sub(r"\s+", " ", content)[:180]
        fallback = (chapter.page_start or 0, chapter.page_end or chapter.page_start or 0)
        record["page_start"], record["page_end"] = _pages_for(spans, record["_start"], record["_end"], fallback)
        record["figure_refs"] = []
        seen = set()
        for start, _, text in record["_lines"]:
            for match in _FIGURE.finditer(text):
                label = _figure_label(match)
                if label in seen:
                    continue
                seen.add(label)
                mention_page = _pages_for(spans, start + match.start(), start + match.end(), fallback)[0]
                record["figure_refs"].append({
                    "label": label, "page_number": figure_locations.get(label, mention_page),
                    "location": "caption" if label in figure_locations else "reference",
                })
    _mark_navigation_units(records)
    return records


def _collect(db, textbook_id: str):
    book = db.get(Textbook, textbook_id)
    if book is None:
        raise TeachingSourceError(404, "教材不存在")
    chapters = db.query(Chapter).filter(Chapter.textbook_id == textbook_id).order_by(Chapter.order_index, Chapter.page_start, Chapter.id).all()
    pages = db.query(TextbookPage).filter(TextbookPage.textbook_id == textbook_id).order_by(TextbookPage.page_number).all()
    chunks = db.query(Chunk).filter(Chunk.textbook_id == textbook_id).order_by(Chunk.chunk_index, Chunk.id).all()
    by_chapter = {}
    for chunk in chunks:
        by_chapter.setdefault(chunk.chapter_id, []).append(chunk)
    locations = _figure_locations(pages)
    opening_prefixes = _opening_page_prefixes(chapters, pages)
    rows = []
    for index, chapter in enumerate(chapters):
        source, spans, kind = _chapter_source(chapter, pages, by_chapter.get(chapter.id, []), chapters[index + 1] if index + 1 < len(chapters) else None, opening_prefixes.get(chapter.id))
        records = _section_records(chapter, source, spans, kind, book.title, locations)
        rows.append((chapter, records))
    return book, pages, rows


def get_teaching_content(db, textbook_id: str) -> dict:
    book, pages, rows = _collect(db, textbook_id)
    chapters = [{
        "id": chapter.id, "title": _clean_title(chapter.title),
        "page_start": min([chapter.page_start] + [record["page_start"] for record in records if record["page_start"] > 0]), "page_end": chapter.page_end,
        "sections": [{key: value for key, value in record.items() if not key.startswith("_")} for record in records],
    } for chapter, records in rows]
    section_count = sum(len(chapter["sections"]) for chapter in chapters)
    formal_section_count = sum(section["formal_section"] for chapter in chapters for section in chapter["sections"])
    navigation_unit_count = sum(section["navigation_unit"] for chapter in chapters for section in chapter["sections"])
    recovered_openings = [
        {"chapter_id": chapter.id, "original_page_start": chapter.page_start,
         "page_start": min(record["page_start"] for record in records if record["page_start"] > 0)}
        for chapter, records in rows
        if any(record["source_kind"] == "chapter_and_pages" for record in records)
    ]
    missing = [chapter.id for chapter, records in rows if not any(row["content"] for row in records)]
    warnings = list(book.parse_warnings or [])
    if missing:
        warnings.append(f"{len(missing)} 个章节缺少已解析正文；请查看原页，不能据此认定本章内容已覆盖。")
    has_pdf = False
    try:
        resolve_pdf_path(book)
        has_pdf = True
    except TeachingSourceError:
        pass
    if not has_pdf:
        warnings.append("原 PDF 不可用，当前只能阅读已保存文本。")
    return {
        "textbook_id": book.id, "title": book.title, "total_pages": book.total_pages,
        "has_pdf": has_pdf, "chapters": chapters,
        "readiness": {
            "chapter_count": len(chapters), "section_count": section_count,
            "formal_section_count": formal_section_count,
            "navigation_unit_count": navigation_unit_count,
            "recovered_openings": recovered_openings,
            "chapters_with_text": len(chapters) - len(missing), "missing_chapter_ids": missing,
            "stored_page_count": len(pages), "source": "stored_text",
            "status": "text_available" if section_count and not missing else "partial",
            "is_teaching_priority_reviewed": False,
            "message": "按教材正文标题整理，未自动判断教学重点；图号定位不代表图像内容已审核。",
            "warnings": warnings,
        },
    }


def _match_offsets(value: str, query: str):
    chars, positions = [], []
    for index, char in enumerate(value):
        folded = _compact(char)
        chars.extend(folded)
        positions.extend([index] * len(folded))
    at = "".join(chars).find(query)
    if at < 0:
        return None
    return positions[at], positions[at + len(query) - 1] + 1


def _topic_key(value: str) -> str:
    """Normalize heading decoration for ranking, without changing recall or text."""
    value = unicodedata.normalize("NFKC", value or "").strip()
    value = re.sub(r"^(?:第\s*[一二三四五六七八九十百千\d]+\s*[章节]|[一二三四五六七八九十百]+\s*[、.]|\([一二三四五六七八九十百\d]+\)|\d{1,3}[.、])\s*", "", value)
    if re.search(r"[\u4e00-\u9fff]", value):
        # Remove recognizable English translations, keeping chemical symbols and
        # uppercase medical abbreviations (e.g. C, B12, DNA) as part of a topic.
        value = re.sub(r"\((?=[^)]*[a-z])[A-Za-z][A-Za-z0-9 /,-]*\)", "", value)
        value = re.sub(r"\s*[A-Za-z][a-z][A-Za-z0-9 /,-]*$", "", value)
    return _compact(value)


def search_teaching_content(db, textbook_id: str, query: str, limit: int = 20) -> dict:
    clean_query = _compact(query)
    query_topic = _topic_key(query)
    if not clean_query:
        raise TeachingSourceError(422, "请输入教材内的章节标题或关键词")
    _, _, rows = _collect(db, textbook_id)
    results = []
    for chapter, records in rows:
        chapter_exact = bool(query_topic and _topic_key(chapter.title) == query_topic)
        first_unit_id = next((record["id"] for record in records if record["navigation_unit"]), None)
        for record in records:
            title_match = clean_query in _compact(record["title"])
            matching = None
            for start, end, text in record["_lines"]:
                offsets = _match_offsets(text, clean_query)
                if offsets:
                    matching = start + offsets[0], start + offsets[1], text, offsets[0]
                    break
            if matching is None:
                raw = record["_source"][record["_start"]:record["_end"]]
                offsets = _match_offsets(raw, clean_query)
                if offsets:
                    matching = record["_start"] + offsets[0], record["_start"] + offsets[1], raw, offsets[0]
            if not title_match and matching is None:
                continue
            first, last = record["page_start"], record["page_end"]
            excerpt = record["excerpt"]
            if matching:
                start, end, line, at = matching
                first, last = _pages_for(record["_spans"], start, end, (first, last))
                excerpt = ("…" if at > 60 else "") + line[max(0, at - 60):at + 180]
            if chapter_exact and (record["title"] == "本章正文" or record["id"] == first_unit_id):
                rank = (0, 0)
            elif query_topic and _topic_key(record["title"]) == query_topic:
                rank = (1, 0)
            elif chapter_exact:
                rank = (2, 0)
            else:
                rank = (3 if title_match else 4, 0)
            results.append({
                "id": record["id"], "section_id": record["id"], "title": record["title"],
                "chapter_id": chapter.id, "chapter_title": _clean_title(chapter.title),
                "page_start": first, "page_end": last, "excerpt": excerpt,
                "_rank": rank,
            })
    results.sort(key=lambda row: row["_rank"])
    return {"query": query.strip(), "items": [{key: value for key, value in item.items() if not key.startswith("_")} for item in results[:max(1, min(limit, 50))]], "total": len(results)}


def resolve_pdf_path(book) -> Path:
    filename = str(book.filename or "")
    if book.format.lower() != "pdf" or not filename or Path(filename).suffix.lower() != ".pdf":
        raise TeachingSourceError(404, "本教材没有可用的原 PDF")
    # Stored filenames are untrusted too. Disallow absolute paths and path components.
    if Path(filename).name != filename or "/" in filename or "\\" in filename or ":" in filename:
        raise TeachingSourceError(404, "原 PDF 路径不可用")
    for directory in (TEXTBOOK_ROOT, LEGACY_TEXTBOOK_ROOT):
        root = directory.resolve()
        path = (root / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        if path.stat().st_size > MAX_PDF_BYTES:
            raise TeachingSourceError(413, "原 PDF 超过在线预览大小限制")
        return path
    raise TeachingSourceError(404, "原 PDF 文件不存在")


@lru_cache(maxsize=8)
def _render_page(path: str, file_size: int, modified_ns: int, page_number: int) -> bytes:
    import fitz

    try:
        with fitz.open(path) as document:
            if not document.is_pdf:
                raise TeachingSourceError(415, "源文件不是有效 PDF")
            if document.needs_pass:
                raise TeachingSourceError(422, "PDF 已加密，无法预览")
            if page_number < 1 or page_number > document.page_count:
                raise TeachingSourceError(404, "该物理页码不存在")
            page = document.load_page(page_number - 1)
            width, height = page.rect.width, page.rect.height
            if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                raise TeachingSourceError(422, "PDF 页面尺寸无效")
            # A small margin accounts for MuPDF rounding pixel edges upward.
            scale = min((MAX_IMAGE_SIDE - 2) / max(width, height), math.sqrt((MAX_IMAGE_PIXELS - 2 * MAX_IMAGE_SIDE) / (width * height)), 2.0)
            for _ in range(3):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
                data = pixmap.tobytes("png")
                if len(data) <= MAX_IMAGE_BYTES:
                    return data
                scale *= 0.65
            raise TeachingSourceError(413, "该页图像超过预览大小限制")
    except TeachingSourceError:
        raise
    except Exception as exc:
        raise TeachingSourceError(422, "无法读取原 PDF 页面，请检查文件是否损坏") from exc


def render_teaching_page(db, textbook_id: str, page_number: int) -> tuple[bytes, str]:
    book = db.get(Textbook, textbook_id)
    if book is None:
        raise TeachingSourceError(404, "教材不存在")
    if page_number < 1:
        raise TeachingSourceError(422, "物理页码必须从 1 开始")
    path = resolve_pdf_path(book)
    stat = path.stat()
    data = _render_page(str(path), stat.st_size, stat.st_mtime_ns, page_number)
    return data, hashlib.sha256(data).hexdigest()
