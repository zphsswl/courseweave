# 从教师操作到 Agent 执行：一堂 45 分钟课的技术链路

整理日期：2026-10-29。依据本地 `lesson_agent_v3` 实现；配套阅读：[详细技术复盘](./Agent架构技术复盘.md)、[架构与配置](./Agent系统架构.md)。

下面用一个具体示例把界面、请求、函数和数据库状态对上。它是依据源码与离线回归解释的执行路径，**不是一次真实在线模型运行记录**。实际模型可以选择不同动作和查询，也可能无法完成交付；程序没有把下面的六步写成固定顺序。

## 1. 示例条件与教师真正要做的事

课程中已有教材甲、教材乙，两本都已解析、生成 Chunk 并确认目录；本例假定它们是保留了源文件的 PDF。服务端已配置可用模型，本地模式允许创建任务。

教师希望讲授“模块的形成与反馈”，面向一年级学生，要求 45 分钟、1 个课堂问题，关注项选择“核心概念”。教材与课程 ID 在下文使用示意名称，不对应真实业务数据。

教师的主要操作只有：

1. 进入“备课 Agent”，点“新建一堂课”，填写条件、选择两本书。
2. 点“检索教材并生成草稿”，等待并查看执行记录。
3. 草稿完成后阅读、回查引用，必要时修改并保存。
4. 点“打印 / PDF”，在打印版中使用浏览器保存 PDF。

检索无结果后改查询、生成 40 分钟草稿后发现缺项并修订，是示例中的 Agent 动作，不需要教师逐步按按钮指挥。

## 2. 按一次真实请求经过的路径对照代码

表中前端工作台函数位于 [`AgentWorkbench.tsx`](../frontend/src/components/AgentWorkbench.tsx)，HTTP 封装位于 [`lessonAgent.ts`](../frontend/src/api/lessonAgent.ts)。后端 Agent API 位于 [`api/agent.py`](../backend/api/agent.py)，运行器位于 [`lesson_runtime.py`](../backend/agents/lesson_runtime.py)。

“API”列专指浏览器向项目后端发出的请求；服务端另会调用模型服务，不是由浏览器逐步调用工具。

### 2.1 从填表到创建、排队与读取状态

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 点“新建一堂课”，填写主题、目标、学情、45 分钟和 1 个问题，选两本教材 | 显示本次备课条件；尚无执行轨迹 | `newLesson()`、`changeBrief()` | 填表本身不创建 Agent 任务 | 无模型/工具执行 | 主要是 React 状态；条件尽力暂存本机 localStorage，还没有新的 Job |
| 点“检索教材并生成草稿” | 按钮进入提交状态；成功提示任务已创建，切换到任务视图 | `startRun()` → `createLessonRun()` | `POST /api/agent/runs` | `create_agent_run()` → `_validate_scope()` → `create_job()` → `initial_agent_result()` → `update_job()` → `enqueue_job()` | `Job.payload` 保存规范化请求；`Job.result` 保存 v3 初始状态；状态先为 pending，轨迹为空，预算用量为 0 |
| 保持任务页打开 | 显示排队、执行、动作记录、预算及当前材料 | 选中任务的 effect 内 `pull()` → `getLessonRun()` | `GET /api/agent/runs/{id}` | `get_agent_run()` → `get_job()` | **只读已有 Job，不入队、不执行工具、不重新生成** |
| 等待系统取走任务 | 状态进入执行；已确认目录的本例不再停在章节确认 | 浏览器仍只是读取状态 | 没有“执行每一步”的前端 POST | `_worker_loop()` → `_dispatch_job()` → `process_course_agent()` → `process_agent_loop()` → `_prepare_environment()` | Job 进入 processing；装载已保存状态与教材观察；确定性准备之后才进入模型动作循环 |

一个示意创建请求如下。前端还会进行表单校验，后端再验证课程、教材和来源范围，不能只信浏览器提交的 ID。

```json
{
  "course_id": "course_example",
  "topic": "模块的形成与反馈",
  "goal": "基于两本教材原文安排45分钟课堂，说明形成过程与观察反馈，并准备1个课堂问题",
  "audience": "一年级学生",
  "prior_knowledge": "已学习基础模块",
  "textbook_ids": ["book_a", "book_b"],
  "requirements": ["核心概念"],
  "duration_minutes": 45,
  "question_count": 1,
  "focus_terms": []
}
```

