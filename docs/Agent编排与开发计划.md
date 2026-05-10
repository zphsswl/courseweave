# Agent 编排与开发计划

## 1. 编排原则

5 小时黑客松采用 **Orchestrator + 专职 Agent + Skill Registry** 模式。借鉴 gstack skill 思想，每个能力声明为独立 skill，包含输入/输出 schema、Prompt 模板、质量检查规则。

### 核心原则
1. **并行优先**：无依赖的 Agent 同时启动，最大化时间利用率
2. **主控集中**：只有 Orchestrator 和 Frontend 两个 Agent 写代码，其余 Agent 仅做研究和验证
3. **文件责任隔离**：每个 Agent 有明确文件清单，避免编辑冲突
4. **渐进式交付**：P0 MVP → P1 增强 → P2 打磨

## 2. Agent 矩阵

### 开发 Agent（代码编写权）

| Agent ID | 名称 | 负责文件 | 职责 |
|---|---|---|---|
| **MASTER** | 主控 Agent | `backend/main.py`, `backend/api/`, `backend/models/`, `backend/agents/`, `backend/services/`, `backend/prompts/`, 集成测试 | 全部后端代码 + 最终集成 |
| **FRONTEND** | 前端 Agent | `frontend/src/`, `frontend/package.json`, `frontend/vite.config.ts` | 全部前端代码 |
| **DOCS** | 文档 Agent | `docs/`, `report/`, `README.md` | 全部文档 |

### 研究/验证 Agent（只读查询，无代码编写权）

| Agent ID | 名称 | 职责 |
|---|---|---|
| **QA** | 质量 Agent | 测试 API 端点、检查页面可用性、验证引用存在 |
| **UI-REVIEW** | UI 审查 Agent | 使用 gstack 截图审查页面效果，对比设计稿 |

### 禁止规则
- 只有 MASTER 和 FRONTEND 可以调用 Edit/Write
- DOCS Agent 可以 Write 文档文件
- 所有其他 Agent 只能 Read/Grep/Glob/Bash（只读）
- 同一文件不能被两个 Agent 同时编辑

## 3. 开发阶段

### Phase 0: 骨架搭建 (0:00-0:25) — 并行

```
MASTER ──── backend/main.py, models/, api/ 路由, SQLite 建表
FRONTEND ── React+Vite 脚手架, Ant Design 布局, Cytoscape 集成
DOCS ────── README.md 初稿, 需求分析.md 骨架
```

**验收**：
- `GET /api/health` 返回 OK
- 浏览器打开 `localhost:5173` 能看到三栏布局
- SQLite 表创建成功

### Phase 1: 教材解析 (0:25-1:10) — 并行

```
MASTER ──── PDF parser, MD/TXT parser, 章节识别, upload API
             Chunking 服务, 状态轮询 API
FRONTEND ── 上传组件, 教材列表, 进度轮询, 章节展示
```

**验收**：
- 上传 PDF 后前端显示页数、章节、解析状态
- Chunk 数据入库

### Phase 2: 知识图谱 (1:10-2:05) — 并行

```
MASTER ──── KG 抽取 Prompt, LLM 调用, nodes/edges 存储
             Embedding 服务, 图谱查询 API
FRONTEND ── Cytoscape 图谱渲染, 节点详情面板, 缩放/拖拽/搜索
```

**验收**：
- 选择教材后可视化知识图谱
- 点击节点显示定义、章节、原文

### Phase 3: 跨教材整合 (2:05-2:55) — 串行

```
MASTER ──── 语义对齐, merge/keep/remove 决策, 压缩算法, 整合图谱 API
FRONTEND ── 整合图谱视图, 决策列表, 压缩比展示
```

**验收**：
- 显示合并决策、理由、置信度
- 整合图谱标注来源
- 压缩比低于 30%

### Phase 4: RAG 问答 (2:55-3:40) — 并行

```
MASTER ──── FAISS/Chroma 索引, rag/query API, 防幻觉 Prompt, 引用格式化
FRONTEND ── RAG 问答面板, 引用展示, 原文展开
```

**验收**：
- 输入问题返回带引用回答
- 引用包含教材名、章节、页码

### Phase 5: 教师对话与报告 (3:40-4:15) — 并行

```
MASTER ──── 教师对话 Agent, 决策修改 API, 报告生成
FRONTEND ── 教师聊天框, 报告面板, 导出按钮
DOCS ────── 更新报告和文档
```

**验收**：
- 教师输入"把抗原和免疫原分开"，系统修改决策
- 报告面板显示压缩比和决策摘要

### Phase 6: 文档与演示 (4:15-5:00) — 并行

```
DOCS ────── 补齐需求分析、系统设计、Agent架构说明、整合报告
QA ──────── API 测试, 页面功能测试, 引用验证
UI-REVIEW ─ 页面截图, UI 建议
```

**验收**：
- 所有文档完整
- 演示路径可走通
- 页面布局合理

## 4. Agent 通信协议

采用 **SQLite job 表** 作为状态总线，无需消息队列：

```
┌──────────────────────────────────────────┐
│              SQLite DB                    │
│                                           │
│  jobs 表: id, type, status, progress,     │
│           payload, result, error          │
│  textbooks, chapters, chunks, nodes,      │
│  edges, decisions, chat_history           │
│                                           │
│  MASTER 写 → 前端轮询 GET /api/jobs/{id} │
└──────────────────────────────────────────┘
```

### 状态机

```
pending → processing → completed
                     → failed → retry → processing
```

### Skill 注册表

