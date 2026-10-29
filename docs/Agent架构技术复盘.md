# CourseWeave Agent 架构技术复盘

初始记录日期：2026-10-28；最近增量更新：2026-10-29。记录对象：本地 `lesson_agent_v3` 实现，本轮尚未以提交号作为版本锚点。

本文由未承担这轮生产实现的架构记录子 agent 交叉读取代码和测试编写。目标是让项目所有者能解释、修改和验证系统。后续变更在文末按日期追加决策记录，并同步修正文中当前实现；历史理由保留。

快速配置和 API 查阅见 [Agent 系统架构](./Agent系统架构.md)；本文解释为什么这样做、代码如何联动、替代方案有什么代价。测试通过只能证明对应断言，不能替代真实模型评测或教师教学审核。

衍生展示材料：[两页架构、选型与验证 PDF](../output/pdf/courseweave-agent-rag-architecture-20261029.pdf)、[高清架构图](../output/pdf/courseweave-agent-rag-architecture-5400.png)，由[生成脚本](../scripts/build_agent_rag_brief.py)制作。制图日期为 2026-10-29，实现与工程验收基线为 2026-10-28；其中 RAG 检索数据来自 2026-09-24 的历史回归，本轮未重跑。此次仅导出展示材料，未改变生产架构，无需新增 ADR；技术事实仍以本文、源码和对应验收记录为准。

## 1. 先说明项目究竟解决什么问题

教师面对的任务不是“让模型生成一段话”，而是从多本教材中找出适合本课的材料，保留表述与来源差异，组织课时，核对后留下可编辑的教案。产品中的图谱、检索和 Agent 分别承担其中一部分，不应混为一种能力。

| 产品功能 | 在备课中的职责 | 为什么保留这个模块 | 主要代码入口与边界 |
| --- | --- | --- | --- |
| 课程与教材管理 | 明确本次可以使用哪些教材 | 来源范围必须先于检索与生成确定 | [`api/agent.py`](../backend/api/agent.py) 的 `_validate_scope`；课程不是多用户权限系统的替代物 |
| 教材解析与目录校对 | 将文件变成章节、页码和 Chunk，允许教师核对定位 | 错误页码会使后续所有引用失去意义 | [`ingestion_agent.py`](../backend/agents/ingestion_agent.py) 的 `ingest_textbook`、`chunk_textbook`；[`chapter_review.py`](../backend/services/chapter_review.py)；v3 将它们作为确定性前置条件 |
| 原文阅读与跨教材对照 | 让教师先核对不同书的真实表述 | 并排原文比未经验证的“共同结论”更容易审核 | [`teaching_service.py`](../backend/services/teaching_service.py)、[`teaching_bridge.py`](../backend/services/teaching_bridge.py)；检索命中不等于教学相关性已确认 |
| 教师材料板与关系记录 | 保存选材顺序、讲授标题、备注和关联理由 | 教师意图不能只保存在模型对话中 | [`teaching_board.py`](../backend/services/teaching_board.py) 的 `get_board_agent_context`；进入 Agent 时转换为受限上下文 |
| 知识树、概念关联与知识分布 | 帮助浏览来源模块和跨书关系 | 教材结构与可核对的语义关系适合可视化探索 | [`kg_extraction_agent.py`](../backend/agents/kg_extraction_agent.py)、[`alignment_agent.py`](../backend/agents/alignment_agent.py)、[`knowledgeDistributionModel.ts`](../frontend/src/components/knowledgeDistributionModel.ts)；教材/目录归属线不是语义边，教师确认关系另行处理；v3不自动批准关系，也不强制先抽完整图谱 |
| 教材问答 RAG | 检索、整理与教材问题相关的证据 | 是查证工具，也能供 Agent 按缺口多次调用 | [`rag_agent.py`](../backend/agents/rag_agent.py) 的 `query_rag`；检索、融合与回答方法本轮保持不变 |
| 备课 Agent | 根据结果选择下一动作，补查、修稿或提问 | 教案缺项经常在第一次检索或起草后才暴露 | [`lesson_runtime.py`](../backend/agents/lesson_runtime.py)；行动空间受工具、范围和预算限制 |
| 教师修改、投屏与导出 | 形成可继续使用的教学文档 | 教师最终判断必须能落入持久稿件 | [`AgentWorkbench.tsx`](../frontend/src/components/AgentWorkbench.tsx)、[`LessonPresenter.tsx`](../frontend/src/components/LessonPresenter.tsx)、[`lesson_print.py`](../backend/services/lesson_print.py)；编辑稿与模型稿分开 |

当前材料板、任务、教师稿和浏览器中的备课条件仍是不同对象；没有把它们统一建模为一个跨设备同步的 Lesson 聚合。这是现状，也是未来扩展时需要先处理的数据边界。

## 2. 从工作流到 Agent，实际改变发生在哪里

旧版 `course_agent._plan()` 预先规定八步，代码依次执行检查、准备、检索、生成和验证。即使其中调用了模型、复用了索引，控制下一步的主体仍是程序中的固定分支。

v3 的改变是：`process_agent_loop()` 把当前状态交给 `decide_next_action()`，模型只提出一个动作；执行后的真实观察再次进入下一轮输入。模型可以改变查询、补读原文、再次起草，也可以提出必要问题。它不能自行执行 Python、访问任意网络或宣布检查通过。

```text
确定性准备：教材范围 → 缺失解析 → 章节确认
                                      ↓
恢复已保存状态 → 模型提出一个动作 → 契约校验 → 服务端工具执行
       ↑                                       ↓
       └──── 真实观察、检查反馈、预算、检查点 ────┘
                     ↓
      教师回答后续跑 / 检查通过交付 / 有原因地停止
```

这是一种有边界的单 Agent 设计。开发过程中使用多个独立子 agent 做实现、复核和记录，不代表运行中的 CourseWeave 产品存在多个自治 Agent，也不代表使用了多 Agent 协商框架。

值得区分三种“计划”：旧版 `plan` 是预先列出的流程；v3 `plan` 主要是已选择动作的兼容展示镜像；真正的下一步动作来自每轮 policy 返回值。v3 没有另一个持久化的长期任务规划器，也没有跨任务学习记忆。

## 3. 模块怎么拆，为什么这样拆

### 3.1 入口 API：先固定任务，再让模型行动

入口是 [`create_agent_run`](../backend/api/agent.py)。它验证课程存在、教材均属于课程、上下文中的章节与 Chunk 位于本次教材范围，再创建 `Job(type="course_agent")`。来源板会在创建时展开为真实选材、备注和关系；补充来源与原有来源合并去重，最多 48 段。

