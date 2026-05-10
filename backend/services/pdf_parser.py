import re
from pathlib import Path
from backend.database import SessionLocal, Textbook, Chapter

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
    chapters = _split_by_headings(content)
    # Assign page numbers based on average chars per page (rough)
    avg_chars_per_page = max(2000, len(content) // max(len(chapters) * 3, 1))
    current_page = 1
    for ch in chapters:
        ch_pages = max(1, ch["char_count"] // avg_chars_per_page)
        ch["page_start"] = current_page
        ch["page_end"] = current_page + ch_pages - 1
        current_page = ch["page_end"] + 1
    total_chars = sum(c["char_count"] for c in chapters)
    return {"textbook_id": textbook_id, "total_pages": current_page - 1, "total_chars": total_chars, "chapters": chapters}

def _parse_pdf(file_path: str, textbook_id: str) -> dict:
    """Page-level PDF parsing with proper page tracking."""
    pages = []  # list of (page_no, text)
    try:
        import fitz
        doc = fitz.open(file_path)
        for i, page in enumerate(doc):
            text = page.get_text()
            pages.append((i + 1, text))
        doc.close()
    except Exception:
        import pypdf
        reader = pypdf.PdfReader(file_path)
        for i, page in enumerate(reader.pages):
            t = page.extract_text()
            pages.append((i + 1, t or ""))

    total_pages = len(pages)

    # Clean each page
    cleaned_pages = [(pno, _clean_text(text)) for pno, text in pages]

    # Build chapter structure preserving page numbers
    full_text = "\n".join([text for _, text in cleaned_pages])
    chapters = _split_by_headings_with_pages(full_text, cleaned_pages)

    total_chars = sum(c["char_count"] for c in chapters)

    return {
        "textbook_id": textbook_id,
        "total_pages": total_pages,
        "total_chars": total_chars,
        "chapters": chapters
    }

def _split_by_headings_with_pages(full_text: str, page_list: list) -> list:
    """Split text by chapter headings while preserving page numbers."""
    pattern = r'(第[一二三四五六七八九十百千\d]+章\s*[^\n]*)'
    parts = re.split(pattern, full_text)

    # Build page map: for each position in full_text, determine the page number
    # Simplified approach: assign pages based on text position ratio
    total_len = max(len(full_text), 1)
    total_pages = len(page_list)

    def pos_to_page(pos):
        return max(1, min(total_pages, int(pos / total_len * total_pages) + 1))

    chapters = []
    ch_idx = 0

    # Handle text before first chapter heading
    if parts and not re.match(pattern, parts[0]):
        intro_text = parts[0].strip()
        if len(intro_text) > 200:
            pos = full_text.find(intro_text) if intro_text else 0
            chapters.append({
                "chapter_id": f"ch_{ch_idx:03d}",
                "title": "绪论/前言",
                "page_start": pos_to_page(pos),
                "page_end": pos_to_page(pos + len(intro_text)),
                "content": intro_text,
                "char_count": len(intro_text)
            })
            ch_idx += 1

    for i in range(1, len(parts), 2):
        title = parts[i].strip() if i < len(parts) else "未命名章节"
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if len(body) < 50:
            continue

        pos = full_text.find(body) if body else 0
        chapters.append({
            "chapter_id": f"ch_{ch_idx:03d}",
            "title": title,
            "page_start": pos_to_page(pos),
            "page_end": pos_to_page(pos + len(body)),
            "content": body,
            "char_count": len(body)
        })
        ch_idx += 1

    # Fallback: if no chapters found, split by page groups
    if not chapters:
        group_size = max(1, total_pages // 10)
        for g in range(0, total_pages, group_size):
            g_start = g + 1
            g_end = min(g + group_size, total_pages)
            group_text = "\n".join([t for pno, t in page_list if g_start <= pno <= g_end])
            if len(group_text) < 100:
                continue
            chapters.append({
                "chapter_id": f"ch_{ch_idx:03d}",
                "title": f"第{g_start}-{g_end}页",
                "page_start": g_start,
                "page_end": g_end,
                "content": group_text,
                "char_count": len(group_text)
            })
            ch_idx += 1

    return chapters

def _clean_text(text: str) -> str:
    text = re.sub(r'\n\d+\n', '\n', text)
    text = re.sub(r'^\d+\s*$', '', text, flags=re.MULTILINE)
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
        book = Textbook(
            id=book_data["textbook_id"],
            filename=filename,
            title=_extract_title(filename),
            format=fmt,
            file_size=file_size,
            total_pages=book_data["total_pages"],
            total_chars=book_data["total_chars"],
            parse_status="completed"
        )
        db.merge(book)
        for ch in book_data["chapters"]:
            ch["chapter_id"] = f"{book_data['textbook_id']}_{ch['chapter_id']}"
            chapter = Chapter(
                id=ch["chapter_id"],
                textbook_id=book_data["textbook_id"],
                title=ch["title"],
                page_start=ch.get("page_start", 1),
                page_end=ch.get("page_end", 1),
                content=ch["content"],
                char_count=ch["char_count"]
            )
            db.merge(chapter)
        db.commit()
    finally:
        db.close()

def _extract_title(filename: str) -> str:
    name = Path(filename).stem
    name = re.sub(r'^\d+[_\-\s]*', '', name)
    return name or filename
