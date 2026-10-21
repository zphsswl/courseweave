import { useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { readLocal, writeLocal } from '../api/teaching';
import { boardPayload, createTeachingBoard, getTeachingBoard, getTeachingSources, listTeachingBoards, updateTeachingBoard } from '../api/teachingBoard';
import type { BoardSummary, TeachingBoard } from '../api/teachingBoard';

export const boardCacheKey = (course: string, topic: string, ids: string[]) =>
  'courseweave:board-draft:' + course + ':' + topic.trim().toLowerCase() + ':' + [...ids].sort().join(',');
const fresh = (course: string, topic: string, ids: string[]): TeachingBoard => ({ id: '', course_id: course, topic: topic.trim(), textbook_ids: ids, revision: 0, selections: [], connections: [] });
interface DraftBackup { board: TeachingBoard; saved: string; createdAt: string }
export const boardFingerprint = (board: TeachingBoard) => JSON.stringify(boardPayload(board));
const normalizeSaved = (value: string) => {
  try { const data = JSON.parse(value); return JSON.stringify({ ...data, selections: data.selections.map((source: any) => ({ chunk_id: source.chunk_id, dimension: source.dimension || '', note: source.note || '', teaching_title: source.teaching_title || '' })) }); }
  catch { return value; }
};
const cached = (course: string, topic: string, ids: string[]) => {
  const value = readLocal<{ board: TeachingBoard; saved: string } | null>(boardCacheKey(course, topic, ids), null);
  return value?.board?.course_id === course && Array.isArray(value.board.selections) && Array.isArray(value.board.connections)
    ? { board: value.board, saved: normalizeSaved(value.saved) } : { board: fresh(course, topic, ids), saved: '' };
};
export function boardError(error: any, fallback: string): string {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((item) => typeof item?.msg === 'string' ? item.msg : '请检查输入内容').join('；');
  return fallback;
}

export default function useTeachingBoard(courseId: string, initialTopic: string, initialIds: string[], readOnly: boolean) {
  const [initial] = useState(() => cached(courseId, initialTopic, initialIds));
  const [board, setBoard] = useState(initial.board);
  const [saved, setSaved] = useState(initial.saved);
  const [history, setHistory] = useState<BoardSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [opening, setOpening] = useState(false);
  const [hydrating, setHydrating] = useState(false);
  const [error, setError] = useState('');
  const [localStored, setLocalStored] = useState(true);
  const [conflict, setConflict] = useState<TeachingBoard | null>(() => readLocal(boardCacheKey(courseId, initialTopic, initialIds) + ':conflict', null));
  const [backup, setBackup] = useState<DraftBackup | null>(() => readLocal(boardCacheKey(courseId, initialTopic, initialIds) + ':draft-backup', null));
  const boardRef = useRef(board), savedRef = useRef(saved), savingRef = useRef(false), alive = useRef(true);
  const openRequest = useRef<AbortController | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
  const metadataRequest = useRef<AbortController | null>(null);
  const metadataAttempted = useRef(new Set<string>());
  const retain = (value: TeachingBoard, marker: string) => {
    if (value.topic.trim().length >= 2) setLocalStored(writeLocal(boardCacheKey(courseId, value.topic, value.textbook_ids), { board: value, saved: marker }));
  };
  const accept = (value: TeachingBoard, marker = savedRef.current) => {
    boardRef.current = value; savedRef.current = marker; retain(value, marker);
    if (alive.current) { setBoard(value); setSaved(marker); }
  };
  const update = (transform: (current: TeachingBoard) => TeachingBoard) => {
    if (savingRef.current || readOnly) return;
    accept(transform(boardRef.current));
  };
  const retainBackup = () => {
    const current = boardRef.current;
    if (!(current.id || current.selections.length) || boardFingerprint(current) === savedRef.current) return;
    const value = { board: current, saved: savedRef.current, createdAt: new Date().toISOString() };
    const key = boardCacheKey(courseId, current.topic, current.textbook_ids) + ':draft-backup';
    writeLocal(key, value); writeLocal(key + ':' + (current.id || 'new'), value); setBackup(value);
  };
  const refreshHistory = async () => {
    historyRequest.current?.abort(); const controller = new AbortController(); historyRequest.current = controller;
    try { const { data } = await listTeachingBoards(courseId, controller.signal); if (alive.current && !controller.signal.aborted) setHistory(data.items); }
    catch (e) { if (alive.current && !controller.signal.aborted) setError(boardError(e, '已保存的本课关系加载失败，请重试')); }
  };
  useEffect(() => {
    alive.current = true; refreshHistory();
    return () => { alive.current = false; openRequest.current?.abort(); historyRequest.current?.abort(); metadataRequest.current?.abort(); };
    // The parent remounts this hook when changing courses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);
  useEffect(() => {
    const missing = board.selections.filter((source) => !source.concept_key || !source.title_origin);
    if (!missing.length) return;
    const scope = boardCacheKey(courseId, board.topic, board.textbook_ids), signature = scope + ':' + missing.map((source) => source.chunk_id).sort().join(',');
    if (metadataAttempted.current.has(signature)) return;
    metadataAttempted.current.add(signature); metadataRequest.current?.abort();
    const controller = new AbortController(); metadataRequest.current = controller; setHydrating(true);
    getTeachingSources(courseId, board.topic, board.textbook_ids, missing.map((source) => source.chunk_id), controller.signal).then(({ data }) => {
      if (controller.signal.aborted || !alive.current) return;
      const current = boardRef.current;
      if (boardCacheKey(courseId, current.topic, current.textbook_ids) !== scope) return;
      const sources = new Map(data.items.map((source) => [source.chunk_id, source]));
      accept({ ...current, selections: current.selections.map((source) => {
        const original = sources.get(source.chunk_id);
        return original ? { ...original, teaching_title: source.teaching_title || '', note: source.note, dimension: source.dimension } : source;
      }) });
    }).catch((e) => { if (!controller.signal.aborted && alive.current) setError(boardError(e, '旧草稿的原文信息暂未恢复，教师修改仍保留，请刷新重试')); })
      .finally(() => { if (!controller.signal.aborted && alive.current) setHydrating(false); });
    // The request only hydrates immutable source fields; local edits and order
    // are read again at completion and never replaced by an old saved board.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, board.topic, board.textbook_ids.join(','), board.selections.map((source) => source.chunk_id + ':' + (source.concept_key || '')).join(',')]);
  const switchScope = (topic: string, ids: string[]) => {
    if (savingRef.current) return false;
    openRequest.current?.abort(); setOpening(false); retain(boardRef.current, savedRef.current);
    const old = boardRef.current;
    if (old.topic.trim().toLowerCase() === topic.trim().toLowerCase() && old.selections.length) {
      const selections = old.selections.filter((source) => ids.includes(source.textbook_id)), kept = new Set(selections.map((source) => source.chunk_id));
      accept({ ...old, textbook_ids: ids, selections, connections: old.connections.filter((link) => kept.has(link.source_chunk_id) && kept.has(link.target_chunk_id)) });
    } else { const next = cached(courseId, topic, ids); accept(next.board, next.saved); }
    setConflict(readLocal(boardCacheKey(courseId, topic, ids) + ':conflict', null)); setBackup(readLocal(boardCacheKey(courseId, topic, ids) + ':draft-backup', null)); setError(''); return true;
  };
  const save = async (next = boardRef.current): Promise<TeachingBoard | null> => {
    if (readOnly || savingRef.current) return null;
    if (!next.id && !next.selections.length) { message.info('先选入本课要讲的原文'); return null; }
    savingRef.current = true; setSaving(true); setError('');
    const snapshot = boardFingerprint(next);
    try {
      const response = next.id ? await updateTeachingBoard(courseId, next.id, next.revision, boardPayload(next)) : await createTeachingBoard(courseId, boardPayload(next));
      const current = boardRef.current;
      const accepted = boardFingerprint(current) === snapshot ? response.data : { ...current, id: response.data.id, revision: response.data.revision };
      accept(accepted, boardFingerprint(response.data));
      if (alive.current) { refreshHistory(); message.success('本课知识点、关系和讲授顺序已保存'); }
      return response.data;
    } catch (e: any) {
      if (e?.response?.status === 409) { writeLocal(boardCacheKey(courseId, next.topic, next.textbook_ids) + ':conflict', next); if (alive.current) setConflict(next); }
      if (alive.current) setError(e?.response?.status === 409 ? '课程里已有新版本。本机修改已另存冲突稿，请先导出核对，再打开最新版手动合并。' : boardError(e, '保存失败，本机草稿仍保留')); return null;
    } finally { savingRef.current = false; if (alive.current) setSaving(false); }
  };
  const open = async (id: string): Promise<TeachingBoard | null> => {
    if (savingRef.current) return null;
    openRequest.current?.abort(); const controller = new AbortController(); openRequest.current = controller;
    setOpening(true); setError(''); retainBackup(); retain(boardRef.current, savedRef.current);
    try {
      const { data } = await getTeachingBoard(courseId, id, controller.signal);
      if (controller.signal.aborted || !alive.current) return null;
      if (data.course_id !== courseId) throw new Error('course mismatch');
      accept(data, boardFingerprint(data)); setConflict(readLocal(boardCacheKey(courseId, data.topic, data.textbook_ids) + ':conflict', null)); return data;
    } catch (e) { if (!controller.signal.aborted && alive.current) setError(boardError(e, '本课关系加载失败')); return null; }
    finally { if (!controller.signal.aborted && alive.current) setOpening(false); }
  };
  return { board, boardRef, history, saving, opening, hydrating, error, setError, localStored, conflict, backup, update, switchScope, save, open,
    dirty: !!(board.id || board.selections.length) && boardFingerprint(board) !== saved };
}
