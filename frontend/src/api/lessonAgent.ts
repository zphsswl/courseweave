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

export interface LessonResult extends Omit<AgentResult, 'artifact' | 'quality'> {
  artifact?: LessonArtifact | null;
  lesson_draft?: LessonArtifact | null;
  draft_revision?: number;
  delivery?: LessonDelivery;
  request?: Partial<LessonRequest>;
  quality?: (AgentQuality & { semantic_reviewed?: boolean; source_check_score?: number }) | null;
}

export interface LessonRun extends Omit<AgentRun, 'result'> {
  result: LessonResult;
  payload?: Partial<LessonRequest>;
}

const runPath = (id: string) => `/runs/${encodeURIComponent(id)}`;
export const getLessonRuns = (courseId: string, signal?: AbortSignal) => api.get<LessonRun[]>('/runs', { params: { course_id: courseId, limit: 12 }, signal });
export const getLessonRun = (id: string, signal?: AbortSignal) => api.get<LessonRun>(runPath(id), { signal });
export const createLessonRun = (request: LessonRequest, signal?: AbortSignal) => api.post<LessonRun>('/runs', request, { signal });
export const resumeLessonRun = (id: string, signal?: AbortSignal) => api.post<LessonRun>(`${runPath(id)}/resume`, {}, { signal });
export const retryLessonRun = (id: string, signal?: AbortSignal) => api.post<LessonRun>(`${runPath(id)}/retry`, {}, { signal });
export const saveLessonDraft = (id: string, expectedRevision: number, artifact: LessonArtifact, signal?: AbortSignal) => api.patch<LessonRun>(`${runPath(id)}/draft`, { expected_revision: expectedRevision, artifact }, { signal });
export const exportLessonMarkdown = (id: string, signal?: AbortSignal) => api.get<string>(`${runPath(id)}/export`, { params: { format: 'markdown' }, responseType: 'text', signal });
export const exportLessonPrint = (id: string, signal?: AbortSignal) => api.get<string>(`${runPath(id)}/export`, { params: { format: 'html' }, responseType: 'text', signal });

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
  if (run.result.textbook_ids.length > 1 && !artifact?.textbook_differences?.length) missing.push('未提供有依据的教材比较');
  return {
    status: artifact?.generation_method === 'evidence_fallback' && !artifact?.teacher_edited ? 'evidence_only' : 'needs_work',
    missing_items: missing.length ? missing : ['旧任务尚未按本次目标逐项检查，请教师核对'],
    checks: [],
  };
}
