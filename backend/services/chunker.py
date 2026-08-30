import hashlib
import re
from backend.config import CHUNK_SIZE, CHUNK_OVERLAP
from backend.database import SessionLocal, Chapter, Chunk, Textbook


_CN_NUMERALS = "一二三四五六七八九十百千"
_SECTION_PATTERNS = (
    (2, re.compile(rf"^第\s*[{_CN_NUMERALS}\d０-９]+\s*节(?:\s*[|｜]\s*)?\s*(.+)?$")),
    (3, re.compile(rf"^[{_CN_NUMERALS}]+\s*[、.]\s*(.+)$")),
    (4, re.compile(rf"^[（(][{_CN_NUMERALS}]+[）)]\s*(.+)$")),
    (5, re.compile(r"^\d{1,2}(?:\.\s+|、\s*)(.+)$")),
    (6, re.compile(r"^【([^】]{1,40})】$")),
    (5, re.compile(r"^#{3,6}\s+(.+)$")),
)
_LIST_ITEM_PATTERN = re.compile(r"^(?:[（(]\d{1,2}[）)]|[①-⑳]|[A-Za-z][.)])\s*")
_BACK_MATTER_PATTERN = re.compile(
    r"^(?:主要)?参考文献$|^推荐阅读$|^(?:中英文|中文|英文)?(?:名词对照)?索引$"
)
_BACK_MATTER_PREFIXES = ("主要参考文献", "参考文献", "推荐阅读", "本章目标测试")
_DECORATION_PATTERN = re.compile(
    r"^(?:本章)?(?:数字资源|思维导图|学习目标|目标测试|扫码看视频|解题思路)$"
)
_SENTENCE_END_PATTERN = re.compile(r"[。！？!?；;](?:[”’\"』】）)]*)")
_INCOMPLETE_TITLE_END_PATTERN = re.compile(r"[-‐‑‒–—−] *$")
_INSTRUCTION_TITLE_PATTERN = re.compile(
    r"^(?:了解|熟悉|掌握|早日|及时|正确|合理|应当|应用)"
)
_STRONG_PROSE_HEADING_PATTERN = re.compile(
    r"(?:肿瘤呈|符合下列|即可诊断|可摸到|肺门部见|发病灶.{0,24}淋巴结)"
)


def _is_back_matter_heading(value: str) -> bool:
    """Recognize a standalone tail heading without truncating ordinary prose."""
    compact = _compact_heading(value)
    if _BACK_MATTER_PATTERN.fullmatch(compact):
        return True
    for prefix in _BACK_MATTER_PREFIXES:
        if not compact.startswith(prefix):
            continue
        suffix = compact[len(prefix):]
        if re.fullmatch(r"(?:[：:]?(?:references?|continued|续)|[（(][^）)]{1,16}[）)]|[…·.―—-]+)", suffix, re.I):
            return True
    return False


def _looks_like_numbered_prose(value: str) -> bool:
    """Reject ambiguous numbered prose while keeping the complete source line."""
    candidate = re.sub(r"\s+", " ", value or "").strip()
    if not candidate:
        return True
    if _INCOMPLETE_TITLE_END_PATTERN.search(candidate):
        return True
    if re.search(r"[，,。！？；;：:]", candidate):
        return True
    if _INSTRUCTION_TITLE_PATTERN.match(candidate) or _STRONG_PROSE_HEADING_PATTERN.search(candidate):
        return True
    return bool(re.search(
        r".{2,}(?:是|为|由|具有|导致|引起|参与|产生|构成|组成|内有|含有|位于|分布于|包括|根据|可见|可分|可摸到)",
        candidate,
    ))


def _looks_like_parenthetical_prose(value: str) -> bool:
    candidate = re.sub(r"\s+", " ", value or "").strip()
    return bool(_STRONG_PROSE_HEADING_PATTERN.search(candidate))

