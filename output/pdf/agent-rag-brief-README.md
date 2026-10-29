# CourseWeave Agent / RAG 两页速览

制图日期：2026-10-29。实现与工程验收基线：2026-10-28。

- [两页矢量 PDF](./courseweave-agent-rag-architecture-20261029.pdf)：第一页完整架构；第二页设计取舍、验证方法与理由。
- [架构图高清 PNG](./courseweave-agent-rag-architecture-5400.png)、[说明页高清 PNG](./courseweave-agent-rag-decisions-validation-5400.png)：均为 5400 × 3600。
- [架构图 SVG](./courseweave-agent-rag-architecture.svg)、[说明页 SVG](./courseweave-agent-rag-decisions-validation.svg)：可编辑文字与图形，需本机具有相应中文字体。
- [生成脚本](../../scripts/build_agent_rag_brief.py)：使用 ReportLab 输出矢量 PDF，再用 PyMuPDF 栅格化 PNG；不调用模型、不读取业务数据库。

事实来源是[详细技术复盘](../../docs/Agent架构技术复盘.md)、[工程验收](../../docs/evaluation/agent-v3-engineering-validation-20261028.md)和生产代码。RAG 指标来自 2026-09-24 的[历史固定检索回归](../../docs/evaluation/teacher-benchmark-v3.md)，此轮没有重跑该语料评测，也没有将其作为新 Agent 的教学质量评分。

独立子 agent 审查了检索启用条件、工具与来源边界、状态与预算、历史指标口径，并审查最终图中文字与连线。图片与 PDF 是同一份代码绘制并逐页视觉复验，PDF 保留可选择文字；SVG 供后续版式编辑。

复现命令（需安装 `reportlab` 与 `PyMuPDF`）：

```powershell
python scripts/build_agent_rag_brief.py
```

中文字体默认使用 Windows 的微软雅黑 / 宋体。其他系统可通过 `COURSEWEAVE_FONT_REGULAR`、`COURSEWEAVE_FONT_BOLD`、`COURSEWEAVE_FONT_DISPLAY` 指定可用的 TrueType 中文字体。
