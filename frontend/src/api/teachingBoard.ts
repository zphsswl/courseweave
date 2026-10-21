import axios from 'axios';

const api = axios.create({ baseURL: '/api', timeout: 60000 });
export type TeachingRelation = 'equivalent_to' | 'extends' | 'prerequisite' | 'contrasts_with' | 'conflicts_with' | 'related_to';
export interface BoardSelection {
  id: string;
  chunk_id: string;
  textbook_id: string;
  textbook_title: string;
  chapter: string;
  chapter_id?: string;
  section_path: string[];
  page_start: number;
  page_end: number;
  quote: string;
  quote_truncated?: boolean;
  dimension: string;
  note: string;
  teaching_title?: string;
  source_heading?: string;
  display_title?: string;
  title_origin?: 'source_heading' | 'source_subheading' | 'topic_excerpt';
  concept_key?: string;
  page_image_url?: string | null;
}
export interface BoardConnection {
  id: string;
  source_chunk_id: string;
  target_chunk_id: string;
  relation_type: TeachingRelation;
  reason: string;
  status: 'draft' | 'confirmed';
}
export interface TeachingBoard {
  id: string;
  course_id: string;
  topic: string;
  textbook_ids: string[];
  revision: number;
  selections: BoardSelection[];
  connections: BoardConnection[];
  created_at?: string;
  updated_at?: string;
}
export interface BoardSummary {
  id: string;
  topic: string;
  textbook_ids: string[];
  revision: number;
  selection_count: number;
  connection_count: number;
  selection_counts: Record<string, number>;
  confirmed_count: number;
  draft_count: number;
}
export interface BoardPayload {
  topic: string;
  textbook_ids: string[];
  selections: { chunk_id: string; dimension: string; note: string; teaching_title: string }[];
  connections: BoardConnection[];
}
const root = (courseId: string) => `/courses/${encodeURIComponent(courseId)}/teaching/boards`;
export const listTeachingBoards = (courseId: string, signal?: AbortSignal) => api.get<{ items: BoardSummary[]; total: number }>(root(courseId), { signal });
export const getTeachingBoard = (courseId: string, id: string, signal?: AbortSignal) => api.get<TeachingBoard>(`${root(courseId)}/${encodeURIComponent(id)}`, { signal });
export const getTeachingSources = (courseId: string, topic: string, bookIds: string[], chunkIds: string[], signal?: AbortSignal) => api.get<{ items: BoardSelection[] }>(`${root(courseId)}/sources`, { params: { q: topic, textbook_ids: bookIds.join(','), chunk_ids: chunkIds.join(',') }, signal });
export const createTeachingBoard = (courseId: string, payload: BoardPayload) => api.post<TeachingBoard>(root(courseId), payload);
export const updateTeachingBoard = (courseId: string, id: string, revision: number, payload: BoardPayload) => api.patch<TeachingBoard>(`${root(courseId)}/${encodeURIComponent(id)}`, { ...payload, expected_revision: revision });
export const boardPayload = (board: TeachingBoard): BoardPayload => ({
  topic: board.topic,
  textbook_ids: board.textbook_ids,
  selections: board.selections.map(({ chunk_id, dimension, note, teaching_title }) => ({ chunk_id, dimension, note, teaching_title: teaching_title || '' })),
  connections: board.connections,
});
