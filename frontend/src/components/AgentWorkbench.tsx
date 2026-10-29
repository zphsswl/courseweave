import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, InputNumber, Modal, Select, Spin, message } from 'antd';
import { BookOutlined, CheckOutlined, CopyOutlined, DownOutlined, EditOutlined, ExportOutlined, FileSearchOutlined, PlusOutlined, PrinterOutlined, ReloadOutlined, SaveOutlined, SendOutlined, StopOutlined } from '@ant-design/icons';
import type { AgentArtifactRow, AgentCitation, ModelStatus, Textbook } from '../types';
import { cancelLessonRun, createLessonRun, exportLessonMarkdown, exportLessonPrint, getLessonRun, getLessonRuns, lessonDelivery, lessonExecution, normalizedArtifact, parseLessonTimestamp, respondLessonRun, resumeLessonRun, retryLessonRun, saveLessonDraft } from '../api/lessonAgent';
import type { AgentLessonContext, LessonArtifact, LessonBlock, LessonRequest, LessonRun } from '../api/lessonAgent';
import SourcePageViewer from './SourcePageViewer';
import './AgentWorkbench.css';

interface Props {
  courseId: string; courseTitle: string; textbooks: Textbook[];
  modelStatus: ModelStatus | null; onGoLibrary: () => void; readOnly?: boolean;
  context?: AgentLessonContext; onOpenLesson?: (runId: string) => void; initialRunId?: string;
  onSelectedRunChange?: (id: string) => void;
  onCollectedEvidenceConsumed?: (intentId: string, owned: AgentLessonContext) => void;
}
interface Brief {
  topic: string; goal: string; bookIds: string[]; requirements: string[];
  duration: number; questions: number; focusTerms: string[];
  audience: string; priorKnowledge: string;
}
interface StoredBrief {
  value: Brief; dirty: boolean; appliedIntentId?: string;
  originContext?: AgentLessonContext; contextDetached?: boolean;
  collectionNotice?: string;
}
interface BriefState extends StoredBrief { courseId: string }
interface Editor { runId: string; artifact: LessonArtifact; revision: number; dirty: boolean }
type RowKey = 'lesson_blocks' | 'knowledge_sequence' | 'common_ground' | 'textbook_differences' | 'misconceptions' | 'teaching_focus';
type EditableRow = AgentArtifactRow & Partial<LessonBlock>;
type StringKey = 'teaching_objectives' | 'classroom_questions' | 'unresolved_questions';
const OPTIONS = ['核心概念', '教材差异', '重点难点', '易混淆点', '课堂提问'];
const ACTIVE = new Set(['pending', 'processing']);
const labels: Record<string, string> = { pending: '任务排队中', processing: '正在执行备课任务', waiting_user: '等待教师处理', completed: '本次处理已结束', failed: '本次处理失败', cancelled: '本次执行已停止' };
const briefKey = (course: string) => `courseweave:lesson-brief:${course}`;
const draftKey = (course: string, run: string) => `courseweave:lesson-edit:${course}:${run}`;
const readLocal = <T,>(key: string): T | null => { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } };
const writeLocal = (key: string, value: unknown) => { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } };
const removeLocal = (key: string) => { try { localStorage.removeItem(key); } catch { /* Storage is optional. */ } };
const errorText = (error: any, fallback: string) => typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : fallback;
const cancelled = (error: any) => error?.code === 'ERR_CANCELED' || error?.name === 'AbortError';
const clone = (artifact: LessonArtifact) => normalizedArtifact(JSON.parse(JSON.stringify(artifact)));
const serverArtifact = (run: LessonRun | null) => run?.result?.lesson_draft || run?.result?.artifact || null;
const runTitle = (run: LessonRun) => serverArtifact(run)?.title || run.result.topic || '未命名教案';
const initialBrief = (books: Textbook[], context?: AgentLessonContext): Brief => ({
  topic: context?.topic || '', goal: '', bookIds: context?.textbookIds?.length ? context.textbookIds : books.slice(0, 2).map((book) => book.id),
  requirements: ['核心概念', '教材差异', '重点难点'], duration: 45, questions: 3, focusTerms: context?.focusTerms || [], audience: '', priorKnowledge: '',
});
const sameScope = (first: string[], second: string[]) => JSON.stringify([...new Set(first)].sort()) === JSON.stringify([...new Set(second)].sort());
const matchesContext = (brief: Brief, origin?: AgentLessonContext) => Boolean(origin && brief.topic.trim() === (origin.topic || '').trim() && sameScope(brief.bookIds, origin.textbookIds || []) && (!origin.sourceBookId || brief.bookIds.includes(origin.sourceBookId)));
const freshBrief = (courseId: string, books: Textbook[], context?: AgentLessonContext): BriefState => {
  const value = initialBrief(books, context);
  return { courseId, value, dirty: false, appliedIntentId: context?.intentId, originContext: context ? { ...context, textbookIds: [...value.bookIds] } : undefined };
};
type CollectedEvidence = { chunkId: string; textbookId: string; courseId?: string };
const collectionQueue = (context?: AgentLessonContext): CollectedEvidence[] => {
  const value = context?.collectedEvidence;
  return value ? Array.isArray(value) ? value : [value] : [];
};
const evidenceKey = (delta: CollectedEvidence, courseId: string) => `${delta.courseId || courseId}:${delta.textbookId}:${delta.chunkId}`;
const mergeCollectedEvidence = (state: BriefState, books: Textbook[], context: AgentLessonContext): BriefState => {
  if (!context.collectedEvidence || !context.intentId || state.appliedIntentId === context.intentId) return state;
  const deltas = [...new Map(collectionQueue(context).map((delta) => [evidenceKey(delta, state.courseId), delta])).values()];
  if (!deltas.length) return { ...state, appliedIntentId: context.intentId, collectionNotice: undefined };
  const rejected = (collectionNotice: string): BriefState => ({ ...state, appliedIntentId: context.intentId, collectionNotice });
  if (deltas.some((delta) => (delta.courseId && delta.courseId !== state.courseId) || (books.length && !books.some((book) => book.id === delta.textbookId)) || (!delta.courseId && !books.some((book) => book.id === delta.textbookId)))) return rejected('补充材料含其他课程的来源，本批材料未加入本次备课条件。');
  if (deltas.some((delta) => !delta.chunkId?.trim() || !delta.textbookId?.trim())) return rejected('补充原文的来源信息不完整，本批材料未加入本次备课条件。');
  const bookIds = [...new Set([...state.value.bookIds, ...deltas.map((delta) => delta.textbookId)])];
  if (bookIds.length > 12) return rejected('加入本批材料会超过 12 本教材上限，本批材料尚未加入。');
  // The brief owns its context. The parent's topic/board may describe an older reading task.
  const { collectedEvidence: _ignored, ...owned } = state.originContext || {};
  const selected = owned.selectedChunkIds || [];
  const supplemental = owned.supplementalChunkIds || [];
  const sourceIds = new Set([...selected, ...supplemental]);
  const additions = [...new Set(deltas.map((delta) => delta.chunkId))].filter((id) => !sourceIds.has(id));
  if (sourceIds.size + additions.length > 48) return rejected('加入本批材料会超过 48 段原文上限，本批材料尚未加入。');
  const originContext: AgentLessonContext = { ...owned, topic: state.value.topic, textbookIds: bookIds, focusTerms: [...state.value.focusTerms] };
  if (additions.length) {
    if (owned.boardId) originContext.supplementalChunkIds = [...supplemental, ...additions];
    else originContext.selectedChunkIds = [...selected, ...additions];
  }
  return { ...state, value: { ...state.value, bookIds }, originContext, dirty: true, contextDetached: false, collectionNotice: undefined, appliedIntentId: context.intentId };
};
const ownedLessonContext = (state: BriefState): AgentLessonContext => {
  const { collectedEvidence: _ignored, ...owned } = state.originContext || {};
  return { ...owned, topic: state.value.topic, textbookIds: [...state.value.bookIds], focusTerms: [...state.value.focusTerms] };
};
const conditionsFromRun = (run: LessonRun, courseId: string, appliedIntentId?: string): BriefState => {
  const request = { ...run.payload, ...run.result.request };
  const value: Brief = {
    topic: request.topic || run.result.topic || '', goal: request.goal || run.result.goal || '',
    audience: request.audience || '', priorKnowledge: request.prior_knowledge || '',
    bookIds: request.textbook_ids?.length ? [...request.textbook_ids] : [...run.result.textbook_ids],
    requirements: [...(request.requirements || run.result.requirements || [])], duration: request.duration_minutes || 45,
    questions: request.question_count ?? 3, focusTerms: [...(request.focus_terms || [])],
  };
  const originContext: AgentLessonContext | undefined = request.context ? {
    topic: value.topic, textbookIds: [...value.bookIds], focusTerms: [...value.focusTerms],
    sourceBookId: request.context.source_book_id, sectionId: request.context.section_id,
    boardId: request.context.board_id, selectedChunkIds: request.context.selected_chunk_ids,
    supplementalChunkIds: request.context.supplemental_chunk_ids,
  } : undefined;
  return { courseId, value, dirty: true, appliedIntentId, originContext };
};
const citationPresentation = (source: AgentCitation, books: Textbook[]) => {
  const book = books.find((item) => item.id === source.textbook_id);
  const pdf = book?.format === 'pdf';
  return {
    location: pdf ? source.page_start ? `PDF ${source.page_start}${source.page_end > source.page_start ? `–${source.page_end}` : ''} 页` : 'PDF 页码待核对'
      : `原文位置 · ${source.section_path?.join(' / ') || source.chapter || '教材摘录'}`,
    page: pdf && source.page_start > 0 ? { bookId: source.textbook_id, title: source.textbook, page: source.page_start, total: book.total_pages || source.page_end } : null,
  };
};
const collectionOwner = (state: BriefState, selectedRunId: string | null, run: LessonRun | null): BriefState | null => {
  if (!selectedRunId) return state;
  if (!run || run.id !== selectedRunId || run.course_id !== state.courseId) return null;
  return conditionsFromRun(run, state.courseId, state.appliedIntentId);
};
const restoreBrief = (courseId: string, books: Textbook[], context?: AgentLessonContext, initialRunId?: string): BriefState => {
  const cached = readLocal<StoredBrief | Brief>(briefKey(courseId));
  const stored = cached && 'value' in cached ? cached : cached ? { value: cached, dirty: true } as StoredBrief : null;
  // Returning from a lesson preview must load that lesson before assigning new sources.
  // The cached brief belongs to a separate preparation and remains available for backup.
  if (context?.collectedEvidence && initialRunId) return stored
    ? { ...stored, value: { ...initialBrief(books), ...stored.value }, courseId }
    : freshBrief(courseId, books);
  if (context?.collectedEvidence) {
    const queued = collectionQueue(context);
    const sameCourse = queued.length > 0 && queued.every((delta) => delta.courseId ? delta.courseId === courseId && (!books.length || books.some((book) => book.id === delta.textbookId)) : books.some((book) => book.id === delta.textbookId));
    // A first collection can seed its question, but must never inherit a parent's stale board.
    const current = stored ? { ...stored, value: { ...initialBrief(books), ...stored.value }, courseId }
      : freshBrief(courseId, books, sameCourse ? { topic: context.topic, textbookIds: [...new Set(queued.map((delta) => delta.textbookId))] } : undefined);
    return mergeCollectedEvidence(current, books, context);
  }
  if (context?.intentId && context.intentId !== stored?.appliedIntentId) {
    if (stored) writeLocal(`${briefKey(courseId)}:backup`, stored);
    return freshBrief(courseId, books, context);
  }
  return stored ? { ...stored, value: { ...initialBrief(books), ...stored.value }, courseId } : freshBrief(courseId, books, context);
};
const timeLabel = (value?: string) => {
  const date = parseLessonTimestamp(value);
  return date ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date) : '';
};

