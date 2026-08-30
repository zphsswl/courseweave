import axios from 'axios';
import type {
  Textbook,
  Chapter,
  Job,
  GraphData,
  Decision,
  RagStatus,
  QueryResult,
  ReportSummary,
  BenchmarkResult,
  HealthStatus,
  ModelStatus,
  Diagnostics,
  CompressionStats,
  IntegrationResult,
  Course,
  AlignmentList,
  BenchmarkSuite,
  AgentRun,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const msg = error?.response?.data?.detail || error.message || '未知错误';
    console.error('[API Error]', msg, error.config?.url);
    return Promise.reject(error);
  }
);

/* ========== Health ========== */
export const getHealth = () => api.get<HealthStatus>('/health');

/* ========== Textbooks ========== */
export const uploadTextbook = (file: File, courseId: string, onProgress?: (pct: number) => void) => {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('course_id', courseId);
  return api.post<Textbook>('/textbooks/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total));
    },
  });
};

export const getTextbooks = (courseId?: string) =>
  api.get<Textbook[]>('/textbooks', { params: courseId ? { course_id: courseId } : undefined });

/* ========== Courses ========== */
export const getCourses = () => api.get<Course[]>('/courses');

export const createCourse = (data: Pick<Course, 'title'> & Partial<Pick<Course, 'description' | 'subject' | 'default_granularity'>>) =>
  api.post<Course>('/courses', data);

export const deleteCourse = (courseId: string) => api.delete(`/courses/${courseId}`);

export const getChapters = (id: string) => api.get<Chapter[]>(`/textbooks/${id}/chapters`);

export const updateChapterStructure = (id: string, chapters: Chapter[], confirmed: boolean = true) =>
  api.patch(`/textbooks/${id}/chapters`, {
    confirmed,
    chapters: chapters.map((chapter, index) => ({
      id: chapter.id,
      title: chapter.title,
      order_index: chapter.order_index ?? index,
      parent_id: chapter.parent_id || '',
      level: chapter.level || 1,
    })),
  });

export const confirmChapterStructure = async (id: string) => {
  const chapters = await getChapters(id);
  return updateChapterStructure(id, chapters.data, true);
};

export const deleteTextbook = (id: string) => api.delete(`/textbooks/${id}`);

/* ========== Jobs ========== */
export const startParseJob = (textbookId: string, force: boolean = false) =>
  api.post<Job>('/jobs/parse', { textbook_id: textbookId, force });

export const startExtractGraphJob = (textbookId: string, force: boolean = false) =>
  api.post<Job>('/jobs/extract-graph', { textbook_id: textbookId, force });

export const startIntegrateJob = (courseId: string, textbookIds: string[]) =>
  api.post<Job>('/jobs/integrate', { course_id: courseId, textbook_ids: textbookIds });

export const getJobStatus = (id: string) =>
  api.get<Job>(`/jobs/${id}`);

/* ========== Lesson preparation Agent ========== */
export const createAgentRun = (data: {
  course_id: string;
  topic: string;
  goal: string;
  textbook_ids: string[];
  requirements: string[];
}) => api.post<AgentRun>('/agent/runs', data);

export const getAgentRuns = (courseId: string, limit: number = 12) =>
  api.get<AgentRun[]>('/agent/runs', { params: { course_id: courseId, limit } });

export const getAgentRun = (id: string) =>
  api.get<AgentRun>(`/agent/runs/${id}`);

export const resumeAgentRun = (id: string) =>
  api.post<AgentRun>(`/agent/runs/${id}/resume`);

export const retryAgentRun = (id: string) =>
  api.post<AgentRun>(`/agent/runs/${id}/retry`);

/* ========== Graph ========== */
export interface GraphParams {
  course_id?: string;
  min_importance?: number;
  granularity?: string;
  essence_only?: boolean;
  limit?: number;
  offset?: number;
}

export const getBookGraph = (id: string, params?: GraphParams) =>
  api.get<GraphData>(`/graph/book/${id}`, { params });

export const getIntegratedGraph = (params?: GraphParams) =>
  api.get<GraphData>('/graph/integrated', { params });

/* ========== Decisions ========== */
export const getDecisions = () =>
  api.get<Decision[]>('/decisions');

export const updateDecision = (id: string, data: Partial<Decision>) =>
  api.patch<Decision>(`/decisions/${id}`, data);

/* ========== RAG ========== */
export const buildRagIndex = (courseId: string) =>
  api.post<RagStatus>('/rag/index', { course_id: courseId });

export const getRagStatus = (courseId: string) =>
  api.get<RagStatus>('/rag/status', { params: { course_id: courseId } });

export const queryRag = (
  question: string,
  courseId: string,
  mode: 'all' | 'compare' = 'all',
  textbookIds?: string[],
) => api.post<QueryResult>('/rag/query', {
  question,
  course_id: courseId,
  mode,
  textbook_ids: textbookIds,
});

/* ========== Cross-textbook review ========== */
export const getAlignmentCandidates = (courseId: string, textbookIds: string[], status: string = 'pending') =>
  api.get<AlignmentList>(`/courses/${courseId}/alignments`, {
    params: { status, textbook_ids: textbookIds },
    paramsSerializer: { indexes: null },
  });

export const getAlignmentGraph = (courseId: string, textbookIds: string[]) =>
  api.get<GraphData>(`/courses/${courseId}/alignments/graph`, {
    params: { textbook_ids: textbookIds },
    paramsSerializer: { indexes: null },
  });

export const reviewAlignment = (
  courseId: string,
  candidateId: string,
  data: { action: 'approve' | 'reject' | 'edit'; relation_type?: string; reason?: string },
) => api.patch(`/courses/${courseId}/alignments/${candidateId}`, data);

/* ========== Chat ========== */
export const sendChatMessage = (message: string) =>
  api.post<{ response?: string; operation?: string; detail?: string }>('/chat', { message });

/* ========== Report ========== */
export const getReportSummary = () =>
  api.get<ReportSummary>('/report/summary');

export const exportReport = () =>
  api.post('/report/export', {}, { responseType: 'blob' });

/* ========== Benchmark ========== */
export const getBenchmarkResults = (courseId: string) =>
  api.get<BenchmarkResult[]>('/benchmark', { params: { course_id: courseId } });

export const runBenchmark = (courseId: string) =>
  api.post<BenchmarkResult[]>('/benchmark/run', { course_id: courseId });

export const getBenchmarkSuite = () => api.get<BenchmarkSuite>('/benchmark/suite');

/* ========== Model ========== */
export const getModelStatus = (refresh: boolean = false) =>
  api.get<ModelStatus>('/model/status', { params: { refresh } });

export const probeModel = () => api.post<ModelStatus>('/model/probe');

/* ========== Node RAG Query ========== */
export const queryNodeRag = (nodeId: string, question: string, courseId?: string) =>
  api.post<QueryResult>('/rag/node-query', { node_id: nodeId, question, course_id: courseId });

/* ========== Diagnostics ========== */
export const getDiagnostics = () =>
  api.get<Diagnostics>('/system/diagnostics');

/* ========== Text Integration ========== */
export const getCompressionStats = () =>
  api.get<CompressionStats>('/integration/compression');

export const runIntegration = () =>
  api.post('/integration/run');

export const integrateConcept = (id: string) =>
  api.post(`/integration/concept/${id}`);

export const getIntegrationResults = () =>
  api.get<IntegrationResult[]>('/integration/results');

export default api;
