import axios from 'axios';
import type { AgentArtifact, AgentArtifactRow, AgentQuality, AgentResult, AgentRun } from '../types';

const api = axios.create({ baseURL: '/api/agent', timeout: 60000 });

export interface AgentLessonContext {
  intentId?: string;
  topic?: string;
  textbookIds?: string[];
  focusTerms?: string[];
  boardId?: string;
  selectedChunkIds?: string[];
  supplementalChunkIds?: string[];
  sourceBookId?: string;
  sectionId?: string;
  /** A frontend-only additive intent; never forwarded as request context. */
  collectedEvidence?: { chunkId: string; textbookId: string; courseId?: string } | Array<{ chunkId: string; textbookId: string; courseId?: string }>;
}

export interface LessonBlock {
  title: string;
  minutes: number;
  content: string;
  source_ids: string[];
}

export interface LessonArtifact extends Omit<AgentArtifact, 'generation_method'> {
  generation_method: AgentArtifact['generation_method'] | 'teacher_edited';
  teacher_edited?: boolean;
  lesson_blocks?: LessonBlock[];
  teaching_focus?: AgentArtifactRow[];
}

export interface LessonDelivery {
  status: 'evidence_only' | 'draft_ready' | 'needs_work';
  missing_items: string[];
  checks: Array<{ id: string; label: string; passed: boolean; value: string | number }>;
}

export interface LessonRequest {
  course_id: string;
  topic: string;
  goal: string;
  audience?: string;
  prior_knowledge?: string;
  textbook_ids: string[];
  requirements: string[];
  duration_minutes: number;
  question_count: number;
  focus_terms: string[];
  context?: { source_book_id?: string; section_id?: string; board_id?: string; selected_chunk_ids?: string[]; supplemental_chunk_ids?: string[] };
}

export interface LessonApproval {
  type?: string;
  title?: string;
  message?: string;
  textbooks?: Array<{ id: string; title: string }>;
  question?: string;
  options?: string[];
  request_id?: string;
}
export interface LessonTrajectoryEntry {
  id: string;
  step: number;
  action: string;
  summary: string;
  status: string;
  started_at?: string;
  finished_at?: string;
  observation?: Record<string, unknown>;
  error?: string;
}
export interface LessonBudget {
  max_steps: number;
  steps_used: number;
  max_rag_queries: number;
  rag_queries_used: number;
  max_drafts: number;
  drafts_used: number;
  elapsed_seconds: number;
  max_runtime_seconds?: number;
}
export interface LessonResult extends Omit<AgentResult, 'artifact' | 'quality' | 'approval'> {
  artifact?: LessonArtifact | null;
  lesson_draft?: LessonArtifact | null;
  draft_revision?: number;
  delivery?: LessonDelivery;
  request?: Partial<LessonRequest>;
  quality?: (AgentQuality & { semantic_reviewed?: boolean; source_check_score?: number }) | null;
  execution_mode?: 'model_driven' | 'evidence_workflow' | string;
  trajectory?: LessonTrajectoryEntry[];
  budget?: Partial<LessonBudget>;
  stop_reason?: string;
  approval?: LessonApproval | null;
  teacher_answers?: Array<{ question: string; answer: string; answered_at?: string }>;
}

export interface LessonRun extends Omit<AgentRun, 'result' | 'status'> {
  status: AgentRun['status'] | 'cancelled';
  result: LessonResult;
  payload?: Partial<LessonRequest>;
}