`Job.payload` 是本次任务的基准，包含主题、目标、教材范围、学情、时长、问题数和教师上下文。回答不会直接重写原始请求，而是进入 `teacher_answers`。这是为了区分“最初要求”与“执行中的补充条件”。

选择理由：模型之前先做确定性检查，可以让越界请求根本不进入工具执行阶段，也使同一次任务的范围可复现。替代方案是让模型自行解释教师输入并选择所有教材，交互更自由，但会把范围选择与检索错误混在一起；本项目先采用明确教材选择。

### 3.2 Policy：模型负责提出下一步

[`lesson_policy.py`](../backend/agents/lesson_policy.py) 的 `decide_next_action(payload, state, timeout=...)` 调用已有 OpenAI-compatible 客户端。系统消息定义动作与边界，状态只出现在标记为不可信的 user 数据中；返回 JSON 经契约解析后交给运行器。

同一模型配置也用于教案生成，但“下一动作”和“完整教案”是不同调用。决策调用最多输出 800 tokens、温度 0.1，运行器传入不超过 45 秒的超时。SDK 自动重试被关闭，使调用次数与失败路径尽量由运行器控制。

状态并非全部塞给模型：保留最近六条动作；证据先转为带 Chunk ID 和 `S#` 的短摘录；草稿、观察、检查和回答分别限制大小。`_bounded_data()` 在序列化后继续裁剪，避免转义字符使 JSON 意外膨胀。

选择理由：只做单轮决策，让服务端控制执行与状态，容易替换模型，也容易用脚本策略测试。替代方案及代价：

| 方案 | 优点 | 代价与本轮选择 |
| --- | --- | --- |
| 一次让模型生成完整计划后固定执行 | 模型调用较少，顺序易展示 | 新证据出现后计划容易过时；不能替代反馈闭环 |
| 原生 function calling | 参数结构化体验成熟 | 不同兼容服务支持程度不同；本轮用严格 JSON 协议复用既有客户端 |
| LangGraph 等状态图框架 | 分支、持久化与扩展能力丰富 | 当前工具数与任务形态较小，增加依赖和抽象成本；需要复杂子图时再评估 |
| 自写任意代码 Agent | 动作自由度很高 | 很难保证教材范围、费用和副作用边界；当前没有这个需求 |

提示词中的“不可信”标记是模型输入约束，不是注入攻击的数学防护。真正能强制执行的边界来自白名单、数据库范围过滤和服务端验证。

### 3.3 Contracts：模型的句子变成受限动作

[`lesson_contracts.py`](../backend/agents/lesson_contracts.py) 使用 Pydantic 严格模型：拒绝多余字段、错误类型和未知动作，不把字符串数字悄悄转换为整数。`validate_decision()` 是无数据库、无网络的纯校验层。

所有动作共有三个字段，顶层 `summary` 是给教师看的动作摘要，长度 1–300 字；不是隐含推理。

```json
{"action":"inspect_course","arguments":{},"summary":"查看教材准备状态"}
{"action":"query_rag","arguments":{"question":"模块形成与反馈的教材依据","textbook_ids":["book_a","book_b"],"mode":"compare","top_k":8},"summary":"补查两本教材的相关原文"}
{"action":"read_source","arguments":{"chunk_id":"chunk_a"},"summary":"读取已知来源模块"}
{"action":"write_draft","arguments":{"instructions":"依据检查项补足45分钟课时"},"summary":"修订课时安排"}
{"action":"validate_draft","arguments":{},"summary":"核对稿件的引用和交付项"}
{"action":"ask_teacher","arguments":{"question":"本课重点是概念比较还是练习？","options":["概念比较","练习"]},"summary":"请教师确认教学侧重点"}
{"action":"finish","arguments":{"summary":"已形成待教师审核的草稿"},"summary":"提交当前草稿供教师审核"}
```

上面每行是一个独立动作示例，不能把七行一起作为一次模型响应。`query_rag` 的教材列表可省略或为空，表示原任务全部教材；非空时只能取其子集。`course_id`、URL 和 timeout 不属于模型参数。`read_source` 只接受本地 ID 形状，再由运行器核对真实归属。

| 参数 | 当前限制 | 为什么需要 |
| --- | --- | --- |
| 查询 question | 2–500 字 | 保留具体查证意图，限制状态增长 |
| `top_k` | 严格整数 3–15，默认 8 | 单次召回有界；适配器作为通用边界另支持 1–15 |
| mode | `all` / `compare` | 不接纳任意检索模式；compare 在适配器要求至少两本书 |
| 起草 instructions | 最多 2000 字 | 用于修订，不授予新权限 |
| 教师问题 / 选项 | 问题最多 500 字，最多 4 个选项，每项最多 500 字 | 避免等待区变成无界对话输出 |
| 教师回答 | 最多 2000 字，一任务最多 4 次 | 给任务补充条件，同时限制反复提问 |

选择理由：纯函数便于穷举非法输入，执行器不必同时处理“解析 JSON”和“修改数据库”。替代方案是工具内部各自读字典，会重复默认值与错误处理，容易出现某条路径漏校验。

### 3.4 Runtime：执行权和状态所有权

[`lesson_runtime.py`](../backend/agents/lesson_runtime.py) 的 `process_agent_loop()` 是闭环核心，`_execute()` 是七个允许动作的分发器。它不接收模型提交的可执行代码，也没有动态 import 模型工具名。

一轮的实际顺序如下，阅读代码时应逐句对应：

1. 读取任务，检查取消状态和剩余运行时间。
2. 先增加 `steps_used` 并保存检查点，再请求模型决策。
3. 再次校验动作、取消状态与时间，检查是否重复。
4. 对 RAG / 起草先增加对应预算，记录 `running` 动作并保存检查点。
5. 执行工具；返回后再次检查取消，更新观察和动作状态。
6. 保存结果；若等待教师或允许交付则退出，否则进入下一轮。

先预留预算再调用，是为了进程在外部调用途中退出时不会“免费重试”。代价是某次预算可能已经扣除，但调用没有真正完成；本项目选择防止无限费用，而不是精确还原每个外部服务是否实际计费。

异常有不同语义：动作参数或工具业务错误记 `rejected`，反馈给模型；模型不可用记可恢复的 `failed`；未知执行异常保留检查点，仅展示安全错误类型。`RunCancelled` 不再写回旧结果。

选择理由：用一个小控制器集中决定预算、范围和停止，比将这些规则分散在提示词中可靠。替代方案是把“重试、提问、结束”都交给模型文本，自由但难测试，且会把模型一句“完成了”误作成功。

