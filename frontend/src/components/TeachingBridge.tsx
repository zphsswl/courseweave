import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, Modal, Select, Spin } from 'antd';
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons';
import type { Textbook } from '../types';
import { getBridgeDiagnostics, getTeachingBridge, readLocal, writeLocal } from '../api/teaching';
import type { BridgeDiagnostics, TeachingBridgeResult } from '../api/teaching';
import SourcePageViewer from './SourcePageViewer';
import { reflowSource } from './sourceText';
import './Teaching.css';

interface Props { courseId: string; textbooks: Textbook[]; sourceBook: Textbook | null; initialQuery: string; onBack: () => void; onScopeChange: (ids: string[]) => void; onTopicChange: (query: string) => void; refreshToken?: number; children?: React.ReactNode }

const Passage: React.FC<{ quote: string; query: string }> = ({ quote, query }) => {
  const [expanded, setExpanded] = useState(false);
  const readable = reflowSource(quote);
  const at = readable.indexOf(query);
  const start = Math.max(0, at - 60);
  const short = readable.length > 280;
  const preview = `${start ? '…' : ''}${readable.slice(start, start + 280)}${start + 280 < readable.length ? '…' : ''}`;
  return <><blockquote>{expanded || !short ? readable : preview}</blockquote>{short && <button className="text-link evidence-expand" onClick={() => setExpanded(!expanded)}>{expanded ? '收起引用' : `展开此条引用（${readable.length} 字）`}</button>}</>;
};