队列位于 [`job_queue.py`](../backend/services/job_queue.py)。`Job` 表在 [`database.py`](../backend/database.py) 中定义，使用 SQLite 持久化；队列自身是进程内单 worker，并非浏览器维持的一段异步任务。

任务正在 pending/processing 时，工作台在一次读取结束后约 **1.8 秒**继续 GET。进入 waiting_user、completed、failed 或 cancelled 后不继续定时 pull；回答、继续、重试等操作会触发重新读取。“刷新”也只是 GET，不是再次 POST 创建。

### 2.2 从第一次查不到，到生成、检查与修订

下面给出一种六轮轨迹。每轮均先由 [`decide_next_action()`](../backend/agents/lesson_policy.py) 读取当前条件、证据、反馈与预算，再经 [`validate_decision()`](../backend/agents/lesson_contracts.py) 校验，最后由运行器 `_execute()` 执行。模型不能直接调用任意 Python 函数。

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 等待，第 1 轮模型查询“模块基础” | 实际动作记录显示查询；本次新增来源为 0 | `pull()` 读取；`lessonExecution()` 生成展示模型 | 仅前端 GET 状态；**不是浏览器再 POST RAG** | `process_agent_loop()` → policy → contract → `_execute(query_rag)` → `query_rag_tool()` → `rag_agent.query_rag()` | 先保存 `steps_used=1`、`rag_queries_used=1` 与 running 记录；结束后保存 observation 和 completed 记录，evidence 仍为空 |
| 等待，第 2 轮模型根据无结果反馈改查“模块的形成与反馈” | 新增两本书的来源，轨迹出现第二次查询 | 同上 | 同上 | RAG 调用后，适配器 `_local_items()` 和运行器 `_read_sources()` / `_add_evidence()` 按 ID 从本地重新装载来源 | `steps_used=2`、RAG 用量为 2；evidence 含两书的真实 Chunk、章节、页码、正文摘录与完整正文哈希 |
| 等待，第 3 轮模型选择起草；示例第一稿只安排了 40 分钟 | 可以出现草稿与本次生成动作；尚未说明交付检查通过 | 同上 | 同上 | `_execute(write_draft)` → `course_agent._generate_artifact()` → `_normalize_artifact()` | `steps_used=3`、`drafts_used=1`；写入 artifact；旧 quality/delivery 清空；模型不能自行替换服务端 citations |
| 等待，第 4 轮模型显式选择检查草稿 | 记录“课时 40/45”缺项，产物尚未齐全 | 同上 | 同上 | `_execute(validate_draft)` → `_validate()` → `verify_artifact()` | `steps_used=4`；delivery 为 needs_work；missing_items 包含课时问题；`semantic_reviewed=false` |
| 等待，第 5 轮模型根据缺项选择修订 | 轨迹记录再次起草；新稿安排 45 分钟 | 同上 | 同上 | `_execute(write_draft)` 传入 `_agent_feedback`、`_agent_previous_draft` 与修订 instructions，再调用生成器 | `steps_used=5`、`drafts_used=2`；40 分钟旧稿进入 artifact_versions，新 artifact 为 45 分钟，待重新检查 |
| 等待，第 6 轮模型提出 finish | 当前稿满足规则后显示“教案草稿 · 待教师核对” | 同上；终态后不再续定时轮询 | 同上 | `_execute(finish)` **再次执行 `_validate()`**，通过后才允许交付 | `steps_used=6`；`status=completed`、`delivery.status=draft_ready`、`stop_reason=delivery_ready`；仍未完成教学语义审核 |

这里有两件事尤其容易看错：

- `write_draft` **不会自动跟随验证**。第 4 轮是模型提出的独立 `validate_draft` 动作；模型也可以直接提出 `finish`，但 finish 内部仍会重新校验，不能复用旧的通过声明绕过门禁。
- 轨迹描述的是已经发生的动作，不是前端预先画好的进度表。动作很快时，轮询不一定展示每个瞬间的中间画面，但已落库的轨迹仍可查看。

