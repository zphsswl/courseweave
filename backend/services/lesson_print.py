"""Printable, offline lesson documents from the same saved artifact as Markdown."""
from html import escape, unescape
import re


def _lesson_body(text: str) -> str:
    """Render the headings, lists and tables emitted by lesson_markdown, with no executable HTML."""
    lines = text.splitlines()
    output, list_kind, in_table = [], None, False
    def inline(value):
        return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escape(unescape(value)))
    def close_blocks():
        nonlocal list_kind, in_table
        if list_kind:
            output.append(f"</{list_kind}>")
            list_kind = None
        if in_table:
            output.append("</tbody></table>")
            in_table = False
    for index, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            if re.fullmatch(r"[| :\-]+", line):
                continue
            if not in_table:
                close_blocks()
                output.append("<table><tbody>")
                in_table = True
            header = index + 1 < len(lines) and bool(re.fullmatch(r"[| :\-]+", lines[index + 1].strip()))
            cell = "th" if header else "td"
            output.append("<tr>" + "".join(f"<{cell}>{inline(value.strip())}</{cell}>" for value in line.strip("|").split("|")) + "</tr>")
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        bullet = re.match(r"^(?:[-*]\s+|\d+\.\s+)(.*)$", line)
        if bullet:
            kind = "ol" if line[0].isdigit() else "ul"
            if list_kind != kind or in_table:
                close_blocks()
                output.append(f"<{kind}>")
                list_kind = kind
            output.append(f"<li>{inline(bullet.group(1))}</li>")
        else:
            close_blocks()
            if heading:
                size = len(heading.group(1))
                output.append(f"<h{size}>{inline(heading.group(2))}</h{size}>")
            elif line and line != "---":
                output.append(f"<p>{inline(line)}</p>")
    close_blocks()
    return "\n".join(output)


def lesson_print_html(text: str, title: str) -> str:
    # Escape model/teacher HTML before Markdown rendering; the document needs no scripts or remote assets.
    body = _lesson_body(text)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>{escape(title)}</title><style>
@page{{size:A4;margin:20mm}}*{{box-sizing:border-box}}body{{font:15px/1.85 'Microsoft YaHei','Noto Sans SC',sans-serif;color:#20372d;background:#f2f3ed;margin:0}}main{{max-width:850px;margin:32px auto;padding:40px 50px;background:white}}h1,h2,h3{{font-family:'Noto Serif SC',SimSun,serif;line-height:1.5;break-after:avoid}}h1{{font-size:27px;border-bottom:2px solid #176450;padding-bottom:16px}}h2{{font-size:20px;margin-top:30px}}h3{{font-size:17px}}p,li{{orphans:3;widows:3}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border:1px solid #cbd5ce;padding:8px;text-align:left;vertical-align:top}}blockquote{{border-left:3px solid #b5c6ba;margin:15px 0;padding-left:16px}}.print-note{{padding:14px 20px;background:#e7eee7;text-align:center;font-size:13px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}@media print{{body{{background:white}}main{{padding:0;margin:0;max-width:none}}.print-note{{display:none}}a{{color:inherit;text-decoration:none}}}}
</style></head><body><div class="print-note">打印教案：按 Ctrl + P，选择打印机或“保存为 PDF”。此文件来自已保存教案，内容仍需教师核对。</div><main>{body}</main></body></html>'''
