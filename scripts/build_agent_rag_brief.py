"""Render the code-audited two-page Agent/RAG briefing as vector PDF/SVG and PNG.

Requires reportlab and PyMuPDF. No model, database, network or application state.
Run from the repository root. Chinese font defaults to Windows fonts; override
COURSEWEAVE_FONT_REGULAR / _BOLD / _DISPLAY for other operating systems.
"""
from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path

import fitz
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'pdf'
W, H = 1800, 1200
C = {
    'bg': '#F5F6F1', 'paper': '#FFFFFF', 'ink': '#183B34', 'muted': '#65746B',
    'line': '#CDD8D0', 'teal': '#237E6C', 'mint': '#E7F1E9', 'dark': '#153D34',
    'amber': '#AF7D32', 'sand': '#FBF1DD', 'blue': '#536C95', 'ice': '#EDF1F8',
    'light': '#F8FAF6', 'white': '#FFFFFF',
}
FONT_FILES = {
    'Body': os.getenv('COURSEWEAVE_FONT_REGULAR', 'C:/Windows/Fonts/msyh.ttc'),
    'Bold': os.getenv('COURSEWEAVE_FONT_BOLD', 'C:/Windows/Fonts/msyhbd.ttc'),
    'Display': os.getenv('COURSEWEAVE_FONT_DISPLAY', 'C:/Windows/Fonts/simsun.ttc'),
}
SVG_FONTS = {'Body': 'Microsoft YaHei', 'Bold': 'Microsoft YaHei', 'Display': 'SimSun'}


class Sheet:
    def __init__(self, pdf, name):
        self.c = pdf
        self.name = name
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
        self.text_items = []
        self.rect(0, 0, W, H, fill='bg', stroke=None, radius=0)

    def rect(self, x, y, w, h, fill='paper', stroke='line', radius=12, width=1):
        self.c.setLineWidth(width)
        self.c.setFillColor(HexColor(C.get(fill, fill)))
        if stroke:
            self.c.setStrokeColor(HexColor(C.get(stroke, stroke)))
        self.c.roundRect(x, H-y-h, w, h, radius, fill=1, stroke=int(bool(stroke)))
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{C.get(fill,fill)}" stroke="{C.get(stroke,stroke) if stroke else "none"}" stroke-width="{width}"/>')

    def text(self, x, y, value, size=16, font='Body', color='ink', max_width=None):
        width = pdfmetrics.stringWidth(value, font, size)
        if max_width is not None and width > max_width + .1:
            raise ValueError(f'{self.name}: text exceeds width {width:.1f}>{max_width}: {value}')
        if x < 0 or y < 0 or x+width > W+.1 or y+size > H:
            raise ValueError(f'{self.name}: text outside page: {value}')
        baseline = y + size*.89
        self.c.setFont(font, size)
        self.c.setFillColor(HexColor(C.get(color, color)))
        self.c.drawString(x, H-baseline, value)
        weight = '700' if font == 'Bold' else '400'
        self.svg.append(f'<text x="{x}" y="{baseline}" font-family="{SVG_FONTS[font]}" font-size="{size}" font-weight="{weight}" fill="{C.get(color,color)}">{html.escape(value)}</text>')
        self.text_items.append({'text': value, 'x': x, 'y': y, 'width': width, 'size': size})

    def para(self, x, y, value, width, size=15, color='muted', font='Body', leading=None, max_lines=None):
        leading = leading or size*1.52
        lines = []
        for raw in value.split('\n'):
            line = ''
            for ch in raw:
                if line and pdfmetrics.stringWidth(line+ch, font, size) > width:
                    lines.append(line)
                    line = ch
                else:
                    line += ch
            lines.append(line)
        if max_lines and len(lines) > max_lines:
            raise ValueError(f'{self.name}: too many lines {len(lines)}>{max_lines}: {value}')
        for i, line in enumerate(lines):
            self.text(x, y+i*leading, line, size, font, color, width)
        return len(lines)*leading

    def line(self, points, color='teal', width=2, dashed=False, arrow=True, both=False):
        self.c.setStrokeColor(HexColor(C.get(color, color)))
        self.c.setFillColor(HexColor(C.get(color, color)))
        self.c.setLineWidth(width)
        self.c.setLineJoin(1)
        self.c.setDash([5, 5] if dashed else [])
        path = self.c.beginPath()
        path.moveTo(points[0][0], H-points[0][1])
        for x, y in points[1:]:
            path.lineTo(x, H-y)
        self.c.drawPath(path)
        dash = ' stroke-dasharray="5 5"' if dashed else ''
        self.svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{C.get(color,color)}" stroke-width="{width}" stroke-linejoin="round"{dash}/>')
        self.c.setDash([])
        def head(tip, previous):
            angle = math.atan2(tip[1]-previous[1], tip[0]-previous[0])
            length, spread = 8, .48
            tri = [tip, (tip[0]-length*math.cos(angle-spread), tip[1]-length*math.sin(angle-spread)),
                   (tip[0]-length*math.cos(angle+spread), tip[1]-length*math.sin(angle+spread))]
            p = self.c.beginPath()
            p.moveTo(tri[0][0], H-tri[0][1])
            for a, b in tri[1:]:
                p.lineTo(a, H-b)
            p.close()
            self.c.drawPath(p, fill=1, stroke=0)
            self.svg.append(f'<polygon points="{" ".join(f"{a},{b}" for a,b in tri)}" fill="{C.get(color,color)}"/>')
        if arrow:
            head(points[-1], points[-2])
        if both:
            head(points[0], points[1])

    def tag(self, x, y, value, fill='mint', color='teal', size=12, width=None):
        width = width or pdfmetrics.stringWidth(value, 'Bold', size)+24
        self.rect(x, y, width, size+16, fill, None, 6)
        self.text(x+12, y+7, value, size, 'Bold', color, width-24)

    def header(self, title, subtitle, index, label):
        self.text(56, 29, 'COURSEWEAVE  /  ARCHITECTURE NOTES', 12, 'Bold', 'teal')
        self.text(56, 57, title, 38, 'Display', 'ink')
        self.text(58, 108, subtitle, 16, 'Body', 'muted')
        self.tag(1450, 48, f'{index:02d} / 02   {label}', width=294, fill='dark', color='white', size=14)

    def footer(self, index, reference):
        self.line([(56,1151),(1744,1151)], 'line', 1, arrow=False)
        self.text(56, 1166, reference, 10.5, color='muted', max_width=1420)
        self.text(1512, 1164, f'2026-10-29  /  {index:02d}', 12, 'Bold', 'teal')

    def save_svg(self):
        self.svg.append('</svg>')
        (OUT / f'{self.name}.svg').write_text('\n'.join(self.svg), encoding='utf-8')