def chunk_textbook(textbook_id: str) -> int:
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == textbook_id).first()
        if not book:
            return 0

        chapters = db.query(Chapter).filter(
            Chapter.textbook_id == textbook_id
        ).order_by(Chapter.order_index, Chapter.page_start).all()
        existing = db.query(Chunk).filter(Chunk.textbook_id == textbook_id).count()
        if existing > 0:
            return existing

        total = 0
        for ch in chapters:
            chunks = _split_semantic_text_with_offsets(
                ch.content,
                CHUNK_SIZE,
                CHUNK_OVERLAP,
                chapter_title=ch.title,
                textbook_title=book.title,
            )
            for idx, (start, end, chunk_text, section_path) in enumerate(chunks):
                page_start, page_end = _pages_for_range(
                    ch.source_spans or [], start, end, ch.page_start, ch.page_end
                )
                chunk = Chunk(
                    id=f"{ch.id}_chunk_{idx:04d}",
                    textbook_id=textbook_id,
                    chapter_id=ch.id,
                    textbook_title=book.title,
                    chapter_title=ch.title,
                    page_start=page_start,
                    page_end=page_end,
                    content=chunk_text,
                    char_count=len(chunk_text),
                    chunk_index=idx,
                    section_path=section_path,
                    content_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                )
                db.add(chunk)
                total += 1

        book.index_status = "completed"
        db.commit()
        from backend.services.retrieval_service import invalidate_course_cache
        invalidate_course_cache(book.course_id)
        return total
    finally:
        db.close()

def _split_text(text: str, chunk_size: int, overlap: int) -> list:
    """Backward-compatible wrapper used by older scripts and tests."""
    return [chunk for _, _, chunk in _split_text_with_offsets(text, chunk_size, overlap)]


def _split_text_with_offsets(text: str, chunk_size: int, overlap: int):
    """Backward-compatible triple output for older callers and page-offset tests."""
    return [
        (start, end, content)
        for start, end, content, _ in _split_semantic_text_with_offsets(
            text,
            chunk_size,
            overlap,
        )
    ]


