/* ===== MedEssence Agent - TypeScript Interfaces ===== */

export interface Textbook {
  id: string;
  course_id?: string;
  filename: string;
  original_filename?: string;
  title: string;
  format: string;
  file_size: number;
  total_pages: number;
  total_chars: number;
  chapter_count: number;
  parse_status: string;
  graph_status: string;
  index_status: string;
  structure_status?: 'pending' | 'review' | 'confirmed';
  parse_warnings?: string[];
}

export interface Course {
  id: string;
  title: string;
  description: string;
  subject: string;
  status: 'draft' | 'processing' | 'review' | 'published' | 'archived';
  default_granularity: 'outline' | 'core' | 'detailed';
  textbook_count: number;
  canonical_concept_count: number;
  pending_review_count: number;
  updated_at?: string;
}

export interface Chapter {
  id: string;
  title: string;
  page_start: number;
  page_end: number;
  char_count: number;
  order_index?: number;
  parent_id?: string;
  level?: number;
  review_status?: string;
}

export interface Job {
  id: string;
  course_id?: string;
  type: string;
  status: string; // pending, processing, waiting_user, completed, failed
  progress: number;
  total: number;
  message: string;
  result: any;
  error: string;
  stage?: string;
  retry_count?: number;
  recoverable?: boolean;
  payload?: Record<string, any>;
  created_at: string;
  updated_at?: string | null;
}

export type AgentStepStatus = 'pending' | 'running' | 'waiting' | 'completed' | 'skipped' | 'failed';

export interface AgentStep {
  id: string;
  title: string;
  description: string;
  tool: string;
  status: AgentStepStatus;
  message?: string;
  output?: Record<string, any>;
}

export interface AgentCitation {
  source_id: string;
  textbook_id: string;
  textbook: string;
  chapter: string;
  section_path: string[];
  page_start: number;
  page_end: number;
  quote: string;
  retrievers?: string[];
}

export interface AgentArtifactRow {
  title?: string;
  explanation?: string;
  claim?: string;
  textbook?: string;
  perspective?: string;
  issue?: string;
  guidance?: string;
  source_ids: string[];
}

export interface AgentArtifact {
  title: string;
  executive_summary: string;
  teaching_objectives: string[];
  knowledge_sequence: AgentArtifactRow[];
  common_ground: AgentArtifactRow[];
  textbook_differences: AgentArtifactRow[];
  misconceptions: AgentArtifactRow[];
  classroom_questions: string[];
  unresolved_questions: string[];
  citations: AgentCitation[];
  generation_method: 'llm_grounded' | 'evidence_fallback';
  generated_at: string;
}

export interface AgentQuality {
  score: number;
  status: 'passed' | 'needs_review';
  message: string;
  used_source_ids: string[];
  covered_textbook_ids: string[];
  checks: Array<{ id: string; label: string; passed: boolean; value: string }>;
}

export interface AgentResult {
  agent_version: string;
  goal: string;
  topic: string;
  requirements: string[];
  textbook_ids: string[];
  plan: AgentStep[];
  approval?: {
    type: 'chapter_review';
    title: string;
    message: string;
    textbooks: Array<{ id: string; title: string }>;
  } | null;
  observations: {
    textbooks?: Array<{
      id: string;
      title: string;
      parse_status: string;
      structure_status: string;
      graph_status: string;
      pages: number;
    }>;
    evidence_count?: number;
    model?: string;
    retrieval_mode?: string;
  };
  artifact?: AgentArtifact | null;
  quality?: AgentQuality | null;
  retry_count: number;
  tools_used: string[];
  created_at: string;
  completed_at?: string;
}

export interface AgentRun extends Omit<Job, 'result'> {
  result: AgentResult;
}

export interface GraphNode {
  id: string;
  label: string;
  definition: string;
  category: string;
  importance: number;
  textbook: string;
  textbook_id?: string;
  chapter: string;
  section_path?: string[];
  page: number;
  page_start?: number;
  page_end?: number;
  source_paragraph: string;
  source_sentences: string[];
  aliases: string[];
  color: string;
  is_merged: boolean;
  teacher_locked: boolean;
  frequency: number;
  size: number;
  quality_score?: number;
  learning_objective?: string;
  is_essence?: boolean;
  granularity?: string; // chapter_topic, section_topic, core_concept, detail_fact
  display_level?: string;
  created_by?: string; // demo_seed, real
  parent_id?: string;
  node_role?: string;
  course_id?: string;
  canonical_concept_id?: string;
  review_status?: string;
  evidence_status?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation_type: string;
  description: string;
  confidence: number;
  relation_subtype?: string;
  is_cross_textbook?: boolean;
  review_status?: string;
  why?: string;
  source_evidence?: RelationEvidenceSummary;
  target_evidence?: RelationEvidenceSummary;
}

export interface RelationEvidenceSummary {
  node_id: string;
  concept: string;
  textbook_id: string;
  textbook: string;
  chapter: string;
  page_start: number;
  page_end: number;
  quote: string;
  verified: boolean;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  textbook_colors?: Record<string, string>;
  total_nodes?: number;
  truncated?: boolean;
  offset?: number;
  limit?: number;
  groups?: Array<{ id: string; title: string; color: string; node_count: number }>;
  total_edges?: number;
}