## 4. 状态结构：先掌握三层，不要只看一个 status

第一层是 `Job.status`：任务是否排队、执行、等待、结束、失败或取消。第二层是 `delivery.status`：产物是待教师审核的草稿、仍有缺项还是证据材料。第三层是 `stop_reason`：这次为什么退出。

例如 `completed + needs_work + step_budget` 表示达到轮数上限且稿件仍有缺项；`completed` 本身不能解释为教案质量通过。预算停止时若现有稿已符合检查，`delivery` 也可能为 `draft_ready`，但停止原因仍然保留。

下面是结构示意，省略部分字段，不是完整响应 schema：

```json
{
  "status": "waiting_user",
  "payload": {"course_id":"course_x","topic":"模块","textbook_ids":["book_a","book_b"],"duration_minutes":45},
  "result": {
    "agent_version":"lesson_agent_v3",
    "execution_mode":"model_driven",
    "budget":{"max_steps":12,"steps_used":3,"max_rag_queries":6,"rag_queries_used":1,"max_drafts":3,"drafts_used":1,"max_runtime_seconds":300,"elapsed_seconds":15},
    "evidence":[{"id":"chunk_a","textbook_id":"book_a","content":"本地原文摘录","source_hash":"sha256..."}],
    "trajectory":[{"id":"action_x","step":3,"action":"ask_teacher","summary":"确认教学侧重点","status":"completed","observation":{"summary":"等待教师补充"}}],
    "approval":{"type":"teacher_question","request_id":"question_x","question":"重点是什么？","options":[]},
    "teacher_answers":[],
    "artifact":null,
    "lesson_draft":null,
    "draft_revision":0,
    "quality":null,
    "delivery":null,
    "stop_reason":null
  }
}
```

| 状态字段 | 谁负责写 | 关键不变量 |
| --- | --- | --- |
| payload | 创建 API | 模型不能扩大原请求课程和教材范围 |
| evidence | 运行器从本地 DB 重新装载 | 不采纳上游返回的正文和归属作为权威来源 |
| artifact | 草稿生成器，经服务端规范化 | 模型不能替换服务器提供的 citations |
| artifact_versions | 运行器 | 修稿时保存有限旧模型稿，当前最多保留三份历史快照 |
| lesson_draft | 教师保存 API | 自动 `write_draft` 拒绝覆盖；优先于 artifact 展示与导出 |
| draft_revision | 教师保存 API | 用期望版本防止覆盖另一标签页的教师修改 |
| quality / delivery | 本地验证器 | 模型的通过声明不构成检查结果 |
| trajectory | 运行器 | 实际动作、结果、拒绝与中断，不是预先编造的八步 |
| approval / teacher_answers | 运行器和控制 API | 回答必须匹配当前唯一问题编号 |
| budget | 运行器 | 重试、续跑不重置已花费次数；等待教师的时间不计入运行时间 |

为什么继续用 `Job.payload/result` JSON？它与已有 SQLite、队列、历史 API 兼容，本轮不需要数据库迁移。代价是大 JSON 会反复写入，字段关系没有独立表那样严格，也不是完整事件日志。未来如需审计每次状态转换、多 worker 争抢任务或跨任务分析，应考虑独立运行表、动作事件表和显式状态版本。

## 5. RAG 工具边界：保持算法，改变调用关系

本轮不重写 [`rag_agent.py`](../backend/agents/rag_agent.py)、[`retrieval_service.py`](../backend/services/retrieval_service.py) 或 [`api/rag.py`](../backend/api/rag.py)。已有检索负责 BM25、可选向量、图谱扩展及融合；已有 RAG 负责基于来源回答。新 Agent 不在旁边另造一套检索来冒充外部工具。

[`rag_tool.query_rag_tool()`](../backend/agents/rag_tool.py) 提供两种传输：默认直接调用既有 `query_rag`；服务端设置 `AGENT_RAG_URL` 时，向完整地址发送同形状的 HTTP POST。逻辑上的工具隔离不要求默认就拆成独立部署；需要独立服务时可切换传输。

选内部调用的好处是部署简单、沿用当前数据库与索引；不足是同进程故障和调用时间仍受既有实现影响。HTTP 隔离便于单独部署与替换，但增加网络故障、访问控制和来源 ID 映射成本。目前远端必须返回可映射到本地的 Chunk ID，不能直接接入任意外部文档编号。

### 5.1 为什么还要从本地数据库读一次

RAG 返回的 `citations` 是“候选来源声明”。适配器用这些 ID 查询真实 Chunk、教材、章节，核对课程、教材和章节归属，从本地取回正文与页码。运行器加入证据池时又只用 ID，重新建立自己的来源快照；直接 read_source 与教师选定上下文也统一检查 `Chapter.textbook_id == Textbook.id`，不能绕过RAG层的章节归属检查。章节标题取真实 Chapter，不依赖可能过期的 Chunk 缓存标题。

这相当于将“找到什么”和“什么可以成为本任务的证据”分开。即使远端说某条来自教材甲第 10 页，数据库实际上不是，就不能让这段元数据流入教师教案。

无效、空白、重复或超额引用会被拒绝/去重。删减引用可能改变上游 `S1/S2` 的含义，所以适配器不继续保留可能悬空的回答编号，而是降级为证据材料。工具报错也不能被解释为“教材不存在这个知识点”。

HTTP 地址只来自服务端，不允许模型改 URL；请求不跟随重定向、不沿用环境代理，响应最多 1 MiB。30 秒是 httpx 连接、读写等阶段超时的上限配置，不应描述为整个响应必定在 30 秒内结束的硬墙钟保证。

### 5.2 Chunk ID、`S#` 和概念 ID 不是一回事

`chunk_id` 是数据库原文块身份；`S1` 是当前证据列表内的临时引用编号；知识节点或 canonical concept 则表示来源模块/概念组织。生成器通过 `_citations(items)` 按证据顺序建立 `S# → chunk_id` 对照，不接受模型另写一套 citations。

证据加入采用追加去重顺序，已有编号不会因为一次补查重新排序。模型起草的各行只能引用已有 `S#`，未知 `S999` 被规范化去除，随后来源绑定检查会暴露缺项。引用存在不等于该结论得到引用的语义支持。

### 5.3 来源快照与截断为什么分层

