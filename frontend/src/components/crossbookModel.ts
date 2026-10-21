import type { BridgeEvidence, TeachingBridgeResult } from '../api/teaching';
import type { BoardConnection, BoardSelection, TeachingBoard, TeachingRelation } from '../api/teachingBoard';
import type { RelationCanvasEdge, RelationCanvasNode } from './ConceptRelationCanvas';

export const RELATIONS: Record<TeachingRelation, string> = {
  equivalent_to: '同一概念', extends: '补充与扩展', prerequisite: '前置知识',
  contrasts_with: '侧重点差异', conflicts_with: '条件下的冲突', related_to: '教学关联',
};
export const DIRECTED = new Set<TeachingRelation>(['extends', 'prerequisite']);
export const DIMENSIONS = ['未归类', '定义与范围', '结构与组成', '功能与机制', '应用与病例', '教学辨析'];
export interface ConceptGroup {
  id: string; bookId: string; bookTitle: string; title: string;
  kind: RelationCanvasNode['kind']; evidences: BoardSelection[]; selected: BoardSelection[];
}
export interface ComparisonColumn {
  bookId: string; bookTitle: string; sources: BoardSelection[]; source?: BoardSelection; conceptId?: string;
}
const BOOK_COLORS = ['#55735d', '#a47440', '#5e7b8b', '#867553', '#7c6d84', '#577f79'];
/** A book keeps its colour when results, filters or the comparison order change. */
export function textbookColor(id: string): string {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return BOOK_COLORS[hash % BOOK_COLORS.length];
}
/** Project the same immutable source records into a side-by-side reading view. */
export function comparisonColumns(groups: ConceptGroup[], bookIds: string[], picked: Record<string, string>, view: 'explore' | 'lesson'): ComparisonColumn[] {
  return [...new Set(bookIds)].map((bookId) => {
    const matching = groups.filter((group) => group.bookId === bookId);
    const sources = [...new Map(matching.flatMap((group) => (view === 'lesson' ? group.selected : group.evidences)).map((source) => [source.chunk_id, source])).values()];
    const selectedIds = new Set(matching.flatMap((group) => group.selected.map((source) => source.chunk_id)));
    const source = sources.find((item) => item.chunk_id === picked[bookId]) || sources.find((item) => selectedIds.has(item.chunk_id)) || sources[0];
    return { bookId, bookTitle: matching[0]?.bookTitle || '', sources, source,
      conceptId: source ? matching.find((group) => group.evidences.some((item) => item.chunk_id === source.chunk_id))?.id : undefined };
  });
}
export const pageRange = (source: Pick<BoardSelection, 'page_start' | 'page_end'>) =>
  `PDF ${source.page_start}${source.page_end > source.page_start ? `–${source.page_end}` : ''}`;