const LegacyExecutionTrace: React.FC<{ steps: ReturnType<typeof lessonExecution>['legacyPlan']; title: string; hint: string; active?: boolean }> = ({ steps, title, hint, active }) => <details className="la-trace" open={active}><summary>{title} <small>{steps.filter((step) => ['completed', 'skipped'].includes(step.status)).length} / {steps.length} 步</small></summary><p className="la-evidence-note">{hint}</p><ol>{steps.map((step, index) => <li key={`${step.id}:${index}`} className={step.status}><strong>{step.title}</strong><span>{step.summary}</span><small>{step.statusLabel}</small></li>)}</ol></details>;

const AgentExecutionPanel: React.FC<{ run: LessonRun; execution: ReturnType<typeof lessonExecution>; busy: string; readOnly: boolean; onCancel: () => void }> = ({ run, execution, busy, readOnly, onCancel }) => <section className={`la-execution la-execution-${execution.mode}`} aria-label="Agent 执行记录">
  <header><div><span className="la-execution-mode">{execution.modeLabel}</span><p>{execution.modeDescription}</p></div>{execution.canCancel && !readOnly && <Button icon={<StopOutlined />} loading={busy === 'cancel'} disabled={Boolean(busy)} onClick={onCancel}>停止本次执行</Button>}</header>
  {(execution.budget.length > 0 || execution.elapsed !== null) && <dl className="la-budget" aria-label="本次执行预算">
    {execution.budget.map((item) => <div key={item.id} className={item.max !== null && item.used !== null && item.used >= item.max ? 'at-limit' : ''}><dt>{item.label}</dt><dd>{item.used ?? '—'} <span>/ {item.max ?? '未提供'}</span></dd></div>)}
    {execution.elapsed !== null && <div><dt>已运行</dt><dd>{Math.floor(execution.elapsed)} <span>{execution.runtimeLimit !== null ? `/ ${execution.runtimeLimit} 秒` : '秒'}</span></dd></div>}
  </dl>}
  {execution.stopReason && <p className="la-stop-reason" role="status"><strong>{run.status === 'waiting_user' ? '暂停说明' : ACTIVE.has(run.status) ? '执行说明' : '结束说明'}</strong>{execution.stopReason}</p>}
  {execution.mode === 'evidence_workflow' && !execution.trajectory.length ? <LegacyExecutionTrace steps={execution.legacyPlan} title="证据工作流记录" hint="本次使用固定证据整理流程。以下步骤不代表模型自主选择的动作。" active={ACTIVE.has(run.status) || run.status === 'waiting_user'} /> : <details className="la-trace la-loop-trace" open={ACTIVE.has(run.status) || run.status === 'waiting_user'}><summary>实际动作记录 <small>{execution.trajectory.length} 条记录</small></summary>
    {execution.trajectory.length ? <ol>{execution.trajectory.map((entry, index) => <li key={`${entry.id}:${index}`} className={entry.status}><span className="la-loop-number">{entry.step !== null ? `第 ${entry.step} 步` : `记录 ${index + 1}`}</span><div className="la-loop-entry"><header><strong>{entry.title}</strong><span className="la-loop-status">{entry.statusLabel}</span></header><p>{entry.summary || '尚未提供动作摘要。'}</p>{entry.observation.length > 0 && <p className="la-loop-observation"><b>调用结果</b>{entry.observation.join('；')}</p>}{entry.error && <p className="la-loop-error">{entry.error}</p>}{(entry.startedAt || entry.finishedAt) && <time>{timeLabel(entry.startedAt)}{entry.finishedAt ? ` → ${timeLabel(entry.finishedAt)}` : entry.status === 'running' ? ' · 执行中' : ''}</time>}</div></li>)}</ol> : <p className="la-loop-empty">服务端尚未返回实际动作记录。等待与刷新不会补造步骤。</p>}
  </details>}
  {execution.teacherAnswers.length > 0 && <details className="la-teacher-answers"><summary>教师已补充的条件 · {execution.teacherAnswers.length} 次</summary>{execution.teacherAnswers.map((item, index) => <article key={index}><strong>{item.question || '教师补充条件'}</strong><p>{item.answer || '未提供回答内容'}</p>{item.answeredAt && <small>{timeLabel(item.answeredAt)}</small>}</article>)}</details>}
</section>;