| 层次 | 当前处理 | 设计目的 / 限制 |
| --- | --- | --- |
| 数据库 Chunk | 保留规范正文与页码 | 原始证据权威来自这里 |
| 运行器 evidence | 正文最多 12000 字，同时对完整正文做 SHA-256 | 控制 Job JSON 体积；正文后半部分变化仍能被哈希发现 |
| Policy 摘录 | 每条先取最多 600 字，再受总上下文预算约束 | 给下一动作选择足够线索，避免全文淹没状态 |
| read_source 观察 | `last_read` 正文最多 8000 字 | 可补读较长片段，但不是无限读取整本书 |
| 教案生成来源 | 每段上限 `max(400,min(6000,48000/n))` | 在多来源时控制模型输入；有裁剪记录，不假装全部已读 |
| 产物 citation quote | 每条最多 6000 字 | 支持界面回查，完整阅读仍应返回教材来源 |

短摘录可能遗漏教学条件，这是上下文控制的代价；正确改进方向是按范围补读或改善来源选择，而不是在模型看不到时让它猜测。

## 6. 起草、检查与修订，如何构成真实闭环

`_execute(write_draft)` 将修订要求、上一版模型稿、上次交付缺项和最近教师回答传给 [`course_agent._generate_artifact()`](../backend/agents/course_agent.py)。这是实参传递，不只是在界面展示“正在反思”。

生成器将修订上下文放入 `UNTRUSTED_REVISION_CONTEXT`，教材原文材料放入 SOURCE 区域。旧稿过长时舍弃旧稿正文，保留检查项与回答；原文输入裁剪另有 `source_context_trace`。起草超时由剩余预算约束，最多配置 60 秒，自动重试关闭。

模型输出会经过 `_normalize_artifact()`：仅取现有结构字段、使用服务端 citations、清理引用编号、规范分钟值；只得到一本教材支持的 `common_ground` 会移入单教材讲解顺序并留下待确认说明。模型提交的 `teacher_edited`、`semantic_reviewed` 或自行创建的来源均不构成权限。

### 6.1 验证器到底验证什么

[`verify_artifact()`](../backend/agents/course_agent.py) 的确定性断言包括：选定教材是否被实际条目引用覆盖；引用是否属于教材范围；使用的页码是否有效；结构行是否绑定已知编号；教材差异条目的书名与引用是否对应；共同结论是否关联至少两本不同教材。

交付断言包括：课时分钟总和等于请求、问题数量等于请求、概览/目标/讲解顺序存在、要求字段存在、教师选定原文被使用。`focus_terms` 目前主要检查词面出现；自定义未映射关注项会标记需要教师核验，不存在通用的目标语义判定器。

不能从这些断言推出：结论在学理上正确、两本教材真正同义、活动适合该班学生、难度或时间分配合理。`semantic_reviewed` 始终为 false，`source_check_score` 只反映来源规则通过比例，不能作为教案智能质量分。

### 6.2 为什么 `finish` 不能信缓存

`_validate()` 会重新核对来源快照，再运行真实验证器，写入当前检查与 `validated_signature` 校验记录。每次改稿或新增证据会清除该记录。重复动作检测使用的是当轮重新计算的 `_signature(state)`，存为轨迹的 `input_signature`；不是直接信任旧的 `validated_signature`。

`finish` **每次重新调用 `_validate()`**，不因为 state 里有旧的 `draft_ready` 就直接结束。系统提示建议先 `validate_draft` 再 `finish`，但运行器也允许模型直接提出 `finish`，并在该动作内完成真实检查。因此“没有单独 validate 动作”不等于绕过验证。

选择每次重验而非只比较签名，是为了让完成门禁保持直观可靠，代价是多一次本地计算和来源读取。当前数据规模与验证成本适合这个选择。

### 6.3 一条测试中实际执行的失败修复轨迹

对应 [`test_empty_query_changes_then_validation_failure_drives_a_real_revision`](../tests/test_agent_runtime.py)。测试替换决策策略、RAG 传输和草稿模型，范围过滤、DB 来源装载、预算、检查点与验证器执行生产代码。

| 轮次 | 动作与真实反馈 | 累计 RAG / 起草 | 下一轮可见的状态变化 |
| --- | --- | --- | --- |
| 1 | 查询“模块基础”，无来源 | 1 / 0 | `added_count=0`，不能直接生成有依据的教案 |
| 2 | 改查“模块的形成与反馈”，获得两本书来源 | 2 / 0 | evidence 加入 `chunk_a/chunk_b`，可建立 S1/S2 |
| 3 | 起草，模型桩仅排 40 分钟 | 2 / 1 | 生成稿存在，旧 quality/delivery 清空 |
| 4 | 检查请求为 45 分钟，返回缺项 | 2 / 1 | delivery 为 `needs_work`，明确课时 40/45 |
| 5 | 根据反馈修订为 45 分钟 | 2 / 2 | 上一版稿进入 artifact_versions，新稿待检查 |
| 6 | finish 内重新检查，通过 | 2 / 2 | `completed + draft_ready + delivery_ready`；仍待教师审核 |

测试断言第二次生成的实参包含失败反馈与 40 分钟旧稿，最终稿为 45 分钟，旧版仍保留，并断言实际查询 2 次、起草 2 次。这证明修订通道接通；不证明真实模型必然会作出这一序列的选择。

## 7. 人类参与：两种等待不能混用

`chapter_review` 是确定性来源定位检查点，教师到目录核对后走 `/resume`；`teacher_question` 是模型提出的具体教学问题，带唯一 `request_id`，必须通过 `/respond` 提交回答。只按一个“继续”按钮处理所有等待，会丢失补充条件或绕过提问。

回答成功时，API 将问题、答案、时间和 request_id 加入 `teacher_answers`，清空 approval，任务变为 pending，再入队恢复。原证据、模型稿、已花费预算保留；不要求从头检索。重复提交、旧 request_id、空白回答或超出次数均拒绝。

一个反例是多标签页：标签 A 正在回答 Q1，标签 B 已回答 Q1，Agent 很快又问 Q2。此时状态又是 `waiting_user`，只比较 status 无法判断 A 的回答已经过期，这就是此处的 ABA 问题。

### 7.1 CAS 为什么比“按钮防双击”更重要

`respond`、`resume` 和 `cancel` 都在写入时比较所读的整个 `Job.result`，并限制当前任务状态，只有快照仍相等才更新。它相当于“我只修改刚才看到的那一版”。若工具或另一请求先更新，则返回 409，让界面刷新并保留输入。

仅在 Python 中先 `if status == ...` 再无条件写入不够；判断和写入之间可能已有新检查点。仅比较 status 也不够，因为状态可能离开后又回到同一个值。