该六轮模式对应 [`test_empty_query_changes_then_validation_failure_drives_a_real_revision`](../tests/test_agent_runtime.py)：测试用脚本替代模型决策、RAG 传输和草稿模型，实际运行生产控制器、范围检查、来源装载、检查点和验证器。它验证接线与控制逻辑，不保证真实模型必然按此顺序行动。

本例花费 6 轮、2 次 RAG、2 次起草，均低于默认 12/6/3 上限。预算在调用前落库，重启或重试不重置；“RAG 调用数”也不等于全部模型请求数，因为决策、RAG 回答与教案生成是不同调用。

### 2.3 RAG 这一跳究竟发生在哪里

```text
浏览器：GET 任务状态，读取执行结果
                   ↑
单 worker：运行器 → query_rag_tool → 既有 rag_agent.query_rag
                                      ↓
                        retrieval_service.retrieve
                                      ↓
                      检索、融合、证据与 RAG 回答
                                      ↓
适配器按来源 ID 重取本地记录 → 运行器保存证据与观察 → 下一轮模型决策
```

**默认是后端 Python 内部函数调用，不额外发 HTTP 到 `/api/rag/query`。** 只有配置了 `AGENT_RAG_URL` 才通过 HTTP 访问指定完整查询地址；模型参数里不能指定这个地址。独立问答界面的公开 RAG API 与 Agent 的默认内部工具调用是两条入口。

适配器位于 [`rag_tool.py`](../backend/agents/rag_tool.py)，原方法位于 [`rag_agent.py`](../backend/agents/rag_agent.py) 和 [`retrieval_service.py`](../backend/services/retrieval_service.py)。本轮没有重写原检索、融合与问答方法。

来源库是 `Course → Textbook → Chapter → Chunk`。远端/工具返回的是候选来源声明，不能替换本地正文、章节归属和页码。运行器建立的证据快照及哈希保存在 Job.result；短摘录不等于完整教材已被模型阅读。

## 3. 草稿形成之后：教师阅读、修改与保存

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 阅读已完成草稿 | 显示课时、问题、教材引用、待核对项及真实轨迹 | `serverArtifact()`、`lessonDelivery()`、`lessonExecution()` | 读取任务 GET | `get_agent_run()` | 展示时优先 `lesson_draft`，没有教师稿才用 artifact；GET 不调用模型 |
| 点“编辑草稿”，修改讲授标题、环节内容或引用选择 | 标记有未保存修改；未点击保存前不算同步到课程 | `setEditing(true)`、`updateArtifact()`、`changeRow()` 等 | 编辑输入本身无保存 API | 无后端生成或验证调用 | 编辑器内存与尽力 localStorage 暂存；服务端原稿仍在 |
| 点“保存修改” | 成功后显示教师修订版；冲突保留本机编辑并提示处理 | `saveDraft()` → 前端 `validateDraft()` → `saveLessonDraft()` | `PATCH /api/agent/runs/{id}/draft`，含 `expected_revision` 与 artifact | `save_lesson_draft()` → `validate_lesson_draft()` → `verify_artifact()` → 条件更新 | 写 `result.lesson_draft`，`draft_revision + 1`，重算 quality/delivery；不替换模型原稿 artifact |

首次教师保存可提交 `expected_revision=0`；成功后为 1。另一标签页已保存新版本时，旧 revision 返回 **409**，不能覆盖。正在执行或等待的任务也不能直接保存教师稿；先完成或停止。

引用有两层保护：前端提交时使用服务端原稿的 citations；后端仍核对原始引用表、来源范围和条目的 `source_ids`，不能靠修改请求伪造新教材或新页码。引用不是用户随意填写的附件。

保存会重新计算交付检查，但并不要求所有教学目标已完成才允许保留教师工作。例如教师修改后总时长不再等于 45 分钟，稿件可以保留，同时 delivery 呈现待补内容；保存成功不等于所有检查或教学语义通过。格式无效、引用非法等则会被拒绝。

