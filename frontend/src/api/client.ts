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
export const uploadTextbook = (file: File, onProgress?: (pct: number) => void) => {
  const fd = new FormData();
  fd.append('file', file);
  return api.post<Textbook>('/textbooks/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total));
    },
  });
};

export const getTextbooks = () => api.get<Textbook[]>('/textbooks');

export const getChapters = (id: string) => api.get<Chapter[]>(`/textbooks/${id}/chapters`);

export const deleteTextbook = (id: string) => api.delete(`/textbooks/${id}`);

/* ========== Jobs ========== */
export const startParseJob = (textbookId: string, force: boolean = false) =>
  api.post<Job>('/jobs/parse', { textbook_id: textbookId, force });

export const startExtractGraphJob = (textbookId: string, force: boolean = false) =>
  api.post<Job>('/jobs/extract-graph', { textbook_id: textbookId, force });

export const startIntegrateJob = () =>
  api.post<Job>('/jobs/integrate', {});

export const getJobStatus = (id: string) =>
  api.get<Job>(`/jobs/${id}`);

/* ========== Graph ========== */
export const getBookGraph = (id: string) =>
  api.get<GraphData>(`/graph/book/${id}`);

export const getIntegratedGraph = () =>
  api.get<GraphData>('/graph/integrated');

/* ========== Decisions ========== */
export const getDecisions = () =>
  api.get<Decision[]>('/decisions');

export const updateDecision = (id: string, data: Partial<Decision>) =>
  api.patch<Decision>(`/decisions/${id}`, data);

/* ========== RAG ========== */
export const buildRagIndex = () =>
  api.post<RagStatus>('/rag/index', {});

export const getRagStatus = () =>
  api.get<RagStatus>('/rag/status');

export const queryRag = (question: string) =>
  api.post<QueryResult>('/rag/query', { question });

/* ========== Chat ========== */
export const sendChatMessage = (message: string) =>
  api.post<{ response?: string; operation?: string; detail?: string }>('/chat', { message });

/* ========== Report ========== */
export const getReportSummary = () =>
  api.get<ReportSummary>('/report/summary');

export const exportReport = () =>
  api.post('/report/export', {}, { responseType: 'blob' });

/* ========== Benchmark ========== */
export const getBenchmarkResults = () =>
  api.get<BenchmarkResult[]>('/benchmark');

export const runBenchmark = () =>
  api.post<BenchmarkResult[]>('/benchmark/run', {});

/* ========== Model ========== */
export const getModelStatus = () =>
  api.get<ModelStatus>('/model/status');

/* ========== Node RAG Query ========== */
export const queryNodeRag = (nodeId: string, question: string) =>
  api.post<QueryResult>('/rag/node-query', { node_id: nodeId, question });

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