```
backend/skills/
├── parse_textbook.skill.md    # PDF/MD/TXT 解析
├── chunk_sections.skill.md    # 章节切分
├── extract_kg.skill.md        # 知识图谱抽取
├── align_concepts.skill.md    # 跨教材对齐
├── compress_essence.skill.md  # 30% 压缩
├── rag_answer.skill.md        # RAG 问答
├── teacher_patch.skill.md     # 教师对话
└── generate_report.skill.md   # 报告生成
```

每个 skill 含：名称、场景、输入/输出 schema、Prompt 模板、重试策略、质量规则。

## 5. 数据流

```
PDF/MD/TXT 上传
  → Ingestion Agent 逐页解析 → textbook + chapter JSON → SQLite
  → Chunking Agent 切分正文 → chunks → SQLite + FAISS 索引
  → KG Extraction Agent 按章抽取 → nodes + edges → SQLite
  → Alignment Agent 跨教材对齐 → merge candidates → SQLite
  → Compression Agent 评分压缩 → merge decisions → SQLite
  → RAG Agent 建索引 → 检索 + 生成
  → Teacher Dialogue Agent 修改决策 → 更新图谱
  → Report Agent 汇总统计 → report/整合报告.md
```

## 6. 技术决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 前端框架 | React 18 + Vite + TypeScript | 搭建快，HMR 热更新 |
| UI 库 | Ant Design 5 | Table/Tabs/Upload 组件省时间 |
| 图谱 | Cytoscape.js + react-cytoscapejs | 医学概念图谱交互丰富 |
| 后端 | FastAPI + Uvicorn | 异步原生支持，开发快 |
| 数据库 | SQLite + SQLAlchemy | 零配置，足够黑客松 |
| PDF 解析 | PyMuPDF (fitz) | 中文支持好，逐页解析快 |
| 向量库 | ChromaDB | 比 FAISS 更易集成，内置 embedding |
| Embedding | paraphrase-multilingual-MiniLM-L12-v2 | 中文支持好，可本地运行 |
| LLM | OpenAI API 兼容接口 | 灵活切换 DeepSeek/通义千问 |
| 后台任务 | FastAPI BackgroundTasks | 轻量，不引入 Celery |
| 部署 | 单进程 FastAPI + 静态文件 | 最简单部署 |

## 7. 文件结构

```
C:\try03\
├── README.md
├── .env.example
├── requirements.txt
├── package.json              (frontend)
├── docs/
│   ├── 需求分析.md
│   ├── 系统设计.md
│   ├── Agent架构说明.md
│   ├── Agent编排与开发计划.md  (this file)
│   └── 接口文档.md
├── report/
│   └── 整合报告.md
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── api/
│   │   ├── textbooks.py
│   │   ├── jobs.py
│   │   ├── graph.py
│   │   ├── rag.py
│   │   ├── chat.py
│   │   └── report.py
│   ├── models/
│   │   └── schemas.py
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── ingestion_agent.py
│   │   ├── kg_extraction_agent.py
│   │   ├── alignment_agent.py
│   │   ├── compression_agent.py
│   │   ├── rag_agent.py
│   │   ├── teacher_dialogue_agent.py
│   │   └── report_agent.py
│   ├── services/
│   │   ├── pdf_parser.py
│   │   ├── chunker.py
│   │   ├── embeddings.py
│   │   └── vector_store.py
│   ├── prompts/
│   │   ├── kg_extraction.txt
│   │   ├── concept_alignment.txt
│   │   └── teacher_dialogue.txt
│   └── skills/
│       ├── parse_textbook.skill.md
│       ├── extract_kg.skill.md
│       ├── align_concepts.skill.md
│       ├── compress_essence.skill.md
│       ├── rag_answer.skill.md
│       ├── teacher_patch.skill.md
│       └── generate_report.skill.md
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── App.css
│       ├── api/
│       │   └── client.ts
│       ├── types/
│       │   └── index.ts
│       └── components/
│           ├── Layout.tsx
│           ├── TopBar.tsx
│           ├── TextbookPanel.tsx
│           ├── GraphCanvas.tsx
│           ├── NodeDetail.tsx
│           ├── DecisionPanel.tsx
│           ├── RagPanel.tsx
│           ├── TeacherChatPanel.tsx
│           └── ReportPanel.tsx
└── data/
    └── .gitkeep
```

## 8. 风险与兜底

| 风险 | 兜底方案 |
|---|---|
| LLM API 不可用 | 规则抽取 + 预置 mock 数据 |
| PDF 解析慢 | 后台逐页处理，前端显示进度 |
| ChromaDB 安装失败 | 降级为 TF-IDF + BM25 |
| 7 本教材全量处理超时 | 优先每本前 3 章用于演示 |
| 前端组件库安装慢 | 降级为纯 HTML/CSS/JS 单文件 |
| 整合图谱节点过多 | 限制每本最多 30 节点，过滤低重要度 |

## 9. 演示脚本（3 分钟）

1. 打开工作台 → 7 本教材已加载
2. 点击《病理学》→ 章节列表
3. 知识图谱 → 点击"炎症"节点 → 定义/章节/原文
4. 整合图谱 → 炎症来自 3 本教材 → 已合并为统一节点
5. 整合决策 → merge 理由和置信度 0.92
6. RAG 问答 → "炎症的基本病理变化是什么？" → 带引用回答
7. 教师对话 → "把抗原和免疫原分开" → 决策修改
8. 整合报告 → 压缩比 27.3% < 30%
9. Agent 架构文档 → Mermaid 图 + 并行 Agent 说明
