import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Empty, Input, Modal, Radio, Select, Spin, Tag, Typography, message } from 'antd';
import { BookOutlined, BranchesOutlined, SendOutlined } from '@ant-design/icons';
import type { Citation, QueryResult, RagStatus, Textbook } from '../types';
import * as api from '../api/client';
import SourcePageViewer from './SourcePageViewer';
import './RagPanel.css';

interface Props {
  courseId: string; textbooks: Textbook[]; ragStatus: RagStatus | null;
  onBuildIndex: () => void; isBuilding: boolean; compact?: boolean; readOnly?: boolean;
  preferredTextbookIds?: string[]; onCollectEvidence?: (citation: Citation, question: string) => void;
}
interface Answer { question: string; bookIds: string[]; mode: 'all' | 'compare'; result: QueryResult }
interface Session { question: string; mode: 'all' | 'compare'; bookIds: string[]; answers: Answer[] }
const sessionKey = (course: string) => `courseweave:questions:${course}`;
const restore = (course: string, preferred: string[]): Session => {
  try {
    const saved = JSON.parse(localStorage.getItem(sessionKey(course)) || 'null');
    if (saved && typeof saved.question === 'string' && Array.isArray(saved.bookIds) && Array.isArray(saved.answers)) return { ...saved, mode: saved.mode === 'compare' ? 'compare' : 'all', answers: saved.answers.filter((answer: Answer) => answer?.result && Array.isArray(answer.result.citations)).slice(0, 5) };
  } catch { /* Browser storage is optional. */ }
  return { question: '', mode: preferred.length >= 2 ? 'compare' : 'all', bookIds: preferred, answers: [] };
};
const RagPanel: React.FC<Props> = ({ courseId, textbooks, ragStatus, onBuildIndex, isBuilding, compact = false, readOnly = false, preferredTextbookIds = [], onCollectEvidence }) => {
  const [session, setSession] = useState(() => restore(courseId, preferredTextbookIds));
  const [owner, setOwner] = useState(courseId);
  const [answerIndex, setAnswerIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [storageFailed, setStorageFailed] = useState(false);
  const [source, setSource] = useState<Citation | null>(null);
  const [page, setPage] = useState(1);
  const request = useRef<AbortController | null>(null);
  const currentCourse = useRef(courseId); currentCourse.current = courseId;
  useEffect(() => {
    request.current?.abort(); setLoading(false); setError(''); setSource(null); setAnswerIndex(0);
    setSession(restore(courseId, preferredTextbookIds)); setOwner(courseId);
    return () => request.current?.abort();
    // Changing pages within a course must preserve the question and scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);
  useEffect(() => {
    if (owner !== courseId) return;
    try { localStorage.setItem(sessionKey(courseId), JSON.stringify(session)); setStorageFailed(false); } catch { setStorageFailed(true); }
  }, [courseId, owner, session]);
  const patch = (value: Partial<Session>) => setSession((current) => ({ ...current, ...value }));
  const available = new Set(textbooks.map((book) => book.id));
  const selectedBooks = session.bookIds.filter((id) => available.has(id));
  const answer = owner === courseId ? session.answers[answerIndex] : undefined;
  const result = answer?.result;
  const preferred = preferredTextbookIds.filter((id) => available.has(id));
  const differentScope = preferred.length > 0 && [...preferred].sort().join() !== [...selectedBooks].sort().join();
  const ask = async () => {
    const question = session.question.trim();
    if (question.length < 2) return message.warning('请输入至少两个字的问题');
    if (session.mode === 'compare' && selectedBooks.length < 2) return message.warning('对比模式至少选择两本教材');
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setLoading(true); setError(''); const mode = session.mode;
    try {
      const { data } = await api.queryRag(question, courseId, mode, selectedBooks.length ? selectedBooks : undefined, controller.signal);
      if (controller.signal.aborted || currentCourse.current !== courseId) return;
      setSession((current) => ({ ...current, answers: [{ question, bookIds: selectedBooks, mode, result: data }, ...current.answers].slice(0, 5) })); setAnswerIndex(0);
    } catch (failure: any) {
      if (!controller.signal.aborted && currentCourse.current === courseId) setError(typeof failure?.response?.data?.detail === 'string' ? failure.response.data.detail : '暂时无法检索，请重试。上一次回答仍保留。');
    } finally {
      if (!controller.signal.aborted && currentCourse.current === courseId) setLoading(false);
      window.dispatchEvent(new Event('courseweave:model-status-changed'));
    }
  };
  const sourceBook = textbooks.find((book) => book.id === source?.textbook_id);
  const sourceLocation = (citation: Citation) => {
    const start = citation.page_start || citation.page;
    if (!start) return '章节原文';
    const prefix = textbooks.find((book) => book.id === citation.textbook_id)?.format === 'pdf' ? 'PDF ' : '原文位置 ';
    return `${prefix}${start}${citation.page_end && citation.page_end !== start ? `–${citation.page_end}` : ''}`;
  };
  const bookLabel = (ids: string[]) => ids.length ? ids.map((id) => textbooks.find((book) => book.id === id)?.title || '已移除教材').join('、') : '本课程全部教材';
  return <div className={`evidence-rag ${compact ? 'compact-rag' : ''}`}>
    <section className="rag-ready-strip"><BookOutlined /><span>{ragStatus?.indexed ? '教材已就绪，可以查证' : '教材问答尚未就绪'}</span>{!ragStatus?.indexed && !readOnly && <Button size="small" loading={isBuilding} onClick={onBuildIndex}>准备教材问答</Button>}</section>
    {storageFailed && <Alert type="warning" message="浏览器暂存不可用，刷新前请复制需要的答案。" />}
    {ragStatus?.status === 'stale' && <Alert type="warning" showIcon message="教材已更新，索引需要刷新" action={!readOnly ? <Button size="small" loading={isBuilding} onClick={onBuildIndex}>更新教材问答</Button> : undefined} />}
    <section className="rag-compose">
      <Radio.Group value={session.mode} onChange={(event) => patch({ mode: event.target.value })} buttonStyle="solid"><Radio.Button value="all"><BookOutlined /> 课程问答</Radio.Button><Radio.Button value="compare"><BranchesOutlined /> 跨教材对比</Radio.Button></Radio.Group>
      <Select mode="multiple" aria-label="问答教材范围" maxTagCount="responsive" placeholder="检索本课程全部教材" value={selectedBooks} onChange={(bookIds) => patch({ bookIds })} options={textbooks.map((book) => ({ value: book.id, label: book.title }))} />
      {differentScope && <button className="rag-use-scope" onClick={() => patch({ bookIds: preferred, mode: preferred.length >= 2 ? 'compare' : 'all' })}>使用当前页面的教材范围</button>}
      <Input.TextArea aria-label="教材问题" value={session.question} maxLength={2000} onChange={(event) => patch({ question: event.target.value })} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); if (!loading) ask(); } }} rows={3} placeholder="输入知识点或教学问题，如：甲状腺的位置与形态，给出原文依据" />
      <small className="rag-input-note">Enter 查证 · Shift + Enter 换行 · 此浏览器保留最近 5 次查证</small>
      <Button type="primary" block icon={<SendOutlined />} loading={loading} disabled={!ragStatus?.indexed || !session.question.trim()} onClick={ask}>{session.mode === 'compare' ? '对照教材证据' : '查找教材依据'}</Button>
    </section>
    {error && <Alert type="error" showIcon message={error} />}
    {loading && <div className="rag-loading" role="status"><Spin size="small" /><span>正在查找原文依据，上一次回答会保留…</span></div>}
    {!!session.answers.length && <label className="rag-history"><span>查证记录</span><Select aria-label="查证记录" value={answerIndex} onChange={setAnswerIndex} options={session.answers.map((item, index) => ({ value: index, label: item.question }))} /></label>}
    {result && answer && <section className="rag-result">
      <div className="rag-result-head"><strong>{answer.question}</strong><Tag>{result.answer_method === 'llm_grounded' ? '已关联来源 · 待核对' : result.answer_method === 'no_evidence' ? '本次未命中' : '原文材料'}</Tag></div>
      <p className="rag-answer-scope">回答范围：{bookLabel(answer.bookIds)}</p><Typography.Paragraph className="rag-answer" copyable={{ text: result.answer }}>{result.answer}</Typography.Paragraph>
      {!result.citations.length && <p className="rag-no-hit-help">本次未找到足够证据，不代表教材一定没有相关内容。可缩短为知识点、扩大教材范围，或到教材目录查找。</p>}
      <div className="evidence-stack">{result.citations.map((citation, index) => <article className="evidence-card" key={citation.chunk_id || index}>
        <div className="evidence-card-head"><span className="evidence-id">{citation.source_id || `S${index + 1}`}</span><strong>{citation.textbook}</strong><span>{sourceLocation(citation)}</span></div>
        <div className="evidence-path">{citation.section_path?.join(' › ') || citation.chapter}</div><blockquote>{citation.quote || result.source_chunks[index]}</blockquote>
        <div className="rag-evidence-actions"><Button size="small" disabled={!citation.textbook_id || !(citation.page_start || citation.page)} onClick={() => { setSource(citation); setPage(citation.page_start || citation.page || 1); }}>查看原页与上下文 ↗</Button>{!readOnly && onCollectEvidence && citation.chunk_id && <Button size="small" onClick={() => onCollectEvidence(citation, answer.question)}>加入当前备课</Button>}</div>
      </article>)}</div>
      <details className="rag-diagnostics"><summary>检索详情</summary><p>{ragStatus?.method === 'bm25_vector' ? '关键词、向量和知识关系' : '关键词和知识关系'} · {ragStatus?.chunk_count || 0} 段可检索材料</p><p>本次路径：{result.retrieval_trace?.retrievers?.join(' + ') || 'BM25'}</p>{result.citations.map((citation, index) => <p key={index}>{citation.source_id || `S${index + 1}`}：{citation.chunk_id} · {citation.retrievers?.join(' + ')}</p>)}</details>
    </section>}
    {!loading && !result && !error && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="查证后可打开教材原页，或将证据加入备课" />}
    <Modal open={!!source} onCancel={() => setSource(null)} footer={null} title="核对教材原文" width={1050} destroyOnClose className="rag-source-modal">{source && <div className="rag-source-layout"><div><strong>{source.textbook} · {sourceLocation(source)}</strong><p>{source.section_path?.join(' / ') || source.chapter}</p><blockquote>{source.quote || result?.source_chunks[result.citations.indexOf(source)]}</blockquote></div>{sourceBook?.format === 'pdf' && source.textbook_id ? <SourcePageViewer textbookId={source.textbook_id} title={source.textbook} page={page} totalPages={sourceBook.total_pages} onPageChange={setPage} /> : <p>该教材没有可用的 PDF 原页，请核对原文摘录及章节。</p>}</div>}</Modal>
  </div>;
};
export default RagPanel;