| 方案 | 优点 | 代价 |
| --- | --- | --- |
| 当前：完整 JSON 快照比较 | 不迁移 DB，能阻止旧结果覆盖新检查点 | 比较和写入较重；JSON 顺序/后端表示的迁移需要谨慎 |
| 显式 `state_version` 整数 CAS | 条件短，跨存储更清楚 | 需要迁移并保证所有状态写入都递增版本 |
| 悲观行锁 | 事务逻辑直观 | SQLite 行锁能力与长请求不适合照搬；仍不能把网络调用包进锁 |

当前 CAS 保护这几个用户控制入口，不应宣传为全系统多 worker 并发所有权协议。运行器检查点依赖现有单 worker 部署；多进程执行同一任务需要另加领取租约/执行版本。

## 8. 取消、失败和重启：最容易在演示中被忽略的逻辑

### 8.1 取消先保护数据库状态

`cancel` 只支持 v3 活跃状态。它保留材料和稿件，写 `cancelled`、清空等待问题并记录 `user_cancelled`。重复取消已取消任务是幂等的；已经 completed/failed 的任务返回冲突。

运行器工具返回后还会 `_ensure_active()`；`save_checkpoint()` 的 SQL 也包含 `status != cancelled`。前者是及时发现，后者是原子写入保护；两者缺一会留下“检查后又被取消”的窗口。

如果取消读快照后工具刚保存了新稿，取消的完整 JSON CAS 会冲突，返回 409，并保留新稿；不会拿旧快照盖回去。这时用户可以刷新后再停止。

取消是协作式停止：不能保证立即终止已经发出的模型/RAG 请求，也不能撤销已发生的外部计费。这里的强保证是被取消的任务不能被迟到工具结果改回 processing/completed。

### 8.2 持久任务不等于 exactly-once

[`job_queue.py`](../backend/services/job_queue.py) 使用一个进程内 worker 和 `_enqueued` 去重集合；任务数据保存在 SQLite。启动时 [`_recover_interrupted_jobs()`](../backend/database.py) 将 pending/processing 任务重新排队。

恢复循环先把上一次 `running` 轨迹和对应 plan 行标记为 interrupted/failed，再让模型根据已保存状态选择下一步。已经保存成功的查询不直接从头重放；已预留预算仍然消耗。

但外部调用若实际完成而结果尚未落库就崩溃，系统不能证明它从未发生。再次决策仍可能产生一次相似调用。本轮没有服务端外部幂等键、事务发件箱或完整事件溯源，因此不能宣称 exactly-once 或零重复费用。

单 worker 选择适合本地项目与演示，减少并发复杂度；代价是长任务占用队列、吞吐有限。替代方案是 Celery/Redis 或带租约的数据库 worker，适合并行任务和水平扩容，但引入部署、抢占、重复执行与可观测性成本。

还有一个不能靠前端防重解决的队列交接窗口：运行器已经保存 waiting/failed，旧 worker 尚未退出 `_dispatch_job()`；教师此时回答、确认或重试，API把任务改回 pending，但入队因为 ID 仍在 `_enqueued` 中被去重。若旧 worker 只移除去重标记，这个 pending 就失去唤醒。

本轮独立源码复核提出此反例，注入测试确认旧逻辑在回答、重试、章节继续三条路径均会失败。当前 `_worker_loop()` 的 finally 先释放旧去重标记，再读数据库最新状态，只对 pending 再调用幂等 `enqueue_job()`。尚未回答的 waiting、终态和取消不会忙重排；它修复的是本进程交接，仍不构成分布式任务领取协议。

### 8.3 来源变化不悄悄重绑定旧稿

`_evidence_current()` 对照真实 Chunk 的正文哈希、教材、章节、路径和页码。发生变化时清空旧通过结果，将交付标为 needs_work，并要求基于新来源创建任务；原教师稿保留。

为什么不直接更新旧稿的来源？因为旧结论可能依据的是修改前的正文，换成新引用会制造错误的证据链。替代方案是给教材与 Chunk 建独立版本并保存旧原文，使旧稿继续可回溯；这更完整，但本轮未引入版本化原文存储。

### 8.4 无模型配置也不能丢稿

[`process_course_agent()`](../backend/agents/course_agent.py) 根据版本与配置分流：历史 v2 沿用旧流程；全新未配置模型的任务明确运行 `evidence_workflow`。它整理原文证据，不宣称模型自主规划。

如果 v3 已有真实轨迹、教师稿，或已有模型驱动原稿，撤除模型配置后重试会保留检查点并报告模型未配置，不切到可能重新生成的旧流程。这个判断既保护有轨迹任务，也保护历史数据中“有教师稿但没有 trajectory”的情况。

选择显式降级的好处是无密钥仍可使用材料整理；代价是双路径与历史兼容代码更复杂。不能简单把所有失败都转入旧流程，因为旧流程与新运行器的产物签名、预算和教师稿保护语义不同。

## 9. 如何控制循环，而不假装模型能自律

| 控制项 | 默认值 / 实际规则 | 为何选择及替代方案 |
| --- | --- | --- |
| 决策轮次 | 12，环境可设 4–40 | 防止无界反思；单纯提示词“尽快结束”没有执行保障 |
| RAG 查询 | 6，环境可设 1–15 | 给补查空间，也限制时间与上游模型费用 |
| 起草尝试 | 3，环境可设 1–6 | 允许修订，避免整篇反复生成 |
| 运行时间 | 300 秒，环境可设 30–900 | 调度前与模型返回后都检查；不作为硬强杀保证 |
| 重复动作 | 相同动作参数 + 相同材料/稿件签名，已有两次后拒绝 | 改写公开摘要不能绕过；改查询可尝试新方向 |
| 无进展计数 | 达到 4 后停止 | 查不到新证据或连续拒绝不能无限继续 |

`decision_fingerprint()` 忽略公开摘要，查询教材集合先排序，finish 摘要也不影响指纹。`_signature()` 反映证据 ID/哈希与当前稿，避免把材料变化后的同一动作误认为没有变化。

“进展”目前是工程启发式：材料/稿件变化，或读取/检查/观察类动作；不是教学质量提升。重复指纹和总轮数共同兜底，因此不能用 `no_progress_count` 作为智能效果指标。

时间使用 monotonic 计时，等待教师前保存已用时间，恢复后累计新增运行时间。例：先前 11 秒、准备 7 秒，暂停时为 18；教师离开一小时不计入，恢复准备 2 秒后为 20。内部 RAG 沿用原有超时，不能靠外层一个数字强制中断它。

## 10. 前端为什么按现在的方式显示