## 4. 点击引用到原页：先读已有摘录，再请求图片

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 点一条 `S1 · 教材甲` 引用，或“核对教材证据” | 打开双侧证据弹窗，先展示已保存的书名、目录、页码与 quote | `sourceChips()` / 栏目按钮 → `showEvidence()` → `renderSource()` | **这一步通常无新 API 请求**，使用任务已返回的 citations | 无新检索，无模型调用 | 只改变 sourcePair/evidenceOpen 等前端状态；不生成或保存新关系 |
| 在 PDF 来源卡点“打开教材原页” | 切换为原页阅读器，可翻页和缩放 | `citationPresentation()` → `setSourcePage()` → `SourcePageViewer` → `pageImageUrl()` | 浏览器图片 GET：`/api/textbooks/{book_id}/teaching/pages/{page}/image` | `teaching_page_image()` → `render_teaching_page()` → 定位源 PDF、渲染 PNG | 读取真实源文件，返回图片与缓存头；不改变 Agent 的轨迹、预算或教案 |

原页接口位于 [`api/teaching.py`](../backend/api/teaching.py)，阅读器位于 [`SourcePageViewer.tsx`](../frontend/src/components/SourcePageViewer.tsx)，路径封装位于 [`api/teaching.ts`](../frontend/src/api/teaching.ts)，PDF 渲染位于 [`teaching_service.py`](../backend/services/teaching_service.py)。

这里的页码按 **PDF 文件页序**，不保证与书内印刷页码一致。非 PDF、没有有效页码或源 PDF 已不可用时，系统只能展示对应摘录/目录位置或原页不可用提示，不会合成一张“原页”。

## 5. 打印与 PDF：导出已保存成果，不重新生成教案

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 保存修改后，点“打印 / PDF” | 新开打印版窗口；有未保存修改时先要求保存 | `printDraft()` → `exportLessonPrint()` | `GET /api/agent/runs/{id}/export?format=html` | `export_lesson()` 优先读 lesson_draft，否则 artifact → `lesson_markdown()` → `lesson_print_html()` | 只读取已保存产物，返回 HTML；不调用模型、不写新 Job |
| 在打印版按 `Ctrl + P`，选“保存为 PDF”或打印机 | 浏览器打印预览与本地文件保存 | 浏览器自身打印能力 | 没有项目后端“生成 PDF”接口 | 后端这一步无执行 | PDF 文件由浏览器保存到用户选定位置，不作为新教案版本写回 SQLite |
| 可选：点“Markdown” | 下载同一已保存教案的 Markdown | `exportDraft()` → `exportLessonMarkdown()` | `GET .../export?format=markdown` | `export_lesson()` → `lesson_markdown()` | 只读导出 |

`printDraft()` 先在用户点击时预留新窗口，再异步写入服务端 HTML，减少弹窗拦截；失败会关闭预留窗口并提示。打印版的内容与安全转义由 [`lesson_print.py`](../backend/services/lesson_print.py) 生成，页面提示使用浏览器打印。按钮叫“打印 / PDF”，不代表后端已经生成 PDF 二进制。

## 6. 三个中途分支：回答、章节确认与停止

### 6.1 模型询问教师：回答同一个问题，继续同一个任务

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 等待时模型选择 `ask_teacher` | 出现具体问题、建议选项和回答框；任务等待 | `lessonExecution()` 区分 teacher_question | 前端 GET 读到等待状态，随后停止续定时 pull | `_execute(ask_teacher)` 生成唯一 request_id 并保存等待检查点 | `status=waiting_user`；approval 含问题、选项与 request_id；已有证据和稿件保留 |
| 点建议或填写回答 | 建议只填入，不自动提交；可自己编辑 | `changeTeacherAnswer()` | 无提交请求 | 无 | 按 course/run/request_id 尽力暂存本机；新问题不继承旧答案 |
| 点“提交回答并继续” | 成功继续同一任务；旧问题或冲突时保留该问题输入 | `respondToTeacherQuestion()` → `respondLessonRun()` | `POST /api/agent/runs/{id}/respond`，体为 `{answer, request_id}` | `respond_to_agent()` 校验当前等待与问题、比较完整结果快照 → `enqueue_job()` | 回答追加到 teacher_answers，approval 清空，状态改 pending；再次进入原运行器，保留已花预算 |

