import re
import hashlib
from pathlib import Path
from backend.database import SessionLocal, Textbook, TextbookPage, Chapter


CHAPTER_HEADING_PATTERN = re.compile(
    r"(?m)^(?:第[ \t]*[一二三四五六七八九十百千\d０-９]+[ \t]*章[ \t]*[^\n]*|Chapter[ \t]+\d+[ \t]*[^\n]*|#{1,2}[ \t]+[^\n]+)$",
    re.IGNORECASE,
)
PDF_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

def parse_textbook(file_path: str, textbook_id: str) -> dict:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(file_path, textbook_id)
    elif ext in (".md", ".txt"):
        return _parse_text(file_path, textbook_id)
    else:
        raise ValueError(f"Unsupported format: {ext}")

def _parse_text(file_path: str, textbook_id: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Plain text has no physical pages. Keep page 1 instead of inventing page numbers.
    pages = [{
        "page_number": 1,
        "printed_page_number": "",
        "text": content,
        "extraction_method": "text",
    }]
    chapters = _split_by_headings_with_pages(pages)
    total_chars = sum(c["char_count"] for c in chapters)
    return {
        "textbook_id": textbook_id,
        "total_pages": 1,
        "total_chars": total_chars,
        "pages": pages,
        "chapters": chapters,
        "warnings": ["TXT/Markdown 不包含物理页码，引用统一标记为第 1 页。"],
    }

def _parse_pdf(file_path: str, textbook_id: str) -> dict:
    """Page-level PDF parsing with proper page tracking."""
    pages = []
    extraction_method = "native"
    try:
        import fitz
        doc = fitz.open(file_path)
        try:
            for i, page in enumerate(doc):
                pages.append({
                    "page_number": i + 1,
                    "printed_page_number": "",
                    # Geometry-aware sorting keeps visual headings before the body.
                    # Without it, several chapter titles are emitted near the page end
                    # and the opening paragraphs are assigned to the previous chapter.
                    "text": page.get_text("text", sort=True) or "",
                    "extraction_method": "native",
                })
        finally:
            doc.close()
    except Exception:
        import pypdf
        # Discard a partially extracted fitz result before retrying the whole
        # document, otherwise page numbers and text are duplicated.
        pages = []
        extraction_method = "pypdf"
        reader = pypdf.PdfReader(file_path)
        for i, page in enumerate(reader.pages):
            pages.append({
                "page_number": i + 1,
                "printed_page_number": "",
                "text": page.extract_text() or "",
                "extraction_method": extraction_method,
            })

    total_pages = len(pages)
    cleaned_pages = []
    empty_pages = 0
    repaired_pages = 0
    repaired_characters = 0
    for page in pages:
        raw_text = page["text"] or ""
        bad_character_count = len(PDF_CONTROL_PATTERN.findall(raw_text)) + raw_text.count("\uFFFD")
        if bad_character_count:
            repaired_pages += 1
            repaired_characters += bad_character_count
        cleaned_text = _clean_text(page["text"])
        if not cleaned_text:
            empty_pages += 1
        cleaned_pages.append({**page, "text": cleaned_text})

    chapters = _split_by_headings_with_pages(cleaned_pages)

    total_chars = sum(c["char_count"] for c in chapters)
    warnings = []
    if total_pages == 0:
        warnings.append("PDF 没有可解析页面。")
    elif empty_pages / total_pages >= 0.3:
        warnings.append(f"{empty_pages}/{total_pages} 页没有可提取文本，可能需要 OCR。")
    if repaired_characters:
        warnings.append(
            f"已清理 {repaired_pages} 页中的 {repaired_characters} 个 PDF 隐藏控制字符；"
            "清理后的原文已用于知识点和引用。"
        )

    return {
        "textbook_id": textbook_id,
        "total_pages": total_pages,
        "total_chars": total_chars,
        "pages": cleaned_pages,
        "chapters": chapters,
        "warnings": warnings,
    }

def _split_by_headings_with_pages(page_list: list[dict]) -> list:
    """Split on page-local heading positions so citations retain physical pages."""
    markers = []
    for page_index, page in enumerate(page_list):
        for match in CHAPTER_HEADING_PATTERN.finditer(page["text"]):
            title = match.group(0).lstrip("#").strip()
            if not _is_valid_chapter_heading(title):
                continue
            markers.append({
                "page_index": page_index,
                "page_number": page["page_number"],
                "start": match.start(),
                "end": match.end(),
                "title": title,
            })

    if not markers:
        return _fallback_page_groups(page_list)

    markers, skipped_front_matter = _select_chapter_markers(markers)
    if not markers:
        return _fallback_page_groups(page_list)

    chapters = []
    first = markers[0]
    intro_text, intro_pages, intro_spans = _slice_page_range(page_list, None, first)
    if not skipped_front_matter and len(intro_text) > 200 and intro_pages:
        chapters.append(_chapter_record(len(chapters), "绪论/前言", intro_text, intro_pages, intro_spans))

    for marker_index, marker in enumerate(markers):
        next_marker = markers[marker_index + 1] if marker_index + 1 < len(markers) else None
        body, body_pages, body_spans = _slice_page_range(page_list, marker, next_marker)
        if len(body) < 50 or not body_pages:
            continue
        chapters.append(_chapter_record(len(chapters), marker["title"], body, body_pages, body_spans))

    return chapters or _fallback_page_groups(page_list)


def _is_valid_chapter_heading(title: str) -> bool:
    """Reject sentence fragments such as “第14章）。肝...” at line starts."""
    value = re.sub(r"\s+", " ", title or "").strip()
    match = re.match(
        r"^第\s*[一二三四五六七八九十百千\d]+\s*章\s*(.*)$",
        value,
        re.IGNORECASE,
    )
    if not match:
        return True
    suffix = match.group(1).strip()
    if not suffix:
        return True
    if suffix[0] in "）)】]。，,；;！？":
        return False
    clean_suffix = re.split(r"(?:\.{4,}|…{2,})", suffix, maxsplit=1)[0].strip()
    return 1 <= len(clean_suffix) <= 40 and not re.search(r"[。！？；;]", clean_suffix)


def _chapter_identity(title: str) -> str:
    normalized = re.sub(r"\s+", "", title or "")
    match = re.match(r"第([一二三四五六七八九十百千\d]+)章", normalized)
    if match:
        return f"zh:{match.group(1)}"
    match = re.match(r"chapter(\d+)", normalized, re.IGNORECASE)
    return f"en:{match.group(1)}" if match else normalized.lower()


def _chapter_number(identity: str) -> int | None:
    if identity.startswith("en:") and identity[3:].isdigit():
        return int(identity[3:])
    if not identity.startswith("zh:"):
        return None
    value = identity[3:]
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in digits:
        return digits[value]
    if value.startswith("十"):
        return 10 + digits.get(value[1:], 0)
    if value.endswith("十"):
        return digits.get(value[0], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return None


def _select_chapter_markers(markers: list[dict]) -> tuple[list[dict], bool]:
    """Ignore TOC markers and repeated running headers, keeping one real start per chapter."""
    identities = [_chapter_identity(marker["title"]) for marker in markers]
    numbers = [_chapter_number(identity) for identity in identities]
    content_start = 0
    highest_seen = 0
    for index, number in enumerate(numbers):
        if number is None:
            continue
        identity = identities[index]
        repeated_first = identity in identities[:index]
        later_second = any(later == 2 for later in numbers[index + 1:])
        if number == 1 and highest_seen >= 2 and repeated_first and later_second:
            content_start = index
            break
        highest_seen = max(highest_seen, number)

    selected = []
    selected_index = {}
    for marker, identity in zip(markers[content_start:], identities[content_start:]):
        clean_title = re.sub(r"\s+", " ", marker["title"]).strip()
        if identity in selected_index:
            current = selected[selected_index[identity]]
            if len(clean_title) > len(current["title"]):
                current["title"] = clean_title
            continue
        selected_index[identity] = len(selected)
        selected.append({
            **marker,
            "title": clean_title,
        })
    return selected, content_start > 0


def _slice_page_range(page_list: list[dict], start_marker: dict | None, end_marker: dict | None):
    start_page_index = start_marker["page_index"] if start_marker else 0
    end_page_index = end_marker["page_index"] if end_marker else len(page_list) - 1
    segments = []
    page_numbers = []
    spans = []
    chapter_offset = 0
    for page_index in range(start_page_index, end_page_index + 1):
        page = page_list[page_index]
        start = start_marker["end"] if start_marker and page_index == start_page_index else 0
        end = end_marker["start"] if end_marker and page_index == end_page_index else len(page["text"])
        segment = page["text"][start:end].strip()
        if segment:
            if segments:
                chapter_offset += 2
            segments.append(segment)
            page_numbers.append(page["page_number"])
            spans.append({
                "page_number": page["page_number"],
                "chapter_start": chapter_offset,
                "chapter_end": chapter_offset + len(segment),
            })
            chapter_offset += len(segment)
    return "\n\n".join(segments), page_numbers, spans


def _chapter_record(
    index: int,
    title: str,
    content: str,
    page_numbers: list[int],
    source_spans: list[dict] | None = None,
):
    return {
        "chapter_id": f"ch_{index:03d}",
        "title": title,
        "page_start": min(page_numbers),
        "page_end": max(page_numbers),
        "content": content,
        "char_count": len(content),
        "order_index": index,
        "level": 1,
        "review_status": "unreviewed",
        "source_spans": source_spans or [],
    }


def _fallback_page_groups(page_list: list[dict]) -> list:
    total_pages = len(page_list)
    if total_pages == 0:
        return []
    group_size = max(1, min(10, (total_pages + 9) // 10))
    chapters = []
    for start in range(0, total_pages, group_size):
        group = page_list[start:start + group_size]
        content = "\n\n".join(page["text"] for page in group if page["text"])
        if len(content) < 50:
            continue
        page_numbers = [page["page_number"] for page in group]
        chapters.append(_chapter_record(
            len(chapters),
            f"第{min(page_numbers)}-{max(page_numbers)}页",
            content,
            page_numbers,
            _full_page_spans(group),
        ))
    return chapters


def _full_page_spans(pages: list[dict]):
    spans = []
    chapter_offset = 0
    has_segment = False
    for page in pages:
        segment = page["text"].strip()
        if not segment:
            continue
        if has_segment:
            chapter_offset += 2
        spans.append({
            "page_number": page["page_number"],
            "chapter_start": chapter_offset,
            "chapter_end": chapter_offset + len(segment),
        })
        chapter_offset += len(segment)
        has_segment = True
    return spans

def _clean_text(text: str) -> str:
    # PDF 字体映射经常混入退格、私有控制符和 Unicode replacement glyph。
    # 它们会在模型往返后被放大成连续乱码，因此必须在章节、chunk 和知识点之前清理。
    text = PDF_CONTROL_PATTERN.sub(" ", text or "")
    text = text.replace("\uFFFD", " ")
    text = re.sub(r'\n\d+\n', '\n', text)
    text = re.sub(r'^\d+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _split_by_headings(text: str) -> list:
    pattern = r'(第[一二三四五六七八九十百千\d]+章\s*[^\n]*)'
    parts = re.split(pattern, text)
    chapters = []
    ch_idx = 0

    if parts and not re.match(pattern, parts[0]):
        intro_text = parts[0].strip()
        if len(intro_text) > 200:
            chapters.append({
                "chapter_id": f"ch_{ch_idx:03d}",
                "title": "绪论/前言",
                "page_start": 1, "page_end": 1,
                "content": intro_text,
                "char_count": len(intro_text)
            })
            ch_idx += 1

    for i in range(1, len(parts), 2):
        title = parts[i].strip() if i < len(parts) else "未命名章节"
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if len(body) < 50:
            continue
        chapters.append({
            "chapter_id": f"ch_{ch_idx:03d}",
            "title": title,
            "page_start": 1, "page_end": 1,
            "content": body,
            "char_count": len(body)
        })
        ch_idx += 1

    if not chapters:
        chunk_size = max(200, len(text) // 10)
        for i in range(0, len(text), chunk_size):
            seg = text[i:i + chunk_size]
            chapters.append({
                "chapter_id": f"ch_{ch_idx:03d}",
                "title": f"第{ch_idx + 1}部分",
                "page_start": 1, "page_end": 1,
                "content": seg,
                "char_count": len(seg)
            })
            ch_idx += 1

    return chapters

def save_parsed_textbook(book_data: dict, filename: str, file_size: int, fmt: str):
    db = SessionLocal()
    try:
        book = db.query(Textbook).filter(Textbook.id == book_data["textbook_id"]).first()
        if book is None:
            book = Textbook(
                id=book_data["textbook_id"],
                filename=filename,
                original_filename=filename,
                title=_extract_title(filename),
                format=fmt,
                file_size=file_size,
            )
            db.add(book)
        # Preserve upload metadata such as course_id, original title and content hash.
        book.total_pages = book_data["total_pages"]
        book.total_chars = book_data["total_chars"]
        book.parse_status = "completed"
        book.structure_status = "review"
        book.parse_warnings = book_data.get("warnings", [])
        for page in book_data.get("pages", []):
            page_text = page.get("text", "")
            db.merge(TextbookPage(
                id=f"{book_data['textbook_id']}_page_{page['page_number']:04d}",
                textbook_id=book_data["textbook_id"],
                page_number=page["page_number"],
                printed_page_number=page.get("printed_page_number", ""),
                text=page_text,
                char_count=len(page_text),
                content_hash=hashlib.sha256(page_text.encode("utf-8")).hexdigest(),
                has_text=bool(page_text.strip()),
                extraction_method=page.get("extraction_method", "native"),
            ))
        for ch in book_data["chapters"]:
            ch["chapter_id"] = f"{book_data['textbook_id']}_{ch['chapter_id']}"
            chapter = Chapter(
                id=ch["chapter_id"],
                textbook_id=book_data["textbook_id"],
                title=ch["title"],
                page_start=ch.get("page_start", 1),
                page_end=ch.get("page_end", 1),
                content=ch["content"],
                char_count=ch["char_count"],
                order_index=ch.get("order_index", 0),
                level=ch.get("level", 1),
                review_status=ch.get("review_status", "unreviewed"),
                source_spans=ch.get("source_spans", []),
            )
            db.merge(chapter)
        db.commit()
    finally:
        db.close()

def _extract_title(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r'^\d+[_\-\s]*', '', name)
    return name or filename