export interface Decision {
  id: string;
  action: string; // merge, keep, remove, split
  affected_nodes: string[];
  result_node: string;
  result_name: string;
  reason: string;
  confidence: number;
  teacher_override: boolean;
  teacher_feedback: string;
  created_at: string;
  evidence?: string[];
  alternatives_considered?: string[];
  risk?: string;
  similarity_name?: string;
  similarity_definition?: string;
  similarity_context?: string;
  decision_effect?: string;
}

export interface RagStatus {
  indexed: boolean;
  chunk_count: number;
  indexed_chunk_count?: number;
  status?: 'not_built' | 'building' | 'ready' | 'failed' | 'stale';
  method?: 'none' | 'bm25' | 'bm25_vector';
  embedding_available?: boolean;
  message?: string;
  built_at?: string | null;
}

export interface Citation {
  source_id?: string;
  textbook_id?: string;
  textbook: string;
  chapter: string;
  section_path?: string[];
  page: number;
  page_start?: number;
  page_end?: number;
  chunk_id?: string;
  relevance_score: number;
  retrievers?: string[];
  quote?: string;
}

export interface QueryResult {
  answer: string;
  citations: Citation[];
  source_chunks: string[];
  answer_method?: 'llm_grounded' | 'evidence_fallback' | 'no_evidence';
  mode?: 'all' | 'compare';
  retrieval_trace?: {
    course_id: string;
    mode?: string;
    scoped_chunks?: number;
    vector_used?: boolean;
    graph_expansions?: number;
    retrievers?: string[];
  };
}

export interface AlignmentNode {
  id: string;
  name: string;
  definition: string;
  textbook_id: string;
  textbook_title: string;
  chapter_title: string;
  page_start: number;
  page_end: number;
  source_quote: string;
  evidence_status: string;
}

export interface AlignmentCandidate {
  id: string;
  proposed_relation: string;
  confidence: number;
  reason: string;
  differences: string;
  status: string;
  scores: { name: number; definition: number; context: number };
  source: AlignmentNode | null;
  target: AlignmentNode | null;
}

export interface AlignmentList {
  items: AlignmentCandidate[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface ReportSummary {
  textbooks: { count: number; total_pages: number; total_chars: number; list: any[] };
  chapters: { total: number };
  knowledge_graph: {
    total_nodes: number;
    non_merged_nodes: number;
    merged_nodes_count: number;
    total_edges: number;
    edge_types: Record<string, number>;
    chapter_topics?: number;
    section_topics?: number;
    core_concepts?: number;
  };
  decisions: { total: number; merge: number; keep: number; remove: number; split: number; teacher_overrides: number };
  rag: { total_chunks: number; indexed: boolean };
  compression_ratio?: number;
}

export interface ModelStatus {
  provider: string;
  model: string;
  api_key_configured: boolean;
  availability: 'available' | 'unknown' | 'balance_insufficient' | 'authentication_failed' | 'unavailable' | 'degraded' | 'not_configured';
  degraded: boolean;
  message: string;
  fallback_mode: string;
  last_checked_at?: string | null;
  last_error_code?: string | null;
}

export interface BenchmarkResult {
  metric: string;
  score: number;
  description: string;
  numerator?: number;
  denominator?: number;
  category?: 'teacher_questions' | 'system';
}

export interface BenchmarkSuite {
  version: string;
  description: string;
  question_count: number;
  answerable_count: number;
  compare_count: number;
  rejection_count: number;
  questions: Array<{
    id: string;
    category: string;
    question: string;
    mode: 'all' | 'compare';
    answerable: boolean;
  }>;
}

export interface HealthStatus {
  status: string;
  name: string;
  version: string;
  public_demo_read_only?: boolean;
}

export interface CytoscapeNodeData {
  id: string;
  label: string;
  definition: string;
  category: string;
  textbook: string;
  frequency: number;
  is_merged: boolean;
  confidence: number;
  teacher_locked: boolean;
  color: string;
  chapters: string[];
}

export interface CytoscapeEdgeData {
  id: string;
  source: string;
  target: string;
  relation_type: string;
  label: string;
  weight: number;
}

export interface Diagnostics {
  status: 'healthy' | 'warning' | 'error';
  checks: Array<{
    component: string;
    status: string;
    message?: string;
  }>;
}

export interface CompressionStats {
  textbooks: number;
  total_source_chars: number;
  decisions: {
    total: number;
    merge: number;
    keep: number;
    remove: number;
    integrated: number;
  };
  nodes: {
    total: number;
    merged: number;
    compressed_pct: string;
  };
  text_compression: {
    original_chars: number;
    integrated_chars: number;
    ratio: number;
    ratio_pct: string;
    integrated_concepts: number;
  } | null;
}

export interface IntegrationResult {
  id: string;
  action: string;
  result_name: string;
  source_textbook_count: number;
  original_chars: number;
  integrated_chars: number;
  compression_ratio: number;
  compression_pct: string;
  integrated_text: string;
  integrated_definition: string;
  source_texts: Array<{
    id: string;
    name: string;
    textbook: string;
    chapter: string;
    definition: string;
  }>;
  confidence: number;
}