[`lessonAgent.ts`](../frontend/src/api/lessonAgent.ts) 将后端结果转换为 `lessonExecution()` 展示模型，识别 v3 模型执行、证据降级和历史 v2。`trajectoryObservation()` 只展示有限事实字段，不原样渲染任意 provider payload。

[`AgentWorkbench.tsx`](../frontend/src/components/AgentWorkbench.tsx) 的目标是让教师看懂任务停在哪里并继续教学判断。轨迹按实际动作显示，预算是用量，不画成“教案完成百分比”。章节确认、教师提问和未知等待状态分别处理，未知类型不会自动续跑。

回答草稿按 `course/run/request_id` 在本机 localStorage 尽力暂存，提交成功才清除；409或网络失败保留该问题草稿，新 request_id 不自动继承旧回答。它不跨设备同步，浏览器禁用存储或配额耗尽时，仍可保留当前内存输入，但不能保证刷新后恢复。建议选项只填入输入框，不替教师自动提交。

`beginMutation()`、AbortController 和 epoch 共同限制前端竞态：防双击、切课程/任务后不接纳旧响应、操作完成后读取最新状态。取消结果若已是 completed，就显示最新状态，不能仅因点击过停止而虚报 cancelled。

旧 Job 时间使用没有时区后缀的 UTC ISO 字符串，新轨迹使用带 `+00:00` 的时间。`parseLessonTimestamp()` 将前者明确按 UTC 解析、保留后者时区信息，工作台共用后再转成本地时间，避免任务历史和轨迹相差八小时。`model_not_configured` 的通用文案只说保留材料；是否实际执行证据工作流由 `execution_mode` 单独解释，避免失败恢复时误报。

选择按任务持久结果轮询而非直接串流模型文本，便于刷新恢复与保持来源/产物一致；代价是状态反馈没有 token 流式输出细。可替代为 SSE 推送结构化事件，但服务端持久状态和版本判断仍需保留，不能只靠流式文字。

## 11. 本轮独立复核发现了什么，为什么要记录

下面是已在本轮修复并固化的失败路径。它们比“有工具调用、有思考动画”更能说明项目的工程难点。后续若重构，不能只保留正常交付样例而删除这些回归。

| 发现的问题 | 原因与修复 | 回归入口 |
| --- | --- | --- |
| 中断恢复后 plan 仍显示 running | 只修 trajectory，未同步兼容展示行；恢复时按动作 ID 同步标失败 | `test_tool_interruption_resumes_without_replaying_completed_query_or_leaving_running_rows` |
| 空白原文也能被算作某书证据 | read_source 路径缺少空正文拒绝；DB hydration 增加 strip 检查 | `test_empty_stored_source_cannot_count_as_a_books_supporting_evidence` |
| read_source绕过RAG的章节归属检查 | Chunk可指向另一书章节；运行器同样join Chapter并校验所属教材，标题取规范章节表 | `test_cross_book_chapter_reference_cannot_bypass_rag_scope_checks`；`test_current_chapter_title_is_authoritative_over_stale_chunk_title_cache` |
| 模型决策耗尽时间后仍启动工具 | 只在决策前检查时间；增加返回后检查 | `test_policy_spending_the_remaining_time_cannot_start_its_proposed_tool` |
| 章节等待前准备时间未计入 | 绕过统一计时 checkpoint；改用统一入口 | `test_chapter_pause_saves_active_elapsed_time_and_resume_excludes_teacher_wait` |
| 撤除模型配置后教师稿被旧流程清空 | 无 key 无条件切旧流程；对已有轨迹/教师稿/模型稿保留失败检查点 | [`test_agent_no_key_recovery.py`](../tests/test_agent_no_key_recovery.py) |
| 取消时旧快照盖掉刚保存的新稿 | 只按活跃 status 写回；增加 result CAS，冲突409 | [`test_agent_control_races.py`](../tests/test_agent_control_races.py) 的 `test_cancel_cannot_erase_a_tool_checkpoint_saved_after_its_read` |
| 旧 Q1 回答覆盖新 Q2 | 状态回到 waiting_user 后仅 status 无法识别 ABA；增加快照 CAS | 同文件 `test_old_question_response_cannot_overwrite_a_new_waiting_question` |
| 旧 resume 恢复已取消任务 | ORM 状态写入未限制原快照；改条件更新 | 同文件 `test_old_chapter_resume_cannot_revive_a_concurrently_cancelled_run` |
| 已回答/重试任务丢失入队唤醒 | 原worker尚持去重标记，新pending入队被挡；finally释放后重读pending并幂等入队 | [`test_agent_queue_handoff.py`](../tests/test_agent_queue_handoff.py) 的回答、重试、章节继续三个回归，及不忙重排控制组 |
| 历史时间与新轨迹显示相差八小时 | naive UTC被浏览器按本地时区解析；使用统一时间解析函数 | [`lesson-execution.test.mjs`](../frontend/tests/lesson-execution.test.mjs) 的时间解析回归 |

运行器回归集中在 [`test_agent_runtime.py`](../tests/test_agent_runtime.py)，生成实参与引用规范化集中在 [`test_agent_generation.py`](../tests/test_agent_generation.py)。还有不信旧 quality 的 finish 回归、原文漂移、跨课程来源拒绝、教师稿拒绝覆盖和各类预算测试。队列交接回归中临时恢复旧 finally 会使三个唤醒场景失败，修复后连同终态控制组四项通过；这是一轮实际的红绿对照，不是只验证测试桩本身。

主任务还在隔离合成教材数据库上完成了浏览器验收：建议选项填入但不自动提交、刷新保留输入、真实 HTTP 停止、完成稿与三条实际动作显示。该证据验证交互，不代表真实教材上的模型语义质量；合成验收任务不能混入正式课程历史或效果数据集。

本轮最终工程记录见 [Agent v3 工程验收](./evaluation/agent-v3-engineering-validation-20261028.md)：主任务实跑后端 310/310、前端 83/83 与生产构建通过，原 RAG 三个核心文件无差异。架构记录者另独立运行本文涉及的运行器、生成器、并发、无模型恢复和队列交接共 45 项，全部通过；这些数字只描述该版本的工程回归，不是教学效果评分。

### 11.1 验证分层，不能拿一层替代另一层

