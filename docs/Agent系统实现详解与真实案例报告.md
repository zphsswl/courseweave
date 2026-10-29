# CourseWeave Agent 系统实现详解与真实案例报告

报告日期：2026-10-29。对象：初版 `lesson_agent_v3`（`5cdcd7e`）的实际实现与甲状腺备课任务 `job_96a1dd73b1a2`。

本文与对应 PDF 保留首次实现及原始案例。后续上下文、进展判断、书名规范化和自动评测的改动，以[本轮自动评测报告](./evaluation/agent-evaluation-20261029.md)和[持续技术复盘](./Agent架构技术复盘.md)为准。

本文回答五类具体问题：工具怎么定义与选择；每轮状态怎么落库；下一次模型究竟看到什么；“记忆”保存了什么；教案哪些部分由人工模板规定、哪些由模型生成。最后逐轮核对真实任务，包含失败退出，而非只给理想流程。

源码链接带行号，基于本轮工作区；之后修改函数时需要同步复核。真实案例只公开原请求、模型稿件、运行轨迹、检查结果和来源元数据，不上传教材原文、citation quote、API 密钥或完整业务数据库。

## 1. 先把系统拆成可指认的函数

| 职责 | 实际函数 / 位置 | 输入 | 输出与执行权 |
| --- | --- | --- | --- |
| 接收教师任务 | [`create_agent_run`:73](../backend/api/agent.py#L73) | Pydantic 校验后的条件 | 创建 Job，入队；不在请求 handler 内完成全部备课 |
| 串行调度 | [`_dispatch_job`:26](../backend/services/job_queue.py#L26) | job_id | 按 Job.type 调用执行器 |
| 新旧版本分流 | [`process_course_agent`:887](../backend/agents/course_agent.py#L887) | 保存的 payload/result | v3 模型循环、无模型证据工作流，或历史 v2 路径 |
| 决策闭环 | [`process_agent_loop`:309](../backend/agents/lesson_runtime.py#L309) | Job 与已保存状态 | 请求单个动作、校验、执行、保存、继续或停止 |
| 下一动作模型 | [`decide_next_action`:165](../backend/agents/lesson_policy.py#L165) | 受限任务上下文 | 一个 Decision；不直接执行任何工具 |
| 动作契约 | [`validate_decision`:101](../backend/agents/lesson_contracts.py#L101) | 原始模型 JSON 与 payload | 严格校验后的动作及规范化参数 |
| 工具分发 | [`_execute`:228](../backend/agents/lesson_runtime.py#L228) | 合法 Decision、剩余时间 | 执行七类分支，返回观察与可选终态 |
| RAG 边界 | [`query_rag_tool`:157](../backend/agents/rag_tool.py#L157) | 查询、课程、教材范围 | 本地核对后的来源与查证观察 |
| 完整稿生成 | [`_generate_artifact`:410](../backend/agents/course_agent.py#L410) | 教材证据、条件、修订反馈 | 规范化结构稿或证据降级产物 |
| 交付规则 | [`verify_artifact`:516](../backend/agents/course_agent.py#L516) | 当前稿、选书与请求 | 来源规则和交付结构检查；不用模型 |

核心调用关系是：

```text
教师请求 → API规范化 → SQLite Job → 单worker
    → 恢复状态 / 确定性准备
    → 组装本轮上下文 → 决策模型返回一个动作JSON
    → 契约 + 运行时检查 → 服务端执行工具
    → 观察 / 证据 / 稿件 / 检查结果落库
    → 重新组装下一轮上下文，或等待 / 交付 / 停止
```

它不是“模型一次生成八步计划、程序照表执行”。v3 的 `plan` 主要兼容展示已选择的动作；不是下一轮必须遵循的完整计划。独立子 agent 参与开发复核，也不代表产品运行时采用多 Agent 协商。

## 2. 三类模型调用：输入不同、职责不同

| 调用 | 什么时候发生 | 真正交给模型的任务 | 当前参数 | 什么情况下不发生 |
| --- | --- | --- | --- | --- |
| Policy 决策 | 每一轮提出动作之前 | 根据材料、旧稿、检查缺项、教师回答与预算，选择一个动作 | temperature=0.1；max_tokens=800；JSON 输出；SDK重试关闭；运行器传入不超过45秒的 timeout | 已终止、等待教师、已耗尽调度时间/轮数等 |
| RAG 内部回答 | 执行 query_rag，检索到材料后 | 依据 SOURCE 回答这一次具体查证问题，并绑定引用 | temperature=0.1；默认 max_tokens=1600；timeout=60；沿用原 RAG 客户端行为 | 没有检索材料则直接 no_evidence；模型不可用或引用检查失败则降级为材料 |
| 教案起草/修订 | 执行 write_draft | 按指定结构生成/修订一份教案 | v3 temperature=0.15；max_tokens=6000；JSON 输出；SDK重试关闭；timeout按剩余时间且最多60秒配置 | 无证据或无模型返回材料；已有教师保存稿则运行器拒绝自动覆盖 |

依据：[Policy调用:165–198](../backend/agents/lesson_policy.py#L165-L198)、[RAG模型:91–109](../backend/agents/rag_agent.py#L91-L109)、[RAG问题处理:168–222](../backend/agents/rag_agent.py#L168-L222)、[教案调用:467–495](../backend/agents/course_agent.py#L467-L495)。

默认内部调用时，三类请求都使用 `LLM_MODEL` 和 [`create_openai_client`:16](../backend/services/llm_client.py#L16)，即同一套模型、base URL与认证配置，但提示词、输入与职责不同，不是三个自治角色进程。若 RAG 改接独立 HTTP 服务，远端模型配置由远端决定。

这里的 timeout 不是整个任务一定在该秒数内被强制终止的保证；内部原 RAG 继续沿用其网络调用行为。不能把“2次RAG、1次起草”当作本次全部模型请求数，决策调用也在消耗时间和费用。

### 2.1 每轮返回的不是教案，也不是完整计划

Decision 的顶层恰好是三个字段：

```json
{
  "action": "query_rag",
  "arguments": {
    "question": "甲状腺的位置与形态",
    "textbook_ids": ["任务范围内教材ID"],
    "mode": "all",
    "top_k": 8
  },
  "summary": "补查所选教材中甲状腺的位置与形态"
}
```

这是协议示意，不冒充真实任务某轮原始响应。顶层 summary 是1–300字的公开动作摘要，不是思维链。完整稿在 write_draft 的另一次调用中产生；finish本身不再另写一份教案。

### 2.2 这不是原生 function calling

当前发送给模型的是 system 提示词、一个 `UNTRUSTED_STATE_JSON` user 消息与 `response_format={"type":"json_object"}`；没有传 OpenAI `tools` schema，也没有接收原生 `tool_calls`。程序从模型返回文本中解析 JSON，经 Pydantic 验证，再走 `_execute()` 中的固定分支。

因此准确描述是“严格 JSON 动作协议 + 服务端工具分发”。模型输出了一个合法名字，并不等于已经执行；运行器还会检查预算、范围、取消、来源与重复动作。

## 3. 七个工具，逐个说明 schema、选择策略和落库结果

[`_StrictModel`:41–42](../backend/agents/lesson_contracts.py#L41-L42) 设置 `extra="forbid"`、`strict=True` 和字符串去首尾空白。整数参数不能用字符串或布尔值混过，多余的URL、course_id、passed字段会被拒绝。

| action | arguments 精确形状 | 模型在什么情况下被提示选择 | 实际程序行为与状态变化 |
| --- | --- | --- | --- |
| inspect_course | `{}` | 需要核对当前教材与证据状态 | `_books()`查询原范围；更新 observations.textbooks；不抽图谱、不建整库索引 |
| query_rag | question:2–500字；textbook_ids:最多12个，省略/空表示原范围；mode:all/compare，默认all；top_k:严格整数3–15，默认8 | 缺少某本教材、某一切面证据时改写查询或缩小到范围内某书 | 调用RAG适配；追加本地证据；更新 retrieval_history、rag_answer、per_book_counts与动作观察 |
| read_source | chunk_id:1–160字的本地ID | 已知来源需要更多原文上下文，或已有教师选材可直接读取 | 联查课程、书、章、Chunk；拒绝空白与跨书章节；更新 evidence和observations.last_read |
| write_draft | instructions:最多2000字，默认空 | 证据足够时起草，或按缺项修订 | 生成完整结构稿；旧artifact有限保留到artifact_versions；清空旧quality/delivery/校验记录 |
| validate_draft | `{}` | 有新稿后检查要求是否满足 | 重查来源是否变化；执行本地verify；写quality、delivery与validated_signature |
| ask_teacher | question:1–500字；options:最多4项，每项非空且最多500字，默认空 | 无法从现有材料解决的必要教学条件或选择 | 保存唯一request_id、问题和选项；任务进入waiting_user；最多接受四次教师回答 |
| finish | summary:最多500字，默认空 | 当前材料与稿件足以交付时提出结束 | **重新执行本地_validate**；只有draft_ready才标delivery_ready并允许正常交付 |

schema依据：[契约类:45–76](../backend/agents/lesson_contracts.py#L45-L76)，实际分发依据：[运行器:228–306](../backend/agents/lesson_runtime.py#L228-L306)。

### 3.1 模型选择策略来自什么地方

策略来自人工写入的 [`POLICY_SYSTEM_PROMPT`:19–46](../backend/agents/lesson_policy.py#L19-L46)，其中包括：

- 已有原文要复用；缺证据就针对缺口检索；检索无结果不能证明教材不存在该知识。
- 检查失败后补查或修订；不能原样重复被拒绝的动作。
- 只有草稿通过服务端检查才应提出finish；不能把模型自评当作通过。
- 必要教学信息才询问教师；能自行检索/修订解决的，不反复提问。
- 遵守预算，不能为了宣称完成而编造来源或内容。

这不是一个训练出来的专用planner，也不是手写的“第1轮必须检索”。每轮由配置的通用模型依据当前有限状态判断。策略提示是软约束；工具白名单、数据库条件和预算才是程序能强制执行的部分。

### 3.2 服务端又检查什么

[`validate_decision`:101–142](../backend/agents/lesson_contracts.py#L101-L142) 先解析字符串JSON，拒绝超过32768字符的动作文本，验证顶层、分动作arguments及教材子集。read_source拒绝URL、路径和控制字符形状，但真实来源归属仍必须查数据库。

[`decision_fingerprint`:145](../backend/agents/lesson_contracts.py#L145) 对动作及参数计算哈希，忽略顶层摘要；query的教材集合排序，finish的摘要也不改变指纹。运行器结合当前证据/稿件签名，已有两次相同输入下的相同动作后拒绝再重复。

并非所有策略错误都能由schema发现：一句不相关但格式合法的检索问题仍可能被执行；看似合理的修订instructions也可能无效。这需要真实策略评测，不能由白名单推导为模型总会选择正确动作。

## 4. 原始请求如何变成持久任务

前端 [`startRun`:368](../frontend/src/components/AgentWorkbench.tsx#L368) 将表单转换为 `LessonRequest`，通过 [`createLessonRun`:108](../frontend/src/api/lessonAgent.ts#L108) 提交 `POST /api/agent/runs`。后端规范化主题/目标、去重教材和关注项，验证课程、教材、章节、板与选定原文。

创建分成三件事：[create_job:28](../backend/agents/orchestrator.py#L28) 插入pending Job；[initial_agent_result:94](../backend/agents/course_agent.py#L94) 创建初始result；[enqueue_job:17](../backend/services/job_queue.py#L17) 将ID交给内存队列。客户端收到job_id后只读状态，不负责维持后端执行。

### 4.1 SQLite里的实际字段

[`Job`:304–319](../backend/database.py#L304-L319) 不是一张只保存“完成/失败”的表。

| 字段 | 内容 | 为什么需要 |
| --- | --- | --- |
| id / course_id / type | 任务身份、课程归属、course_agent类型 | 找到同一任务并与其他处理任务分流 |
| payload JSON | 初始主题、目标、教材、学情、时长、问题数、关注与教师上下文 | 原始范围和要求的基准，不由模型扩大 |
| result JSON | 下面列出的运行状态、材料、稿件和检查结果 | 重启、恢复、界面读取的持久状态 |
| status / stage / message | pending/processing/waiting_user/completed/failed/cancelled及当前阶段、文案 | 区分执行是否结束、在哪里停下 |
| error | 安全错误信息 | 不把带密钥/URL的上游异常原文直接公开 |
| progress / total | 历史兼容进度字段 | v3界面以实际动作与预算为主，不冒充教案完成百分比 |
| retry_count | Job级重试计数 | 失败任务重试资格；不能误读为result里兼容保留的同名字段 |
| created_at / updated_at | 创建及最近写入时间 | 历史排序与状态展示 |

result 中的重要字段如下：

```text
agent_version / execution_mode / available_tools
goal / topic / request / textbook_ids
evidence[]                         本地规范来源快照
observations                       最新工具摘要、RAG答复、每书计数等
retrieval_history[]                 有限检索历史
trajectory[] / plan[] / tools_used  实际动作与兼容展示
artifact / artifact_versions[]     模型稿与有限旧稿
lesson_draft / draft_revision      教师保存稿及乐观锁版本
quality / delivery                 本地规则检查结果
validated_signature                当前校验记录
approval / teacher_answers[]       等待问题和已接收回答
budget / no_progress_count         已花费预算与无进展计数
stop_reason / completed_at         为什么结束及结束时间
```

### 4.2 “保存state”具体是哪一条数据库写入

[`save_checkpoint`:74–84](../backend/agents/lesson_runtime.py#L74-L84) 深拷贝整个result，执行SQLAlchemy条件UPDATE，同时写status、stage、message、error、updated_at与兼容progress。条件包含正确job_id/type以及 `Job.status != "cancelled"`，防止迟到工具结果恢复已取消任务。

写操作交给 [`_write_with_retry`:11–26](../backend/agents/orchestrator.py#L11-L26)：创建Session → 执行短更新 → commit → close；SQLite锁错误才rollback并指数退避，最多六次尝试。它不是将网络请求包在一个长数据库事务里。

每次UPDATE替换这个Job的最新result，**不会自动保存所有历次result完整副本**。trajectory保留动作历史、artifact_versions有限保存旧模型稿，但没有一张不可变“每轮完整prompt/响应/状态事件表”。所以“每步有检查点”不等于事后可以无损还原每步全部模型输入。

数据库连接初始化启用WAL、busy_timeout=30000与外键，见 [`database.py:22–40`](../backend/database.py#L22-L40)。WAL/重试用于减少本地读写冲突，不是分布式锁。

### 4.3 一轮准确在哪里写盘

| 时点 | 先更新什么 | 落库的意义 |
| --- | --- | --- |
| 进入/恢复任务 | 补默认字段；旧running动作改interrupted，并同步plan行 | 读取到的是可解释的恢复状态，不永久显示旧动作执行中 |
| 请求决策之前 | `steps_used += 1`；stage=planning | 决策调用途中退出也计入已花轮数 |
| 合法工具即将执行 | RAG或起草次数先加一；trajectory和plan记running | 外部执行前预留预算，避免崩溃后无限免费重试 |
| 工具成功后 | canonical evidence、artifact或quality等；动作completed；last_tool_result | 下一轮从真实结果继续，前端可查看 |
| 动作被拒绝 | rejected记录、安全错误、no_progress_count | 后续模型收到拒绝反馈，错误也属于轨迹 |
| 等待教师 | approval与waiting_user、累计活动时间 | 教师离开页面不丢材料；等待时间不计活动时限 |
| 正常交付 | 当前稿重验通过，delivery_ready及completed | 结构检查通过，仍待教师语义核对 |
| 预算/无进展退出 | 保留当前成果，填写对应stop_reason | completed仅表示这次执行结束，未必正常finish |

顺序见 [`process_agent_loop:331–433`](../backend/agents/lesson_runtime.py#L331-L433)。工具返回与checkpoint之间再次检查取消；SQL条件是最后一道原子保护。

### 4.4 恢复与并发保证到底到哪里

启动时 [`_recover_interrupted_jobs`:447](../backend/database.py#L447) 将未结束的pending/processing任务恢复排队；等待教师的任务不会无故自启。重新进入循环不会逐条重放已完成轨迹，而是保留已花预算，让模型重新判断下一动作。

但外部调用已完成、结果尚未落库就崩溃时，不能证明外部动作没有发生；没有exactly-once承诺。已预留但未完成的预算不退还，是保守控制费用的选择。

回答、章节继续和取消使用完整result快照CAS，见 [`agent.py:225–316`](../backend/api/agent.py#L225-L316)。例如旧Q1响应读后任务已到Q2，即便都叫waiting_user，旧快照UPDATE也不能成功。教师稿使用draft_revision条件更新。

当前只有单进程worker的去重集合。worker退出旧调用后会再次检查是否刚被教师改回pending，防止快速回答/重试的入队信号被旧去重占用吞掉，见 [`job_queue.py:61–80`](../backend/services/job_queue.py#L61-L80)。这不是多进程任务领取租约。

## 5. 每轮上下文传什么、裁剪什么

不是把所有历史消息无界追加到聊天窗口。每次 [`decide_next_action`](../backend/agents/lesson_policy.py#L165) 都新建请求，发送固定system策略和当轮重新组装的JSON。模型可用的信息由 `_policy_context(payload,state)`决定。

### 5.1 Policy输入的字段与真实预算

以下是 **字符/JSON长度预算，不是token预算**；来源为 [`_policy_context:121–162`](../backend/agents/lesson_policy.py#L121-L162)。

| 分区 | 模型看到的内容 | 实际分区上限 |
| --- | --- | ---: |
| goal | 本任务目标 | 原文本最多500字 |
| request | course_id、topic、goal、audience、prior_knowledge、textbook_ids、duration、question_count、requirements、focus_terms、context | 6000字符JSON |
| observations | 教材状态、last_tool_result、rag_answer、per_book_counts、last_read等 | 5000 |
| evidence | 最多48项；每项source_id、chunk_id、书名、章名、页码、原文摘录 | 24000；每项原文先取最多600字 |
| artifact | 标题、摘要、目标、讲解、课时、重点、共同点、差异、误区、问题、待确认等当前稿字段 | 5000 |
| quality | 本地检查结果及缺项 | 5000 |
| trajectory | 最近六条动作，不是全任务轨迹 | 6000 |
| teacher_answers | 最近六条存量回答；运行器/API实际最多接受四次 | 4000 |
| budget | 轮次、RAG、起草与时间用量 | 1000 |

`MAX_CONTEXT_CHARS=60000` 在文件第16行有定义，但当前代码没有对最终整段context直接执行“超过60000就截断”。真正执行的是上表的分区限制，其预算加总约56500字符，再加JSON键名、分隔与提示包装；不能把一个常量描述成独立执行过的全局token门禁。

### 5.2 `_bounded_data()`不是简单切字符串

[`_bounded_data:70–118`](../backend/agents/lesson_policy.py#L70-L118) 对输入递归构造有限JSON：单字符串最多2000字；字典最多48项、键最多100字；列表最多48项；到深度5时省略更深数据；预算耗尽用truncated标记。非有限浮点会变null。

构造后再用JSON实际编码长度检查，防止转义膨胀；仍超出分区预算时，转换为有preview和truncated标记的合法JSON，并逐步缩短preview，而不是直接截断到非法JSON。

风险是丢信息：5000字的草稿摘要可能未保留全部教学环节；检查结果过长时某些缺项也可能被省略；列表中的后项可能不再出现。`omitted_count=0`只反映前置48项筛选，并不保证后续 `_bounded_data` 没再裁剪。

### 5.3 工具结果怎么进入下一轮

RAG返回后，运行器把原文ID重新查库，追加到 `state.evidence`，不是直接相信RAG正文；把答复最多4000字放到 `observations.rag_answer`；把各书计数放到 `per_book_counts`；把新增数与警告放到 `last_tool_result`。下一轮再进入上表不同分区。

RAG检索历史只保留最近15条；详细trace序列化超过12000字符时，缩为truncated摘要并裁剪警告。`read_source` 的last_read最多8000字，但交给policy仍受observations整体5000字限制。依据：[运行器RAG/read分支:238–268](../backend/agents/lesson_runtime.py#L238-L268)。

write_draft成功会改变artifact并清空旧quality/delivery；validate会写新的quality/delivery；动作拒绝会把安全错误写入last_tool_result。模型因此能“看到刚才查空了/当前稿还缺什么/参数被拒了”，但看不到被省略的原始全文或未保留的旧响应。

教材、RAG答复、工具错误、旧稿均当作不可信数据，不提升为system消息。提示词标记不是充分的防注入证明；强制边界仍靠服务端参数、范围和交付规则。

## 6. 记忆：有任务级持久状态，没有跨任务自学习

| 可以称为哪种记忆 | 实际存储与读取路径 | 保留什么 | 不代表什么 |
| --- | --- | --- | --- |
| 当前轮工作状态 | Python的state字典；从Job深拷贝恢复 | 当前证据、稿件、观察与预算 | 进程内字典本身不抗退出，靠checkpoint落库 |
| 任务级持久记忆 | SQLite Job.payload/result；`_load()`、`save_checkpoint()` | 初始请求、工具历史、材料、稿件、教师回答、检查与停止原因 | 不会自动把前一个job的经验灌入新job |
| 有限工作上下文 | `_policy_context()`每轮重新挑选/裁剪 | 最近六动作、材料摘录、当前稿与反馈 | 不是全部持久状态都能放进模型上下文 |
| 浏览器条件与编辑缓存 | localStorage与React状态 | 未提交表单、未保存编辑、待提交回答 | 不跨设备同步；存储被禁用/满额时不保证刷新恢复 |
| 教材知识库 | Course/Textbook/Chapter/Chunk、既有索引与图谱 | 可供不同任务检索的规范材料 | 教材库不是Agent从任务中自动学到的个人长期记忆 |

前端key见 [`AgentWorkbench.tsx:35–39`](../frontend/src/components/AgentWorkbench.tsx#L35-L39) 及 [回答key:333](../frontend/src/components/AgentWorkbench.tsx#L333)：`courseweave:lesson-brief:{course}`、`courseweave:lesson-edit:{course}:{run}`、`courseweave:lesson-answer:{course}:{run}:{request_id}`。

跨任务“复用条件新建”是前端显式复制条件再创建任务，不是隐式长期记忆检索。当前没有自动总结每次备课经验、写入长期memory库、跨任务检索经验、在线更新模型权重或用户画像学习逻辑。独立的ChatHistory表也不能因为存在就被算作此Agent已读取的长期记忆。

## 7. 来源：身份、正文、哈希与S编号怎么绑定

[`_read_sources:104–119`](../backend/agents/lesson_runtime.py#L104-L119) 联查Chunk、Textbook、Chapter，限制课程和本次书单，并核对章节属于同一本书；空白正文拒绝。章节名称取真实Chapter，不依赖Chunk里可能过期的缓存标题。

[`_snapshot:92–101`](../backend/agents/lesson_runtime.py#L92-L101) 将ID、书名、章节、路径、页码、正文前12000字存为证据快照，对**完整正文**计算SHA-256。哈希在Job.result快照里，不是数据库Chunk额外新增的哈希列。

`_evidence_current()`恢复或再次使用时重查这些字段；正文尾部即使没进入12000字摘录，改变仍会触发哈希差异。来源变化后不能悄悄把旧稿引用改到新原文，而是标needs_work、保留教师稿并要求新任务。

`S1/S2`由 [`_citations:216–231`](../backend/agents/course_agent.py#L216-L231) 按证据列表顺序建立，与实际chunk_id对应。它是本任务内部引用编号，不是全库永久概念ID。证据追加去重保持已有编号顺序，模型不能另造一张citations表。

### 7.1 默认RAG是内部函数调用

[`query_rag_tool:157–199`](../backend/agents/rag_tool.py#L157-L199) 默认直接调用 `rag_agent.query_rag(**payload)`，不是浏览器或后端额外POST自己的 `/api/rag/query`。只有服务器设置完整 `AGENT_RAG_URL` 才走HTTP。

HTTP方式最多读1MiB响应，socket阶段timeout最多配置30秒，不跟随重定向、不沿用环境代理；不保证30秒硬墙钟终止。适配器调用前后核对范围，按返回chunk_id从本地重取原文，见 [`_local_items:102–154`](../backend/agents/rag_tool.py#L102-L154)。

过滤、去重或截断来源会使上游编号可能失效，所以有相关警告时不照搬原RAG答复，而降级为材料。原检索、融合、回答方法仍在既有RAG核心文件，本层增加的是工具边界，不是另一套检索算法。

### 7.2 RAG内部也有确定性的筛选，而不是直接让LLM搜书

[`retrieve:847`](../backend/services/retrieval_service.py#L847) 先解析查询中明确指定的书名、应用课程/教材范围，装载范围内Chunk，并做scope support判断；不支持时可在检索排序前直接返回unsupported_query_topics。

之后准备词项/主题/意图特征，BM25作为主路径。向量仅在索引ready、embedding可用且语料签名匹配时参与；图谱候选只有BM25没有候选时才作为弱兜底，不是每次始终三路并行。

融合使用 `Σ weight/(60+rank)`，bm25/vector/graph权重分别为1.0/0.8/0.05，再做正文支持过滤；compare或多书范围会优先挑各书候选，再补足top_k。这些是程序规则，不是policy模型本轮临时决定的排名算法。最后才由RAG回答模型依据检索SOURCE组织查证答复。

因此模型可通过改写question、选择范围内教材、mode和top_k影响查询，但不能在动作JSON里任意改RRF权重或绕过支持性判断。弱相关材料仍可能通过规则，需要结合本次S1案例理解算法边界。

## 8. 教案生成：人工模板具体规定了什么

人工定义的是 [`LESSON_PACKAGE_PROMPT:26–73`](../backend/agents/course_agent.py#L26-L73)，不是一份预写好的甲状腺答案。模板把目标、学情、先修、关注项、选书、时长、问题数、检索切面、教师备注与SOURCE放入固定位置。

### 8.1 人工规定的内容边界

模板要求只能依据SOURCE，不自行补教材外知识；共同结论需至少两书；差异证据不足时写待确认；课时minutes总和等于请求；问题数量等于请求；教师选材顺序是建议讲授顺序，关系草稿不等于语义已确认。

来源文本放在 `UNTRUSTED_SOURCES`，教师备注放在 `UNTRUSTED_TEACHER_CONTEXT`，修订放在 `UNTRUSTED_REVISION_CONTEXT`。这些标签是提示边界；不是将不可信内容自动变可信。

### 8.2 模板要求的输出结构

```json
{
  "title": "模型生成的标题",
  "executive_summary": "只基于证据的概览",
  "teaching_objectives": ["可观察的教学目标"],
  "knowledge_sequence": [{"title":"讲解标题","explanation":"讲解内容","source_ids":["S1"]}],
  "lesson_blocks": [{"title":"课堂环节","minutes":10,"content":"活动内容","source_ids":["S1"]}],
  "teaching_focus": [{"title":"重点难点","explanation":"说明","source_ids":["S1"]}],
  "common_ground": [{"claim":"跨书共同结论","source_ids":["S1","S2"]}],
  "textbook_differences": [{"textbook":"来源书名","perspective":"侧重点","source_ids":["S1"]}],
  "misconceptions": [{"issue":"混淆点","guidance":"辨析","source_ids":["S1"]}],
  "classroom_questions": ["课堂问题"],
  "unresolved_questions": ["待教师确认事项"]
}
```

上面是schema示意，单个10分钟环节不表示完整课时。标题、正文、目标、环节、问题由模型填充；字段、来源约束、时长要求与后处理规则由开发者定义；教师之后可编辑保存独立稿件。

### 8.3 起草和决策看到的文本并不一样

| 环节 | 实际限制 | 说明 |
| --- | --- | --- |
| 原文给生成器 | 每段 `max(400,min(6000,48000//来源数))` 字 | 控制来源正文总量约48000字；元数据/提示包装另计 |
| 生成时的citations | 每条quote最多6000字，来自本地快照 | 来源权威不来自模型提交；公开报告不复制这些原文 |
| 修订instructions | 最多2000字 | 从当前write_draft动作传入 |
| 上一版模型稿 | 去掉citations和teacher_context_trace后放入revision | 给模型具体待改对象，不只一句“再想想” |
| 上次交付缺项 | `_agent_feedback=state.delivery` | 明确哪些规则没满足 |
| 教师回答 | 最近四条 | 来自当前任务，不能据此越权换教材 |
| revision JSON | 长度超过24000触发省略旧稿正文 | **不是对最终JSON做绝对24000截断**；会保留checks和回答重新序列化 |

来源见 [`_generate_artifact:433–464`](../backend/agents/course_agent.py#L433-L464)。source_context_trace记录每来源裁剪上限与被截来源数；不能据引用表较长而假设模型已读完每条引用全文。

### 8.4 教师选材上下文如何裁剪

[`_teacher_context:339–407`](../backend/agents/course_agent.py#L339-L407) 将教师板上的chunk_id映射到当前S编号。最多48项选材、120条关系；只保留双方都在所选来源中的关系。标题100字、dimension60字；备注单项1000字/总8000字；关系理由单项1000字/总4000字。

长备注不是简单截断整个JSON，而是water-filling分配剩余文本预算，短备注尽量保全，长备注共享额度。omitted统计进入teacher_context_trace；有省略会在unresolved_questions加入提示。没有来源映射的备注不会被当作SOURCE本身。

### 8.5 模型响应还经过哪些程序后处理

[`_parse_model_json:234`](../backend/agents/course_agent.py#L234) 处理可能出现的代码围栏或外围文本，再解析JSON；[`_normalize_artifact:265–318`](../backend/agents/course_agent.py#L265-L318) 只提取既定字段，并：

- 将结构行的文本转成字符串；非结构对象忽略，全部空文本行不保留。
- source_ids只保留服务器citations里存在的S编号，去重；无效编号去除后会在绑定检查中暴露。
- minutes只接纳非布尔整数0–240，其他归0；实际完成检查要求每块大于0且总和匹配。
- 共同结论若不足两本书支持，移到讲解顺序，添加待确认说明，不保留为跨书共同结论。
- citations、generation_method、generated_at由服务器附加；模型不能自行设置teacher_edited或semantic_reviewed。

这套生成输出处理比Decision协议更宽容，是规范化，不是对所有生成字段进行严格Pydantic schema拒绝。不能把“严格JSON动作契约”误说成“整份教案所有字段都经过相同严格schema”。

生成失败会返回 `_fallback_artifact()`：真实材料摘要与待确认原因，标记evidence_fallback，不伪造完整教学方案。

## 9. 校验与交付：程序判定哪些，完全没判定哪些

[`_validate:163–177`](../backend/agents/lesson_runtime.py#L163-L177) 先确认当前稿存在，再比对来源快照是否变化，然后调用本地verify，写quality/delivery/validated_signature。**它不调用模型裁判。**

[`verify_artifact:516–594`](../backend/agents/course_agent.py#L516-L594) 的规则可分两组：

| 规则组 | 具体判断 | 不是在证明什么 |
| --- | --- | --- |
| 教材覆盖 | 真正被条目引用的来源是否覆盖全部选书 | 不说明每本书相关内容已检索充分 |
| 范围与编号 | 引用属于书单，使用的source_id确实在引用表 | 不证明某句结论得到该段语义支持 |
| 页码 | 所用引用的页码正数、结束不早于开始 | 不证明解析后的内容与原页一字不差 |
| 行绑定 | 讲解、课时、重点、共同点、差异、误区各行有已知引用 | 不检查引用和语句是否蕴涵关系 |
| 归属 | 差异条目书名与至少一个引用对应；共同结论关联两书 | 不验证两书确实同义/冲突 |
| 课时/数量/结构 | 分钟总和、正分钟、问题数量、概览/目标/顺序等 | 不判课堂难度、合理时间分配或问题质量 |
| 切面与关注项 | focus_terms词面出现；既定关注项对应字段存在；自定义项待教师核验 | 不是开放式教学目标理解器 |
| 选定材料 | 教师选定chunk_id确实被稿件条目引用 | 不说明材料选择本身正确 |

返回 `source_check_score` 只表示来源规则通过比例；旧score保留为0，semantic_reviewed=false。`draft_ready`意为结构和来源规则齐备的草稿，仍待教师核对，不应称医学或教学结论已经审定。

`unresolved_questions`非空目前不是硬否决项；检查器也不判断“差异里说确定不存在、待确认里又说需核实”的语义矛盾。因此有待确认事项与draft_ready可以同时出现，不能把缺项列表为空解释成没有任何知识风险。

### 9.1 为什么validate通过还不能等同于正常finish

validate工具把结果保存下来，循环仍可能继续。正常finish要求模型提出合法finish动作，服务端再次 `_validate()`；这次通过才写 `stop_reason=delivery_ready`。

如果之后连续动作无效，运行器也可以用no_progress停止；`_partial()`还会重算当前稿delivery。于是完全可能同时出现：**Job.status=completed、delivery=draft_ready、stop_reason=no_progress**。这是“有符合本地规则的草稿，但本次自主收尾失败”，不是正常finish。

validated_signature是校验记录，finish不只信它；重复判断使用当轮重新计算的 `_signature(state)` 作为input_signature。新增证据和改稿会清除旧校验记录。

## 10. 预算、停止与无效动作怎样解释

默认预算由 [`runtime_fields:40–52`](../backend/agents/lesson_runtime.py#L40-L52) 创建：12轮、6次RAG、3次起草、300秒调度活动时间；环境可限幅调整到4–40、1–15、1–6、30–900。恢复使用setdefault，不退还已花次数。

相同动作参数+相同输入签名出现过两次后，重复执行被拒绝；无进展计数达到4停止。当前“进展”是工程启发式：材料/稿件改变，或读取/检查/观察动作；不代表教学质量进步。

进入一轮先生成占位entry，action为invalid_action、summary为检查模型动作。只有决策JSON通过校验后才替换成真实action。因此轨迹里的invalid_action不是一个被执行的工具，也不能据此推断模型原本想选择哪个工具。

当前旧任务若只保留泛化的“动作参数或返回结构未通过检查”，不能确定是JSON错误、缺字段、类型错误、越界教材还是别的schema原因。没有保存的原始响应、finish_reason或错误字段位置，不能从截图补推回来。

四种结果需分开：

- 模型不可用：安全失败，保留检查点，可按任务条件重试。
- 决策无效/业务参数被拒：写rejected反馈，下一轮再决策，累计无进展。
- 次数/时间/无进展停止：保存部分成果和明确原因，不把结束叫目标完成。
- 用户取消：原子标cancelled，拒绝迟到写回；不能强杀已发出的请求或撤销费用。

### 10.1 2026-10-29增加了安全的字段反馈，但不改写旧任务

旧任务5–8轮只有泛化错误。为改善后续的可修正性，当前契约错误新增 `issues`：只记录服务器定义的字段路径和Pydantic错误类型，最多5项、最多取4段loc；未知字段名替换为`<extra_field>`，不保存模型提交值、原始报文或含任意输入的错误文案。实现为 [`_safe_issues:27–38`](../backend/agents/lesson_contracts.py#L27-L38)。

运行器把error_code、validation_issues、固定correction提示和allowed_actions写入拒绝动作的observation与last_tool_result，见 [rejected分支:419–428](../backend/agents/lesson_runtime.py#L419-L428)；下一轮policy可以按具体字段修正。系统提示也增加[合法finish示例:45](../backend/agents/lesson_policy.py#L45)，顶层summary须非空，arguments不能用整份教案代替。反馈仍受第5节分区长度限制，不等于模型可见无限完整诊断历史。

```json
{
  "error_code": "invalid_arguments",
  "validation_issues": [{"field":"arguments.top_k","type":"int_type"}],
  "correction": "按白名单动作参数修正；只返回action、arguments、summary",
  "allowed_actions": ["inspect_course","query_rag","read_source","write_draft","validate_draft","ask_teacher","finish"]
}
```

上面仅展示新反馈形状，不是甲状腺旧任务已经记录的错误；correction为便于阅读的缩写，程序实际写入固定提示。详情保存供policy与诊断读取，当前工作台仍以动作摘要和错误为主，不宣称已新增完整字段诊断面板。

本轮还修正取消展示：如果Job已cancelled，而原trajectory条目仍是running，前端 [`lessonExecution:177–182`](../frontend/src/api/lessonAgent.ts#L177-L182)将其显示为stopped/“已停止接收结果”。只改变视图解释，不改数据库制造“外部请求已被强杀”的假状态。

这些改动提高错误反馈和状态解释质量，**不能证明已经定位旧任务5–8轮的具体字段，也不能证明真实模型收尾已经修好**。一次额外线上策略重放尝试被自动审批在进程创建前拒绝，产生0次模型请求；没有可用的线上重放结果，不把它写成实际复现成功。

## 11. 真实案例：甲状腺任务的原请求、逐轮行为和产物

本节以指定任务的去原文快照为证据，保留其失败退出；不会用另一条离线理想轨迹替换。本轮真实案例快照由主任务只读提取，架构记录者不直接读业务数据库或调用在线模型。

### 11.1 真实原请求，不是事后编造的演示任务

```json
{
  "course_id": "course_default",
  "topic": "甲状腺功能",
  "goal": "围绕“甲状腺功能”组织 45 分钟课堂，准备 3 个问题",
  "audience": "护理专业一年级",
  "prior_knowledge": "",
  "textbook_ids": ["book_01", "book_02"],
  "requirements": ["核心概念", "教材差异", "重点难点"],
  "duration_minutes": 45,
  "question_count": 3,
  "focus_terms": [],
  "context": {"selected_chunk_ids": []}
}
```

book_01为《局部解剖学》，book_02为《组织学与胚胎学》。先修知识未填，没有预选Chunk，没有教师选材板带入的材料；不能把本次结果归因于教师事先提供了正确引用。

### 11.2 八轮实际做了什么，下一轮输入如何变化

快照保存了动作参数与观察，没有保存每一次完整模型请求/原始响应。下表“本轮可用输入”按实际控制器与已有轨迹重建；不是声称拿到了逐token原始prompt，分区裁剪仍可能省略其中细节。

这也限定了本报告的“真实输入”：第11.1是保存的原请求，Q1/Q2和write instructions是保存的真实工具参数；逐轮state变化按记录与代码核对。不存在的原始模型报文、未落库的错误字段与旧版完整state不在这里假造。

| 轮次 | 本轮可用输入的变化 | 已保存动作与参数 | 工具/校验结果 | 写入后下一轮的关键变化 |
| --- | --- | --- | --- | --- |
| 1 | 原请求、教材状态、空材料/空稿、未用预算 | query_rag；Q1；两书；all；top_k=8 | 0来源，reason=unsupported_query_topics | last_tool_result新增0；evidence仍空；RAG次数1 |
| 2 | 已知上次无材料，保留原目标与范围 | query_rag；Q2；两书；all；top_k=8 | 8来源，其中book_01为1、book_02为7；answer_method=evidence_fallback | evidence新增8项；每书计数与RAG观察改变；RAG次数2 |
| 3 | 8项来源及其S编号、查询观察、护理一年级/45分钟/3问题 | write_draft；带具体instructions，见下 | 生成1份llm_grounded模型稿，引用8条 | artifact写入；quality/delivery清空；起草次数1 |
| 4 | 当前稿、8项证据、原请求与前3轮轨迹 | validate_draft；arguments={} | draft_ready、missing_items=[]、semantic_reviewed=false | quality/delivery已齐；后续模型应该考虑合法finish等动作 |
| 5 | 合法稿与通过结果仍在；没有新材料 | invalid_action，占位；status=rejected | “动作参数或返回结构未通过检查” | 增加拒绝反馈与无进展计数1；没有执行新工具 |
| 6 | 加入上一轮拒绝反馈；原稿保留 | invalid_action；rejected | 同类泛化拒绝 | 无进展计数2；材料和稿件不变 |
| 7 | 再加入拒绝记录；最近六轮窗口移动 | invalid_action；rejected | 同类泛化拒绝 | 无进展计数3；不能推断原本想调用的工具 |
| 8 | 已有三次连续无效；通过稿仍在 | invalid_action；rejected | 第四次无效 | 达无进展阈值，保留稿并stop_reason=no_progress；**没有finish动作** |

Q1原文：

> 甲状腺功能的核心概念、教材差异、重点难点，包括甲状腺激素的合成、分泌、调节及临床意义

Q2原文：

> 甲状腺激素的合成、分泌、调节机制，以及甲状腺功能亢进和减退的临床表现

第3轮实际instructions：

> 基于现有证据，围绕“甲状腺功能”为护理专业一年级学生设计45分钟课堂，准备3个问题。要求涵盖核心概念、教材差异、重点难点。请从组织学与胚胎学教材中提取甲状腺激素的合成、分泌、调节及临床意义，并注意局部解剖学教材中相关内容较少，需在问题中体现教材差异。问题应适合护理专业，注重临床应用。

这说明决策模型已将学情、时长、问题数、关注项及检索分布转成起草参数；也说明“检索分布”开始被模型解释为“某教材内容较少”。后者需要证据，不是统计数字能证明的结论。

### 11.3 本次RAG实际使用了哪些路径

第一次调用trace：scoped_chunks=1178、reason=unsupported_query_topics、answer_method=no_evidence。它在支持性判断处没有给出来源；不能单靠这个reason断言教材不存在甲状腺内容。

第二次调用trace：transport=internal、retrievers=[bm25]、vector_used=false、graph_expansions=0，仍在同两书的1178个Chunk范围。**本次不是三路始终并行，也没有实际使用向量或图谱扩展。**

第二次RAG返回answer_method=evidence_fallback，warnings=[]，但提供8个可装载的来源。不能说本次RAG回答模型成功生成了合格查证回答；仅凭这个值也不能确定是网络失败、输出缺引用还是其他原因。Agent后续起草使用的是重载后的真实证据，而不是把RAG答复当已审核的最终教案。

本次source_context_trace记录每来源上限6000、被该生成阶段裁剪的来源数0；teacher_context_trace记录0项选材、0条关系、omitted全0。这说明本次没有教师板备注被带入，给生成器的8段材料均未超过该6000字限度；不等于模型读完两本书，也不能反推召回已经覆盖全部相关章节。

### 11.4 真实产物：标题、目标与45分钟安排

以下均为**实际artifact中的未审核模型稿内容**，用来说明系统输出形状和暴露问题；不是报告作者对医学或教材事实的确认。

标题：**甲状腺功能**。generation_method=llm_grounded，表示本次生成路径返回了模型结构稿，不是“语义已grounded”的质量认证。

executive_summary原稿：

> 甲状腺是重要的内分泌腺，由滤泡和滤泡旁细胞组成。滤泡上皮细胞合成和分泌甲状腺激素（T3、T4），调节新陈代谢、神经兴奋性和生长发育；滤泡旁细胞分泌降钙素，降低血钙。甲状腺激素的合成与分泌受下丘脑-垂体-甲状腺轴调控。胚胎期甲状腺的发生和功能对胎儿发育至关重要。

teaching_objectives共5项：描述甲状腺组织结构；解释激素合成、储存与释放；说明生理作用与调节；识别甲亢/甲减表现；比较甲状腺激素与降钙素。它们是模型生成的学习目标，不是人工模板预写的甲状腺课程答案。

| 实际lesson_blocks标题 | 分钟 | 实际content | 引用 |
| --- | ---: | --- | --- |
| 导入：甲状腺功能异常案例 | 5 | 展示甲亢和甲减的典型症状图片或案例，引导学生思考甲状腺的功能。 | S2 |
| 甲状腺的组织学基础 | 10 | 讲解甲状腺滤泡和滤泡旁细胞的结构，强调滤泡上皮细胞合成甲状腺激素，滤泡旁细胞分泌降钙素。 | S2、S3、S5、S6 |
| 甲状腺激素的合成与分泌过程 | 10 | 详细讲解甲状腺激素的合成、储存、碘化、重吸收、分解和释放过程，结合电镜图说明细胞器的作用。 | S3 |
| 甲状腺激素的生理作用与调节 | 10 | 讲解甲状腺激素对新陈代谢、神经兴奋性和生长发育的影响，以及下丘脑-垂体-甲状腺轴的调节。 | S2、S4、S8 |
| 临床应用与教材差异讨论 | 5 | 讨论甲状腺功能异常（甲亢、甲减）的临床表现，指出《局部解剖学》未涉及甲状腺功能，而《组织学与胚胎学》详细描述，引导学生关注教材差异。 | S1、S2 |
| 总结与提问 | 5 | 总结甲状腺功能的核心概念，提出3个课堂问题，检查学生理解。 | S2、S3、S4、S8 |

总和5+10+10+10+5+5=45。注意：稿中建议“展示图片”“结合电镜图”不代表系统生成或附带了这些教学图片；当前产物是文字安排。第5环节的全书否定性断言也没有因绑定S1而获得证实，见11.7。

### 11.5 其余主要栏目，哪些是真有、哪些为空

| 栏目 | 实际内容与引用 | 应如何读 |
| --- | --- | --- |
| knowledge_sequence | 共10项：组织结构(S2/S3/S5/S6)、合成与分泌(S3)、生理作用(S2)、调节(S4/S8)、降钙素(S2/S6)、发生(S7)，另4项标题为“单教材结论” | 不是10个独立检索工具调用，而是一次起草响应规范化后的教学条目 |
| teaching_focus | 共4项：合成分泌机制(S3)、生理作用/临床(S2)、调节轴(S4/S8)、教材侧重点(S1/S2) | 第4项仍包含待核对的全书未涉及断言 |
| common_ground | 空数组 | 没有保留可按两书来源规则成立的共同结论；不能把同一本书多个S编号算作跨书证据 |
| textbook_differences | 2项：局部解剖学“未涉及甲状腺功能，仅包含盆部与会阴的临床病例，与甲状腺无关”(S1)；组织学与胚胎学“详细描述…组织结构、激素…及胚胎发生”(S2/S3/S7) | 第一项是模型的未审核断言，不能当作报告确认的教材事实 |
| misconceptions | 2项：混淆甲状腺激素和降钙素(S2/S3/S6)；误以为激素直接从胶质释放入血(S2/S3) | 模型稿的辨析材料，仍需教师对照原文核对 |
| unresolved_questions | 3项，详见下 | 写“待确认”不自动使其他栏目的相反确定表述变得安全 |

稿中出现4条“单教材结论”，未保留原始生成JSON，因此不能逐行复原它们在原始响应中的位置；不过unresolved包含程序的共同结论降级提示，能确认规范化过程中发生了跨书来源不足的降级。

三道classroom_questions原稿：

1. “甲状腺滤泡上皮细胞合成甲状腺激素的过程包括哪些关键步骤？”
2. “甲状腺功能亢进和减退分别有哪些典型临床表现？其解剖学基础是什么？”
3. “为什么《局部解剖学》教材中没有涉及甲状腺功能的内容，而《组织学与胚胎学》详细描述？这反映了不同教材的什么特点？”

第3题把未经确认的“整本书没有涉及”作为题干前提，是本次真实输出的局限。系统目前也没有为这三题另外生成标准答案、提问目的和评价rubric，不能把问题清单当作完整教学测评方案。

unresolved_questions原稿：

> 《局部解剖学》中未提供甲状腺功能相关内容，无法进行教材间直接比较，需教师确认是否补充其他教材或资料。

> 教材中未明确甲状腺激素对心血管系统的具体作用机制，需教师根据临床知识补充。

> 部分结论未关联两本不同教材，已移入讲解顺序，不能视为教材共同结论。

前两条仍是模型对证据覆盖的解释，不是经过全书查证的事实；第三条对应程序来源规则的降级提示。原稿与教师修改必须区分：本节展示artifact，没有把它称为教师终审稿，也没有补写不存在的人工评审过程。

### 11.6 八条引用：只公开身份和位置，不公开教材原文

| S编号 | 书名 | 真实章节元数据 | 文件页序 | chunk_id |
| --- | --- | --- | --- | --- |
| S1 | 局部解剖学 | 第五章 盆部与会阴 | 204 | book_01_ch_004_chunk_0065 |
| S2 | 组织学与胚胎学 | 第13 章 内分泌系统 | 151 | book_02_ch_012_chunk_0004 |
| S3 | 组织学与胚胎学 | 第13 章 内分泌系统 | 151 | book_02_ch_012_chunk_0003 |
| S4 | 组织学与胚胎学 | 第13 章 内分泌系统 | 155 | book_02_ch_012_chunk_0012 |
| S5 | 组织学与胚胎学 | 第13 章 内分泌系统 | 157–158 | book_02_ch_012_chunk_0020 |
| S6 | 组织学与胚胎学 | 第13 章 内分泌系统 | 157 | book_02_ch_012_chunk_0019 |
| S7 | 组织学与胚胎学 | 第23 章 消化系统和呼吸系统的发生 | 252–253 | book_02_ch_022_chunk_0002 |
| S8 | 组织学与胚胎学 | 第13 章 内分泌系统 | 156 | book_02_ch_012_chunk_0016 |

本报告没有复制这些引用的quote/content。S1位于盆部与会阴章节，其主题支持性值得教师追查；“来自正确书、真实章页”只证明来源身份合法，不能证明它支持甲状腺教学结论。

### 11.7 检查全部通过，仍暴露两个真实问题

快照中的来源检查为100%，规则项目包括教材覆盖2/2、页码8/8、绑定行24/24；交付检查为45/45分钟、3/3问题、基本结构及三项关注齐全，missing_items=[]，semantic_reviewed=false。

与此同时unresolved_questions有3条；它没有进入当前交付检查的硬否决条件，所以程序仍能给draft_ready。这是现有规则的具体行为，不应删掉这些待确认事项让报告看起来更成功。

第一是**策略收尾失败**：第4轮validate通过后，5–8轮都没有形成合法动作，最后按no_progress停止，而不是正常finish。没有保留5–8轮原始响应，不能声称它们一定是finish参数哪一项错了；需要新增安全诊断或独立探针另作定位，不能篡改旧轨迹。

第二是**语义覆盖误判**：book_01只命中一段盆部与会阴材料，模型却在差异、重点、课时和第3题多处写“教材没有涉及甲状腺功能”。“本次检索未覆盖”不等于“整本教材不存在”；纯结构检查只看到S1属于book_01且行有引用，于是仍算教材覆盖和归属通过。这是目前验证器的边界，必须教师核对，而不是把通过分数宣传成语义正确率。

本次最终状态的准确读法：

```json
{
  "job_id": "job_96a1dd73b1a2",
  "status": "completed",
  "stop_reason": "no_progress",
  "delivery_status": "draft_ready",
  "semantic_reviewed": false,
  "steps_used": 8,
  "rag_queries_used": 2,
  "drafts_used": 1,
  "elapsed_seconds": 87.047
}
```

其中delivery_status是为阅读简化的表示，原字段在 `result.delivery.status`；预算字段原在 `result.budget`。这87.047秒是一例任务记录，不能作为一般性能指标；没有完整tokens、费用和每次网络重试日志，不应据此编造总费用或精确模型请求数。

### 11.8 本次没有发生的事

没有read_source、ask_teacher或finish动作；没有第二次write修稿；没有向量或图谱检索实际启用证据；没有记录本任务的教师最终语义审核。不能把前面解释的“45分钟任务先写40分钟再修订”的离线回归当成本次甲状腺任务，它们是不同证据。

## 12. 稿件的人工修改与浏览器行为

生成稿保存在artifact；教师编辑在前端editor中进行，点击保存之前主要是React状态与本地缓存。保存通过 `PATCH /api/agent/runs/{id}/draft`，见 [`save_lesson_draft:174–204`](../backend/api/agent.py#L174-L204)。

服务端先拒绝活跃/等待任务编辑，核对expected_revision和原书单，用 `validate_lesson_draft()`校验文本、分钟与来源，再运行verify重算delivery。条件UPDATE成功后写lesson_draft、draft_revision+1，而不覆盖模型artifact。

服务端字段/引用硬校验通过但课时总和或目标字段未齐时，教师工作可以保存为needs_work；保存成功不是强制draft_ready。输入的citations不能替换原始引用表，模型生成规则与教师修改规则也不能混为一套。

前端GET在pending/processing时约1.8秒续轮询，只读取已保存Job，不运行策略或工具；waiting/终态不继续定时pull，依赖手动或操作后刷新。切任务使用epoch/abort拒绝迟到响应。点击S1先展示返回的引用摘录，点击可用PDF原页再请求真实图片。

打印前有本机未保存编辑时先要求保存；服务端优先lesson_draft，否则artifact，返回HTML供新窗口显示，再由用户Ctrl+P另存PDF，不自动生成后端PDF文件，也不调用生成模型。依据：[printDraft:449](../frontend/src/components/AgentWorkbench.tsx#L449)、[export_lesson:208](../backend/api/agent.py#L208)。

## 13. 本次能说清的能力与不能补写的能力

已实现：模型逐轮动作、严格JSON分发、既有RAG工具适配、来源重载与哈希、检查点、预算、问答/继续/取消、教师稿保护、本地来源/结构门禁。

未实现或未证明：任意工具执行、多Agent协商、跨任务自动学习、专用语义裁判、来源版本库、分布式领取租约、exactly-once外部调用、在线模型总能收尾、教案语义零幻觉。

详细说明应接受失败案例检验：如果真实任务已validate通过，却在后续四轮不断产生invalid_action，说明“有草稿”和“Agent完成自主交付”是两个指标。应查决策响应质量与诊断缺口，不能只展示一张成功草稿截图。

## 14. 验证资料与后续复核入口

工程验收见 [2026-10-28记录](./evaluation/agent-v3-engineering-validation-20261028.md)；它验证当时310后端、83前端与构建，并非本次真实模型任务表现的分数。本报告中的真实任务另按其实际轨迹评价。

2026-10-29本轮再次实际执行全量：后端313项通过（2.958秒）、前端84项通过（354.838毫秒），TypeScript与Vite生产构建通过；主包990.83kB仍有体积提示。原RAG三个核心文件无差异。新增回归覆盖安全字段错误过滤、未知模型键脱敏、拒绝反馈进入下一轮并纠错，以及取消后的轨迹展示；这些是工程约束验证，不是旧任务收尾问题已在线解决或教学语义正确的证据。历史310/83与本轮313/84属于不同日期的回归结果，不能相加。

后续每次改动应复核：动作契约与公开文案是否一致；分区预算是否真的执行；新增state字段是否持久且能传给下一轮；模型稿与教师稿是否仍分离；错误诊断是否保留足够安全事实；源码行号与案例是否仍对应旧版行为。

测试源码可按问题定位：[运行器轨迹](../tests/test_agent_runtime.py)、[生成模板实参](../tests/test_agent_generation.py)、[policy上下文](../tests/test_lesson_policy.py)、[RAG适配](../tests/test_agent_rag_tool.py)、[CAS竞态](../tests/test_agent_control_races.py)、[无模型护稿](../tests/test_agent_no_key_recovery.py)、[队列交接](../tests/test_agent_queue_handoff.py)。
