import type { BoardSelection } from '../api/teachingBoard';
import type { ConceptGroup } from './crossbookModel';

/** Optional source metadata is read here without importing the Canvas or React. */
type LocatedSource = BoardSelection & { chapter_id?: string; section_path_ids?: string[] };
type Segment = { title: string; token: string };
export interface DistributionScopeBook { id: string; title?: string }
export interface DistributionResultBook {
  textbook_id: string; title?: string; items: readonly { id: string }[];
  total_matches?: number; has_more?: boolean;
}
export interface DistributionResult { groups: readonly DistributionResultBook[] }
export interface DistributionBookSummary {
  id: string; title: string;
  /** Unique candidate passages in this response, excluding board/seed additions. */
  loaded: number;
  /** Total candidate passages for this query, never total knowledge modules. */
  total: number | null;
  moduleCount: number;
  /** Unique loaded/retained passages represented by these ConceptGroups. */
  evidenceCount: number;
  selectedModuleCount: number;
  selectedEvidenceCount: number;
  hasMore: boolean;
  loadState: 'not_loaded' | 'partial' | 'loaded' | 'unknown' | 'inconsistent';
  /** Only this query's candidate pagination is complete; never all book knowledge. */
  completeForQuery: boolean;
}

const value = (input: unknown): string => typeof input === 'string' ? input.trim() : '';
const compare = (first: string, second: string) => first < second ? -1 : first > second ? 1 : 0;
const page = (input: unknown): number => typeof input === 'number' && Number.isFinite(input) && input >= 1 ? input : Infinity;
const evidenceId = (source: Pick<BoardSelection, 'chunk_id' | 'id'>) => value(source.chunk_id) || value(source.id);

/** Keep module identity exactly as conceptGroups established it; do not regroup by names. */
function moduleSources(group: ConceptGroup): LocatedSource[] {
  const unique = new Map<string, LocatedSource>();
  [...group.evidences, ...group.selected].forEach((source) => {
    if (source.textbook_id !== group.bookId) return;
    const id = evidenceId(source);
    if (id && !unique.has(id)) unique.set(id, source);
  });
  return [...unique.values()].sort((first, second) => page(first.page_start) - page(second.page_start)
    || compare(evidenceId(first), evidenceId(second)));
}

function sourceSegments(source: LocatedSource): Segment[] {
  const chapter = value(source.chapter), chapterId = value(source.chapter_id);
  const path = Array.isArray(source.section_path) ? source.section_path : [];
  const ids = Array.isArray(source.section_path_ids) ? source.section_path_ids : [];
  const segments = path.flatMap((heading, index) => {
    const title = value(heading);
    if (!title) return [];
    const id = value(ids[index]);
    return [{ title, token: id ? `id:${id}` : `label:${title}` }];
  });
  if (chapter) {
    if (segments[0]?.title === chapter) {
      // A chapter ID distinguishes repeated chapter labels within the same book.
      if (chapterId && !value(ids[0])) segments[0] = { title: chapter, token: `id:${chapterId}` };
    } else segments.unshift({ title: chapter, token: chapterId ? `id:${chapterId}` : `label:${chapter}` });
  }
  return segments;
}

/** A module spanning different leaves belongs only under their proven common ancestor. */
function commonSegments(group: ConceptGroup): Segment[] {
  const paths = moduleSources(group).map(sourceSegments);
  if (!paths.length) return [];
  const common = [...paths[0]];
  for (const path of paths.slice(1)) {
    let length = 0;
    while (length < common.length && length < path.length && common[length].token === path[length].token) length++;
    common.length = length;
  }
  return common;
}

/** Human-readable source hierarchy, not inferred concept or prerequisite relationships. */
export function distributionNodePaths(groups: readonly ConceptGroup[]): Map<string, string[]> {
  return new Map([...groups].sort((a, b) => compare(a.id, b.id)).map((group) => [group.id, commonSegments(group).map((segment) => segment.title)]));
}

function meaningfulSourceHeading(heading: string): boolean {
  const numbering = '[一二三四五六七八九十百千\\d０-９]+';
  const normalized = heading
    .replace(new RegExp(`^第\\s*${numbering}\\s*[章节篇部]\\s*`), '')
    .replace(new RegExp(`^(?:[（(]\\s*${numbering}\\s*[）)]|${numbering}(?:[.．]${numbering})*[、.．]|${numbering}\\s+)\\s*`), '')
    .replace(/[【】\[\]（）()]/g, '').replace(/\s+/g, '');
  return Boolean(normalized) && !/^(?:内容|正文|本章正文|本节正文|概述|概论|绪论|绪言|前言|导论|引言)$/.test(normalized);
}