| 层 | 可以证明 | 不能证明 |
| --- | --- | --- |
| 契约与 policy 单测 | 真正调用参数、严格解析、上下文限制、安全错误处理 | 在线模型总能选对动作 |
| RAG 适配测试 | 原方法透传、HTTP 边界、本地来源过滤与回答降级 | 真实教材查询召回充分 |
| 脚本轨迹 + 内存 DB | 生产控制器能补查/修订/恢复/停止并保持约束 | 模型实际会采取这些策略 |
| 生成器模拟响应 | 反馈、旧稿和回答确实传入；引用由服务端控制 | 教案知识正确、无语义幻觉 |
| 竞态故障注入 | 指定交错写入不会覆盖新状态 | 所有部署规模下不存在竞态 |
| 前端 handler 回归与构建 | 防重复、迟到响应、错误恢复与类型/打包正确 | 所有屏幕布局、可访问性或教学效率 |
| 真实模型与教师评测（待持续建设） | 可量化动作成功率、内容质量、人工修改量 | 不能从本轮离线桩直接推断这些指标 |

## 12. 项目所有者的学习与动手路线

建议按照一次请求经过的顺序学习，而不是先背 Agent 框架名：

1. 阅读 `api/agent.py:create_agent_run`，手画原始请求范围，解释为什么模型不能加教材。
2. 阅读 `initial_agent_result` 和 `runtime_fields`，把 payload、result、status、delivery、stop_reason 分开。
3. 阅读 `lesson_contracts`，亲手构造非法额外字段、字符串 top_k 和范围外教材，看它们在哪一层被拒绝。
4. 顺读 `process_agent_loop`，标出每一个 checkpoint 与预算增加位置，解释崩溃前后可能留下什么。
5. 阅读 `rag_tool._local_items` 和 runtime `_read_sources`，沿 S1 回查到真实 Chunk，区分检索结果与规范证据。
6. 阅读 `_generate_artifact`、`_normalize_artifact`、`verify_artifact`，解释“模型输出”“服务端规范化”“本地校验”三者不同职责。
7. 阅读 respond/cancel/resume 的条件更新，再运行竞态回归，解释 status-only 为什么会错。
8. 阅读前端 `lessonExecution`、回答 handler 和 epoch，解释为什么后端 CAS 与前端防重都需要。

