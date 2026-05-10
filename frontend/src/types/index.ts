/* ===== MedEssence Agent - TypeScript Interfaces ===== */

export interface Textbook {
  id: string;
  filename: string;
  title: string;
  format: string;
  file_size: number;
  total_pages: number;
  total_chars: number;
  chapter_count: number;
  parse_status: string;
  graph_status: string;
  index_status: string;
}

export interface Chapter {
  id: string;
  title: string;
  page_start: number;
  page_end: number;
  char_count: number;
}

export interface Job {
  id: string;
  type: string;
  status: string; // pending, processing, completed, failed
  progress: number;
  total: number;
  message: string;
  result: any;
  error: string;
  created_at: string;
}

export interface GraphNode {
  id: string;
  label: string;
  definition: string;
  category: string;
  importance: number;
  textbook: string;
  chapter: string;
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
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  textbook_colors?: Record<string, string>;
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
}

export interface Citation {
  textbook: string;
  chapter: string;
  page: number;
  relevance_score: number;
}

export interface QueryResult {
  answer: string;
  citations: Citation[];
  source_chunks: string[];
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
  status: string;
}

export interface BenchmarkResult {
  metric: string;
  score: number;
  description: string;
}

export interface HealthStatus {
  status: string;
  name: string;
  version: string;
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
