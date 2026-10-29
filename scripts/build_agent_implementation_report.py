"""Build the detailed, code-audited Agent report. Optional ReportLab/PyMuPDF tools.

Reads only the repository Markdown report; no application DB, model or network.
Wide source tables become labelled records in the portrait PDF for legibility.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import fitz
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, CondPageBreak,
    Table, TableStyle, XPreformatted, HRFlowable,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'docs'/'Agent系统实现详解与真实案例报告.md'
DEST = ROOT/'output'/'pdf'/'courseweave-agent-implementation-report-20261029.pdf'
QA = ROOT/'.gstack'/'agent-report-pdf-qa'
INK, GREEN, MUTED = '#193D35', '#237B67', '#68756D'
WIDTH = A4[0]-104


def inline(value):
    value = html.escape(value)
    def link(match):
        label, target = match.groups()
        if target.startswith('../'):
            target = 'https://github.com/zphsswl/courseweave/blob/codex/lesson-agent-v3/' + target[3:]
        elif target.startswith('./'):
            target = 'https://github.com/zphsswl/courseweave/blob/codex/lesson-agent-v3/docs/' + target[2:]
        return f'<link href="{target}" color="{GREEN}">{label}</link>'
    value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, value)
    value = re.sub(r'`([^`]+)`', r'<font color="#235F53">\1</font>', value)
    value = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', value)
    return value


class ReportDoc(SimpleDocTemplate):
    def afterFlowable(self, flow):
        if isinstance(flow, Paragraph) and flow.style.name in {'H1','H2'}:
            level = 0 if flow.style.name == 'H1' else 1
            key = f'section-{self.seq.nextf("outline")}'
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flow.getPlainText(), key, level, closed=False)


def draw_page(c, doc):
    c.saveState()
    if doc.page>1:
        c.setFillColor(colors.HexColor(MUTED)); c.setFont('ReportBody',8)
        c.drawString(52,A4[1]-30,'COURSEWEAVE  /  AGENT IMPLEMENTATION & CASE STUDY')
        c.setStrokeColor(colors.HexColor('#D4DDD6'))
        c.line(52,A4[1]-39,A4[0]-52,A4[1]-39)
    c.setFillColor(colors.HexColor(MUTED)); c.setFont('ReportBody',8)
    c.drawString(52,28,'2026-10-29 · 源码事实、实际运行记录与验证边界')
    c.drawRightString(A4[0]-52,28,str(doc.page))
    c.restoreState()


def main():
    DEST.parent.mkdir(parents=True,exist_ok=True); QA.mkdir(parents=True,exist_ok=True)
    pdfmetrics.registerFont(TTFont('ReportBody','C:/Windows/Fonts/msyh.ttc'))
    pdfmetrics.registerFont(TTFont('ReportBold','C:/Windows/Fonts/msyhbd.ttc'))
    pdfmetrics.registerFont(TTFont('ReportDisplay','C:/Windows/Fonts/simsun.ttc'))
    pdfmetrics.registerFontFamily('ReportBody',normal='ReportBody',bold='ReportBold',italic='ReportBody',boldItalic='ReportBold')
    styles={
        'body':ParagraphStyle('Body',fontName='ReportBody',fontSize=10,leading=16,textColor=colors.HexColor(INK),spaceAfter=7,wordWrap='CJK',splitLongWords=True),
        'small':ParagraphStyle('Small',fontName='ReportBody',fontSize=8.4,leading=12,textColor=colors.HexColor(MUTED),spaceAfter=5,wordWrap='CJK',splitLongWords=True),
        'H1':ParagraphStyle('H1',fontName='ReportBold',fontSize=17,leading=25,textColor=colors.HexColor(INK),spaceBefore=16,spaceAfter=10,keepWithNext=True,wordWrap='CJK'),
        'H2':ParagraphStyle('H2',fontName='ReportBold',fontSize=12.4,leading=19,textColor=colors.HexColor(GREEN),spaceBefore=12,spaceAfter=7,keepWithNext=True,wordWrap='CJK'),
        'record':ParagraphStyle('Record',fontName='ReportBold',fontSize=10,leading=15,textColor=colors.HexColor(INK),spaceBefore=9,spaceAfter=5,keepWithNext=True,wordWrap='CJK'),
        'cell':ParagraphStyle('Cell',fontName='ReportBody',fontSize=8.5,leading=12.5,textColor=colors.HexColor(INK),wordWrap='CJK',splitLongWords=True),
        'headcell':ParagraphStyle('Headcell',fontName='ReportBold',fontSize=8.5,leading=12.5,textColor=colors.white,wordWrap='CJK'),
        'code':ParagraphStyle('Code',fontName='ReportBody',fontSize=7.6,leading=11.3,textColor=colors.HexColor('#284A40'),backColor=colors.HexColor('#F0F4EF'),borderPadding=8,spaceBefore=5,spaceAfter=9,wordWrap='CJK'),
    }
    story=[]
    p=lambda text,kind='body':Paragraph(inline(text),styles[kind])
    story += [Spacer(1,43),p('COURSEWEAVE / TECHNICAL REPORT','small'),Spacer(1,13),
              Paragraph('Agent 系统实现详解<br/>与真实案例报告',ParagraphStyle('Cover',fontName='ReportDisplay',fontSize=29,leading=44,textColor=colors.HexColor(INK))),
              Spacer(1,20),p('工具怎样选择、状态落在哪里、上下文如何组装、记忆如何保留，以及教案里哪些内容由程序预先设计。'),
              Spacer(1,18),HRFlowable(width='100%',color=colors.HexColor(GREEN),thickness=2),Spacer(1,20)]
    cover=[('报告日期','2026-10-29'),('实现对象','lesson_agent_v3 · 单 Agent、有界工具、持久检查点'),
           ('真实案例','甲状腺功能 · 45 分钟 · 3 个课堂问题'),
           ('实际结果','生成稿通过结构检查，随后动作协议连续拒绝，最终 no_progress'),
           ('证据边界','代码与既有运行记录；未额外重放模型；不公开教材原文')]
    for label,value in cover:
        story.append(p(f'**{label}**　{value}'))
    story += [Spacer(1,23),p('阅读路线','record'),p('1–3：执行职责与工具协议；4–7：状态、上下文、记忆与来源；8–10：人工模板、检查与停止；11：真实输入到产物；12–14：教师修改、限制与复核。'),
              Spacer(1,13),p('PDF 将宽表格改为逐条记录，便于纵向阅读；代码、字段、案例与 Markdown 主报告保持同源。左侧书签可直接跳转章节。','small'),PageBreak()]
    lines=SOURCE.read_text(encoding='utf-8-sig').splitlines()
    i=0
    def emit_table(rows):
        heads=rows[0]; data=rows[1:]
        if len(heads)>=5:
            for record in data:
                record=record+['']*(len(heads)-len(record))
                story.append(p(f'{heads[0]}：{record[0]}','record'))
                for label,value in zip(heads[1:],record[1:]):
                    story.append(p(f'**{label}：** {value}'))
                story.append(HRFlowable(width='100%',thickness=.45,color=colors.HexColor('#DEE5DF'),spaceBefore=3,spaceAfter=5))
            return
        n=len(heads)
        raw=[]
        for row in rows:
            row=row+['']*(n-len(row))
            raw.append([p(cell,'headcell' if not raw else 'cell') for cell in row[:n]])
        weights=[max(8,min(36,max(len(row[j]) if j<len(row) else 0 for row in rows)))**.65 for j in range(n)]
        widths=[WIDTH*w/sum(weights) for w in weights]
        t=Table(raw,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1,splitInRow=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor(INK)),('VALIGN',(0,0),(-1,-1),'TOP'),
                              ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
                              ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
                              ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F3F6F1')]),
                              ('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#D8E0D9'))]))
        story.extend([t,Spacer(1,10)])
    while i<len(lines):
        line=lines[i].rstrip()
        if i==0 and line.startswith('# '):i+=1;continue
        if not line.strip():i+=1;continue
        if line.startswith('```'):
            code=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):
                source_line=lines[i].replace('\t','    ')
                while pdfmetrics.stringWidth(source_line,'ReportBody',7.6)>WIDTH-18:
                    j=1
                    while j<len(source_line) and pdfmetrics.stringWidth(source_line[:j+1],'ReportBody',7.6)<=WIDTH-18:j+=1
                    code.append(source_line[:j]);source_line='  '+source_line[j:]
                code.append(source_line);i+=1
            story.append(XPreformatted(html.escape('\n'.join(code)),styles['code']))
            i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[v.strip() for v in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',v or '-') for v in cells):rows.append(cells)
                i+=1
            if rows:emit_table(rows)
            continue
        if line.startswith('## '):
            story += [CondPageBreak(95),p(line[3:],'H1')];i+=1;continue
        if line.startswith('### '):story.append(p(line[4:],'H2'));i+=1;continue
        if line.startswith('#### '):story.append(p(line[5:],'record'));i+=1;continue
        if re.fullmatch(r'[-*_]{3,}',line.strip()):story.append(HRFlowable(width='100%',color=colors.HexColor('#DEE5DF')));i+=1;continue
        if line.startswith('- '):story.append(p('• '+line[2:]));i+=1;continue
        if line.startswith('> '):story.append(p(line[2:]));i+=1;continue
        if re.match(r'^\d+\. ',line):story.append(p(line));i+=1;continue
        block=[line];i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r'^(#|\||```|- |\d+\. )',lines[i]):block.append(lines[i]);i+=1
        story.append(p(' '.join(block)))
    doc=ReportDoc(str(DEST),pagesize=A4,rightMargin=52,leftMargin=52,topMargin=54,bottomMargin=52,
                  title='CourseWeave Agent 系统实现详解与真实案例报告',author='CourseWeave / independent code audit')
    doc.build(story,onFirstPage=draw_page,onLaterPages=draw_page)
    report=fitz.open(DEST)
    full='\n'.join(page.get_text() for page in report)
    for expected in ('query_rag','teacher_answers','no_progress','甲状腺','记忆','上下文'):
        assert expected in full,expected
    assert '\ufffd' not in full
    for index,page in enumerate(report):
        page.get_pixmap(matrix=fitz.Matrix(1.3,1.3),alpha=False).save(QA/f'page-{index+1:02d}.png')
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                for span in line['spans']:
                    x0,y0,x1,y1=span['bbox']
                    assert x0>=0 and y0>=0 and x1<=A4[0]+1 and y1<=A4[1]+1,(index,span)
    print(f'Created {DEST}; {len(report)} pages; searchable Chinese; rendered every page into {QA}.')


if __name__=='__main__':main()
