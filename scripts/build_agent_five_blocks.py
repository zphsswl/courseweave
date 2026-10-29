"""Simple five-part Agent diagram; SVG and 4800x3000 PNG, no model or DB.

Uses the existing drawing helpers and an in-memory PDF to preserve Chinese
glyphs in the PNG. The SVG retains editable text; no PDF file is written.
"""
from io import BytesIO
from pathlib import Path

import fitz
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import build_agent_rag_brief as graphics


def main():
    root=Path(__file__).resolve().parents[1]
    graphics.W,graphics.H=1600,1000
    graphics.OUT=root/'docs'/'showcase'
    for name,path in graphics.FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name,path))
    buffer=BytesIO()
    pdf=canvas.Canvas(buffer,pagesize=(1600,1000),pageCompression=1)
    s=graphics.Sheet(pdf,'courseweave-agent-five-blocks')
    s.text(50,29,'COURSEWEAVE  /  FIVE BUILDING BLOCKS',12,'Bold','teal')
    s.text(50,60,'一个 Agent，五个部分怎样配合',38,'Display')
    s.text(50,115,'主循环：状态 → 上下文 → LLM → 工具 → 更新状态',21,'Bold','teal')
    s.tag(1290,48,'本项目 · 简明架构',width=260,fill='dark',color='white',size=16)

    s.rect(50,170,710,61,'paper')
    s.text(70,186,'用户输入：主题、教材、课时、教学要求',20,'Bold')
    s.line([(215,231),(215,320)],'teal')
    s.text(228,265,'保存为任务条件',14,color='muted')

    # Context is built from state; model action is checked before execution.
    boxes=[
        (50,'01  状态','当前任务的“账本”',
         '任务条件、教材证据、当前稿\n工具结果、检查反馈\n执行记录、剩余预算','SQLite / Job：每步前后保存','paper'),
        (440,'02  上下文','这一轮交给模型的内容',
         '目标、证据摘要、当前稿与反馈\n最近 6 步动作、剩余预算\n按长度限制选取和裁剪','每轮重新组装有限输入','paper'),
        (830,'03  LLM','决定下一步，按需生成内容',
         '决策：选择一个动作及参数\n生成：根据原文写或修改教案\n同一模型配置，不同调用','输出动作 JSON，交给程序执行','dark'),
        (1220,'04  工具','程序提供的七种能力',
         '查看课程 · RAG 检索 · 读原文\n起草 / 修订 · 检查草稿\n询问教师 · 结束检查','执行前校验：参数、范围、预算','paper'),
    ]
    for x,title,subtitle,body,caption,fill in boxes:
        ink='white' if fill=='dark' else 'ink'
        muted='white' if fill=='dark' else 'muted'
        s.rect(x,320,330,250,fill,None if fill=='dark' else 'line',12)
        s.text(x+20,340,title,25,'Bold',ink)
        s.text(x+20,380,subtitle,17,'Bold',ink,max_width=290)
        s.para(x+20,420,body,292,17,color=muted,leading=28,max_lines=3)
        s.text(x+20,536,caption,13.2,'Body',muted,max_width=292)
    for a,b,label in [(380,440,'选取裁剪'),(770,830,'本轮输入'),(1160,1220,'动作')]:
        s.line([(a,448),(b,448)],'teal')
        s.text(a+3,421,label,12,'Bold','teal')

    # The extra content-generation request is distinct from selecting an action.
    s.line([(1385,320),(1385,268),(995,268),(995,320)],'blue',1.7,dashed=True)
    s.text(952,239,'写稿 / 整理回答时，工具按需另调 LLM 生成内容',14,'Bold','blue',max_width=570)

    # Every executed result returns to durable state and a new context.
    s.line([(1385,570),(1385,627),(215,627),(215,570)],'teal',2.5)
    s.rect(492,607,610,38,'bg',None,0)
    s.text(516,613,'把结果、稿件与检查反馈写回状态，进入下一轮',19,'Bold','teal')

    # Memory is supplied by existing stores rather than a separate thinking agent.
    s.rect(50,714,1500,190,'mint',None,12)
    s.text(72,731,'05  记忆',25,'Bold')
    s.text(240,738,'本项目通过已有存储，保留与复用信息',17,'Body','muted')
    memory=[(74,'任务级记忆','同一任务的状态已落库，可继续与恢复'),
            (572,'教材知识库','原文长期保留，经 RAG / 原文工具取用'),
            (1068,'本机暂存','表单、未保存编辑、待提交回答')]
    for x,title,body in memory:
        s.text(x,787,title,19,'Bold')
        s.text(x,823,body,16,color='muted',max_width=455)
    s.text(74,869,'当前没有“跨任务自动总结经验、自学习”的长期记忆。',16,'Bold','teal')
    s.line([(100,714),(100,570)],'muted',1.5,dashed=True)
    s.text(112,676,'重启后恢复',13,color='muted')
    s.line([(1500,714),(1500,570)],'muted',1.5,dashed=True)
    s.text(1418,676,'按需取用',13,color='muted')

    s.text(50,935,'循环出口：缺证据就查，缺内容就改，需要条件就问；finish 重新检查通过后，交付已有稿件供教师审核。',16,color='ink',max_width=1500)
    s.line([(50,967),(1550,967)],'line',1,arrow=False)
    s.text(50,979,'默认内置 RAG 路径：有限动作、持久状态、每轮重建上下文。虚线表示生成调用或信息恢复 / 取用。',11,color='muted')
    s.text(1423,978,'2026-10-29',12,'Bold','teal')
    s.save_svg()
    pdf.showPage();pdf.save()
    document=fitz.open(stream=buffer.getvalue(),filetype='pdf')
    document[0].get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).save(graphics.OUT/'courseweave-agent-five-blocks.png')
    preview=root/'.gstack'/'agent-five-blocks-preview.png'
    document[0].get_pixmap(matrix=fitz.Matrix(1,1),alpha=False).save(preview)
    print(f'Created SVG + 4800x3000 PNG in {graphics.OUT}; preview: {preview}')


if __name__=='__main__':main()