/**
 * Generic topic excerpts borrow only their proven source context, not an inferred
 * concept name. The Canvas must keep the excerpt kind label and original node ID.
 */
export function distributionNodeTitles(groups: readonly ConceptGroup[]): Map<string, string> {
  return new Map([...groups].sort((a, b) => compare(a.id, b.id)).map((group) => {
    const teacherNamed = [...group.evidences, ...group.selected].some((source) => source.textbook_id === group.bookId && value(source.teaching_title));
    if (group.kind !== 'topic_excerpt' || teacherNamed) return [group.id, group.title];
    const heading = commonSegments(group).map((segment) => segment.title).reverse().find(meaningfulSourceHeading);
    return [group.id, heading ? `${heading} · 相关原文` : group.title];
  }));
}

/**
 * Stable book-scoped ancestry keys for directory grouping. Use these as branch IDs
 * and distributionNodePaths only for labels. Explicit IDs outrank matching names;
 * missing identity is not guessed from another source's matching heading.
 */
export function distributionNodePathIds(groups: readonly ConceptGroup[]): Map<string, string[]> {
  return new Map([...groups].sort((a, b) => compare(a.id, b.id)).map((group) => {
    const path = commonSegments(group);
    return [group.id, path.map((_, index) => JSON.stringify([group.bookId, ...path.slice(0, index + 1).map((segment) => segment.token)]))];
  }));
}

/** Stable source order for layout; selected state and teacher display titles never move modules. */
export function distributionNodeOrder(groups: readonly ConceptGroup[], bookOrder: readonly string[] = []): string[] {
  const rank = new Map([...new Set(bookOrder)].map((id, index) => [id, index]));
  return [...groups].sort((first, second) => {
    const bookRank = (rank.get(first.bookId) ?? Infinity) - (rank.get(second.bookId) ?? Infinity);
    return bookRank || compare(first.bookId, second.bookId)
      || page(moduleSources(first)[0]?.page_start) - page(moduleSources(second)[0]?.page_start)
      || compare(first.id, second.id);
  }).map((group) => group.id);
}

/**
 * Explicit scope order includes books with zero matches. With no supplied scope,
 * use discovered book IDs in lexical order. A response is query coverage, never a
 * census of the book: moduleCount, retained passages and pagination stay separate.
 */
export function distributionBookTotals(
  groups: readonly ConceptGroup[],
  result: DistributionResult | null | undefined,
  scopeBooks: readonly DistributionScopeBook[] = [],
): DistributionBookSummary[] {
  const response = new Map((result?.groups || []).map((book) => [book.textbook_id, book]));
  const scopes = new Map(scopeBooks.map((book) => [book.id, book]));
  const ids = scopes.size ? [...scopes.keys()] : [...new Set([...response.keys(), ...groups.map((group) => group.bookId)])].sort(compare);
  return ids.map((id) => {
    const modules = [...new Map(groups.filter((group) => group.bookId === id).map((group) => [group.id, group])).values()];
    const row = response.get(id);
    const candidateIds = new Set((row?.items || []).map((item) => value(item.id)).filter(Boolean));
    const loaded = candidateIds.size;
    const reported = row?.total_matches;
    const total = typeof reported === 'number' && Number.isInteger(reported) && reported >= 0 ? reported : null;
    const evidenceIds = new Set(modules.flatMap((group) => moduleSources(group).map(evidenceId)));
    const selectedIds = new Set(modules.flatMap((group) => group.selected.filter((source) => source.textbook_id === id).map(evidenceId)).filter(Boolean));
    const selectedModuleCount = modules.filter((group) => group.selected.some((source) => source.textbook_id === id && evidenceId(source))).length;
    const inconsistent = total !== null && (total < loaded || (row?.has_more === false && total > loaded));
    const hasMore = row?.has_more === true || (total !== null && total > loaded);
    const completeForQuery = Boolean(row && total !== null && total === loaded && !hasMore && !inconsistent);
    const loadState = !row ? 'not_loaded' : inconsistent ? 'inconsistent' : hasMore ? 'partial' : completeForQuery ? 'loaded' : 'unknown';
    return {
      id, title: value(scopes.get(id)?.title) || value(row?.title) || modules.map((group) => group.bookTitle).filter(Boolean).sort(compare)[0] || id,
      loaded, total, moduleCount: modules.length, evidenceCount: evidenceIds.size,
      selectedModuleCount, selectedEvidenceCount: selectedIds.size, hasMore, loadState, completeForQuery,
    };
  });
}