const TeachingBridge: React.FC<Props> = ({ courseId, textbooks, sourceBook, initialQuery, onBack, onScopeChange, onTopicChange, refreshToken, children }) => {
  const key = `courseweave:bridge:${courseId}`;
  const stored = readLocal<{ query: string; ids: string[] }>(key, { query: '', ids: [] });
  const available = textbooks.filter((book) => book.parse_status === 'completed');
  const allowedIds = new Set(available.map((book) => book.id));
  const previousIds = stored.ids.filter((id) => allowedIds.has(id));
  const initialIds = sourceBook ? [...new Set([sourceBook.id, ...previousIds])].filter((id) => allowedIds.has(id)) : previousIds;
  const [ids, setIds] = useState<string[]>(initialIds.length >= 2 ? initialIds : [...new Set([...initialIds, ...available.map((book) => book.id)])].slice(0, 2));
  const [query, setQuery] = useState(initialQuery || stored.query);
  const [result, setResult] = useState<TeachingBridgeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [source, setSource] = useState<{ book: Textbook; page: number } | null>(null);
  const [diagnostics, setDiagnostics] = useState<BridgeDiagnostics | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { writeLocal(key, { query, ids }); }, [query, ids, key]);
  useEffect(() => { onScopeChange(ids); }, [ids, onScopeChange]);
  useEffect(() => { onTopicChange(query); }, [query, onTopicChange]);
  useEffect(() => {
    setDiagnostics(null);
    if (ids.length < 2) return;
    const controller = new AbortController();
    getBridgeDiagnostics(courseId, ids, controller.signal).then(({ data }) => { if (!controller.signal.aborted) setDiagnostics(data); }).catch(() => {});
    return () => controller.abort();
  }, [courseId, ids, refreshToken]);

  const search = async () => {
    if (ids.length < 2) { setError('请选择至少两本教材进行对照'); return; }
    if (query.trim().length < 2) { setError('请输入具体知识点，例如“甲状腺”或“臂丛”'); return; }
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(''); setResult(null);
    try {
      const response = await getTeachingBridge(courseId, ids, query.trim(), controller.signal);
      if (!controller.signal.aborted) setResult(response.data);
    } catch (e: any) {
      if (!controller.signal.aborted) setError(e?.response?.data?.detail || '原文对照加载失败，请重试');
    } finally { if (!controller.signal.aborted) setLoading(false); }
  };
  useEffect(() => { if (initialQuery && ids.length >= 2) search(); }, []); // 由授课台进入时只执行一次，改动后由教师主动检索。
  const changeScope = () => { request.current?.abort(); setLoading(false); setResult(null); setError(''); };

  return (
    <section className="teaching-compare task-page">
      <button className="text-link" onClick={onBack}><ArrowLeftOutlined /> {sourceBook ? `返回《${sourceBook.title}》授课位置` : '返回教材库'}</button>
      <header className="bridge-heading"><div><span className="teaching-overline">READ ACROSS / 跨教材对照</span><h1>同一个知识点，放回各本教材</h1><p>{sourceBook ? `从《${sourceBook.title}》带入知识点；` : ''}并排查阅原文与页码，再判断它们如何关联。</p></div><span className="bridge-source-label">原文证据 · 无需模型生成</span></header>
      <div className="bridge-compose">
        <label>对照教材<Select mode="multiple" value={ids} maxTagCount="responsive" onChange={(value) => { changeScope(); setIds(value); }} options={available.map((book) => ({ value: book.id, label: book.title }))} placeholder="选择至少两本教材" aria-label="对照教材" /></label>
        <label>知识点<Input value={query} onChange={(e) => { changeScope(); setQuery(e.target.value); }} maxLength={80} placeholder="例如：甲状腺" onPressEnter={search} aria-label="对照知识点" /></label>
        <Button type="primary" icon={<SearchOutlined />} loading={loading} onClick={search}>查阅各书原文</Button>
      </div>
      {error && <Alert type="error" showIcon message={error} />}
      {loading && <div className="page-loading"><Spin /> 正在所选教材中查找证据…</div>}
      {!loading && !result && !error && <div className="bridge-empty"><span>01 选择教材</span><span>02 输入具体知识点</span><span>03 对照原页，解释教学联系</span><p>先查清各本书写了什么。检索到的段落会保留书名、章节与 PDF 页序。</p></div>}
      {result && !loading && <>
        <div className="bridge-result-summary"><strong>“{result.query}”的原文对照</strong><p>{result.message || '以下为检索到的教材段落，尚未判断知识关系。未召回不等于两本书没有关联。'}</p></div>
        <div className="bridge-evidence-grid" style={{ gridTemplateColumns: `repeat(${Math.min(3, Math.max(1, result.groups.length))}, minmax(0, 1fr))` }}>
          {result.groups.map((group) => <section className="bridge-book" key={group.textbook_id}><header><span>TEXTBOOK {String(result.groups.indexOf(group) + 1).padStart(2, '0')}</span><h2>{group.title}</h2><small>{group.items.length ? `${group.items.length} 条检索原文 · 尚未判断关系` : '本次未召回证据'}</small></header>{!group.items.length ? <div className="bridge-no-evidence"><strong>没有找到足够匹配的原文</strong><p>可换用教材中的专有术语或缩短查询。当前结果不能用来断言教材之间没有关系。</p></div> : group.items.map((item) => <article className="bridge-evidence" key={item.id}><div className="bridge-evidence-meta"><span>{item.chapter}{item.section_path?.length ? ` / ${item.section_path.slice(-2).join(' / ')}` : ''}</span><strong>{textbooks.find((b) => b.id === group.textbook_id)?.format === 'pdf' ? 'PDF' : '文本页'} {item.page_start}{item.page_end > item.page_start ? `–${item.page_end}` : ''}</strong></div><Passage quote={item.quote} query={result.query} />{textbooks.find((b) => b.id === group.textbook_id)?.format === 'pdf' ? <Button size="small" onClick={() => { const book = textbooks.find((b) => b.id === group.textbook_id); if (book) setSource({ book, page: item.page_start || 1 }); }}>核对教材原页 ↗</Button> : <small>文本教材 · 上方引用保留原文</small>}</article>)}</section>)}
        </div>
        {!!result.confirmed_relations.length && <div className="bridge-confirmed"><strong>已有人工确认的关系：{result.confirmed_relations.length} 条</strong><p>下方关系图中可查看审核记录；本次检索段落不会自动成为已确认关系。</p></div>}
      </>}
      <details className="bridge-advanced" onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}><summary>关系图与候选审核 <span>需要进一步判断概念关系时展开</span></summary>{diagnostics && <div className="bridge-diagnostics"><strong>当前选书组合 · 待审核 {diagnostics.pending_review} 条</strong><p>{diagnostics.message}</p>{diagnostics.latest_run && <><div>{[['可用节点', diagnostics.latest_run.eligible_nodes], ['召回候选对', diagnostics.latest_run.candidate_pairs], ['通过预筛', diagnostics.latest_run.qualified_pairs], ['完成判定', diagnostics.latest_run.judged], ['新建候选', diagnostics.latest_run.candidates_created]].map(([label, value]) => <span key={label}>{label}<b>{value ?? '未记录'}</b></span>)}</div><p>{diagnostics.latest_run.qualified_pairs === 0 ? '本次候选被预筛全部拦截，未进入模型判定。可先使用上方原文对照。' : `最近任务状态：${diagnostics.latest_run.status}`}</p></>}</div>}{advancedOpen && children}</details>
      <Modal open={Boolean(source)} onCancel={() => setSource(null)} footer={null} width={1000} title="核对教材原页" destroyOnClose>{source && <SourcePageViewer textbookId={source.book.id} title={source.book.title} page={source.page} totalPages={source.book.total_pages} onPageChange={(page) => setSource({ ...source, page })} />}</Modal>
    </section>
  );
};
export default TeachingBridge;
