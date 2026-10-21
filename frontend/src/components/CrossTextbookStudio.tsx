import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Drawer, Empty, Input, Modal, Select, Spin, message } from 'antd';
import { ArrowLeftOutlined, SaveOutlined, SearchOutlined } from '@ant-design/icons';
import type { Textbook } from '../types';
import type { TeachingBridgeResult } from '../api/teaching';
import { getTeachingBridge, readLocal, writeLocal } from '../api/teaching';
import type { BoardConnection, BoardSelection } from '../api/teachingBoard';
import type { AgentLessonContext } from '../api/lessonAgent';
import ConceptRelationCanvas from './ConceptRelationCanvas';
import KnowledgeDistributionCanvas from './KnowledgeDistributionCanvas';
import { distributionBookTotals, distributionNodePaths, distributionNodePathIds, distributionNodeTitles } from './knowledgeDistributionModel';
import ConceptEvidencePane, { EvidenceQuote, RelationEvidencePane } from './ConceptEvidencePane';
import SourcePageViewer from './SourcePageViewer';
import useTeachingBoard, { boardCacheKey, boardError } from './useTeachingBoard';
import { canvasEdges, canvasNodes, chunkConceptMap, comparisonColumns, conceptGroups, evidenceSelection, lessonPath, moveLessonGroup, pageRange, RELATIONS, sourceTitle, textbookColor, visibleConcepts } from './crossbookModel';
import type { ConceptGroup } from './crossbookModel';
import './CrossTextbookStudio.css';

interface Props {
  courseId: string; textbooks: Textbook[]; sourceBook: Textbook | null; initialQuery: string;
  onBack: () => void; onScopeChange: (ids: string[]) => void; onTopicChange: (query: string) => void;
  onPrepare: (context: AgentLessonContext) => void; onPrepareReady?: (handler: (() => void) | null) => void;
  readOnly?: boolean; refreshToken?: number; children?: React.ReactNode;
}
interface WorkspaceState {
  view: 'explore' | 'lesson'; anchorId: string; activeNodeId: string; lensQuery: string;
  evidenceIds: Record<string, string>; seed: ConceptGroup | null;
  comparisonEvidenceIds?: Record<string, string>;
}
const emptyWorkspace = (topic: string): WorkspaceState => ({ view: 'explore', anchorId: '', activeNodeId: '', lensQuery: topic, evidenceIds: {}, seed: null });
const workspaceKey = (course: string, topic: string, ids: string[]) => boardCacheKey(course, topic, ids) + ':workspace';
const relationKey = (link: BoardConnection) => link.id || link.source_chunk_id + '>' + link.target_chunk_id;
const randomId = () => 'link_' + crypto.randomUUID();