const runPath = (id: string) => `/runs/${encodeURIComponent(id)}`;
export const getLessonRuns = (courseId: string, signal?: AbortSignal) => api.get<LessonRun[]>('/runs', { params: { course_id: courseId, limit: 12 }, signal });
export const getLessonRun = (id: string, signal?: AbortSignal) => api.get<LessonRun>(runPath(id), { signal });
export const createLessonRun = (request: LessonRequest, signal?: AbortSignal) => api.post<LessonRun>('/runs', request, { signal });
export const resumeLessonRun = (id: string, signal?: AbortSignal) => api.post<LessonRun>(`${runPath(id)}/resume`, {}, { signal });
export const retryLessonRun = (id: string, signal?: AbortSignal) => api.post<LessonRun>(`${runPath(id)}/retry`, {}, { signal });
export const respondLessonRun = (id: string, answer: string, requestId: string, signal?: AbortSignal) => api.post<LessonRun>(`${runPath(id)}/respond`, { answer, request_id: requestId }, { signal });
export const cancelLessonRun = (id: string, signal?: AbortSignal) => api.post<LessonRun>(`${runPath(id)}/cancel`, {}, { signal });
export const saveLessonDraft = (id: string, expectedRevision: number, artifact: LessonArtifact, signal?: AbortSignal) => api.patch<LessonRun>(`${runPath(id)}/draft`, { expected_revision: expectedRevision, artifact }, { signal });
export const exportLessonMarkdown = (id: string, signal?: AbortSignal) => api.get<string>(`${runPath(id)}/export`, { params: { format: 'markdown' }, responseType: 'text', signal });
export const exportLessonPrint = (id: string, signal?: AbortSignal) => api.get<string>(`${runPath(id)}/export`, { params: { format: 'html' }, responseType: 'text', signal });

const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown, limit = 600): string => typeof value === 'string' ? value.trim().slice(0, limit) : '';
const count = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
/** Historical SQLite Job timestamps are UTC without a timezone suffix. */
export function parseLessonTimestamp(value?: string): Date | null {
  if (!value) return null;
  const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value) ? `${value}Z` : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}
const actionLabels: Record<string, string> = {
  inspect_course: '查看课程与教材状态', query_rag: '查询教材证据', read_source: '读取教材原文', write_draft: '编写或修订教案',
  model_decision: '模型选择后续动作', invalid_action: '检查模型动作', prepare_environment: '准备教材与原文定位',
  inspect_textbooks: '查看教材状态', inspect_materials: '查看备课材料', read_sources: '读取教材原文',
  search_evidence: '检索教材证据', rag_query: '检索教材证据', search: '检索教材证据',
  draft_lesson: '编写教案草稿', generate_draft: '编写教案草稿', review_lesson: '检查教案',
  validate_draft: '核对草稿与引用', ask_teacher: '请教师补充条件', finish: '结束本次执行',
};
const stopLabels: Record<string, string> = {
  delivery_ready: '交付结构与引用检查已通过，仍待教师核对', decision_unavailable: '模型决策暂不可用，已保留当前材料',
  model_not_configured: '模型未配置，已保留当前材料', no_progress: '多轮操作未取得新进展，已保留当前材料',
  step_budget: '已达到循环轮次上限', time_budget: '已达到运行时间上限', runtime_error: '执行发生异常，已保留检查点',
  completed: '本次执行已结束', finished: '本次执行已结束', goal_met: '已结束本次目标检查',
  max_steps: '已达到循环轮次上限', step_budget_exhausted: '已达到循环轮次上限',
  max_rag_queries: '已达到教材检索次数上限', rag_budget_exhausted: '已达到教材检索次数上限',
  max_drafts: '已达到教案尝试次数上限', draft_budget_exhausted: '已达到教案尝试次数上限',
  time_budget_exhausted: '已达到运行时间上限', cancelled: '教师已停止本次执行',
  user_cancelled: '教师已停止本次执行', teacher_cancelled: '教师已停止本次执行',
  model_unavailable: '模型不可用，转为证据整理', evidence_workflow: '已按证据工作流整理材料',
};
/** Render only action/results metadata, never arbitrary provider or reasoning payloads. */
export function trajectoryObservation(value: unknown): string[] {
  const item = object(value), lines: string[] = [];
  const summary = text(item.summary, 360); if (summary) lines.push(summary);
  const query = text(item.query, 160); if (query) lines.push(`检索词：${query}`);
  for (const [key, label] of [['evidence_count', '原文'], ['source_count', '来源'], ['selected_count', '已选'], ['added_count', '新增原文'], ['textbook_count', '教材'], ['draft_version', '草稿尝试'], ['count', '返回条目']] as const) {
    const value = count(item[key]); if (value !== null) lines.push(`${label}：${value}`);
  }
  const status = text(item.status, 80); if (status) lines.push(`结果状态：${status}`);
  const delivery = text(item.delivery, 80) || text(object(item.delivery).status, 80);
  if (delivery) lines.push(`交付状态：${({ draft_ready: '教案草稿，待教师核对', needs_work: '仍有缺项', evidence_only: '证据材料' } as Record<string, string>)[delivery] || delivery}`);
  const generation = text(item.generation_method, 80);
  if (generation) lines.push(`生成方式：${({ llm_grounded: '模型草稿，仍待核对', evidence_fallback: '原文证据整理', teacher_edited: '教师修订' } as Record<string, string>)[generation] || generation}`);
  const missing = Array.isArray(item.missing_items) ? item.missing_items.map((entry) => text(entry, 160)).filter(Boolean).slice(0, 8) : [];
  if (missing.length) lines.push(`待补：${missing.join('；')}`);
  const sources = Array.isArray(item.source_ids) ? item.source_ids.map((id) => text(id, 60)).filter(Boolean).slice(0, 8) : [];
  if (sources.length) lines.push(`引用：${sources.join('、')}`);
  return lines;
}