可复现命令使用已安装项目依赖的 Python；当前电脑若 `.venv` 解释器失效，先按 README 修复/选择解释器，不必改测试代码来迁就环境。

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
$env:LLM_API_KEY = ''
$env:OPENAI_API_KEY = ''
$env:DATABASE_URL = 'sqlite:///:memory:'
python -m unittest tests.test_agent_runtime tests.test_agent_generation tests.test_agent_control_races tests.test_agent_no_key_recovery tests.test_agent_queue_handoff -v
Push-Location frontend
node --test tests/lesson-execution.test.mjs tests/lesson-actions.test.mjs
Pop-Location
```

| 练习 | 动手内容 | 你应能预测的结果 |
| --- | --- | --- |
| 手算预算 | 六步脚本轨迹中将 max_drafts 改为1 | 第二次起草被拒，已有40分钟稿保留，不能伪装45分钟交付 |
| 伪造通过结果 | 写入旧 quality=draft_ready，再将当前稿课时改40 | finish 重新计算并拒绝，说明缓存不是门禁 |
| 伪造来源 | 上游返回别的课程 chunk_id 或虚假页码 | 外来 ID 被拒；合法 ID 的页码与正文以本地为准 |
| 修改正文尾部 | 改动超过12000字的 Chunk 后半部分 | 完整正文哈希改变，即使快照摘录没变也发现漂移 |
| 模拟等待 | 先ask，记录预算；回答后恢复 | 旧来源复用、回答进入生成上下文，等待时间不消耗执行预算 |
| 模拟并发 | 在控制API写前插入新checkpoint | 旧快照写入返回409，新稿与预算保持完整 |

练习应在测试自建数据库里进行，不能为理解架构而直接改真实教材、用户任务或密钥配置。

### 12.1 面试或技术讲解时能被源码支持的回答

| 追问 | 可以给出的回答 | 应避免的说法 |
| --- | --- | --- |
| 你的项目为什么是 Agent？ | 模型每轮根据工具结果选择下一动作，控制器执行、持久化并反馈；可以补查、修订、提问 | “用了大模型和几个agent命名文件，所以是Agent” |
| 为什么不直接用某框架？ | 当前七个动作、单任务闭环，用小控制器复用既有DB/队列；复杂分支与并发时再权衡框架 | “框架都没用”或“自研一定更先进” |
| RAG 和 Agent 什么关系？ | RAG 负责证据查证，Agent 根据目标与缺项决定何时、如何调用它 | “把原RAG重命名为Agent” |
| 怎么证明不会胡编？ | 限定来源、规范化引用、检查结构并保留原文；语义正确性仍需教师评测 | “有引用，所以无幻觉” |
| 怎么防止无限循环？ | 轮次/RAG/起草/时间预算、重复指纹、无进展停止；预算先落库 | “让模型自己判断完成” |
| 重启怎么恢复？ | SQLite保存检查点，恢复未结束任务、标记中断动作并重新决策，已花预算保留 | “所有外部调用都exactly-once” |
| 取消为什么还要SQL条件？ | 工具返回与取消存在竞态，原子谓词防止迟到写回复活任务 | “前端abort就取消后端” |
| 做了哪些量化验证？ | 报告真实测试断言、失败注入与回归结果；在线成功率需另设任务集 | 用离线测试数量替代教学效果指标 |

## 13. 已知边界与下一阶段的判断依据

当前没有通用浏览器/文件执行工具，没有多 Agent 协商，没有跨任务自动学习记忆，没有独立的教学语义裁判；也没有分布式 worker 领取租约。产品围绕教师、教材证据和一堂课的有限任务设计。

接下来若想提高模型实际效果，优先建立带教材范围与可审核成果的备课任务集，记录真实动作序列、调用数、无效查询率、教师修改量、引用语义支持和人工节省时间；对照同材料的固定工作流，不能只比较界面是否有轨迹。

如果主要瓶颈是知识内容错误，应先检查解析、召回与证据充分性；如果是动作选择差，应改策略上下文或动作设计；如果是多人并发与长任务，则先升级任务租约、状态版本与队列。不能用“再加一个Agent”代替故障定位。

## 14. 决策记录与后续累积方式

### ADR-001 · 2026-10-28 · 用有限动作单 Agent 替代固定备课顺序

**背景**：缺项要到检索/起草后才出现；原八步难以根据反馈调整。

**决定**：每轮一个动作，服务端执行与检查，保留确定性解析/章节准备。

**替代**：继续固定流程成本低但适应性不足；一次生成长计划容易过时；多 Agent 增加协调与状态成本。

**后果**：可表达补查/修订/提问，但模型调用次数增加，需要预算与真实轨迹；离线测试不能证明模型策略质量。

### ADR-002 · 2026-10-28 · 保持 RAG 算法，以适配层提供工具

**决定**：内部调用默认，HTTP可选；仅接纳能映射本地DB的来源，服务器重新装载证据。

**替代**：重写检索破坏已有评测可比性；完全信任远端引用简单但可能污染来源；立刻拆微服务增加运维成本。

**后果**：检索方法可保持稳定，但外部工具尚不能直接接纳独立文档ID，需要来源同步/映射。

### ADR-003 · 2026-10-28 · JSON 检查点与先预留预算

**决定**：复用 Job 表与单worker，动作前后落库，重启不退还预算。

**替代**：仅内存状态难恢复；独立事件表/工作流引擎更适合复杂审计但迁移成本更高。

**后果**：实现直接、无本轮schema迁移；有重复外部调用窗口，不能声称事件溯源或exactly-once。

### ADR-004 · 2026-10-28 · 完成由本地规则判定，教师稿独立

**决定**：finish重新校验，自动稿和教师稿分开，教师修改使用revision，源码漂移时保留旧稿而要求新任务。

**替代**：模型自评灵活但不可作为客观通过证据；覆盖式修改简单但可能丢失教师工作；保存原文版本更完整但未在本轮实现。

**后果**：来源和结构有确定性门禁，语义仍待教师；自定义关注项需要进一步设计可验证契约。

### ADR-005 · 2026-10-28 · 用户控制接口使用快照 CAS

**决定**：回答、章节继续、取消均比较所读结果与当前状态；冲突409保留最新成果和本机输入。

**替代**：只防双击不能挡多标签；只比较状态挡不住ABA；显式整数状态版本更适合后续跨存储扩展。

**后果**：保护本轮实测竞态，不代替分布式执行锁；完整JSON比较将来应随存储设计复核。

### ADR-006 · 2026-10-28 · worker 释放后检查新的 pending

**背景**：等待/失败检查点已经可被API读取，但原worker尚占去重集合时，新回应的入队信号会被挡住。

**决定**：finally先释放旧所有权，重新读DB，对最新pending幂等入队；其他状态不重排。

**替代**：API延迟重试依赖前端和时间猜测；额外待重排标记可行但增加内存状态；持久化队列/租约更适合多worker但超出本轮部署需求。

**后果**：回答、重试、章节确认能穿过旧worker结束窗口；四项独立注入回归覆盖三条重排路径与不忙循环控制组。仍需按单进程worker边界理解。

### ADR-007 · 2026-10-29 · 给无效动作返回安全字段反馈

**背景**：真实甲状腺任务 `job_96a1dd73b1a2` 两次RAG、一次起草、第4轮结构校验通过，但5–8轮动作无效，最终no_progress停止。旧轨迹只存泛化错误，没有原始决策响应，无法确定具体错字段，不能倒写成正常finish。

**决定**：`DecisionValidationError`携带有限issues；只允许服务器schema字段名与错误类型，未知键替为`<extra_field>`，不保存模型值。运行器把error_code、validation_issues、correction、allowed_actions写入下一轮观察；policy增加按字段修正要求与合法finish例子。

**替代**：继续只给“格式无效”信息少、难自纠；存完整模型响应便于调试但可能泄露原文或不可信数据。当前选择最小诊断事实，仍不等于完整模型可观测平台。

**后果与证据边界**：新增契约安全过滤与运行器反馈纠错离线回归；旧4轮具体原因仍未知。额外线上重放被自动审批在进程创建前拒绝，0次模型请求，没有线上重放成功证据。详见[系统实现详解与真实案例](./Agent系统实现详解与真实案例报告.md)。

### ADR-008 · 2026-10-29 · 取消后的旧running记录按视图解释

**决定**：当run已cancelled而trajectory条目仍running，前端展示stopped/“已停止接收结果”；不改数据库轨迹伪装外部调用已结束。

**替代**：继续显示执行中会与取消状态矛盾；直接把原记录改completed/failed又会虚构调用完成语义。

**后果**：界面表达停止接收迟到成果，保留协作式取消边界；新增前端回归验证。它不强杀网络请求，也不能撤销已有费用。

### 本轮增量记录

| 日期 | 变化 | 验证与限制 |
| --- | --- | --- |
| 2026-10-28 | v3模型动作协议、运行器、RAG适配、教师问答/停止与前端真实轨迹 | 依据实际源码和离线回归；在线模型策略与语义效果未由本轮证明 |
| 2026-10-28 | 独立复核修复中断显示、空白来源、时间预算、无key护稿和控制接口竞态 | 对应第11节具名回归；后续应保留而不是只记测试总数 |
| 2026-10-28 | 架构记录者发现并交独立评审复现队列交接竞态；补finally重排，统一旧新时间解析 | 三种唤醒红绿对照与终态控制组通过；时间解析回归；未增加分布式执行承诺 |
| 2026-10-28 | 架构记录者与工程评审独立发现read_source章节完整性弱于RAG适配；统一规范章节来源 | 跨书章节故障注入修前失败、修后通过；章节标题不依赖Chunk缓存 |
| 2026-10-28 | 建立独立架构记录与持续更新约定 | 本文与项目AGENTS约定对应；由后续变更时的独立记录者更新，不依赖当前子agent进程永久存在 |
| 2026-10-29 | 真实任务报告与安全字段纠错反馈 | 原任务保留no_progress、4轮泛化拒绝；新增字段诊断离线验证，不宣称旧线上根因已解决 |
| 2026-10-29 | 取消视图不再把旧running显示为仍在执行 | 只调整展示，不重写DB成强杀或完成；保留原协作式取消语义 |

### 后续每次架构变更填写

```markdown
### ADR-编号 · 日期 · 决策标题
- 用户/工程触发：具体问题或失败案例是什么？
- 原实现：相关模块、函数、数据与既有不变量。
- 决定：实际改了什么，为什么是当前合适方案？
- 替代：至少一个合理备选，比较适用条件与代价。
- 数据流/状态/接口变化：哪些消费者要同步？
- 失败与并发：中断、重试、取消、来源变化时如何处理？
- 验证：具名测试、故障注入/人工证据，必要时记录提交号。
- 未验证与风险：不能从当前证据推出什么？
- 所有者掌握检查：需要能解释/手算/复现的关键点。
```

维护时同时检查简要架构文档、README与实际实现是否一致。只有明确变更需要时才增加新抽象；文档要解释当前代码，不能把理想架构写成已实现能力。