const CrossTextbookStudio: React.FC<Props> = ({ courseId, textbooks, sourceBook, initialQuery, onBack, onScopeChange, onTopicChange, onPrepare, onPrepareReady, readOnly = false }) => {
  const available = textbooks.filter((book) => book.parse_status === 'completed');
  const [start] = useState(() => {
    const previous = readLocal<{ query: string; ids: string[] }>('courseweave:bridge:' + courseId, { query: '', ids: [] });
    const ids = [...new Set([...(sourceBook ? [sourceBook.id] : []), ...previous.ids])].filter((id) => available.some((book) => book.id === id));
    return { topic: initialQuery || previous.query, ids: ids.length >= 2 ? ids : [...new Set([...ids, ...available.map((book) => book.id)])].slice(0, 2) };
  });
  const [query, setQuery] = useState(start.topic);
  const [draftQuery, setDraftQuery] = useState(start.topic);
  const [ids, setIds] = useState(start.ids);
  const boardState = useTeachingBoard(courseId, start.topic, start.ids, readOnly);
  const { board, history, saving, opening, error, setError, conflict, dirty } = boardState;
  const [workspace, setWorkspace] = useState<WorkspaceState>(() => readLocal(workspaceKey(courseId, start.topic, start.ids), emptyWorkspace(start.topic)));
  const [result, setResult] = useState<TeachingBridgeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [moreBook, setMoreBook] = useState('');
  const [limit, setLimit] = useState(Math.max(2, start.ids.length));
  const [bookFilter, setBookFilter] = useState('');
  const [panel, setPanel] = useState<'node' | 'relation'>('node');
  const [editing, setEditing] = useState<BoardConnection | null>(null);
  const [materialsBook, setMaterialsBook] = useState('');
  const [materialsOpen, setMaterialsOpen] = useState(false);
  const [pdf, setPdf] = useState<BoardSelection | null>(null);
  const [pdfPage, setPdfPage] = useState(1);
  const [pathExpanded, setPathExpanded] = useState(false);
  const [presenting, setPresenting] = useState(false);
  const [surface, setSurface] = useState<'compare' | 'graph' | 'distribution'>(() => {
    const saved = readLocal<string>('courseweave:bridge-surface:' + courseId, 'compare');
    return saved === 'graph' || saved === 'distribution' ? saved : 'compare';
  });
  const [distributionLoading, setDistributionLoading] = useState(false);
  const [comparisonBookIds, setComparisonBookIds] = useState(start.ids.slice(0, 2));
  const [detailOpen, setDetailOpen] = useState(false);
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 700px)').matches);
  const request = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const resultRef = useRef(result); resultRef.current = result;
  const bookMap = useMemo(() => new Map(textbooks.map((book) => [book.id, book])), [textbooks]);
  const groups = useMemo(() => conceptGroups(result, board, workspace.seed), [result, board, workspace.seed]);
  const byId = useMemo(() => new Map(groups.map((group) => [group.id, group])), [groups]);
  const chunkMap = useMemo(() => new Map(groups.flatMap((group) => group.evidences.map((source) => [source.chunk_id, source] as const))), [groups]);
  const chunkToConcept = useMemo(() => chunkConceptMap(groups), [groups]);
  const edges = useMemo(() => canvasEdges(board.connections, groups), [board.connections, groups]);
  const path = useMemo(() => lessonPath(groups, board), [groups, board]);
  const fallbackAnchor = groups.find((group) => group.bookId === sourceBook?.id) || path[0] || groups[0];
  const anchorId = workspace.view === 'lesson' ? (path.some((group) => group.id === workspace.anchorId) ? workspace.anchorId : path[0]?.id || '') : byId.has(workspace.anchorId) ? workspace.anchorId : fallbackAnchor?.id || '';
  const anchor = byId.get(anchorId);
  const active = workspace.view === 'lesson' ? path.find((group) => group.id === workspace.activeNodeId) || path[0] || null : byId.get(workspace.activeNodeId) || anchor || null;
  const evidenceConcept = active && workspace.view === 'lesson' ? { ...active, evidences: active.selected } : active;
  const shownGroups = visibleConcepts(groups, edges, anchorId, limit, workspace.view, bookFilter, active?.id);
  const canvasGroups = workspace.view === 'lesson' ? shownGroups.map((group) => ({ ...group, evidences: group.selected })) : shownGroups;
  const activePathIndex = path.findIndex((group) => group.id === active?.id);
  const busy = saving || opening || boardState.hydrating;
  const patchWorkspace = (patch: Partial<WorkspaceState>) => setWorkspace((current) => ({ ...current, ...patch }));
  const openPage = (source: BoardSelection) => { setPdf(source); setPdfPage(Math.max(1, source.page_start)); };
  const effectiveSurface = narrow && surface === 'graph' ? 'compare' : surface;
  const comparisonScope = [...new Set([...comparisonBookIds.filter((id) => ids.includes(id)), ...ids])].slice(0, 2);
  const columns = comparisonColumns(groups, comparisonScope, workspace.comparisonEvidenceIds || {}, workspace.view);
  const [leftSource, rightSource] = columns.map((column) => column.source);
  const distributionGroups = useMemo(() => groups.filter((group) => ids.includes(group.bookId) && (!bookFilter || group.bookId === bookFilter) && (workspace.view === 'explore' || group.selected.length)).map((group) => workspace.view === 'lesson' ? { ...group, evidences: group.selected } : group), [groups, ids, bookFilter, workspace.view]);
  const distributionPaths = useMemo(() => distributionNodePaths(distributionGroups), [distributionGroups]);
  const distributionPathIds = useMemo(() => distributionNodePathIds(distributionGroups), [distributionGroups]);
  const distributionTitles = useMemo(() => distributionNodeTitles(distributionGroups), [distributionGroups]);
  const retrievedChunks = useMemo(() => new Set(result?.groups.flatMap((book) => book.items.map((item) => item.id)) || []), [result]);
  const distributionNodes = useMemo(() => canvasNodes(distributionGroups, anchorId).map((node) => ({ ...node, title: distributionTitles.get(node.id) || node.title, pageLabel: bookMap.get(node.bookId)?.format === 'pdf' ? node.pageLabel : '原文位置', chapterPath: distributionPaths.get(node.id), chapterPathIds: distributionPathIds.get(node.id), retrieved: !!byId.get(node.id)?.evidences.some((source) => retrievedChunks.has(source.chunk_id)) })), [distributionGroups, anchorId, bookMap, distributionPaths, distributionPathIds, distributionTitles, byId, retrievedChunks]);
  const distributionTotals = useMemo(() => distributionBookTotals(distributionGroups, result, ids.filter((id) => !bookFilter || bookFilter === id).map((id) => ({ id, title: bookMap.get(id)?.title || id }))), [distributionGroups, result, ids, bookFilter, bookMap]);
  const distributionHasMore = result?.groups.some((book) => book.has_more && (!bookFilter || book.textbook_id === bookFilter));

  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current?.abort(); }; }, []);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 700px)');
    const resize = () => setNarrow(media.matches);
    media.addEventListener('change', resize); return () => media.removeEventListener('change', resize);
  }, []);
  useEffect(() => { onScopeChange(ids); onTopicChange(query); writeLocal('courseweave:bridge:' + courseId, { query, ids }); }, [courseId, query, ids, onScopeChange, onTopicChange]);
  useEffect(() => { if (query.trim().length >= 2) writeLocal(workspaceKey(courseId, query, ids), workspace); }, [courseId, query, ids, workspace]);
  useEffect(() => { writeLocal('courseweave:bridge-surface:' + courseId, surface); }, [courseId, surface]);
  const runSearch = async (topic: string, scope: string[]) => {
    if (topic.trim().length < 2) { setError('请输入至少两个字的具体知识点'); return; }
    if (scope.length < 2) { setError('跨教材探索至少需要两本教材'); return; }
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setMoreBook(''); setDistributionLoading(false); setError('');
    try { const { data } = await getTeachingBridge(courseId, scope, topic.trim(), controller.signal); if (!controller.signal.aborted && alive.current) setResult(data); }
    catch (e) { if (!controller.signal.aborted && alive.current) setError(boardError(e, '教材检索失败，请重试')); }
    finally { if (!controller.signal.aborted && alive.current) setLoading(false); }
  };
  useEffect(() => { if (start.topic.length >= 2 && start.ids.length >= 2) runSearch(workspace.lensQuery || start.topic, start.ids); }, []);
  const applyScope = (nextTopic: string, nextIds: string[]) => {
    if (busy) return;
    const topic = nextTopic.trim();
    if (topic.length < 2 || topic.length > 80) { setError('请输入2至80字的具体知识点'); return; }
    if (nextIds.length < 2 || nextIds.length > 12) { setError('请选择2至12本教材'); return; }
    if (!boardState.switchScope(topic, nextIds)) return;
    request.current?.abort(); setResult(null); setMoreBook(''); setQuery(topic); setDraftQuery(topic); setIds(nextIds);
    setWorkspace(readLocal(workspaceKey(courseId, topic, nextIds), emptyWorkspace(topic)));
    setBookFilter(''); setEditing(null); setPanel('node'); setLimit(Math.max(2,nextIds.length)); setPresenting(false);
    runSearch(topic, nextIds);
  };
  const changeBooks = (nextIds: string[]) => {
    if (busy) return;
    request.current?.abort(); setLoading(false); setMoreBook(''); setDistributionLoading(false); setResult(null);
    boardState.switchScope(query, nextIds); setIds(nextIds); setBookFilter(''); setLimit(Math.max(2,nextIds.length)); setEditing(null); setPanel('node');
    setWorkspace(emptyWorkspace(query));
  };
  const loadMore = async (bookId: string) => {
    const group = resultRef.current?.groups.find((book) => book.textbook_id === bookId);
    if (!group?.has_more || moreBook || loading || distributionLoading) return;
    const controller = request.current || new AbortController(); request.current = controller; setMoreBook(bookId);
    try {
      const { data } = await getTeachingBridge(courseId, [bookId], workspace.lensQuery || query, controller.signal, group.items.length);
      if (!controller.signal.aborted && alive.current) setResult((current) => current && ({ ...current, groups: current.groups.map((book) => book.textbook_id === bookId ? { ...data.groups[0], items: [...book.items, ...data.groups[0].items].filter((item, at, all) => all.findIndex((other) => other.id === item.id) === at) } : book) }));
    } catch (e) { if (!controller.signal.aborted && alive.current) setError(boardError(e, '更多候选加载失败')); }
    finally { if (!controller.signal.aborted && alive.current) setMoreBook(''); }
  };
  const expandDistribution = async () => {
    const pending = resultRef.current?.groups.filter((book) => book.has_more && (!bookFilter || book.textbook_id === bookFilter));
    if (!pending?.length || loading || moreBook || distributionLoading) return;
    const controller = request.current || new AbortController(); request.current = controller;
    setDistributionLoading(true); setError('');
    const responses = await Promise.allSettled(pending.map((book) => getTeachingBridge(courseId, [book.textbook_id], workspace.lensQuery || query, controller.signal, book.items.length, 8)));
    if (controller.signal.aborted || !alive.current) return;
    const pages = new Map(responses.flatMap((response) => response.status === 'fulfilled' && response.value.data.groups[0] ? [[response.value.data.groups[0].textbook_id, response.value.data.groups[0]] as const] : []));
    setResult((current) => current && ({ ...current, groups: current.groups.map((book) => {
      const page = pages.get(book.textbook_id);
      return page ? { ...page, items: [...new Map([...book.items, ...page.items].map((item) => [item.id, item])).values()] } : book;
    }) }));
    if (responses.some((response) => response.status === 'rejected')) setError('部分教材未能继续展开，已加载的分布仍保留。请点击“展开更多分布”重试。');
    setDistributionLoading(false);
  };
  const revealEvidence = () => { if (window.innerWidth <= 880) requestAnimationFrame(() => document.querySelector('.cw-evidence-column')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); };
  const chooseNode = (id: string) => { patchWorkspace({ activeNodeId: id }); if (effectiveSurface !== 'distribution') setBookFilter(''); setPanel('node'); if (effectiveSurface !== 'graph' && !presenting) setDetailOpen(true); else revealEvidence(); };
  const evidenceOf = (group: ConceptGroup) => {
    const allowed = workspace.view === 'lesson' ? group.selected : group.evidences;
    return allowed.find((source) => source.chunk_id === workspace.evidenceIds[group.id]) || group.selected[0] || allowed[0];
  };
  const addSource = (source: BoardSelection) => {
    if (readOnly || busy) return;
    if (board.selections.some((item) => item.chunk_id === source.chunk_id)) return;
    if (board.selections.length >= 48) return message.info('每次备课最多选用48段原文，请先整理讲授路径');
    boardState.update((current) => ({ ...current, selections: [...current.selections, source] }));
    message.success('已加入本课讲授路径');
  };
  const editSource = (chunkId: string, patch: Partial<BoardSelection>) => boardState.update((current) => ({ ...current, selections: current.selections.map((source) => source.chunk_id === chunkId ? { ...source, ...patch } : source) }));
  const editTitle = (title: string) => {
    if (!active) return;
    const selected = new Set(active.selected.map((source) => source.chunk_id));
    boardState.update((current) => ({ ...current, selections: current.selections.map((source) => selected.has(source.chunk_id) ? { ...source, teaching_title: title } : source) }));
  };
  const focus = (id: string) => {
    if (presenting) return;
    const group = byId.get(id); if (!group) return;
    const source = evidenceOf(group);
    const reliable = source.title_origin === 'source_heading' || source.title_origin === 'source_subheading';
    const topic = (reliable ? source.display_title || query : query).trim().slice(0, 80);
    patchWorkspace({ anchorId: id, activeNodeId: id, seed: group, lensQuery: topic, view: 'explore' });
    setPanel('node'); setBookFilter(''); setLimit(Math.max(2,ids.length)); runSearch(topic, ids);
  };
  const resetFocus = () => {
    if (presenting) return;
    setWorkspace(emptyWorkspace(query)); setBookFilter(''); setLimit(Math.max(2,ids.length)); setPanel('node'); runSearch(query, ids);
  };
  const draftStoreKey = boardCacheKey(courseId, query, ids) + ':relation-edit';
  const openRelation = (link: BoardConnection) => {
    const drafts = readLocal<Record<string, BoardConnection>>(draftStoreKey, {});
    const current = drafts[relationKey(link)] || link;
    setEditing(current); setPanel('relation'); setDetailOpen(true); setBookFilter('');
    patchWorkspace({ anchorId: chunkToConcept.get(current.source_chunk_id) || anchorId, activeNodeId: chunkToConcept.get(current.target_chunk_id) || active?.id || '' });
    if (effectiveSurface === 'graph') revealEvidence();
  };
  const compareColumns = () => {
    if (!leftSource || !rightSource || leftSource.textbook_id === rightSource.textbook_id) return;
    const existing = board.connections.find((link) => (link.source_chunk_id === leftSource.chunk_id && link.target_chunk_id === rightSource.chunk_id) || (link.source_chunk_id === rightSource.chunk_id && link.target_chunk_id === leftSource.chunk_id));
    openRelation(existing || { id: '', source_chunk_id: leftSource.chunk_id, target_chunk_id: rightSource.chunk_id, relation_type: 'related_to', reason: '', status: 'draft' });
  };
  const chooseComparisonBook = (at: number, id: string) => setComparisonBookIds(() => {
    const next = [...comparisonScope], old = next[at], other = at === 0 ? 1 : 0;
    next[at] = id; if (next[other] === id) next[other] = old; return next;
  });
  const showSourceDetail = (source: BoardSelection, conceptId?: string) => {
    if (!conceptId) return;
    patchWorkspace({ activeNodeId: conceptId, evidenceIds: { ...workspace.evidenceIds, [conceptId]: source.chunk_id } });
    setBookFilter(''); setPanel('node'); setDetailOpen(true);
  };
  const changeRelation = (patch: Partial<BoardConnection>) => setEditing((current) => {
    if (!current) return current;
    const next = { ...current, ...patch, status: 'draft' as const };
    const drafts = readLocal<Record<string, BoardConnection>>(draftStoreKey, {});
    writeLocal(draftStoreKey, { ...drafts, [relationKey(current)]: next, [relationKey(next)]: next }); return next;
  });
  const compareWithAnchor = () => {
    if (!active || !anchor || active.bookId === anchor.bookId) return;
    const source = evidenceOf(anchor), target = evidenceOf(active);
    openRelation({ id: '', source_chunk_id: source.chunk_id, target_chunk_id: target.chunk_id, relation_type: 'related_to', reason: '', status: 'draft' });
  };
  const saveRelation = async (status: 'draft' | 'confirmed') => {
    if (!editing || busy || readOnly) return;
    const source = chunkMap.get(editing.source_chunk_id), target = chunkMap.get(editing.target_chunk_id);
    if (!source || !target || source.textbook_id === target.textbook_id) return message.info('请选择两本不同教材的原文');
    if (status === 'confirmed' && !editing.reason.trim()) return message.info('先写明两段材料如何连接、有什么条件，再确认');
    const selections = [...board.selections];
    [source, target].forEach((item) => { if (!selections.some((other) => other.chunk_id === item.chunk_id)) selections.push(item); });
    if (selections.length > 48) return message.info('已超过48段原文，请先整理本课讲授路径');
    const link = { ...editing, id: editing.id || randomId(), status };
    const next = { ...board, selections, connections: [...board.connections.filter((item) => item.id !== link.id), link] };
    boardState.update(() => next);
    if (await boardState.save(next)) {
      const drafts = readLocal<Record<string, BoardConnection>>(draftStoreKey, {}); delete drafts[relationKey(editing)]; delete drafts[relationKey(link)]; writeLocal(draftStoreKey, drafts);
      setEditing(link);
    }
  };
  const deleteRelation = async () => {
    if (!editing?.id || readOnly || busy) return;
    const next = { ...board, connections: board.connections.filter((link) => link.id !== editing.id) };
    boardState.update(() => next); if (await boardState.save(next)) { setEditing(null); setPanel('node'); }
  };
  const removeGroup = (group: ConceptGroup) => {
    const removed = new Set(group.selected.map((source) => source.chunk_id));
    const count = board.connections.filter((link) => removed.has(link.source_chunk_id) || removed.has(link.target_chunk_id)).length;
    boardState.update((current) => ({ ...current, selections: current.selections.filter((source) => !removed.has(source.chunk_id)), connections: current.connections.filter((link) => !removed.has(link.source_chunk_id) && !removed.has(link.target_chunk_id)) }));
    if (editing && (removed.has(editing.source_chunk_id) || removed.has(editing.target_chunk_id))) { setEditing(null); setPanel('node'); }
    if (count) message.info('已从本课移出该知识点及其 ' + count + ' 条关系；保存前仍为本机修改');
  };
  const removeEvidence = (chunkId: string) => {
    const count = board.connections.filter((link) => link.source_chunk_id === chunkId || link.target_chunk_id === chunkId).length;
    boardState.update((current) => ({ ...current, selections: current.selections.filter((source) => source.chunk_id !== chunkId), connections: current.connections.filter((link) => link.source_chunk_id !== chunkId && link.target_chunk_id !== chunkId) }));
    if (editing && (editing.source_chunk_id === chunkId || editing.target_chunk_id === chunkId)) { setEditing(null); setPanel('node'); }
    message.info('已移出此段原文' + (count ? '及其 ' + count + ' 条本课关系' : '') + '，保存前仍为本机修改');
  };
  const openBoard = async (id: string) => {
    const data = await boardState.open(id); if (!data) return;
    setQuery(data.topic); setDraftQuery(data.topic); setIds(data.textbook_ids); setWorkspace(emptyWorkspace(data.topic));
    setResult(null); setEditing(null); setPanel('node'); setBookFilter(''); setLimit(Math.max(2,data.textbook_ids.length));
    runSearch(data.topic, data.textbook_ids);
  };
  const prepare = async () => {
    if (busy || loading || !query.trim()) return;
    let current = boardState.boardRef.current;
    if (current.selections.length && (!current.id || dirty) && !readOnly) { const saved = await boardState.save(); if (!saved) return; current = saved; }
    if (!alive.current) return;
    onPrepare({ topic: query, textbookIds: ids, boardId: current.selections.length && !readOnly ? current.id || undefined : undefined,
      selectedChunkIds: current.selections.map((source) => source.chunk_id), sourceBookId: sourceBook && ids.includes(sourceBook.id) ? sourceBook.id : ids[0],
      focusTerms: [...new Set(current.selections.map((source) => source.dimension).filter((value) => value && value !== '未归类'))].slice(0, 12) });
  };
  useEffect(() => { onPrepareReady?.(prepare); return () => onPrepareReady?.(null); });
  const goPath = (offset: number) => {
    const at = path[Math.max(0, Math.min(path.length - 1, activePathIndex + offset))]; if (at) chooseNode(at.id);
  };
  const beginLecture = () => {
    if (!path.length) return;
    patchWorkspace({ view: 'lesson', activeNodeId: path[0].id }); setPanel('node'); setPresenting(true);
  };
  useEffect(() => {
    if (!presenting) return;
    const key = (event: KeyboardEvent) => {
      if (pdf || /INPUT|TEXTAREA|SELECT/.test((event.target as HTMLElement)?.tagName || '')) return;
      if (event.key === 'Escape') setPresenting(false);
      if (event.key === 'ArrowRight') { event.preventDefault(); goPath(1); }
      if (event.key === 'ArrowLeft') { event.preventDefault(); goPath(-1); }
    };
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key);
  }, [presenting, activePathIndex, path, pdf]);
  const downloadConflict = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(conflict, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = 'CourseWeave-本机关系冲突稿.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const downloadBackup = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(boardState.backup, null, 2)], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = 'CourseWeave-切换前的本机稿.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const compareDisabledReason = !anchor ? '先选择当前讲授点' : !active || active.id === anchor.id ? '选择另一教材的知识点，即可对照' : active.bookId === anchor.bookId ? '请选另一教材的知识点' : undefined;
  const foundBooks = result?.groups.filter((book) => (book.total_matches ?? book.items.length) > 0).length || 0;
  const materialGroup = result?.groups.find((book) => book.textbook_id === materialsBook) || result?.groups[0];
  const sources = [...chunkMap.values()];
  const visibleError = boardState.localStored ? error : error.replace(/本机草稿仍保留/g, '请保留当前页面并重试保存').replace(/本机修改已另存冲突稿/g, '当前冲突稿可在本页面导出');
  const nodePane = <ConceptEvidencePane topic={query} concept={evidenceConcept} activeEvidenceId={active ? workspace.evidenceIds[active.id] : undefined} onEvidenceChange={(id) => active && patchWorkspace({ evidenceIds: { ...workspace.evidenceIds, [active.id]: id } })} onAdd={addSource} onRemoveEvidence={removeEvidence} onTitleChange={editTitle} onNoteChange={(id, note) => editSource(id, { note })} onDimensionChange={(id, dimension) => editSource(id, { dimension })} onCompareWithAnchor={compareWithAnchor} compareDisabledReason={compareDisabledReason} onOpenPage={openPage} readOnly={readOnly} busy={busy} presenting={presenting} showCompareAction={effectiveSurface !== 'compare'} />;
  const relationPane = editing && <RelationEvidencePane editing={editing} sources={sources} onChange={changeRelation} onSave={saveRelation} onDelete={deleteRelation} onCancel={() => { setPanel('node'); setDetailOpen(false); }} onOpenPage={openPage} readOnly={readOnly} busy={busy} />;

  return <section className={'cross-workbench' + (presenting ? ' cross-presenting' : '')}>
    {!presenting ? <>
      <header className="cw-heading"><div><button className="text-link cw-back" onClick={onBack}><ArrowLeftOutlined /> {sourceBook ? '返回教材阅读位置' : '返回教材库'}</button><h1>跨教材选材</h1></div><div className="cw-actions"><Button icon={<SaveOutlined />} loading={saving} disabled={readOnly || opening || (!board.id && !board.selections.length) || (!!board.id && !dirty)} onClick={() => boardState.save()}>保存本课</Button><Button type="primary" disabled={busy || loading || !query.trim() || ids.length < 2} onClick={prepare}>带入备课 Agent →</Button></div></header>
      <form className="cw-search" onSubmit={(event) => { event.preventDefault(); applyScope(draftQuery, ids); }}><label>课题<Input aria-label="本课知识点" maxLength={80} value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} placeholder="如：甲状腺的位置与形态" disabled={busy} /></label><label>教材范围<Select mode="multiple" aria-label="检索教材" maxTagCount="responsive" value={ids} options={available.map((book) => ({ value: book.id, label: book.title }))} onChange={changeBooks} disabled={busy} /></label><Button htmlType="submit" type="primary" icon={<SearchOutlined />} loading={loading} disabled={busy}>检索原文</Button></form>
      <div className="cw-summary"><span>{board.selections.length} 段已选材料 · {board.connections.filter((link) => link.status === 'confirmed').length} 条已确认关系</span><span className={dirty || !boardState.localStored ? 'cw-unsaved' : ''}>{!boardState.localStored ? '本机暂存失败 · 请保存到课程' : dirty ? '有未保存到课程的修改' : board.id ? '已保存 · 版本 ' + board.revision : '核对原文后加入本课'}</span></div>
    </> : <header className="cw-lecture-header"><div><small>材料路径预览</small><h1>{query}</h1></div><div><Button disabled={activePathIndex <= 0} onClick={() => goPath(-1)}>← 上一个</Button><span>{Math.max(1, activePathIndex + 1)} / {path.length}</span><Button disabled={activePathIndex + 1 >= path.length} onClick={() => goPath(1)}>下一个 →</Button><Button onClick={() => setPresenting(false)}>退出预览</Button></div></header>}
    {error && <Alert type="error" message={visibleError} closable onClose={() => setError('')} />}
    {!boardState.localStored && !presenting && <Alert type="warning" showIcon message="本机暂存失败" description={dirty || !board.id ? '当前修改只在此页面内，请先保存到课程。刷新或关闭页面可能丢失未保存修改。' : '本课已保存到课程，本机恢复缓存暂不可用。'} />}
    {conflict && !presenting && <Alert type="warning" message={boardState.localStored ? '保留了一份本机冲突稿' : '存在版本冲突 · 本机暂存未成功'} description={boardState.localStored ? '打开课程最新版不会覆盖备份，可先导出对照后手动合并。' : '请先导出当前页面的冲突稿，再打开最新版核对。'} action={<Button onClick={downloadConflict}>导出冲突稿</Button>} />}
    {boardState.backup && !presenting && <div className="cw-draft-backup" role="status"><span>{boardState.localStored ? `切换前的“${boardState.backup.board.topic}”未保存稿已独立备份，包含当时的标题、备注和顺序。` : `切换前的“${boardState.backup.board.topic}”仍可在本页面导出；本机缓存未成功写入。`}</span><Button size="small" onClick={downloadBackup}>导出核对</Button></div>}
    {presenting ? <main className="cw-path-preview">{nodePane}</main> : <>
      <div className="cw-workspace-bar"><div className="cw-view-control" aria-label="材料范围"><button aria-pressed={workspace.view === 'explore'} className={workspace.view === 'explore' ? 'active' : ''} onClick={() => patchWorkspace({ view: 'explore' })}>检索候选</button><button aria-pressed={workspace.view === 'lesson'} className={workspace.view === 'lesson' ? 'active' : ''} onClick={() => patchWorkspace({ view: 'lesson' })}>本课材料 {board.selections.length}</button></div><div className="cw-surface-control cw-view-control" aria-label="材料显示方式"><button aria-pressed={effectiveSurface === 'compare'} className={effectiveSurface === 'compare' ? 'active' : ''} onClick={() => { setSurface('compare'); setDetailOpen(false); }}>原文对照</button><button aria-pressed={effectiveSurface === 'distribution'} className={effectiveSurface === 'distribution' ? 'active' : ''} onClick={() => { setSurface('distribution'); setDetailOpen(false); requestAnimationFrame(() => document.querySelector('.knowledge-distribution')?.scrollIntoView({ behavior: 'smooth', block: 'start' })); }}>知识分布</button><button aria-pressed={effectiveSurface === 'graph'} className={'cw-old-relations' + (effectiveSurface === 'graph' ? ' active' : '')} onClick={() => { setSurface('graph'); setDetailOpen(false); }}>教学关系</button></div>{effectiveSurface === 'compare' && <Button className="cw-compare-action" disabled={!leftSource || !rightSource || loading || busy} onClick={compareColumns}>核对两段关系</Button>}<Button className="cw-all-materials" size="small" type="text" disabled={!result} onClick={() => { setMaterialsBook(active?.bookId || ids[0]); setMaterialsOpen(true); }}>全部候选材料 ↗</Button></div>
      {loading && <div className="cw-loading" role="status"><Spin size="small" /> 正在检索{workspace.lensQuery && workspace.lensQuery !== query ? '“' + workspace.lensQuery + '”的' : ''}教材原文…</div>}
      {effectiveSurface === 'compare' ? <main className="cw-comparison" aria-label="不同教材的原文对照">
        {!query ? <div className="cw-search-guide"><strong>从今天要讲的一个知识点开始</strong><p>选择至少两本教材，检索后对照原文，再把要讲的材料加入本课。</p></div> : <>
          <div className="cw-comparison-columns">{columns.map((column, index) => {
            const source = column.source;
            const selected = Boolean(source && board.selections.some((item) => item.chunk_id === source.chunk_id));
            const sourceAt = source ? column.sources.findIndex((item) => item.chunk_id === source.chunk_id) : -1;
            const resultGroup = result?.groups.find((book) => book.textbook_id === column.bookId);
            const pick = (id: string) => patchWorkspace({ comparisonEvidenceIds: { ...workspace.comparisonEvidenceIds, [column.bookId]: id } });
            return <article className="cw-comparison-book" key={column.bookId} style={{ '--cw-book-color': textbookColor(column.bookId) } as React.CSSProperties}>
              <header><span className="cw-comparison-side">{index === 0 ? 'A' : 'B'}</span><label><span>对照教材</span><Select aria-label={`对照${index === 0 ? 'A' : 'B'}侧教材`} value={column.bookId} options={ids.map((id) => ({ value: id, label: bookMap.get(id)?.title || id }))} onChange={(id) => chooseComparisonBook(index, id)} disabled={busy} /></label><span className={selected ? 'cw-source-selected' : 'cw-source-candidate'}>{selected ? '✓ 已选入本课' : source ? '检索候选' : workspace.view === 'lesson' ? '尚未选入' : result ? '未召回' : '待检索'}</span></header>
              {source ? <>
                <label className="cw-passage-picker"><span>原文 <small>{sourceAt + 1} / {column.sources.length}</small></span><Select aria-label={`切换${bookMap.get(column.bookId)?.title || column.bookTitle}原文`} value={source.chunk_id} options={column.sources.map((item) => ({ value: item.chunk_id, label: `${sourceTitle(item, query)} · ${pageRange(item)}${board.selections.some((selectedSource) => selectedSource.chunk_id === item.chunk_id) ? ' · 已选' : ''}` }))} onChange={pick} /></label>
                <div className="cw-passage-heading"><h2 title={sourceTitle(source, query)}>{sourceTitle(source, query)}</h2><Button type="link" onClick={() => openPage(source)}>{pageRange(source)} ↗</Button></div>
                <p className="cw-passage-path" title={[...new Set([source.chapter, ...source.section_path].filter(Boolean))].join(' / ')}>{[...new Set([source.chapter, ...source.section_path].filter(Boolean))].join(' / ')}</p>
                <footer><Button onClick={() => openPage(source)}>查看{bookMap.get(column.bookId)?.format === 'pdf' ? '原页' : '原文'}</Button><Button type="primary" disabled={readOnly || busy || selected} onClick={() => addSource(source)}>{selected ? '✓ 已选入本课' : '加入本课'}</Button><Button type="text" onClick={() => showSourceDetail(source, column.conceptId)}>{selected ? '讲授备注与编辑' : '材料详情'}</Button></footer>
                <EvidenceQuote source={source} query={workspace.lensQuery || query} compact />
                {source.note && <p className="cw-passage-note"><strong>讲授备注</strong>{source.note}</p>}
                <div className="cw-passage-navigation"><Button size="small" disabled={sourceAt <= 0} onClick={() => pick(column.sources[sourceAt - 1].chunk_id)} aria-label={`上一段${bookMap.get(column.bookId)?.title || column.bookTitle}原文`}>← 上一段</Button><span>{pageRange(source)}</span><Button size="small" disabled={sourceAt + 1 >= column.sources.length} onClick={() => pick(column.sources[sourceAt + 1].chunk_id)} aria-label={`下一段${bookMap.get(column.bookId)?.title || column.bookTitle}原文`}>下一段 →</Button></div>
              </> : <div className="cw-comparison-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={loading ? '正在检索教材…' : workspace.view === 'lesson' ? '这本教材还没有选入本课的原文' : result ? '本次未召回原文，可换一个具体术语' : '点击“检索原文”查看这本教材'} />{workspace.view === 'lesson' && <Button onClick={() => patchWorkspace({ view: 'explore' })}>查看检索候选</Button>}</div>}
              {resultGroup?.has_more && workspace.view === 'explore' && <Button className="cw-more-passages" type="text" loading={moreBook === column.bookId} disabled={loading || !!moreBook} onClick={() => loadMore(column.bookId)}>载入更多原文 · {resultGroup.items.length} / {resultGroup.total_matches ?? '更多'}</Button>}
            </article>;
          })}</div>
          <p className="cw-comparison-hint">{workspace.lensQuery && workspace.lensQuery !== query ? '当前材料检索词：' + workspace.lensQuery + '。' : ''}高亮仅表示与检索词相同的文字。完整目录可在材料详情中核对。</p>
          {ids.length > 2 && <p className="cw-comparison-hint">本次检索了 {ids.length} 本教材，可在每侧的教材菜单切换；当前并排核对两本。</p>}
        </>}
      </main> : effectiveSurface === 'distribution' ? <main className="cw-distribution-shell" aria-label="跨教材知识分布">
        <div className="cw-distribution-context"><p>一个节点是一本教材中的来源模块，点击核对教材证据。圆环表示分组，深色连线表示本课记录的教学关系。</p><div><Select aria-label="知识分布教材筛选" value={bookFilter || undefined} allowClear placeholder="全部所选教材" onChange={(id) => setBookFilter(id || '')} options={ids.map((id) => ({ value: id, label: bookMap.get(id)?.title || id }))} />{available.length > ids.length && available.length <= 12 && <Button disabled={busy || loading || distributionLoading} onClick={() => applyScope(query, available.map((book) => book.id))}>扩展至本课程 {available.length} 本</Button>}<Button loading={distributionLoading} disabled={loading || !!moreBook || !distributionHasMore || workspace.view === 'lesson'} onClick={expandDistribution}>{result && !distributionHasMore ? (bookFilter ? '当前教材候选已载入' : '本次候选已全部载入') : '展开更多分布'}</Button></div></div>
        <KnowledgeDistributionCanvas topic={workspace.lensQuery || query || '本课知识点'} nodes={distributionNodes} edges={edges} bookTotals={distributionTotals} activeNodeId={active?.id} activeEdgeId={panel === 'relation' ? editing?.id : undefined} view={workspace.view} loading={loading || distributionLoading} onShowMore={workspace.view === 'explore' && distributionHasMore ? expandDistribution : undefined} onNodeClick={chooseNode} onEdgeClick={(id) => { const link = board.connections.find((item) => item.id === id); if (link) openRelation(link); }} />
        <p className="cw-distribution-footnote">{workspace.view === 'lesson' ? '当前仅展示本课已选模块。' : '图中展示已载入的检索模块，并保留本课已选材料；未载入部分可以继续展开。'}原文数量和模块数量不同，未召回不代表教材没有相关内容。</p>
      </main> : <div className={'cw-main-layout' + (panel === 'relation' ? ' cw-comparing' : '')}>
        <main className="cw-graph-column"><div className="cw-graph-tools"><Select aria-label="图中教材筛选" value={bookFilter || undefined} allowClear placeholder="全部教材" onChange={(id) => { setBookFilter(id || ''); setLimit(2); }} options={ids.map((id) => ({ value: id, label: bookMap.get(id)?.title || id }))} /><span>仅显示本课记录的关系；候选不会自动连线。</span></div><ConceptRelationCanvas topic={workspace.lensQuery || query || '本课知识点'} nodes={canvasNodes(canvasGroups, anchorId)} edges={edges} activeNodeId={active?.id} activeEdgeId={panel === 'relation' ? editing?.id : undefined} view={workspace.view} onNodeClick={chooseNode} onEdgeClick={(id) => { const link = board.connections.find((item) => item.id === id); if (link) openRelation(link); }} onFocus={focus} onResetFocus={resetFocus} hiddenNodeCount={Math.max(0, groups.filter((group) => !bookFilter || group.bookId === bookFilter).length - shownGroups.length)} onShowMore={() => setLimit((current) => current + 8)} /></main>
        <aside className="cw-evidence-column" aria-label="知识点与关系证据"><div className="cw-evidence-tabs"><button className={panel === 'node' ? 'active' : ''} onClick={() => setPanel('node')}>知识点证据</button><button className={panel === 'relation' ? 'active' : ''} disabled={!editing} onClick={() => setPanel('relation')}>双侧关系核对</button></div>{panel === 'relation' && editing ? relationPane : nodePane}</aside>
      </div>}
      <details className="cw-utility"><summary>已保存的本课与教材覆盖{result ? ` · ${foundBooks}/${ids.length} 本召回原文` : ''}</summary><label className="cw-history">已保存的本课<Select aria-label="已保存的本课" placeholder="打开已保存的讲授路径" value={board.id || undefined} options={history.map((item) => ({ value: item.id, label: item.topic + ' · ' + item.selection_count + ' 段证据' }))} onChange={openBoard} disabled={busy} /></label><div className="cw-coverage"><div>{ids.map((id) => { const book = result?.groups.find((entry) => entry.textbook_id === id); return <button key={id} disabled={!book?.items.length} onClick={() => { setMaterialsBook(id); setMaterialsOpen(true); }}><strong>{bookMap.get(id)?.title}</strong><span>{book ? (book.total_matches ?? book.items.length) + ' 条候选' : '待检索'}</span></button>; })}</div><p>未召回不代表没有关联；候选数量不代表已验证的知识关系。</p></div></details>
    </>}
    {!presenting && <section className="cw-path"><header><div><span>本课材料 · {board.selections.length} 段原文</span><h2>{path.length ? '整理讲授顺序' : '把要讲的材料收集在这里'}</h2><p>顺序与知识关系分别保存；整理后可带入备课 Agent 生成教案。</p></div><Button disabled={!path.length} onClick={beginLecture}>预览材料路径 →</Button></header>{path.length ? <ol>{(pathExpanded ? path : path.slice(0, 5)).map((group, index) => <li key={group.id} className={active?.id === group.id ? 'active' : ''}><span className="cw-step-number">{String(index + 1).padStart(2, '0')}</span><button className="cw-path-node" onClick={() => chooseNode(group.id)}><strong>{group.title}</strong><small>{group.bookTitle} · {group.selected.length} 段原文 · {pageRange(group.selected[0])}</small></button><div><Button size="small" aria-label={'上移讲授点：' + group.title} disabled={readOnly || busy || index === 0} onClick={() => boardState.update((current) => moveLessonGroup(current, groups, group.id, -1))}>↑</Button><Button size="small" aria-label={'下移讲授点：' + group.title} disabled={readOnly || busy || index === path.length - 1} onClick={() => boardState.update((current) => moveLessonGroup(current, groups, group.id, 1))}>↓</Button><Button size="small" type="text" danger disabled={readOnly || busy} onClick={() => removeGroup(group)}>移出本课</Button></div></li>)}</ol> : <div className="cw-path-empty">在原文卡片点击“加入本课”，或核对关系后将两侧原文一并选入。</div>}{path.length > 5 && <Button type="text" onClick={() => setPathExpanded(!pathExpanded)}>{pathExpanded ? '收起路径' : '展开全部 ' + path.length + ' 个讲授点'}</Button>}</section>}
    {!presenting && !!board.connections.length && <details className="cw-relationships"><summary>本课已记录的联系与差异（{board.connections.length}）</summary>{board.connections.map((link) => <button key={link.id} onClick={() => openRelation(link)}><span className={'cw-relation-state ' + link.status}>{link.status === 'confirmed' ? '教师已确认' : '关系草稿'}</span><strong>{byId.get(chunkToConcept.get(link.source_chunk_id) || '')?.title} / {byId.get(chunkToConcept.get(link.target_chunk_id) || '')?.title}</strong><span>{RELATIONS[link.relation_type]}</span><p>{link.reason || '待补充关系理由'}</p></button>)}</details>}
    <Drawer open={detailOpen && effectiveSurface !== 'graph' && !presenting} onClose={() => setDetailOpen(false)} width={panel === 'relation' ? 1080 : 560} title={panel === 'relation' ? '核对双侧证据与关系' : '材料详情与本课备注'} destroyOnClose>{panel === 'relation' && editing ? relationPane : nodePane}</Drawer>
    <Drawer open={materialsOpen} onClose={() => setMaterialsOpen(false)} width={650} title="全部检索候选" destroyOnClose><div className="cw-material-drawer"><Select aria-label="候选材料教材" value={materialGroup?.textbook_id} options={result?.groups.map((book) => ({ value: book.textbook_id, label: book.title + ' · ' + (book.total_matches ?? book.items.length) + ' 条' }))} onChange={setMaterialsBook} /><p>词语匹配尚未证明教学关系，逐条核对原文后选用。</p>{materialGroup?.items.length ? materialGroup.items.map((item) => { const source = chunkMap.get(item.id) || evidenceSelection(item, materialGroup.textbook_id, materialGroup.title); const conceptId = chunkToConcept.get(source.chunk_id), selected = board.selections.some((entry) => entry.chunk_id === source.chunk_id); return <article key={item.id}><small>{materialGroup.title} · {pageRange(source)}</small><h3>{sourceTitle(source, query)}</h3><p>{source.quote.slice(0, 220)}{source.quote.length > 220 ? '…' : ''}</p><div><Button onClick={() => { showSourceDetail(source, conceptId); setMaterialsOpen(false); }}>核对与备注</Button><Button onClick={() => openPage(source)}>查看原页</Button><Button disabled={readOnly || busy || selected} onClick={() => addSource(source)}>{selected ? '已在本课' : '加入本课'}</Button></div></article>; }) : <Empty description="本次未召回相关原文，可换术语或核对教材章节" />}{materialGroup?.has_more && <Button block loading={moreBook === materialGroup.textbook_id} disabled={loading || !!moreBook} onClick={() => loadMore(materialGroup.textbook_id)}>加载更多原文（已载入 {materialGroup.items.length} / {materialGroup.total_matches}）</Button>}</div></Drawer>
    <Modal open={!!pdf} onCancel={() => setPdf(null)} footer={null} width={1050} title="核对教材原页" destroyOnClose>{pdf && <div className="cw-pdf-detail"><div><small>{pdf.textbook_title} · {pageRange(pdf)}</small><h3>{sourceTitle(pdf, query)}</h3><p className="cw-original-heading">原目录：{[pdf.chapter, ...pdf.section_path.filter((heading) => heading !== pdf.chapter)].join(' / ')}</p><blockquote>{pdf.quote}</blockquote>{pdf.quote_truncated && <small>此处为原文节选，完整上下文以原页为准。</small>}</div>{bookMap.get(pdf.textbook_id)?.format === 'pdf' ? <SourcePageViewer textbookId={pdf.textbook_id} title={pdf.textbook_title} page={pdfPage} totalPages={bookMap.get(pdf.textbook_id)?.total_pages || pdf.page_end} onPageChange={setPdfPage} /> : <p>此教材没有 PDF 原页，请核对左侧已解析原文。</p>}</div>}</Modal>
  </section>;
};
export default CrossTextbookStudio;
