import axios from 'axios';

const api = axios.create({ baseURL: '/api', timeout: 60000 });

export interface TeachingSection {
  id: string;
  title: string;
  level: number;
  parent_id?: string | null;
  page_start: number;
  page_end: number;
  excerpt: string;
  content: string;
  figure_refs: { label: string; page_number: number }[];
  formal_section?: boolean;
  navigation_unit?: boolean;
}
export interface TeachingChapter {
  id: string;
  title: string;
  page_start: number;
  page_end: number;
  sections: TeachingSection[];
}
export interface TeachingBook {
  textbook_id: string;
  title: string;
  total_pages: number;
  has_pdf: boolean;
  chapters: TeachingChapter[];
  readiness: Record<string, unknown>;
}
export interface TeachingHit {
  id: string;
  section_id: string;
  title: string;
  chapter_id: string;
  chapter_title: string;
  page_start: number;
  page_end: number;
  excerpt: string;
}
export interface BridgeEvidence {
  id: string;
  chapter_id?: string;
  chapter: string;
  section_path: string[];
  page_start: number;
  page_end: number;
  quote: string;
  score: number;
  title?: string;
  match_kind?: 'topic_heading' | 'mention';
  quote_truncated?: boolean;
  source_heading?: string;
  display_title?: string;
  title_origin?: 'source_heading' | 'source_subheading' | 'topic_excerpt';
  concept_key?: string;
}
export interface TeachingBridgeResult {
  query: string;
  groups: {
    textbook_id: string;
    title: string;
    status: 'evidence_found' | 'no_evidence';
    items: BridgeEvidence[];
    total_matches?: number;
    offset?: number;
    has_more?: boolean;
  }[];
  confirmed_relations: { id?: string; relation_type?: string; reason?: string; [key: string]: unknown }[];
  message: string;
}

export const getTeachingBook = (id: string) => api.get<TeachingBook>(`/textbooks/${encodeURIComponent(id)}/teaching`);
export const searchTeachingBook = (id: string, q: string, signal?: AbortSignal) =>
  api.get<{ query: string; items: TeachingHit[]; total: number }>(`/textbooks/${encodeURIComponent(id)}/teaching/search`, { params: { q, limit: 20 }, signal });
export const getTeachingBridge = (course: string, ids: string[], q: string, signal?: AbortSignal, offset = 0, limitPerBook = 4) =>
  api.get<TeachingBridgeResult>(`/courses/${encodeURIComponent(course)}/teaching/bridge`, { params: { textbook_ids: ids.join(','), q, limit_per_book: limitPerBook, offset_per_book: offset }, signal });
export const pageImageUrl = (id: string, page: number) => `/api/textbooks/${encodeURIComponent(id)}/teaching/pages/${page}/image`;
export interface BridgeDiagnostics { pending_review: number; message: string; latest_run: { status: string; eligible_nodes: number | null; candidate_pairs: number | null; qualified_pairs: number | null; judged: number | null; candidates_created: number | null } | null }
export const getBridgeDiagnostics = (course: string, ids: string[], signal?: AbortSignal) => api.get<BridgeDiagnostics>(`/courses/${encodeURIComponent(course)}/teaching/diagnostics`, { params: { textbook_ids: ids.join(',') }, signal });

export function readLocal<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; }
}
export function writeLocal(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}