教师回答只补充本任务条件，不自动扩大原始课程或教材范围；生成器通过 `_agent_teacher_answers` 接收这些信息。`/resume` 不能绕过这个问题。最多四次回答，单次最多 2000 字；并发旧 Q1 回答不能覆盖新 Q2。

### 6.2 目录未确认：先校对来源，再点章节继续

本例两本书已确认，因此不会出现此分支；若教师另选了尚未确认目录的书，以下是实际路径。

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 启动后准备阶段发现目录未确认 | 提示先核对章节；这不是模型提出的教学问题 | 工作台 chapter_review 分支 | GET 状态 | `_prepare_environment()` | `status=waiting_user`；`approval.type=chapter_review`，尚未开始模型动作循环 |
| 点“去核对章节”，在教材目录弹窗核对并点“保存并确认目录” | 目录确认成功 | `onGoLibrary`；`ChapterReviewModal.save()` → `updateChapterStructure(..., true)` | `PATCH /api/textbooks/{book_id}/chapters` | `update_chapter_structure()` → `apply_structure()` | 保存章节结构与教材确认状态；**这一步本身没有替 Agent 调用 `/resume`** |
| 返回该任务，点“已确认，继续” | 原任务重新排队 | `continueRun('resume')` → `resumeLessonRun()` | `POST /api/agent/runs/{id}/resume` | `resume_agent_run()` 再检查教材确认状态及快照 → 入队 | 状态改 pending；重入准备与运行器，累计已用运行时间，教师等待时间不计入 |

目录弹窗位于 [`ChapterReviewModal.tsx`](../frontend/src/components/ChapterReviewModal.tsx)，章节 API 在 [`textbooks.py`](../backend/api/textbooks.py)，章节修改规则在 [`chapter_review.py`](../backend/services/chapter_review.py)。

### 6.3 教师主动停止：停止状态写回，不强杀外部调用

| 用户动作 | 界面反馈 | 前端函数 | API | 后端函数 | 持久状态 |
| --- | --- | --- | --- | --- | --- |
| 在 v3 排队、执行或等待状态点“停止本次执行” | 确认停止后显示已停止；已有材料继续保留 | `cancelRun()` → `cancelLessonRun()` | `POST /api/agent/runs/{id}/cancel` | `cancel_agent_run()` 按当前状态与完整结果快照条件更新 | `status=cancelled`、`stop_reason=user_cancelled`，approval 清空，证据和稿件不删除 |
| 原来的 RAG/模型调用稍后才返回 | 任务保持取消，不被旧结果重新改成执行或完成 | 前端不再轮询活跃态 | 无需新的取消请求 | `_ensure_active()`；`save_checkpoint()` 的 `status != cancelled` 原子谓词 | 拒绝迟到覆盖；已取消任务不会因旧 worker 返回而复活 |

若停止读到旧快照期间工具刚保存新稿，取消会返回 409，让教师刷新后重试，以免盖掉新成果。已经结束的任务也不应因曾点击停止而被前端虚报为取消。它是协作式停止，不能撤回已发出的网络请求或费用。

## 7. 把这条链路记成四个职责

| 层 | 在本例承担什么 | 不承担什么 |
| --- | --- | --- |
| 前端 | 收集条件、POST用户决定、GET真实状态、编辑与回查 | 不自己运行Agent循环，不把刷新当重试 |
| 运行器与契约 | 控制工具权限、预算、状态、来源和交付门禁，保存检查点 | 不因为模型一句“完成”就放行 |
| 模型与RAG | 模型提出下一动作/生成草稿；RAG提供既有教材查证能力 | 不决定引用权限，不覆盖教师稿，不自动批准教学语义 |
| 教师 | 明确任务、补充必要条件、核对原文、修改并审核最终教案 | 无需逐个点击指挥常规检索与修订步骤 |

两类错误要先分开排查：界面刷新后仍旧，先查 GET / Job 状态；轨迹显示查询无结果或检查缺项，查对应工具观察与来源，而不是反复点创建。预算耗尽会保留部分成果与停止原因，不等同于完成教案。

这份文档解释的是用户操作与工程链路。真实模型是否稳定选择合适动作、结论是否得到原文语义支持、是否节省教师备课时间，仍需独立任务集和教师评测，不能由这条示例路径证明。