const AgentWorkbench: React.FC<Props> = ({ courseId, courseTitle, textbooks, modelStatus, onGoLibrary, readOnly = false, context, onOpenLesson, initialRunId, onSelectedRunChange, onCollectedEvidenceConsumed }) => {
  const availableBooks = textbooks.filter((book) => !book.course_id || book.course_id === courseId);
  const [briefState, setBriefState] = useState<BriefState>(() => restoreBrief(courseId, availableBooks, context, initialRunId));
  const brief = briefState.value;
  const [runs, setRuns] = useState<LessonRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadedRun, setRun] = useState<LessonRun | null>(null);
  const run = loadedRun?.course_id === courseId ? loadedRun : null;
  const [historyLoading, setHistoryLoading] = useState(true);
  const [runLoading, setRunLoading] = useState(false);
  const [pollError, setPollError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState<'create' | 'save' | 'retry' | 'resume' | 'respond' | 'cancel' | 'export' | ''>('');
  const [answerDraft, setAnswerDraft] = useState<{ key: string; value: string } | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [editing, setEditing] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [sourcePair, setSourcePair] = useState<string[]>([]);
  const [sourcePage, setSourcePage] = useState<{ bookId: string; title: string; page: number; total: number } | null>(null);
  const [briefBackupAvailable, setBriefBackupAvailable] = useState(() => Boolean(readLocal(`${briefKey(courseId)}:backup`)));
  const [coverageOpen, setCoverageOpen] = useState(false);
  const courseRef = useRef(courseId);
  const selectedRef = useRef<string | null>(null);
  const epochRef = useRef(0);
  const mutationRef = useRef<AbortController | null>(null);
  const stopReadRef = useRef<(() => void) | null>(null);
  const lastContext = useRef(JSON.stringify(context || {}));
  const mounted = useRef(true);
  const consumedCollections = useRef(new Set<string>());
  courseRef.current = courseId;
  const contextSignature = JSON.stringify(context || {});

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; epochRef.current += 1; mutationRef.current?.abort(); stopReadRef.current?.(); }; }, []);
  const chooseRun = (id: string | null) => {
    if (editor?.dirty && editor.runId === run?.id) {
      const retained = writeLocal(draftKey(courseId, editor.runId), editor) && writeLocal(`${draftKey(courseId, editor.runId)}:backup`, editor);
      if (!retained) { message.warning('浏览器无法保留修改，请先保存当前教案后再切换。'); return false; }
    }
    epochRef.current += 1; mutationRef.current?.abort(); mutationRef.current = null; stopReadRef.current?.();
    selectedRef.current = id; setSelectedId(id); setRun(id ? runs.find((item) => item.id === id && item.course_id === courseId) || null : null);
    setEditor(null); setEditing(false); setBusy(''); setAnswerDraft(null); setPollError(''); setEvidenceOpen(false); setSourcePage(null); setCoverageOpen(false);
    onSelectedRunChange?.(id || ''); return true;
  };
  const consumeCollection = (intentId: string, owner: BriefState) => {
    if (!onCollectedEvidenceConsumed || consumedCollections.current.has(intentId)) return;
    consumedCollections.current.add(intentId);
    onCollectedEvidenceConsumed(intentId, ownedLessonContext(owner));
  };
  useEffect(() => {
    const controller = new AbortController(); let live = true;
    epochRef.current += 1; mutationRef.current?.abort(); mutationRef.current = null; stopReadRef.current?.();
    selectedRef.current = null; setSelectedId(null); setRun(null); setEditor(null); setEditing(false); setBusy(''); setAnswerDraft(null);
    setRuns([]); setHistoryLoading(true); setPollError(''); setEvidenceOpen(false); setSourcePage(null);
    setBriefState(restoreBrief(courseId, availableBooks, context, initialRunId));
    setBriefBackupAvailable(Boolean(readLocal(`${briefKey(courseId)}:backup`)));
    lastContext.current = contextSignature;
    getLessonRuns(courseId, controller.signal).then(({ data }) => {
      if (!live || courseRef.current !== courseId) return;
      const ownRuns = data.filter((item) => item.course_id === courseId);
      setRuns(ownRuns);
      if (readOnly && !selectedRef.current && ownRuns[0]) { selectedRef.current = ownRuns[0].id; setSelectedId(ownRuns[0].id); setRun(ownRuns[0]); onSelectedRunChange?.(ownRuns[0].id); }
    }).catch((error) => { if (live && !cancelled(error)) message.error('历史任务加载失败，可刷新页面后重试'); })
      .finally(() => { if (live) setHistoryLoading(false); });
    return () => { live = false; controller.abort(); };
    // Course changes reset the view; historical tasks never overwrite a new brief.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);
  useEffect(() => {
    if (initialRunId && initialRunId !== selectedRef.current) chooseRun(initialRunId);
    // Only an explicit classroom return changes this selection; history refreshes do not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, initialRunId]);
  useEffect(() => { if (briefState.courseId === courseId) writeLocal(briefKey(courseId), briefState); }, [courseId, briefState]);
  useEffect(() => {
    if (briefState.courseId !== courseId) return;
    if (context?.intentId && context.intentId !== briefState.appliedIntentId) {
      if (busy) return;
      if (context.collectedEvidence) {
        // chooseRun updates the ref before React commits selectedId, including cold returns.
        const selectedRunId = selectedRef.current;
        const base = collectionOwner(briefState, selectedRunId, run);
        if (!base) return;
        const next = mergeCollectedEvidence(base, availableBooks, context);
        if (next.collectionNotice) { setBriefState({ ...briefState, appliedIntentId: context.intentId, collectionNotice: next.collectionNotice }); consumeCollection(context.intentId, base); lastContext.current = contextSignature; return; }
        if (selectedRunId && !retainBrief()) return;
        // Switching first preserves an unsaved historical editor; failure leaves the old run open.
        if (!chooseRun(null)) return;
        setBriefState(next); consumeCollection(context.intentId, next);
      } else {
        if (!chooseRun(null)) return;
        writeLocal(`${briefKey(courseId)}:backup`, briefState);
        setBriefState(freshBrief(courseId, availableBooks, context));
      }
      lastContext.current = contextSignature; return;
    }
    if (context?.intentId && context.intentId === briefState.appliedIntentId) { lastContext.current = contextSignature; return; }
    if (context?.collectedEvidence) return;
    if (briefState.dirty) return;
    if (contextSignature !== lastContext.current || (!brief.bookIds.length && availableBooks.length)) {
      setBriefState(freshBrief(courseId, availableBooks, context)); lastContext.current = contextSignature;
    }
    // An untouched brief may inherit new context; teacher edits take precedence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contextSignature, courseId, textbooks, busy, editor?.dirty, run?.id]);
  useEffect(() => {
    if (!selectedRef.current && briefState.courseId === courseId && context?.collectedEvidence && context.intentId && briefState.appliedIntentId === context.intentId) consumeCollection(context.intentId, briefState);
    // A cold restore may already have applied the batch before the mounted intent effect runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, contextSignature, briefState, onCollectedEvidenceConsumed]);
  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController(); let live = true; let timer: number | undefined;
    const stop = () => { live = false; controller.abort(); if (timer) window.clearTimeout(timer); };
    stopReadRef.current = stop;
    setRunLoading(true); setPollError('');
    const pull = async () => {
      try {
        const { data } = await getLessonRun(selectedId, controller.signal);
        if (!live || selectedRef.current !== selectedId || courseRef.current !== courseId) return;
        if (data.course_id !== courseId || data.id !== selectedId) { setRun(null); setEditor(null); setRunLoading(false); setPollError('该任务不属于当前课程，无法查看或修改。请从本课程历史任务重新选择。'); return; }
        setRun(data); setRuns((items) => [data, ...items.filter((item) => item.id !== data.id)]); setRunLoading(false);
        if (ACTIVE.has(data.status)) timer = window.setTimeout(pull, 1800);
      } catch (error) { if (live && !cancelled(error)) { setPollError('暂时无法更新任务状态。刷新只读取状态，不会重复执行任务。'); setRunLoading(false); } }
    };
    pull();
    return () => { stop(); if (stopReadRef.current === stop) stopReadRef.current = null; };
  }, [courseId, selectedId, refresh]);
  useEffect(() => {
    const base = serverArtifact(run); if (!run || !base) return;
    setEditor((current) => {
      if (current?.runId === run.id && current.dirty) return current;
      const local = readLocal<Editor>(draftKey(courseId, run.id));
      if (local?.dirty && local.artifact && local.runId === run.id) return { ...local, artifact: normalizedArtifact({ ...local.artifact, citations: base.citations, generation_method: base.generation_method, generated_at: base.generated_at }) };
      return { runId: run.id, artifact: clone(base), revision: run.result.draft_revision || 0, dirty: false };
    });
  }, [courseId, run?.id, run?.result?.draft_revision, run?.result?.artifact?.generated_at, run?.result?.lesson_draft?.generated_at]);

  const changeBrief = (patch: Partial<Brief>) => setBriefState((state) => {
    const value = { ...state.value, ...patch };
    const detach = Boolean(state.originContext && !matchesContext(value, state.originContext));
    return { ...state, courseId, value, dirty: true, originContext: detach ? undefined : state.originContext, contextDetached: state.contextDetached || detach };
  });
  const retainBrief = () => {
    if (!briefState.dirty && !brief.topic.trim()) return true;
    const kept = writeLocal(`${briefKey(courseId)}:backup`, briefState);
    if (kept) setBriefBackupAvailable(true);
    else message.warning('浏览器无法保留当前备课条件，请先复制记录后再新建。');
    return kept;
  };
  const newLesson = () => {
    if (readOnly || busy || !retainBrief() || !chooseRun(null)) return;
    setBriefState({ ...freshBrief(courseId, availableBooks), dirty: true, appliedIntentId: context?.intentId });
    lastContext.current = contextSignature;
  };
  const copyLessonConditions = () => {
    if (!run || readOnly || busy || !retainBrief()) return;
    if (!chooseRun(null)) return;
    setBriefState(conditionsFromRun(run, courseId, context?.intentId));
    lastContext.current = contextSignature; setCoverageOpen(false);
    window.scrollTo(0, 0); message.info('已复用本课条件。可调整后手动生成，原教案与未保存修改仍保留。');
  };
  const restoreBriefBackup = () => {
    const backup = readLocal<StoredBrief | Brief>(`${briefKey(courseId)}:backup`);
    if (!backup || busy) return;
    const stored = 'value' in backup ? backup : { value: backup, dirty: true };
    if (!retainBrief()) return;
    setBriefState({ ...stored, courseId, value: { ...initialBrief(availableBooks), ...stored.value }, dirty: true, appliedIntentId: context?.intentId });
    lastContext.current = contextSignature;
  };
  const scopeIds = brief.bookIds.filter((id) => availableBooks.some((book) => book.id === id));
  const taskActive = Boolean(run && ACTIVE.has(run.status));
  const execution = run ? lessonExecution(run) : null;
  const answerKey = run && execution?.approval.requestId ? `courseweave:lesson-answer:${courseId}:${run.id}:${execution.approval.requestId}` : '';
  const cachedAnswer = answerKey ? readLocal<unknown>(answerKey) : null;
  const teacherAnswer = answerDraft?.key === answerKey ? answerDraft.value : typeof cachedAnswer === 'string' ? cachedAnswer.slice(0, 2000) : '';
  const changeTeacherAnswer = (value: string) => { if (!answerKey) return; const next = value.slice(0, 2000); setAnswerDraft({ key: answerKey, value: next }); writeLocal(answerKey, next); };
  const activeCourseRun = runs.find((item) => ACTIVE.has(item.status));
  const artifact = run && editor?.runId === run.id ? editor.artifact : serverArtifact(run);
  const delivery = run ? lessonDelivery(run) : null;
  const dirty = Boolean(editor?.dirty && editor.runId === run?.id);
  const requestedMinutes = run?.result.request?.duration_minutes || run?.payload?.duration_minutes || 45;
  const requestedQuestions = run?.result.request?.question_count ?? run?.payload?.question_count ?? 3;
  const requestedBookIds = run?.result.textbook_ids || [];
  const usedSourceIds = new Set((['lesson_blocks', 'knowledge_sequence', 'common_ground', 'textbook_differences', 'misconceptions', 'teaching_focus'] as RowKey[]).flatMap((key) => (serverArtifact(run)?.[key] || []).flatMap((row) => row.source_ids || [])));
  const coveredBookIds = new Set(run?.result.quality?.covered_textbook_ids || (serverArtifact(run)?.citations || []).filter((source) => usedSourceIds.has(source.source_id)).map((source) => source.textbook_id));
  const missingBookIds = requestedBookIds.filter((id) => !coveredBookIds.has(id));
  const citationMap = useMemo(() => new Map((artifact?.citations || []).map((item) => [item.source_id, item])), [artifact]);
  const citationOptions = (artifact?.citations || []).map((item) => ({ value: item.source_id, label: `${item.source_id} · ${item.textbook} · P.${item.page_start}` }));
  const remoteRevision = run?.result.draft_revision || 0;
  const conflict = Boolean(dirty && editor && editor.revision !== remoteRevision);
  const updateArtifact = (transform: (current: LessonArtifact) => LessonArtifact) => setEditor((current) => {
    if (!current || current.runId !== run?.id) return current;
    const next = { ...current, artifact: transform(current.artifact), dirty: true }; writeLocal(draftKey(courseId, current.runId), next); return next;
  });
  const beginMutation = (type: typeof busy) => {
    if (mutationRef.current) return null;
    if (type !== 'export') { stopReadRef.current?.(); setRunLoading(false); }
    const controller = new AbortController(); mutationRef.current = controller; setBusy(type); const epoch = epochRef.current;
    return { controller, type, valid: () => mounted.current && courseRef.current === courseId && epochRef.current === epoch && !controller.signal.aborted };
  };
  const finishMutation = (operation: NonNullable<ReturnType<typeof beginMutation>>) => {
    if (mutationRef.current === operation.controller) { mutationRef.current = null; if (mounted.current) { setBusy(''); if (operation.valid() && ['save', 'retry', 'resume', 'respond', 'cancel'].includes(operation.type)) setRefresh((value) => value + 1); } }
  };
  const acceptRun = (next: LessonRun, expectedId?: string) => {
    if (next.course_id !== courseId || (expectedId && next.id !== expectedId)) { message.error('任务响应与当前课程不一致，已停止展示与修改'); return false; }
    setRun(next); setRuns((items) => [next, ...items.filter((item) => item.id !== next.id)]); return true;
  };
  const startRun = async () => {
    if (readOnly || activeCourseRun) return;
    if (brief.topic.trim().length < 2) return message.warning('请填写至少两个字的备课主题');
    if (!scopeIds.length) return message.warning('请至少选择一本教材');
    if (scopeIds.length > 12) return message.warning('一次最多选择 12 本教材');
    if (brief.focusTerms.length > 12 || brief.focusTerms.some((term) => term.trim().length < 2 || term.length > 80)) return message.warning('比较切面最多 12 项，每项 2–80 个字');
    const operation = beginMutation('create'); if (!operation) return;
    const origin = matchesContext(brief, briefState.originContext) && sameScope(scopeIds, brief.bookIds) ? briefState.originContext : undefined;
    const request: LessonRequest = {
      course_id: courseId, topic: brief.topic.trim(), goal: brief.goal.trim() || `围绕“${brief.topic.trim()}”组织 ${brief.duration} 分钟课堂，准备 ${brief.questions} 个问题`,
      audience: brief.audience.trim(), prior_knowledge: brief.priorKnowledge.trim(),
      textbook_ids: scopeIds, requirements: brief.requirements, duration_minutes: brief.duration, question_count: brief.questions, focus_terms: brief.focusTerms.map((term) => term.trim()),
      context: origin ? { source_book_id: origin.sourceBookId, section_id: origin.sectionId, board_id: origin.boardId, selected_chunk_ids: origin.selectedChunkIds, supplemental_chunk_ids: origin.supplementalChunkIds } : undefined,
    };
    try {
      const { data } = await createLessonRun(request, operation.controller.signal); if (!operation.valid()) return;
      if (!acceptRun(data)) return;
      selectedRef.current = data.id; setSelectedId(data.id); onSelectedRunChange?.(data.id); setEditing(false); message.success('任务已创建，可继续查看处理状态');
    } catch (error) { if (operation.valid() && !cancelled(error)) message.error(errorText(error, '创建失败，请查看历史确认是否已创建后再操作')); }
    finally { finishMutation(operation); }
  };
  const continueRun = async (action: 'resume' | 'retry') => {
    if (!run || readOnly || (action === 'resume' && !execution?.canResume)) return; const operation = beginMutation(action); if (!operation) return;
    try { const { data } = await (action === 'resume' ? resumeLessonRun : retryLessonRun)(run.id, operation.controller.signal); if (operation.valid()) acceptRun(data, run.id); }
    catch (error) { if (operation.valid() && !cancelled(error)) message.error(errorText(error, '操作失败，请检查任务状态后重试')); }
    finally { finishMutation(operation); }
  };
  const respondToTeacherQuestion = async () => {
    if (!run || readOnly || !execution?.canRespond) return;
    const answer = teacherAnswer.trim(); if (!answer) return message.warning('请先填写你的教学选择或补充条件');
    const operation = beginMutation('respond'); if (!operation) return;
    try {
      const { data } = await respondLessonRun(run.id, answer, execution.approval.requestId, operation.controller.signal);
      if (!operation.valid() || !acceptRun(data, run.id)) return;
      removeLocal(answerKey); setAnswerDraft({ key: answerKey, value: '' }); message.success('回答已提交，继续执行本次任务');
    } catch (error: any) { if (operation.valid() && !cancelled(error)) message.error(error.response?.status === 409 ? '这个问题已更新或已处理。回答仍保留，请刷新任务后核对当前问题。' : errorText(error, '回答提交失败，输入仍保留，请刷新状态后重试')); }
    finally { finishMutation(operation); }
  };
  const cancelRun = async () => {
    if (!run || readOnly || !execution?.canCancel) return;
    const operation = beginMutation('cancel'); if (!operation) return;
    try { const { data } = await cancelLessonRun(run.id, operation.controller.signal); if (operation.valid() && acceptRun(data, run.id)) message.info(data.status === 'cancelled' ? '本次执行已停止，已有材料继续保留' : '任务状态已更新，请以最新执行状态为准'); }
    catch (error) { if (operation.valid() && !cancelled(error)) message.error(errorText(error, '停止请求未确认，请刷新状态后重试')); }
    finally { finishMutation(operation); }
  };
  const validateDraft = (draft: LessonArtifact): string | null => {
    if (!draft.title.trim()) return '请填写教案标题';
    const allowed = new Set((serverArtifact(run)?.citations || []).map((source) => source.source_id));
    const fields: Record<RowKey, string[]> = { lesson_blocks: ['title', 'content'], knowledge_sequence: ['title', 'explanation'], common_ground: ['claim'], textbook_differences: ['textbook', 'perspective'], misconceptions: ['issue', 'guidance'], teaching_focus: ['title', 'explanation'] };
    for (const key of Object.keys(fields) as RowKey[]) for (const [index, row] of ((draft[key] || []) as EditableRow[]).entries()) {
      if (fields[key].some((field) => !String((row as unknown as Record<string, unknown>)[field] || '').trim())) return `有一行内容尚未填写完整，请补全或删除（第 ${index + 1} 行）`;
      if (!row.source_ids?.length || row.source_ids.some((id) => !allowed.has(id))) return `第 ${index + 1} 行需要选择至少一条现有教材引用`;
      if (key === 'lesson_blocks' && (!row.minutes || row.minutes < 1 || row.minutes > 240)) return '每个课堂环节需要 1–240 分钟';
      if (key === 'textbook_differences' && row.source_ids.some((id) => citationMap.get(id)?.textbook !== row.textbook)) return '教材侧重点的引用必须来自该行所选教材';
    }
    return null;
  };
  const saveDraft = async () => {
    if (!run || !editor || !dirty || readOnly || taskActive) return;
    const problem = validateDraft(editor.artifact); if (problem) return message.warning(problem);
    const operation = beginMutation('save'); if (!operation) return;
    const submitted = clone(editor.artifact); submitted.citations = serverArtifact(run)?.citations || [];
    try {
      const { data } = await saveLessonDraft(run.id, editor.revision, submitted, operation.controller.signal); if (!operation.valid()) return;
      if (!acceptRun(data, run.id)) return;
      removeLocal(draftKey(courseId, run.id));
      setEditor({ runId: run.id, artifact: clone(serverArtifact(data) || submitted), revision: data.result.draft_revision || 0, dirty: false }); setEditing(false); message.success('教案修改已保存，来源引用一并保留');
    } catch (error: any) {
      if (operation.valid() && !cancelled(error)) message.error(error.response?.status === 409 ? '已有更新版本。你的修改仍保留在浏览器，请刷新任务后核对版本。' : errorText(error, '保存失败，你的修改仍保留在浏览器'));
    } finally { finishMutation(operation); }
  };
  const exportDraft = async () => {
    if (!run) return; if (dirty) return message.info('请先保存当前修改，再导出或预览教案');
    const operation = beginMutation('export'); if (!operation) return;
    try {
      const { data } = await exportLessonMarkdown(run.id, operation.controller.signal); if (!operation.valid()) return;
      const url = URL.createObjectURL(new Blob([data], { type: 'text/markdown;charset=utf-8' })); const link = document.createElement('a'); link.href = url;
      link.download = `${(artifact?.title || '备课材料').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '').slice(0, 90)}.md`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (operation.valid() && !cancelled(error)) message.error(errorText(error, '导出失败，请稍后再试')); }
    finally { finishMutation(operation); }
  };
  const printDraft = async () => {
    if (!run || busy) return;
    if (dirty) return message.info('请先保存当前修改，再打开打印版');
    // Reserve the tab during the user gesture so asynchronous retrieval is not blocked as a popup.
    const preview = window.open('', '_blank');
    if (!preview) return message.warning('打印窗口被浏览器拦截，请允许此站点打开新窗口后重试。');
    preview.opener = null;
    preview.document.title = '正在准备教案打印版';
    preview.document.body.textContent = '正在准备已保存教案的打印版…';
    const operation = beginMutation('export'); if (!operation) { preview.close(); return; }
    try {
      const { data } = await exportLessonPrint(run.id, operation.controller.signal);
      if (!operation.valid()) { preview.close(); return; }
      if (preview.closed) return;
      preview.document.open(); preview.document.write(data); preview.document.close(); preview.focus();
    } catch (error) {
      preview.close();
      if (operation.valid() && !cancelled(error)) message.error(errorText(error, '打印版准备失败，请稍后再试'));
    } finally { finishMutation(operation); }
  };
  const showEvidence = (ids: string[] = []) => {
    const first = citationMap.get(ids[0]) || artifact?.citations[0];
    const second = ids.map((id) => citationMap.get(id)).find((item) => item && item.textbook_id !== first?.textbook_id) || artifact?.citations.find((item) => item.textbook_id !== first?.textbook_id);
    setSourcePair([first?.source_id || '', second?.source_id || '']); setSourcePage(null); setEvidenceOpen(true);
  };
  const sourceChips = (ids: string[] = []) => ids.length ? <div className="la-source-chips">{ids.map((id) => <button key={id} onClick={() => showEvidence([id, ...ids.filter((item) => item !== id)])}><BookOutlined /> {id} · {citationMap.get(id)?.textbook || '来源待核对'}</button>)}</div> : <span className="la-unbound">尚未绑定教材引用</span>;
  const changeRow = (key: RowKey, index: number, patch: Partial<EditableRow>) => updateArtifact((current) => ({ ...current, [key]: (current[key] || []).map((row, at) => at === index ? { ...row, ...patch } : row) }));
  const addRow = (key: RowKey) => updateArtifact((current) => ({ ...current, [key]: [...(current[key] || []), key === 'lesson_blocks' ? { title: '', content: '', minutes: 5, source_ids: [] } : { source_ids: [] }] } as LessonArtifact));
  const renderRows = (key: RowKey, title: string, fields: Array<[keyof EditableRow, string]>, gap: string, notApplicable = false) => {
    const rows = (artifact?.[key] || []) as EditableRow[];
    return <section className="la-document-section" id={`la-${key}`}>
      <header><h3>{title}</h3>{editing && !notApplicable && <Button disabled={Boolean(busy)} size="small" type="text" icon={<PlusOutlined />} onClick={() => addRow(key)}>添加一项</Button>}</header>
      {!rows.length && <p className={`la-column-gap ${notApplicable ? 'neutral' : ''}`}>{notApplicable ? '本次只有一本教材，无需跨教材比较。' : gap}</p>}
      {rows.map((row, index) => <article key={`${key}-${index}`} className={`la-content-row ${key === 'lesson_blocks' ? 'is-block' : ''}`}>
        {key === 'lesson_blocks' && <div className="la-block-index"><span>{String(index + 1).padStart(2, '0')}</span>{editing ? <label><InputNumber disabled={Boolean(busy)} min={1} max={240} value={row.minutes} onChange={(value) => changeRow(key, index, { minutes: value || 1 })} /> 分钟</label> : <small>{row.minutes || '—'} 分钟</small>}</div>}
        <div className="la-row-body">
          {fields.map(([field, label], fieldIndex) => editing ? <label className="la-edit-field" key={field}><span>{label}</span>{field === 'textbook' ? <Select disabled={Boolean(busy)} aria-label={label} value={row.textbook} options={[...new Set((artifact?.citations || []).map((source) => source.textbook))].map((book) => ({ value: book, label: book }))} onChange={(value) => changeRow(key, index, { textbook: value, source_ids: row.source_ids.filter((id) => citationMap.get(id)?.textbook === value) })} /> : <Input.TextArea disabled={Boolean(busy)} aria-label={`${title}第${index + 1}项${label}`} autoSize={{ minRows: fieldIndex ? 2 : 1, maxRows: 12 }} value={String(row[field] ?? '')} onChange={(event) => changeRow(key, index, { [field]: event.target.value })} />}</label> : fieldIndex === 0 && fields.length > 1 ? <h4 key={field}>{String(row[field] || '待补标题')}</h4> : <p key={field}>{String(row[field] || '此项尚未生成，请补充并核对原文。')}</p>)}
          {editing ? <div className="la-reference-editor"><Select disabled={Boolean(busy)} mode="multiple" aria-label={`${title}第${index + 1}项引用`} placeholder="从本任务已有原文选择引用" value={row.source_ids || []} options={key === 'textbook_differences' && row.textbook ? citationOptions.filter((option) => citationMap.get(option.value)?.textbook === row.textbook) : citationOptions} onChange={(ids) => changeRow(key, index, { source_ids: ids })} maxTagCount="responsive" /><Button disabled={Boolean(busy)} danger type="text" onClick={() => updateArtifact((current) => ({ ...current, [key]: (current[key] || []).filter((_, at) => at !== index) }))}>删除此项</Button></div> : sourceChips(row.source_ids)}
        </div>
      </article>)}
    </section>;
  };
  const renderStrings = (key: StringKey, title: string, gap: string, notApplicable = false) => {
    const rows = artifact?.[key] || [];
    return <section className="la-document-section" id={`la-${key}`}><header><h3>{title}</h3>{editing && <Button disabled={Boolean(busy)} size="small" type="text" icon={<PlusOutlined />} onClick={() => updateArtifact((current) => ({ ...current, [key]: [...current[key], ''] }))}>添加一项</Button>}</header>
      {!rows.length && <p className={`la-column-gap ${notApplicable ? 'neutral' : ''}`}>{notApplicable ? '本次未要求课堂问题。' : gap}</p>}
      <ol className="la-text-list">{rows.map((item, index) => <li key={`${key}-${index}`}>{editing ? <div className="la-string-editor"><Input.TextArea disabled={Boolean(busy)} aria-label={`${title}第${index + 1}项`} autoSize={{ minRows: 1, maxRows: 8 }} value={item} onChange={(event) => updateArtifact((current) => ({ ...current, [key]: current[key].map((value, at) => at === index ? event.target.value : value) }))} /><Button disabled={Boolean(busy)} danger type="text" onClick={() => updateArtifact((current) => ({ ...current, [key]: current[key].filter((_, at) => at !== index) }))}>删除</Button></div> : item}</li>)}</ol>
    </section>;
  };
  const renderSource = (source: AgentCitation | undefined, side: number) => {
    const presentation = source ? citationPresentation(source, textbooks) : null;
    return <article className="la-evidence-card">
    <label><span>教材 {side + 1}</span><Select aria-label={`对照教材${side + 1}引用`} value={source?.source_id} options={citationOptions} onChange={(id) => setSourcePair((pair) => pair.map((item, index) => index === side ? id : item))} placeholder="选择已有引用" /></label>
    {source ? <><h3>{source.textbook}</h3><p className="la-source-location">{source.chapter} · {presentation?.location}</p><blockquote>{source.quote}</blockquote>{presentation?.page ? <Button icon={<BookOutlined />} onClick={() => setSourcePage(presentation.page)}>打开教材原页</Button> : <p className="la-evidence-note">此来源没有可用的 PDF 原页，请核对上方原文摘录与目录位置。</p>}</> : <p className="la-column-gap neutral">当前没有另一教材的引用，可在有来源时对照。</p>}
  </article>;
  };

  return <section className="lesson-agent-page">
    <header className="la-page-heading"><div><small>{courseTitle}</small><h1>备课工作台</h1><p>从教材证据到可修改的课堂草稿。</p></div><div className="la-mode-note">{readOnly ? '在线只读示例' : modelStatus?.availability === 'available' ? '模型当前可用' : '模型状态以实际任务返回为准'}</div></header>
    <div className="la-task-switcher"><button className={!selectedId ? 'active' : ''} disabled={readOnly || Boolean(busy)} onClick={newLesson}><PlusOutlined /> 新建一堂课</button><label><span>教案历史</span><Select aria-label="查看教案历史" loading={historyLoading} disabled={Boolean(busy)} allowClear placeholder="选择已保存的教案或处理中的任务" value={selectedId || undefined} onChange={(id) => chooseRun(id || null)} options={runs.map((item) => ({ value: item.id, label: `${runTitle(item)} · ${labels[item.status] || item.status} · ${timeLabel(item.updated_at || item.created_at)}` }))} /></label></div>
    {briefState.collectionNotice && <Alert type="warning" showIcon message={briefState.collectionNotice} />}
    {!selectedId ? <>
      <section className="la-brief"><header><h2>这堂课要帮助学生学会什么</h2>{briefState.originContext?.topic && <span className="la-context-note">带入材料：{briefState.originContext.topic}{!!(briefState.originContext.selectedChunkIds?.length || briefState.originContext.supplementalChunkIds?.length) && ` · ${new Set([...(briefState.originContext.selectedChunkIds || []), ...(briefState.originContext.supplementalChunkIds || [])]).size} 段已选原文`}</span>}</header>
        {briefBackupAvailable && <div className="la-brief-backup"><span>另有一份切换前的备课条件备份。</span><Button size="small" type="text" disabled={readOnly || Boolean(busy)} onClick={restoreBriefBackup}>恢复备课条件</Button></div>}
        {contextSignature !== lastContext.current && <div className="la-context-pending">当前讲授内容已变化，保留你正在填写的任务。<button disabled={readOnly || Boolean(busy)} onClick={() => { writeLocal(`${briefKey(courseId)}:backup`, briefState); setBriefState(freshBrief(courseId, availableBooks, context)); lastContext.current = contextSignature; }}>使用当前讲授新建</button></div>}
        {briefState.contextDetached && <p className="la-context-pending">主题或教材范围已修改，原章节与跨教材材料已解除关联。本次将按当前主题和教材重新检索。</p>}
        <div className="la-brief-first"><label><span>备课主题</span><Input aria-label="备课主题" value={brief.topic} maxLength={160} placeholder="如：甲状腺的位置、形态与功能" disabled={readOnly || Boolean(busy)} onChange={(event) => changeBrief({ topic: event.target.value })} /></label><label><span>课时</span><InputNumber aria-label="课堂时长" min={1} max={240} value={brief.duration} addonAfter="分钟" disabled={readOnly || Boolean(busy)} onChange={(value) => changeBrief({ duration: value || 45 })} /></label><label><span>课堂问题</span><InputNumber aria-label="课堂问题数量" min={0} max={12} value={brief.questions} addonAfter="个" disabled={readOnly || Boolean(busy)} onChange={(value) => changeBrief({ questions: value ?? 3, requirements: value === 0 ? brief.requirements.filter((item) => item !== '课堂提问') : brief.requirements })} /></label></div>
        <div className="la-learner-context"><label><span>教学对象 <small>选填</small></span><Input aria-label="教学对象" value={brief.audience} maxLength={160} placeholder="如：护理专业一年级，首次学习本主题" disabled={readOnly || Boolean(busy)} onChange={(event) => changeBrief({ audience: event.target.value })} /></label><label><span>学生已掌握的知识 <small>选填</small></span><Input.TextArea aria-label="先修知识" value={brief.priorKnowledge} maxLength={500} autoSize={{ minRows: 1, maxRows: 3 }} placeholder="如：已了解颈部基本解剖；尚未学过内分泌调节" disabled={readOnly || Boolean(busy)} onChange={(event) => changeBrief({ priorKnowledge: event.target.value })} /></label></div>
        <div className="la-brief-second"><label><span>教学目标 <small>选填</small></span><Input.TextArea aria-label="教学目标" value={brief.goal} maxLength={500} autoSize={{ minRows: 2, maxRows: 4 }} placeholder="学生需要理解什么，或能解释什么？" disabled={readOnly || Boolean(busy)} onChange={(event) => changeBrief({ goal: event.target.value })} /></label><label><span>具体讲授切面 <small>回车添加</small></span><Select mode="tags" aria-label="具体讲授切面" value={brief.focusTerms} tokenSeparators={[',', '，', '、']} placeholder="如：位置形态、生理作用" disabled={readOnly || Boolean(busy)} onChange={(values) => changeBrief({ focusTerms: values })} /></label></div>
        <div className="la-scope-heading"><strong>教材范围 <span>{scopeIds.length} 本</span></strong><button disabled={readOnly || Boolean(busy)} onClick={() => changeBrief({ bookIds: scopeIds.length === availableBooks.length ? [] : availableBooks.slice(0, 12).map((book) => book.id) })}>{scopeIds.length === availableBooks.length && availableBooks.length ? '取消全选' : '选择全部教材'}</button></div>
        <div className="la-book-choices">{availableBooks.map((book) => <button key={book.id} aria-pressed={scopeIds.includes(book.id)} className={scopeIds.includes(book.id) ? 'selected' : ''} disabled={readOnly || Boolean(busy)} onClick={() => changeBrief({ bookIds: scopeIds.includes(book.id) ? scopeIds.filter((id) => id !== book.id) : [...scopeIds, book.id] })}><span>{scopeIds.includes(book.id) ? <CheckOutlined /> : <BookOutlined />}</span>{book.title}</button>)}</div>
        {!availableBooks.length && <p className="la-column-gap">课程中还没有教材。<button onClick={onGoLibrary}>前往教材库</button></p>}
        <footer><div className="la-requirements">{OPTIONS.map((item) => <button key={item} aria-pressed={brief.requirements.includes(item)} className={brief.requirements.includes(item) ? 'selected' : ''} disabled={readOnly || Boolean(busy)} onClick={() => changeBrief({ requirements: brief.requirements.includes(item) ? brief.requirements.filter((value) => value !== item) : [...brief.requirements, item], questions: item === '课堂提问' && brief.questions === 0 ? 3 : brief.questions })}>{brief.requirements.includes(item) && <CheckOutlined />} {item}</button>)}</div><Button type="primary" size="large" loading={busy === 'create'} disabled={readOnly || historyLoading || Boolean(activeCourseRun) || !availableBooks.length || Boolean(busy)} onClick={startRun}>{readOnly ? '在线示例不执行任务' : '检索教材并生成草稿'}</Button></footer>
        <p className="la-brief-note">模型可在预算内选择后续动作，必要时等待教师补充条件；不可用时明确降级为证据工作流。</p>
      </section>
      {activeCourseRun && <Alert type="info" showIcon message="当前课程已有任务进行中" action={<Button size="small" onClick={() => chooseRun(activeCourseRun.id)}>查看任务</Button>} />}
      <div className="la-start-guide"><FileSearchOutlined /><h2>先明确一段课，再让系统整理材料</h2><p>填写或复用条件不会自动执行。教案历史中的证据和修改继续保留。</p>{runs.length > 0 && <button onClick={() => chooseRun(runs[0].id)}>继续最近一份：{runTitle(runs[0])} →</button>}</div>
    </> : <>
      {runLoading && !run && <div className="la-loading"><Spin /> 正在读取任务…</div>}
      {pollError && <Alert type="warning" showIcon message={pollError} action={<Button size="small" onClick={() => setRefresh((value) => value + 1)}>刷新状态</Button>} />}
      {run && <>
        <section className="la-run-brief"><div><small>{labels[run.status] || run.status}</small><h2>{runTitle(run)}</h2><p>{requestedMinutes} 分钟 · {requestedQuestions} 个课堂问题 · {requestedBookIds.length} 本教材</p></div><details><summary>查看备课条件 <DownOutlined /></summary><p>{run.result.goal}</p><p>教学对象：{run.result.request?.audience || run.payload?.audience || '未填写'}</p><p>先修知识：{run.result.request?.prior_knowledge || run.payload?.prior_knowledge || '未填写'}</p><p>{(run.result.requirements || []).join(' · ')}</p><p>{run.result.request?.focus_terms?.join(' / ')}</p></details><Button icon={<CopyOutlined />} disabled={readOnly || Boolean(busy)} onClick={copyLessonConditions}>复用条件新建</Button><Button type="text" icon={<ReloadOutlined />} disabled={Boolean(busy)} onClick={() => setRefresh((value) => value + 1)}>刷新</Button></section>
        {execution?.isV3 && <AgentExecutionPanel run={run} execution={execution} busy={busy} readOnly={readOnly} onCancel={cancelRun} />}
        {run.status === 'waiting_user' && execution?.approval.kind === 'teacher_question' && <section className="la-teacher-question" aria-label="等待教师补充条件"><header><small>等待你的教学判断</small><h3>{execution.approval.title || '请补充一个备课条件'}</h3></header>{execution.approval.message && <p>{execution.approval.message}</p>}<p className="la-teacher-prompt">{execution.approval.question || '问题内容尚未返回，请刷新任务。'}</p>{execution.approval.options.length > 0 && <div className="la-answer-options" aria-label="回答建议">{execution.approval.options.map((option, index) => <Button key={index} disabled={readOnly || Boolean(busy) || !execution.canRespond} onClick={() => changeTeacherAnswer(option)}>{option}</Button>)}</div>}<Input.TextArea aria-label="回答 Agent 的教学问题" value={teacherAnswer} maxLength={2000} showCount autoSize={{ minRows: 3, maxRows: 8 }} placeholder="填写你的选择，也可以补充适用条件" disabled={readOnly || Boolean(busy) || !execution.canRespond} onChange={(event) => changeTeacherAnswer(event.target.value)} /><footer><span>{readOnly ? '当前为只读示例，不能提交回答。' : !execution.canRespond ? '缺少有效问题编号或内容，请刷新后核对；不会代用继续章节操作。' : '提交后继续同一任务；建议选项只会填入输入框。'}</span>{!readOnly && <Button type="primary" icon={<SendOutlined />} loading={busy === 'respond'} disabled={Boolean(busy) || !execution.canRespond || !teacherAnswer.trim()} onClick={respondToTeacherQuestion}>提交回答并继续</Button>}</footer></section>}
        {run.status === 'waiting_user' && execution?.approval.kind === 'chapter_review' && <Alert type="warning" showIcon message={execution.approval.title || '请先核对教材章节'} description={<>{execution.approval.message}<p>{execution.approval.textbooks.map((book) => book.title).join('、')}</p><Button onClick={onGoLibrary}>去核对章节</Button> {!readOnly && <Button loading={busy === 'resume'} disabled={Boolean(busy)} onClick={() => continueRun('resume')}>已确认，继续</Button>}</>} />}
        {run.status === 'waiting_user' && execution?.approval.kind !== 'teacher_question' && execution?.approval.kind !== 'chapter_review' && <Alert type="warning" showIcon message="任务正在等待教师处理" description="当前等待类型暂无法识别，请刷新状态并核对执行记录。不会自动提交或重启任务。" />}
        {run.status === 'failed' && <Alert type="error" showIcon message="本次任务未能结束" description={<>{run.error || run.message || '请处理问题后再试。'}{!readOnly && <div><Button loading={busy === 'retry'} disabled={Boolean(busy)} onClick={() => continueRun('retry')}>重新执行（可能调用模型）</Button></div>}</>} />}
        {run.status === 'cancelled' && <Alert type="info" showIcon message="本次执行已停止" description="已有材料和教师修改继续保留。可核对当前成果，或复用条件手动新建任务；刷新不会自动重启。" />}
        {taskActive && <div className="la-active-status"><Spin size="small" /><span>{run.message || '正在处理所选教材；完成后会区分教案草稿与证据材料。'}</span>{!execution?.isV3 && <small>{Math.round(run.progress || 0)}%</small>}</div>}
        {artifact ? <article className={`la-document ${editing ? 'is-editing' : ''}`}>
          <header className="la-document-heading"><div><span className={`la-delivery ${delivery?.status}`}>{delivery?.status === 'draft_ready' ? '教案草稿 · 待教师核对' : delivery?.status === 'evidence_only' ? '证据已整理 · 教案待补' : '目标未齐全'}</span>{editing ? <Input disabled={Boolean(busy)} aria-label="教案标题" value={artifact.title} onChange={(event) => updateArtifact((current) => ({ ...current, title: event.target.value }))} /> : <h2>{artifact.title || '备课材料'}</h2>}<p>{artifact.citations.length} 条教材引用 · {run.result.draft_revision ? `教师修订稿 · 第 ${run.result.draft_revision} 版` : '生成原稿'}{dirty ? ' · 有未保存修改' : ''}</p></div><div className="la-document-actions">{!readOnly && <Button icon={editing ? <SaveOutlined /> : <EditOutlined />} loading={busy === 'save'} disabled={Boolean(busy) || taskActive || run.status === 'waiting_user' || (editing && !dirty)} onClick={() => editing ? saveDraft() : setEditing(true)}>{editing ? dirty ? '保存修改' : '尚未修改' : '编辑草稿'}</Button>}{editing && <Button disabled={Boolean(busy)} onClick={() => setEditing(false)}>阅读模式</Button>}<Button icon={<PrinterOutlined />} loading={busy === 'export'} disabled={Boolean(busy) || dirty || taskActive} onClick={printDraft}>打印 / PDF</Button><Button icon={<ExportOutlined />} disabled={Boolean(busy) || dirty || taskActive} onClick={exportDraft}>Markdown</Button>{onOpenLesson && <Button type="primary" disabled={Boolean(busy) || dirty || taskActive} onClick={() => onOpenLesson(run.id)}>预览教案</Button>}</div></header>
          {dirty && <p className="la-local-note">修改暂存于此浏览器，点击“保存修改”后才会同步到课程。来源原文保持不变。</p>}
          {conflict && <Alert type="warning" showIcon message="此稿件已有新的保存版本" description="你的本地修改已保留。加载最新稿后再编辑，避免覆盖其他修改。" action={<Button disabled={Boolean(busy)} onClick={() => { if (!run || !editor || !serverArtifact(run)) return; writeLocal(`${draftKey(courseId, run.id)}:backup`, editor); removeLocal(draftKey(courseId, run.id)); setEditor({ runId: run.id, artifact: clone(serverArtifact(run)!), revision: remoteRevision, dirty: false }); message.info('已加载最新稿；原本地修改另存为浏览器备份'); }}>加载最新稿并保留备份</Button>} />}
          {readLocal<Editor>(`${draftKey(courseId, run.id)}:backup`) && !dirty && <button className="la-restore-backup" onClick={() => { const backup = readLocal<Editor>(`${draftKey(courseId, run.id)}:backup`); if (backup) { setEditor(backup); setEditing(true); writeLocal(draftKey(courseId, run.id), backup); } }}>恢复本地修改备份</button>}
          {!!delivery?.missing_items?.length && <div className="la-missing-goals"><strong>本次尚未完成</strong><ul>{delivery.missing_items.map((item, index) => <li key={index}>{item}</li>)}</ul><small>{dirty ? '保存后会重新检查目标；当前列表对应上次保存的结果。' : '处理已结束不等于教学目标已完成。可以基于材料继续编辑。'}</small><div className="la-missing-actions"><Button size="small" onClick={() => setCoverageOpen(true)}>查看教材覆盖{missingBookIds.length ? ` · 缺 ${missingBookIds.length} 本` : ''}</Button>{!readOnly && <><Button size="small" disabled={Boolean(busy) || taskActive || run.status === 'waiting_user'} onClick={() => { setEditing(true); document.querySelector('.la-document')?.scrollIntoView({ block: 'start' }); }}>编辑补充</Button><Button size="small" disabled={Boolean(busy)} onClick={copyLessonConditions}>调整范围重新备课</Button></>}</div></div>}
          <nav className="la-document-nav" aria-label="稿件栏目"><a href="#la-lesson_blocks">课时安排</a><a href="#la-classroom_questions">课堂问题</a><a href="#la-textbook_differences">教材比较</a><button onClick={() => showEvidence()}>核对教材证据 ↗</button></nav>
          <section className="la-document-section la-summary"><h3>主题概览</h3>{editing ? <Input.TextArea disabled={Boolean(busy)} aria-label="主题概览" autoSize={{ minRows: 3, maxRows: 12 }} value={artifact.executive_summary} onChange={(event) => updateArtifact((current) => ({ ...current, executive_summary: event.target.value }))} /> : <p>{artifact.executive_summary || '尚未生成主题概览。'}</p>}</section>
          {renderStrings('teaching_objectives', '教学目标', '尚未生成可供课堂使用的教学目标。')}
          <div className="la-time-total">已安排 {(artifact.lesson_blocks || []).reduce((sum, block) => sum + (block.minutes || 0), 0)} / {requestedMinutes} 分钟</div>
          {renderRows('lesson_blocks', '课堂讲授安排', [['title', '环节名称'], ['content', '讲授内容']], '尚无分段课时安排。已有原文证据不能替代一份完整教案。')}
          {renderStrings('classroom_questions', `课堂问题 · 目标 ${requestedQuestions} 个`, '尚未生成课堂问题。', requestedQuestions === 0)}
          {!!artifact.classroom_questions.length && <p className="la-question-note">当前为问题清单，未提供独立的参考答案、提问目的与评价标准；请教师结合教材补充后使用。</p>}
          {renderRows('teaching_focus', '重点难点', [['title', '要点'], ['explanation', '讲解建议']], '此栏目尚未提供，请结合学生情况补充。')}
          {renderRows('textbook_differences', '教材侧重点与差异', [['textbook', '教材'], ['perspective', '本书提供的视角']], '尚无有依据的教材比较；没有生成差异不代表教材之间没有差异。', run.result.textbook_ids.length < 2)}
          {renderRows('common_ground', '教材共同结论', [['claim', '共同结论']], '尚未形成可核对的共同结论。', run.result.textbook_ids.length < 2)}
          {renderRows('misconceptions', '易混淆点', [['issue', '容易混淆的内容'], ['guidance', '如何辨析']], '此栏目尚未生成，不能据此判定不存在易混淆点。')}
          <details className="la-materials" open={!artifact.lesson_blocks?.length}><summary>查看概念讲解材料 <span>{artifact.knowledge_sequence.length} 项</span></summary>{renderRows('knowledge_sequence', '主题材料与讲解顺序', [['title', '主题'], ['explanation', '教材材料']], '当前还没有可展示的主题材料。')}</details>
          {renderStrings('unresolved_questions', '教师核对事项', '尚无单列核对事项；所有生成结论仍需教师核对。')}
          <footer className="la-document-footer"><p>自动检查仅核对来源、覆盖和目标结构；尚未替代教师对结论与课堂适用性的审核。</p>{!!delivery?.checks.length && <details><summary>查看自动检查项</summary><ul>{delivery.checks.map((check) => <li key={check.id}><span>{check.passed ? '通过' : '待补'}</span> {check.label} · {check.value}</li>)}</ul></details>}</footer>
        </article> : !taskActive && <div className="la-start-guide"><FileSearchOutlined /><h2>尚无可展示的成果</h2><p>查看下方处理过程，或返回新建任务。刷新只读取状态，不会重新执行。</p></div>}
        {execution && !execution.isV3 && <LegacyExecutionTrace steps={execution.legacyPlan} title="查看历史流程记录" hint="固定步骤保留用于查看历史任务，不代表模型自主选择的执行轨迹。" />}
      </>}
    </>}
    <Modal open={coverageOpen} onCancel={() => setCoverageOpen(false)} title="核对各教材的使用情况" footer={null} width={650}>
      <p className="la-evidence-note">{dirty ? '以下对应上次保存的教案，保存修改后会重新检查。' : '覆盖表示至少有教案条目引用该书，不等于结论已获语义核验。'}</p>
      <ul className="la-book-coverage">{requestedBookIds.map((id) => <li key={id}><strong>{textbooks.find((book) => book.id === id)?.title || run?.result.observations?.textbooks?.find((book) => book.id === id)?.title || id}</strong><span className={coveredBookIds.has(id) ? 'covered' : 'missing'}>{coveredBookIds.has(id) ? '已有条目引用' : '尚无条目引用'}</span></li>)}</ul>
      <div className="la-missing-actions"><Button onClick={onGoLibrary}>查看课程教材</Button>{!readOnly && <Button type="primary" disabled={Boolean(busy)} onClick={copyLessonConditions}>复用条件并调整范围</Button>}</div>
    </Modal>
    <Modal open={evidenceOpen} onCancel={() => { setEvidenceOpen(false); setSourcePage(null); }} title={sourcePage ? '教材原页' : '核对教材证据'} footer={null} width={1100} destroyOnClose className="la-evidence-modal">
      {sourcePage ? <><Button className="la-back-evidence" onClick={() => setSourcePage(null)}>← 返回双侧证据</Button><SourcePageViewer textbookId={sourcePage.bookId} title={sourcePage.title} page={sourcePage.page} totalPages={sourcePage.total} onPageChange={(page) => setSourcePage({ ...sourcePage, page })} /></> : <><p className="la-evidence-note">两侧原文可分别核对。来源可定位不等于两段内容已被确认存在同义、补充或冲突关系。</p><div className="la-evidence-pair">{renderSource(citationMap.get(sourcePair[0]), 0)}{renderSource(citationMap.get(sourcePair[1]), 1)}</div></>}
    </Modal>
  </section>;
};

export default AgentWorkbench;