const genericHeading = (value: string) => /^(?:(?:第\s*[一二三四五六七八九十百千\d]+\s*[章节])|(?:[（(]?[一二三四五六七八九十百千\d]+[）).．、]))?\s*(?:内容|正文|本章正文|概述|概论|绪论)$/.test(value.trim());
export const sourceTitle = (source: BoardSelection, topic: string) => {
  if (source.teaching_title?.trim()) return source.teaching_title.trim();
  if (source.display_title) return source.display_title;
  const heading = source.section_path?.slice(-1)[0] || source.chapter || '';
  return heading && !genericHeading(heading) ? heading : `${topic} · 原文片段`;
};
export function evidenceSelection(item: BridgeEvidence, bookId: string, bookTitle: string): BoardSelection {
  return {
    ...item, id: item.id, chunk_id: item.id, textbook_id: bookId, textbook_title: bookTitle,
    dimension: '未归类', note: '', teaching_title: '',
  };
}
export function conceptGroups(result: TeachingBridgeResult | null, board: TeachingBoard, seed?: ConceptGroup | null): ConceptGroup[] {
  const byChunk = new Map<string, BoardSelection>();
  result?.groups.forEach((book) => book.items.forEach((item) => byChunk.set(item.id, evidenceSelection(item, book.textbook_id, book.title))));
  seed?.evidences.forEach((source) => { if (!byChunk.has(source.chunk_id)) byChunk.set(source.chunk_id, source); });
  board.selections.forEach((source) => byChunk.set(source.chunk_id, { ...byChunk.get(source.chunk_id), ...source }));
  const selectedIds = new Set(board.selections.map((source) => source.chunk_id));
  const groups = new Map<string, ConceptGroup>();
  byChunk.forEach((source) => {
    // Only the source metadata may group evidence. A teacher's display title
    // never merges otherwise unrelated chunks or concepts across books.
    const key = `${source.textbook_id}:${source.concept_key || `chunk:${source.chunk_id}`}`;
    let group = groups.get(key);
    if (!group) {
      const heading = source.section_path?.slice(-1)[0] || source.chapter || '';
      group = { id: key, bookId: source.textbook_id, bookTitle: source.textbook_title,
        title: sourceTitle(source, board.topic),
        kind: source.teaching_title?.trim() ? 'teacher' : source.title_origin || (genericHeading(heading) || !heading ? 'topic_excerpt' : 'source_heading'),
        evidences: [], selected: [] };
      groups.set(key, group);
    }
    group.evidences.push(source);
    if (selectedIds.has(source.chunk_id)) group.selected.push(source);
  });
  groups.forEach((group) => {
    group.selected.sort((a, b) => board.selections.findIndex((source) => source.chunk_id === a.chunk_id) - board.selections.findIndex((source) => source.chunk_id === b.chunk_id));
    const teacherTitle = group.selected.find((source) => source.teaching_title?.trim())?.teaching_title?.trim();
    if (teacherTitle) { group.title = teacherTitle; group.kind = 'teacher'; }
  });
  return [...groups.values()];
}
export function chunkConceptMap(groups: ConceptGroup[]): Map<string, string> {
  return new Map(groups.flatMap((group) => group.evidences.map((source) => [source.chunk_id, group.id] as [string, string])));
}
export function canvasEdges(connections: BoardConnection[], groups: ConceptGroup[]): RelationCanvasEdge[] {
  const mapping = chunkConceptMap(groups);
  return connections.flatMap((link) => {
    const source = mapping.get(link.source_chunk_id), target = mapping.get(link.target_chunk_id);
    return source && target && source !== target ? [{ id: link.id, source, target,
      label: RELATIONS[link.relation_type], reason: link.reason, status: link.status, directed: DIRECTED.has(link.relation_type) }] : [];
  });
}
export function lessonPath(groups: ConceptGroup[], board: TeachingBoard): ConceptGroup[] {
  const mapping = chunkConceptMap(groups), byId = new Map(groups.map((group) => [group.id, group]));
  return [...new Set(board.selections.map((source) => mapping.get(source.chunk_id)).filter(Boolean))].flatMap((id) => byId.get(id!) ? [byId.get(id!)!] : []);
}
export function moveLessonGroup(board: TeachingBoard, groups: ConceptGroup[], id: string, direction: -1 | 1): TeachingBoard {
  const order = lessonPath(groups, board).map((group) => group.id), at = order.indexOf(id), to = at + direction;
  if (at < 0 || to < 0 || to >= order.length) return board;
  [order[at], order[to]] = [order[to], order[at]];
  const mapping = chunkConceptMap(groups);
  return { ...board, selections: order.flatMap((groupId) => board.selections.filter((source) => mapping.get(source.chunk_id) === groupId)) };
}
export function visibleConcepts(groups: ConceptGroup[], edges: RelationCanvasEdge[], anchorId: string, limit: number, view: 'explore' | 'lesson', bookFilter = '', activeId = ''): ConceptGroup[] {
  if (view === 'lesson') return groups.filter((group) => group.selected.length);
  const anchor = groups.find((group) => group.id === anchorId) || groups[0];
  const related = new Set(edges.filter((edge) => edge.source === anchor?.id || edge.target === anchor?.id).flatMap((edge) => [edge.source, edge.target]));
  const candidates = groups.filter((group) => group.id !== anchor?.id && (!bookFilter || group.bookId === bookFilter));
  const firstPerBook = new Set<string>();
  const main = candidates.filter((group) => { if (group.bookId === anchor?.bookId || firstPerBook.has(group.bookId)) return false; firstPerBook.add(group.bookId); return true; });
  const priority = candidates.filter((group) => related.has(group.id) || group.id === activeId);
  const ordered = [...new Map([...priority, ...main, ...candidates.filter((group) => group.selected.length), ...candidates].map((group) => [group.id, group])).values()];
  // Real neighbors remain visible together even when the candidate budget is
  // small; no relation is cut in half by paging.
  const budget = Math.max(limit - (anchor ? 1 : 0), priority.length);
  return anchor ? [anchor, ...ordered.slice(0, budget)] : ordered.slice(0, limit);
}
export function canvasNodes(groups: ConceptGroup[], anchorId: string): RelationCanvasNode[] {
  return groups.map((group) => ({ id: group.id, title: group.title, bookId: group.bookId, bookTitle: group.bookTitle,
    pageLabel: pageRange(group.selected[0] || group.evidences[0]), evidenceCount: group.evidences.length,
    selected: !!group.selected.length, kind: group.kind, isAnchor: group.id === anchorId }));
}