/** Safe display model for both stored v2 runs and the actual v3 execution loop. */
export function lessonExecution(run: LessonRun) {
  const result = object(run.result), isV3 = result.agent_version === 'lesson_agent_v3';
  const mode = isV3 ? result.execution_mode === 'model_driven' ? 'model_driven' : result.execution_mode === 'evidence_workflow' ? 'evidence_workflow' : 'unknown' : 'legacy';
  const modeLabel = mode === 'model_driven' ? '模型驱动执行' : mode === 'evidence_workflow' ? '证据工作流 · 降级' : mode === 'legacy' ? '历史备课流程' : '执行模式待核对';
  const modeDescription = mode === 'model_driven' ? '下方展示实际动作与调用结果；不展示模型内部推理。'
    : mode === 'evidence_workflow' ? '本次按证据整理流程执行，不能据此声称模型已自主规划或完成整堂课。'
      : mode === 'legacy' ? '以下为旧版流程记录，不作为模型自主决策轨迹。' : '服务端尚未提供可识别的执行模式，请以实际材料和任务记录为准。';
  const trajectory = (Array.isArray(result.trajectory) ? result.trajectory : []).map((raw, index) => {
    const entry = object(raw), status = text(entry.status, 40);
    const stopped = run.status === 'cancelled' && status === 'running';
    const knownStatus = stopped ? 'stopped' : ['running', 'completed', 'failed', 'rejected'].includes(status) ? status : 'unknown';
    const action = text(entry.action, 100);
    return { id: text(entry.id, 120) || `entry-${index}`, step: count(entry.step), action,
      title: actionLabels[action] || action || '执行动作', summary: text(entry.summary, 600), status: knownStatus,
      statusLabel: stopped ? '已停止接收结果' : knownStatus === 'running' ? '执行中' : knownStatus === 'completed' ? '已执行' : knownStatus === 'failed' ? '执行失败' : knownStatus === 'rejected' ? '已拒绝' : '状态待核对',
      startedAt: text(entry.started_at, 80), finishedAt: text(entry.finished_at, 80), observation: trajectoryObservation(entry.observation), error: text(entry.error, 600) };
  });
  const legacyPlan = (Array.isArray(result.plan) ? result.plan : []).map((raw, index) => {
    const entry = object(raw), status = text(entry.status, 40);
    return { id: text(entry.id, 120) || `legacy-${index}`, title: text(entry.title, 160) || '历史步骤',
      summary: text(entry.message) || text(entry.description), status,
      statusLabel: ({ skipped: '已复用', completed: '已处理', running: '处理中', waiting: '待确认', failed: '未成功', pending: '未开始' } as Record<string, string>)[status] || '状态待核对' };
  });
  const rawBudget = object(result.budget);
  const budget = ([['steps_used', 'max_steps', '循环轮次'], ['rag_queries_used', 'max_rag_queries', '教材检索'], ['drafts_used', 'max_drafts', '教案尝试']] as const).map(([used, max, label]) => ({
    id: used, label, used: count(rawBudget[used]), max: count(rawBudget[max]),
  })).filter((item) => item.used !== null || item.max !== null);
  const rawApproval = object(result.approval), approvalType = text(rawApproval.type, 80);
  const approvalKind = approvalType === 'teacher_question' ? 'teacher_question' : approvalType === 'chapter_review' || (!approvalType && Array.isArray(rawApproval.textbooks)) ? 'chapter_review' : Object.keys(rawApproval).length ? 'unknown' : null;
  const approval = { kind: approvalKind, title: text(rawApproval.title, 160), message: text(rawApproval.message),
    question: text(rawApproval.question, 2000), requestId: text(rawApproval.request_id, 160),
    options: Array.isArray(rawApproval.options) ? rawApproval.options.map((option) => text(option, 1000)).filter(Boolean).slice(0, 12) : [],
    textbooks: Array.isArray(rawApproval.textbooks) ? rawApproval.textbooks.map((book) => ({ id: text(object(book).id, 120), title: text(object(book).title, 200) })).filter((book) => book.title) : [] };
  const stopReason = text(result.stop_reason, 600);
  const teacherAnswers = (Array.isArray(result.teacher_answers) ? result.teacher_answers : []).map((raw) => {
    const answer = object(raw); return { question: text(answer.question, 2000), answer: text(answer.answer, 2000), answeredAt: text(answer.answered_at, 80) };
  }).filter((item) => item.question || item.answer);
  return { isV3, mode, modeLabel, modeDescription, trajectory, legacyPlan, budget, elapsed: count(rawBudget.elapsed_seconds), runtimeLimit: count(rawBudget.max_runtime_seconds), approval, teacherAnswers,
    stopReason: stopLabels[stopReason] || stopReason,
    canRespond: run.status === 'waiting_user' && approval.kind === 'teacher_question' && Boolean(approval.requestId && approval.question),
    canResume: run.status === 'waiting_user' && approval.kind === 'chapter_review',
    canCancel: isV3 && ['pending', 'processing', 'waiting_user'].includes(run.status) };
}