def _split_semantic_text_with_offsets(
    text: str,
    chunk_size: int,
    overlap: int,
    chapter_title: str = "",
    textbook_title: str = "",
):
    """Split by section and complete semantic units while retaining source offsets."""
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    overlap = max(0, min(overlap, chunk_size // 3))
    soft_target = max(80, int(chunk_size * 0.8))
    hard_limit = max(chunk_size, int(chunk_size * 1.25))
    base_path = [chapter_title] if chapter_title else []
    units = _semantic_units(
        text,
        base_path=base_path,
        repeated_headers=[chapter_title, textbook_title],
        hard_limit=hard_limit,
    )
    if not units:
        return []

    chunks = []
    group_start = 0
    while group_start < len(units):
        group_path = _structural_group_key(units[group_start][3])
        group_end = group_start + 1
        while (
            group_end < len(units)
            and _structural_group_key(units[group_end][3]) == group_path
        ):
            group_end += 1
        chunks.extend(_pack_unit_group(
            units[group_start:group_end],
            target_size=soft_target,
            hard_limit=hard_limit,
            overlap=overlap,
        ))
        group_start = group_end
    return chunks


def _semantic_units(text, base_path, repeated_headers, hard_limit):
    """Create complete sentences/list items and attach the active heading hierarchy."""
    lines = [
        {
            "start": match.start(),
            "end": match.end(),
            "text": match.group(0).strip(),
        }
        for match in re.finditer(r"[^\n]*(?:\n|$)", text)
        if match.group(0)
    ]
    header_keys = {_compact_heading(value) for value in repeated_headers if value}
    path = list(base_path)
    units = []
    buffer = []

    def flush_buffer():
        nonlocal buffer
        if not buffer:
            return
        start = buffer[0]["start"]
        end = buffer[-1]["end"]
        raw = text[start:end]
        units.extend(_sentence_units(raw, start, list(path), hard_limit))
        buffer = []

    index = 0
    while index < len(lines):
        line = lines[index]
        value = line["text"].strip()
        if not value:
            index += 1
            continue
        compact_value = _compact_heading(value)
        if _is_back_matter_heading(value):
            flush_buffer()
            break
        if _DECORATION_PATTERN.fullmatch(_compact_heading(value)) or re.fullmatch(r"\d{1,4}", value):
            flush_buffer()
            index += 1
            continue

        combined_header = ""
        if index + 1 < len(lines):
            combined_header = _compact_heading(value + lines[index + 1]["text"])
        if _compact_heading(value) in header_keys or combined_header in header_keys:
            buffered_text = _compact_heading("".join(item["text"] for item in buffer))
            if buffered_text and len(buffered_text) <= 4 and any(
                buffered_text in header for header in header_keys
            ):
                buffer = []
            else:
                flush_buffer()
            index += 2 if combined_header in header_keys else 1
            continue

        heading = _section_heading(value)
        if heading:
            flush_buffer()
            level, label, inline_body = heading
            path = [entry for entry in path if entry[0] < level] if path and isinstance(path[0], tuple) else _path_to_levels(path)
            path = [entry for entry in path if entry[0] < level]
            path.append((level, _clean_heading_label(label)))
            raw_line = text[line["start"]:line["end"]]
            if inline_body:
                inline_at = raw_line.find(inline_body)
                if inline_at >= 0:
                    _append_source_unit(
                        units,
                        raw_line[:inline_at],
                        line["start"],
                        list(path),
                    )
                    buffer.append({
                        "start": line["start"] + inline_at,
                        "end": line["end"],
                        "text": inline_body,
                    })
                else:
                    # PDF whitespace normalization can make the cleaned body
                    # differ from the raw source (for example two ASCII spaces
                    # collapse to one). Never drop the complete evidence line
                    # merely because a normalized substring cannot be located.
                    _append_source_unit(units, raw_line, line["start"], list(path))
            else:
                # Keep the original heading as evidence. A standalone chunk must
                # remain understandable without relying on hidden metadata.
                _append_source_unit(units, raw_line, line["start"], list(path))
            index += 1
            continue

        if _LIST_ITEM_PATTERN.match(value):
            flush_buffer()
        buffer.append(line)
        index += 1

    flush_buffer()
    normalized = []
    for start, end, content, unit_path in units:
        labels = []
        for entry in unit_path:
            label = entry[1] if isinstance(entry, tuple) else entry
            if label and (not labels or _compact_heading(labels[-1]) != _compact_heading(label)):
                labels.append(label)
        normalized.append((start, end, content, labels))
    return normalized


def _path_to_levels(path):
    """Convert the chapter-only public path to an internal levelled path."""
    return [(1, value) for value in path if value]


def _structural_group_key(path):
    """Keep hard sections separate while allowing short child items to cohere."""
    values = tuple(path or [])
    return values[:2] if len(values) >= 2 else values


def _common_path(paths):
    if not paths:
        return []
    prefix = list(paths[0])
    for path in paths[1:]:
        limit = min(len(prefix), len(path))
        keep = 0
        while keep < limit and prefix[keep] == path[keep]:
            keep += 1
        prefix = prefix[:keep]
        if not prefix:
            break
    return prefix


def _chunk_common_path(units):
    """Ignore heading-only context, but retain substantive parent-level prose."""
    semantic_paths = [
        item[3]
        for item in units
        if not (
            item[3]
            and _compact_heading(item[2]) == _compact_heading(item[3][-1])
        )
    ]
    return _common_path(semantic_paths or [item[3] for item in units])


def _append_source_unit(units, raw, base_offset, path):
    left_trim = len(raw) - len(raw.lstrip())
    right_length = len(raw.rstrip())
    content = raw.strip()
    if content:
        units.append((
            base_offset + left_trim,
            base_offset + right_length,
            content,
            list(path),
        ))


def _section_heading(value):
    compact = re.sub(r"[ \t]+", " ", value or "").strip()
    inline_parenthetical = re.match(
        rf"^(?P<label>[（(](?P<marker>\d{{1,2}}|[{_CN_NUMERALS}]+)[）)]\s*[^：:]{{1,32}})[：:]\s*(?P<body>.+)$",
        compact,
    )
    if inline_parenthetical:
        label = inline_parenthetical.group("label")
        if _looks_like_parenthetical_prose(label):
            return None
        marker = inline_parenthetical.group("marker")
        level = 6 if re.fullmatch(r"\d{1,2}", marker) else 4
        return level, label, inline_parenthetical.group("body").strip()
    has_inline_numeric_body = bool(re.match(r"^\d{1,2}\.\s+", compact) and re.search(r"[\u2002\u2003]", compact))
    if (
        not compact
        or len(compact) > 72
        or (re.search(r"[。！？；;]$", compact) and not has_inline_numeric_body)
    ):
        return None
    for level, pattern in _SECTION_PATTERNS:
        match = pattern.fullmatch(compact)
        if not match:
            continue
        if level in (3, 4) and (len(compact) > 52 or re.search(r"[。！？；;]", compact)):
            continue
        if level in (3, 4) and _looks_like_parenthetical_prose(compact):
            continue
        inline_body = ""
        label = compact
        if level == 5 and re.match(r"^\d", compact):
            numeric = re.match(r"^(\d{1,2}(?:\.\s+|、\s*))(.*)$", compact)
            rest = numeric.group(2) if numeric else ""
            inline_parts = re.split(r"[\u2002\u2003]", rest, maxsplit=1)
            if len(inline_parts) == 2:
                title, inline_body = inline_parts
                if _looks_like_numbered_prose(title):
                    continue
                label = f"{numeric.group(1)}{title}" if numeric else compact
            elif _looks_like_numbered_prose(rest):
                # Bare numeric lines are ambiguous in extracted PDFs. When a
                # prose predicate is present, retain the entire line as source
                # text instead of silently swallowing it into section_path.
                continue
            if len(re.sub(r"\s+", " ", label).strip()) > 32:
                continue
        elif level == 5 and not compact.startswith(("【", "#")) and len(compact) > 32:
            continue
        return level, label, inline_body.strip()
    return None


def _clean_heading_label(value):
    return re.sub(r"\s+", " ", (value or "").replace("｜", "|")).strip(" |")


def _compact_heading(value):
    return re.sub(r"[\s|｜]+", "", value or "").strip()


def _sentence_units(raw, base_offset, path, hard_limit):
    boundaries = [match.end() for match in _SENTENCE_END_PATTERN.finditer(raw)]
    units = []
    cursor = 0
    for boundary in boundaries + [len(raw)]:
        if boundary <= cursor:
            continue
        _append_unit_slices(units, raw, cursor, boundary, base_offset, path, hard_limit)
        cursor = boundary
    return units


def _append_unit_slices(units, raw, start, end, base_offset, path, hard_limit):
    while start < end:
        candidate_end = min(end, start + hard_limit)
        if candidate_end < end:
            weak_boundaries = [
                index + 1
                for index in range(start + hard_limit // 2, candidate_end)
                if raw[index] in "，、：,:\n"
            ]
            if weak_boundaries:
                candidate_end = weak_boundaries[-1]
        segment = raw[start:candidate_end]
        left_trim = len(segment) - len(segment.lstrip())
        right_length = len(segment.rstrip())
        content = segment.strip()
        if content:
            units.append((
                base_offset + start + left_trim,
                base_offset + start + right_length,
                content,
                list(path),
            ))
        start = candidate_end


def _pack_unit_group(units, target_size, hard_limit, overlap):
    chunks = []
    index = 0
    while index < len(units):
        selected = []
        length = 0
        cursor = index
        while cursor < len(units):
            addition = len(units[cursor][2]) + (1 if selected else 0)
            if selected and length + addition > hard_limit:
                break
            selected.append(units[cursor])
            length += addition
            cursor += 1
            if length >= target_size:
                break
        if cursor < len(units):
            remaining_length = sum(len(item[2]) for item in units[cursor:]) + max(0, len(units) - cursor - 1)
            minimum_tail = max(80, target_size // 4)
            if remaining_length < minimum_tail and length + 1 + remaining_length <= hard_limit:
                selected.extend(units[cursor:])
                length += 1 + remaining_length
                cursor = len(units)
        if not selected:
            selected = [units[index]]
            cursor = index + 1
        chunks.append((
            selected[0][0],
            selected[-1][1],
            "\n".join(item[2] for item in selected),
            _chunk_common_path(selected),
        ))
        if cursor >= len(units):
            break
        next_index = cursor
        overlap_size = 0
        while next_index > index + 1:
            addition = len(units[next_index - 1][2]) + (1 if overlap_size else 0)
            if overlap_size + addition > overlap:
                break
            overlap_size += addition
            next_index -= 1
        if next_index < cursor:
            next_unseen_size = len(units[cursor][2]) + 1
            # Never emit an overlap-only suffix chunk. If the overlap prefix
            # leaves no room for the next unseen unit, advance to the frontier
            # instead of repeatedly peeling smaller suffixes from the same end.
            index = cursor if overlap_size + next_unseen_size > hard_limit else next_index
        else:
            index = cursor
    return chunks


def _pages_for_range(source_spans, start, end, fallback_start, fallback_end):
    pages = [
        int(span["page_number"])
        for span in source_spans
        if int(span.get("chapter_end", 0)) > start
        and int(span.get("chapter_start", 0)) < end
    ]
    if not pages:
        return fallback_start, fallback_end
    return min(pages), max(pages)