def page_one(s):
    s.header('Agent × RAG：从教学目标到有据可查的教案', '阅读顺序：任务入口 → Agent 反馈闭环 → 独立 RAG 工具 → 服务端交付门禁', 1, '真实架构')
    # Entry / output: these are outside the decision loop.
    s.rect(56, 155, 360, 87)
    s.text(76, 171, '教师工作台', 20, 'Bold')
    s.text(76, 204, '主题、目标、教材、学情、课时', 15, color='muted')
    s.rect(446, 155, 600, 87)
    s.text(466, 171, '任务入口与确定性准备', 20, 'Bold')
    s.text(466, 202, '范围校验 → Job → 单 worker；解析 / 分块 / 页码映射', 15, color='muted')
    s.text(466, 223, '章节未确认则等待教师；前置准备不属于模型动作', 11.5, color='muted')
    s.line([(416,198),(446,198)])
    s.line([(56,310),(34,310),(34,198),(56,198)],'muted',1.5,dashed=True,both=True)
    s.text(72,250,'提问 / 确认 ⇄ 回答 / 停止',11.5,'Bold','teal')
    s.rect(1100, 155, 644, 87, 'dark', None)
    s.text(1124, 170, '待教师审核的教案', 22, 'Bold', 'white')
    s.text(1124, 207, '可编辑 · 回查原文 · 投屏 / 导出；教师保存稿独立保护', 15, color='white')
    s.line([(746,242),(746,273)])
    s.line([(1010,273),(1010,255),(1422,255),(1422,242)], 'teal')
    s.text(1160, 244, 'finish 重验通过', 10.5, 'Bold', 'teal')

    # Agent main loop.
    s.rect(56,273,990,411,'mint','line',14)
    s.text(80,290,'A  /  单 Agent 反馈闭环',21,'Bold')
    s.text(735,295,'模型只提议，服务端执行',14,'Bold','teal')
    for x, title, lines, code in [
        (80,'状态与真实观察','任务条件、证据、当前稿\n检查缺项、教师回答、剩余预算','Job.result'),
        (390,'模型选择一个动作','每轮读取反馈再决策\n补查 / 修订 / 提问 / 结束','lesson_policy.py'),
        (700,'严格动作契约','JSON、教材范围、严格类型\n拒绝未知工具与额外字段','lesson_contracts.py'),
    ]:
        width = 270 if x < 700 else 320
        s.rect(x,337,width,109)
        s.text(x+18,351,title,19,'Bold')
        s.para(x+18,383,lines,width-36,14,leading=20,max_lines=2)
        s.text(x+18,425,code,10.5,color='teal')
    s.line([(350,391),(390,391)])
    s.line([(660,391),(700,391)])
    s.line([(860,446),(860,492)])
    s.text(870,465,'校验后',11,color='teal')
    s.rect(80,492,940,89,'dark',None)
    s.text(100,506,'执行运行器  /  执行工具、持久化反馈、决定等待或停止',20,'Bold','white')
    s.text(100,541,'调用前预留预算；调用后检查取消；每次动作前后保存检查点',14,color='white')
    s.text(100,563,'默认：12 轮 · 6 次 RAG · 3 次起草 · 300 秒调度时限（非强杀）；重复 / 无进展保护',11.5,color='white',max_width=900)
    s.line([(215,492),(215,446)],'teal')
    s.text(88,465,'结果 / 拒绝反馈',11,'Bold','teal')
    s.line([(550,581),(550,609)])
    tools=[('查看课程','inspect_course'),('调用 RAG','query_rag'),('读取原文','read_source'),
           ('起草 / 修订','write_draft'),('检查草稿','validate_draft'),('询问教师','ask_teacher'),('交付检查','finish')]
    for i,(label,code) in enumerate(tools):
        x=80+i*134
        s.rect(x,610,128,51,'ice' if i==1 else 'paper',None,7)
        s.text(x+10,619,label,14,'Bold','blue' if i==1 else 'ink')
        s.text(x+10,642,code,9.2,color='muted')
    s.text(80,668,'七动作按反馈选择；无模型则执行证据工作流（非自主规划）；预算耗尽保留部分成果。',11.5,color='muted',max_width=940)

    # Draft and local checking: failures loop back, no self-approved success.
    s.rect(56,726,990,174,'paper')
    s.text(80,741,'B  /  起草与交付门禁',20,'Bold')
    s.text(350,746,'各动作分别触发，非自动串行',12,color='muted')
    s.text(747,746,'教学语义仍需教师审核',13,'Bold','amber')
    s.rect(80,785,440,91,'light',None,8)
    s.text(96,797,'教案生成器  /  write_draft',18,'Bold')
    s.para(96,828,'规范原文 + 旧稿 + 缺项反馈 + 教师回答\n起草结果写回状态；教师保存稿不自动覆盖',410,14,leading=21,max_lines=2)
    s.rect(570,785,450,91,'sand',None,8)
    s.text(586,797,'本地验证器  /  validate_draft、finish',17,'Bold')
    s.para(586,828,'来源 / 章节归属、引用覆盖、课时、问题数与结构\nfinish 每次重验；模型说“完成”不能绕过',420,13.5,leading=21,max_lines=2)
    s.line([(546,661),(546,706),(300,706),(300,785)],'teal',both=True)
    s.line([(680,661),(680,713),(800,713),(800,785)],'teal',both=True)
    s.line([(950,785),(950,697),(970,697),(970,684)],'amber',dashed=True)
    s.text(710,691,'缺项反馈 → 补查或改稿',12,'Bold','amber')

    # Persistent data / evidence are distinct responsibilities.
    s.rect(56,929,480,83,'paper')
    s.text(76,942,'Job 检查点与用户控制',18,'Bold')
    s.para(76,971,'轨迹、预算、证据快照 / 哈希、稿件；快照 CAS\n恢复不重置预算，取消后拒绝迟到写回',440,13.5,leading=20,max_lines=2)
    s.line([(80,532),(46,532),(46,969),(56,969)],'muted',1.4,dashed=True,both=True)
    s.rect(566,929,480,83,'paper')
    s.text(586,942,'本地规范来源  /  SQLite',18,'Bold')
    s.para(586,971,'Course → Textbook → Chapter → Chunk\n原文 / 章节 / 页码；read_source 直读，RAG 同库',440,13.5,leading=20,max_lines=2)

    # RAG expansion. BM25 is primary, vector conditional, graph only fallback.
    s.rect(1100,273,644,739,'ice','line',14)
    s.text(1124,290,'C  /  独立 RAG 工具',21,'Bold')
    s.text(1486,295,'既有方法保持不变',14,'Bold','blue')
    s.rect(1124,337,596,65,'paper')
    s.text(1144,349,'工具适配器  /  query_rag_tool',19,'Bold')
    s.text(1144,380,'默认内部调用；可选 AGENT_RAG_URL 接入同来源 HTTP 服务',12.5,color='muted')
    s.line([(1020,517),(1090,517),(1090,367),(1124,367)],'blue')
    s.text(1047,495,'调用',11,'Bold','blue')
    s.line([(1124,921),(1080,921),(1080,559),(1020,559)],'amber')
    s.text(1048,574,'证据',11,'Bold','amber')
    s.rect(1124,429,596,426,'paper','line',10)
    s.text(1144,440,'既有 RAG  /  retrieval_service + rag_agent',12,'Bold','blue')
    s.rect(1144,473,556,61,'ice',None,8)
    s.text(1160,483,'范围与查询理解',17,'Bold')
    s.text(1160,511,'同一来源库语料；范围 / 域外判断、词项与主题 / 意图特征',12.5,color='muted',max_width=524)
    s.line([(1422,402),(1422,429)],'blue')
    s.line([(1422,454),(1422,473)],'blue')
    retrievers=[(1144,'BM25 主路径','范围内 Chunk 的内存索引\n词面 / 目录 / 意图规则排序','mint'),
                (1336,'可选向量','真实 embedding + Chroma\n索引就绪且语料签名一致','ice'),
                (1528,'图谱弱兜底','BM25 无候选时参与\n非始终三路并行','sand')]
    for x,title,body,fill in retrievers:
        s.rect(x,565,172,89,fill,None,8)
        s.text(x+12,577,title,16,'Bold')
        s.para(x+12,607,body,151,11.5,leading=18,max_lines=2)
    s.line([(1422,534),(1422,550),(1230,550),(1230,565)],'teal')
    s.line([(1422,534),(1422,565)],'blue',dashed=True)
    s.line([(1422,534),(1422,550),(1614,550),(1614,565)],'amber',dashed=True)
    s.rect(1144,686,556,66,'light',None,8)
    s.text(1160,697,'加权 RRF → 正文支持过滤 → 跨书覆盖优先 Top-k',15,'Bold',max_width=524)
    s.text(1160,729,'RRF = Σ w/(60+rank)；w = 1.0 / 0.8 / 0.05；默认 k=8',12.5,color='muted',max_width=524)
    for x,color,dash in ((1230,'teal',False),(1422,'blue',True),(1614,'amber',True)):
        s.line([(x,654),(x,671),(1422,671),(1422,686)],color,1.6,dashed=dash)
    s.rect(1144,785,556,52,'ice',None,8)
    s.text(1160,793,'SOURCE → RAG 回答模型 → 引用编号 / 句级绑定检查',14.5,'Bold')
    s.text(1160,818,'无模型 / 检查失败则返回原文材料；无支持则明确拒答',11.5,color='muted')
    s.line([(1422,752),(1422,785)],'blue')
    s.line([(1422,837),(1422,884)],'blue')
    s.rect(1124,884,596,100,'sand',None,10)
    s.text(1144,896,'返回来源 ID 后，再从本地重取规范原文',18,'Bold')
    s.para(1144,928,'联查课程、教材、Chapter、Chunk；过滤越界、空白与伪造来源\n原文入证据池，RAG 回答仅作观察；保留来源哈希以检测变化',555,13,leading=22,max_lines=2)
    s.line([(1046,971),(1060,971),(1060,952),(1124,952)],'amber',1.6)

    # One verifiable example instead of another long feature list.
    s.rect(56,1041,1688,89,'dark',None,10)
    s.text(80,1055,'已验证的反馈路径',17,'Bold','white')
    s.text(80,1085,'无命中 → 改写查询 → 起草 40 分钟 → 45 分钟要求检查失败 → 修订为 45 分钟 → 重新检查',20,'Bold','white')
    s.text(1285,1058,'离线脚本策略验证，非在线模型表现',12,color='white')
    s.footer(1,'实现快照：2026-10-28。依据：lesson_runtime / lesson_policy / lesson_contracts / rag_tool / retrieval_service / rag_agent / Agent架构技术复盘。')