export function normalizedArtifact(artifact: LessonArtifact): LessonArtifact {
  return {
    ...artifact,
    title: artifact.title || '', executive_summary: artifact.executive_summary || '',
    teaching_objectives: artifact.teaching_objectives || [], knowledge_sequence: artifact.knowledge_sequence || [],
    common_ground: artifact.common_ground || [], textbook_differences: artifact.textbook_differences || [],
    misconceptions: artifact.misconceptions || [], classroom_questions: artifact.classroom_questions || [],
    unresolved_questions: artifact.unresolved_questions || [], citations: artifact.citations || [],
    lesson_blocks: artifact.lesson_blocks || [], teaching_focus: artifact.teaching_focus || [],
  };
}

export function lessonDelivery(run: LessonRun): LessonDelivery {
  if (run.result.delivery) return run.result.delivery;
  const artifact = run.result.lesson_draft || run.result.artifact;
  const missing: string[] = [];
  if (!artifact?.lesson_blocks?.length) missing.push('未提供分段课时安排');
  if (!artifact?.classroom_questions?.length && (run.result.request?.question_count ?? 3) > 0) missing.push('未提供课堂问题');
  if ((run.result.textbook_ids?.length || 0) > 1 && !artifact?.textbook_differences?.length) missing.push('未提供有依据的教材比较');
  return {
    status: artifact?.generation_method === 'evidence_fallback' && !artifact?.teacher_edited ? 'evidence_only' : 'needs_work',
    missing_items: missing.length ? missing : ['旧任务尚未按本次目标逐项检查，请教师核对'],
    checks: [],
  };
}