def decision_row(s,y,index,title,why,alternative,proof):
    s.rect(56,y,990,154,'paper')
    s.tag(76,y+18,index,fill='dark',color='white',size=14,width=48)
    s.text(140,y+20,title,21,'Bold')
    s.para(140,y+58,why,868,15,color='ink',leading=23,max_lines=2)
    s.para(140,y+108,alternative,858,12.5,color='muted',leading=18,max_lines=1)
    s.text(140,y+132,proof,11.2,'Bold','teal',max_width=860)


def page_two(s):
    s.header('为什么这样设计，如何证明有效', '把检索质量、执行可靠性与教学效果分开验证；每个结论对应一类证据。', 2, '选型与验证')
    s.text(56,171,'四个关键选择',23,'Bold')
    s.text(1100,171,'三层验证，不能互相替代',23,'Bold')
    decision_row(s,213,'01','有限动作的单 Agent：反馈决定下一步',
                 '用有限动作让模型按缺项调整，用严格 JSON 兼容现有模型 API。服务端限制范围、预算与副作用，控制器保持可读、可测。',
                 '替代：固定流程顺序可预测但适应性弱；多 Agent / 状态图框架扩展强，但增加协调维护成本。',
                 '验证理由：必须验证真实控制器会接收失败反馈并修订，而非只出现“反思”文案。')
    decision_row(s,385,'02','保留 RAG 方法，用适配器形成工具边界',
                 '复用已有检索、融合和引用逻辑，先隔离 Agent 编排带来的变化；内部调用部署简单，需要时再切 HTTP。',
                 '替代：重写检索难隔离收益；立即拆微服务增加网络、运维和来源 ID 映射成本。',
                 '验证理由：原 RAG 三个核心文件无差异；用伪造、越界、空白、跨书章节数据检验来源边界。')
    decision_row(s,557,'03','JSON 检查点 + 单 worker + 快照 CAS',
                 '复用 SQLite 保存轨迹、预算和稿件。回答、停止与续跑比较最新快照，防止旧响应覆盖刚保存的成果。',
                 '替代：纯内存无法可靠恢复；分布式队列 / 状态版本适合扩容，但需租约、迁移与幂等设计。',
                 '验证理由：正常演示看不出竞态；需中断、取消、Q1→Q2、快速续跑交接的故障注入。')
    decision_row(s,729,'04','本地交付检查 + 教师最终判断',
                 '来源、教材覆盖、课时和结构有可解释规则；语义正确与课堂适用性交给教师。自动稿与教师稿分离保护。',
                 '替代：模型自评容易复用同一错误；增加模型裁判仍需人工标注校准，不能直接替代教师。',
                 '验证理由：finish 必须重验最新稿；保存稿、来源漂移和撤除模型配置均有回归。')

    # Evidence layer 1: current engineering tests.
    s.rect(1100,213,644,181,'dark',None)
    s.text(1124,230,'01  工程可靠性',19,'Bold','white')
    s.text(1530,235,'本轮 · 2026-10-28',12,color='white')
    s.text(1124,267,'310',40,'Bold','white')
    s.text(1215,286,'后端',14,color='white')
    s.text(1305,267,'83',40,'Bold','white')
    s.text(1371,286,'前端测试通过',14,color='white')
    s.para(1124,325,'隔离数据库、脚本决策、真实控制器、并发故障注入；构建与浏览器验收。\n独立复核另跑其中 45 项：属于 310 项子集，不能重复相加。',590,13,leading=22,max_lines=2,color='white')
    s.text(1124,374,'能证明：控制、来源、状态约束；不能证明：真实模型稳定选对工具。',11.5,color='white')

    # Evidence layer 2: explicitly dated historical retrieval-only regression.
    s.rect(1100,413,644,290,'paper')
    s.text(1124,432,'02  检索质量',19,'Bold')
    s.text(1430,437,'历史固定回归 · 2026-09-24',12,color='muted')
    s.text(1124,472,'420 题 · 7 本教材 · 137 章',23,'Bold','blue')
    s.text(1124,508,'100 人工核心题 + 320 脚本扩展题；直接调用生产 retrieve',13,color='muted')
    s.line([(1124,538),(1720,538)],'line',1,arrow=False)
    s.text(1124,554,'知识点覆盖命中 @8',14,'Bold')
    s.text(1520,550,'380 / 380',21,'Bold','blue')
    s.text(1124,589,'引用候选相关及页码有效 @3',14,'Bold')
    s.text(1520,585,'86.86%',21,'Bold','blue')
    s.text(1520,616,'985 / 1134 条',11,color='muted')
    s.text(1124,626,'跨书覆盖 41 / 41；域外拒答 40 / 40',13.5,color='ink')
    s.para(1124,654,'@8 为 rubric 覆盖门槛（多项知识≥60%），非逐 gold chunk 召回；@3 为相关及页码规则，非语义正确率。历史报告，本轮未重跑。',590,11.5,leading=18,max_lines=2)

    # Evidence layer 3: future human/model evaluation; never reported as complete.
    s.rect(1100,722,644,161,'sand',None)
    s.text(1124,740,'03  教学效果与真实模型策略',19,'Bold')
    s.tag(1622,737,'待验证',fill='paper',color='amber',size=12,width=98)
    s.para(1124,779,'真实模型能否稳定补查？引用是否支持结论？\n教案是否适合学情，能否减少教师的备课时间？',590,15,leading=25,max_lines=2,color='ink')
    s.text(1124,850,'需要独立任务集、教师盲评与对照实验，不能拿测试数量代替。',12,color='amber')

    # A concrete next experiment and its causal rationale.
    s.rect(56,929,1688,190,'mint',None)
    s.text(80,947,'下一步怎样评 Agent，为什么这样评',21,'Bold')
    steps=[('固定数据版本','教材、任务、rubric 与哈希'),('同条件对照','固定流程 vs Agent；同 RAG / 模型'),
           ('教师双人盲评','语义支持、完成度、课堂适用'),('记录成本与效率','改稿时间、调用费用、p50 / p95')]
    for i,(title,body) in enumerate(steps):
        x=80+i*413
        s.text(x,992,f'{i+1:02d}  {title}',17,'Bold','teal')
        s.text(x,1024,body,12.5,color='ink',max_width=395)
        if i<3:
            s.line([(x+374,1003),(x+403,1003)],'teal',1.6)
    s.text(80,1062,'为什么：控制检索与模型的混杂因素，区分“工程能运行”和“教学有收益”；盲评减少主观偏差，版本与轨迹便于复现。',15,color='ink')
    s.text(80,1092,'边界：当前为单 worker、JSON 检查点、协作式取消；不承诺分布式扩容、外部调用 exactly-once 或语义零幻觉。',12,color='muted')
    s.footer(2,'依据：Agent架构技术复盘；agent-v3-engineering-validation-20261028；teacher-benchmark-v3（历史检索报告，非新 Agent 效果分）。')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    for name,path in FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name,path))
    pdf_path=OUT/'courseweave-agent-rag-architecture-20261029.pdf'
    pdf=canvas.Canvas(str(pdf_path),pagesize=(W,H),pageCompression=1)
    pdf.setTitle('CourseWeave Agent / RAG - 架构、选型与验证')
    pdf.setAuthor('CourseWeave project / code-audited technical brief')
    sheets=[]
    for name,draw in [('courseweave-agent-rag-architecture',page_one),('courseweave-agent-rag-decisions-validation',page_two)]:
        sheet=Sheet(pdf,name)
        draw(sheet)
        sheet.save_svg()
        sheets.append(sheet)
        pdf.showPage()
    pdf.save()
    document=fitz.open(pdf_path)
    if len(document)!=2:
        raise ValueError('Expected exactly two pages')
    for page,sheet in zip(document,sheets):
        page.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).save(OUT/f'{sheet.name}-5400.png')
        page.get_pixmap(matrix=fitz.Matrix(1,1),alpha=False).save(OUT/f'{sheet.name}-preview.png')
        if '\ufffd' in page.get_text():
            raise ValueError('Replacement glyph in PDF text')
    manifest={'pdf':str(pdf_path),'pages':2,'logical_size':[W,H],'png_size':[W*3,H*3],
              'date':'2026-10-29','implementation_snapshot':'2026-10-28','facts':'Current local v3; RAG historical benchmark dated 2026-09-24',
              'sources':['docs/Agent架构技术复盘.md','docs/Agent系统架构.md','docs/evaluation/agent-v3-engineering-validation-20261028.md',
                         'docs/evaluation/teacher-benchmark-v3.md'],
              'text_boxes':{s.name:s.text_items for s in sheets}}
    (OUT/'courseweave-agent-rag-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pdf':str(pdf_path),'pages':2,'png_size':manifest['png_size']},ensure_ascii=False))


if __name__=='__main__':
    main()
