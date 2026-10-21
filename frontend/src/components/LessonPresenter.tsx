import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Modal, Spin } from 'antd';
import type { AgentCitation, Textbook } from '../types';
import { getLessonRun, lessonDelivery } from '../api/lessonAgent';
import type { LessonRun } from '../api/lessonAgent';
import { readLocal, writeLocal } from '../api/teaching';
import SourcePageViewer from './SourcePageViewer';
import { reflowSource } from './sourceText';
import './LessonPresenter.css';

interface Props { courseId: string; runId: string; textbooks: Textbook[]; onBack: (validatedId?: string) => void }
interface Slide { title: string; label: string; content: string[]; sources: string[]; minutes?: number }

const paragraphs = (text: string) => reflowSource(text).split(/\n\s*\n/).filter(Boolean).map((paragraph, index) => <p key={index}>{paragraph}</p>);

const LessonPresenter: React.FC<Props> = ({ courseId, runId, textbooks, onBack }) => {
  const [run, setRun] = useState<LessonRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [index, setIndex] = useState(() => readLocal('courseweave:lesson-slide:' + runId, 0));
  const [focus, setFocus] = useState(false);
  const [large, setLarge] = useState(false);
  const [showTeacherNotes, setShowTeacherNotes] = useState(true);
  const [supplementsOpen, setSupplementsOpen] = useState(false);
  const [source, setSource] = useState<AgentCitation | null>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setRun(null);
    if (!runId) { setLoading(false); setError('未指定教案，请返回备课工作台选择一份教案。'); return; }
    getLessonRun(runId, controller.signal).then(({ data }) => {
      if (controller.signal.aborted) return;
      if (data.course_id !== courseId || data.id !== runId) { setError('这份教案不属于当前课程，请返回后重新选择。'); return; }
      setRun(data);
    }).catch((error) => {
      if (!controller.signal.aborted) setError(typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : '教案加载失败，请重试');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId, courseId, retry]);

  const artifact = run?.result.lesson_draft || run?.result.artifact;
  const delivery = run ? lessonDelivery(run) : null;
  // Only scheduled lesson blocks become pages. Unmapped objectives, comparisons and questions
  // remain supplemental material, so they do not silently extend an already full lesson.
  const slides = useMemo(() => {
    if (!artifact) return [] as Slide[];
    if (artifact.lesson_blocks?.length) return artifact.lesson_blocks.map((block) => ({
      title: block.title, label: '教学环节', content: [block.content], sources: block.source_ids || [], minutes: block.minutes,
    }));
    return (artifact.knowledge_sequence || []).map((row, index) => ({
      title: row.title || '证据讲读 ' + (index + 1), label: '待完善的材料 · 未排定课时',
      content: [row.explanation || row.claim || row.guidance || '请返回备课台补充讲解内容'], sources: row.source_ids || [],
    })) as Slide[];
  }, [artifact]);
  const safeIndex = Math.max(0, Math.min(index, slides.length - 1));
  const slide = slides[safeIndex];
  const requestedMinutes = run?.result.request?.duration_minutes || run?.payload?.duration_minutes || 45;
  const plannedMinutes = (artifact?.lesson_blocks || []).reduce((sum, block) => sum + (block.minutes || 0), 0);
  const audience = run?.result.request?.audience || run?.payload?.audience;
  const priorKnowledge = run?.result.request?.prior_knowledge || run?.payload?.prior_knowledge;

  useEffect(() => { if (slides.length) writeLocal('courseweave:lesson-slide:' + runId, safeIndex); }, [safeIndex, slides.length, runId]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (source || supplementsOpen || event.isComposing || /INPUT|TEXTAREA|SELECT/.test((event.target as HTMLElement)?.tagName || '')) return;
      if (event.key === 'ArrowRight' || event.key === 'PageDown') { event.preventDefault(); setIndex((value) => Math.min(slides.length - 1, value + 1)); }
      if (event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); setIndex((value) => Math.max(0, value - 1)); }
      if (event.key === 'Escape') { setFocus(false); setShowTeacherNotes(true); }
    };
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key);
  }, [slides.length, source, supplementsOpen]);

  const openSource = (citation: AgentCitation) => { setSource(citation); setPage(citation.page_start || 1); };
  const back = () => onBack(run?.course_id === courseId ? run.id : undefined);
  const hasPdf = (citation: AgentCitation) => textbooks.find((book) => book.id === citation.textbook_id)?.format === 'pdf';
  const locationLabel = (citation: AgentCitation) => hasPdf(citation)
    ? 'PDF ' + citation.page_start + (citation.page_end && citation.page_end !== citation.page_start ? '–' + citation.page_end : '')
    : '原文位置 · ' + (citation.section_path?.slice(-1)[0] || citation.chapter || '教材摘录');
  const missingDescription = delivery?.missing_items.join('；') || '请在备课工作台核对课时与课堂问题。';
  const citationLinks = (ids: string[]) => <div className="lp-source-links">
    {(!ids.length || ids.some((id) => !artifact?.citations.some((item) => item.source_id === id))) && <Alert type="warning" message="此段尚缺有效来源，请返回编辑核对教材引用" />}
    {ids.map((id) => {
      const citation = artifact?.citations.find((item) => item.source_id === id);
      return citation ? <Button key={id} onClick={() => openSource(citation)}>{id} · {citation.textbook} · {locationLabel(citation)} ↗</Button> : null;
    })}
  </div>;

  if (loading) return <div className="page-loading"><Spin /> 正在加载已保存教案…</div>;
  if (error) return <section className="teaching-error"><Alert type="error" message={error} /><Button onClick={() => setRetry(retry + 1)}>重试</Button><Button onClick={back}>返回备课工作台</Button></section>;

  return <section className={'lesson-presenter' + (focus ? ' lp-focus' : '') + (large ? ' lp-large' : '')}>
    <header className="lp-header">
      <div><button className="text-link" onClick={back}>← 返回编辑教案</button><span className="lp-mode-label">{focus ? '投屏模式' : '教案预览'}</span>
        <h1>{artifact?.title || run?.result.topic || '本课教案'}</h1>
        <p>{run?.result.lesson_draft ? '已保存的教师修订稿 · 版本 ' + (run.result.draft_revision || 0) : '生成稿 · 内容与引用需教师核对'} · {artifact?.lesson_blocks?.length ? '已安排 ' + plannedMinutes + ' / ' + requestedMinutes + ' 分钟' : '尚未排定课时'}</p>
      </div>
      <div className="lp-controls">
        {focus && delivery?.status !== 'draft_ready' && <span className="lp-projection-status" role="status" title={missingDescription} aria-label={'待完善稿，仍缺内容：' + missingDescription + '退出投屏可查看完整清单。'}>待完善稿</span>}
        <Button aria-pressed={showTeacherNotes} onClick={() => setShowTeacherNotes(!showTeacherNotes)}>{showTeacherNotes ? '隐藏教师备注' : '显示教师备注'}</Button>
        <Button onClick={() => setSupplementsOpen(true)}>补充材料</Button>
        <Button aria-pressed={large} onClick={() => setLarge(!large)}>字号 {large ? 'A−' : 'A+'}</Button>
        <Button type="primary" aria-pressed={focus} onClick={() => { setFocus(!focus); setShowTeacherNotes(focus); }}>{focus ? '退出投屏' : '进入投屏'}</Button>
      </div>
    </header>
    {!focus && delivery?.status !== 'draft_ready' && <Alert className="lp-delivery" type="warning" showIcon message={delivery?.status === 'evidence_only' ? '当前交付为证据材料包，教案尚未完成' : '本课仍有待补充内容'} description={missingDescription} />}
    {!slide ? <div className="lp-empty"><p>尚无可展示的教学环节，请返回工作台编辑教案。</p><Button onClick={back}>返回编辑</Button></div> : <div className="lp-layout">
      <aside aria-label="教案环节顺序">{slides.map((item, at) => <button key={at} aria-current={safeIndex === at ? 'step' : undefined} className={safeIndex === at ? 'active' : ''} onClick={() => setIndex(at)}>
        <span>{String(at + 1).padStart(2, '0')}</span><strong>{item.title}</strong><small>{item.minutes ? item.minutes + ' 分钟' : '未排定课时'}</small>
      </button>)}</aside>
      <article className="lp-slide" key={safeIndex}>
        <div className="lp-slide-label">{slide.label}{!!slide.minutes && ' · ' + slide.minutes + ' 分钟'}</div><h2>{slide.title}</h2>
        <div className="lp-content">{slide.content.map((text, at) => <div key={at}>{paragraphs(text)}</div>)}</div>
        {citationLinks(slide.sources)}
        <footer><Button disabled={safeIndex === 0} onClick={() => setIndex(safeIndex - 1)}>← 上一环节</Button><span>{safeIndex + 1} / {slides.length}</span><Button disabled={safeIndex + 1 >= slides.length} onClick={() => setIndex(safeIndex + 1)}>下一环节 →</Button></footer>
      </article>
    </div>}
    {showTeacherNotes && <aside className="lp-teacher-notes" aria-label="教师备课备注">
      <header><h2>教师备课提示</h2><span>整课提示，尚未按教学环节单独绑定</span></header>
      {(audience || priorKnowledge) && <p className="lp-learner-note">{audience && <>教学对象：{audience}<br /></>}{priorKnowledge && <>先修知识：{priorKnowledge}</>}</p>}
      <div className="lp-notes-columns">
        <section><h3>教学目标</h3>{artifact?.teaching_objectives.length ? <ol>{artifact.teaching_objectives.map((item, at) => <li key={at}>{item}</li>)}</ol> : <p>教学目标待教师补充。</p>}</section>
        <section><h3>重点与辨析</h3>{artifact?.teaching_focus?.length ? artifact.teaching_focus.map((row, at) => <div key={at}><p><strong>{row.title}</strong>{row.explanation}</p>{citationLinks(row.source_ids || [])}</div>) : <p>重点讲授提示待教师补充。</p>}
          {artifact?.misconceptions.map((row, at) => <div key={'issue-' + at}><p><strong>{row.issue}</strong>{row.guidance}</p>{citationLinks(row.source_ids || [])}</div>)}
        </section>
      </div>
      {!!artifact?.unresolved_questions.length && <details><summary>需要教师核对的事项</summary><ul>{artifact.unresolved_questions.map((item, at) => <li key={at}>{item}</li>)}</ul></details>}
      <p className="lp-notes-caution">进入投屏会先隐藏这些备注，可按需重新显示。引用存在不等于内容已由教师确认。</p>
    </aside>}
    <p className="lp-supplement-note">教学目标、教材对比与问题清单保留为补充材料，不额外计入课时。请在编辑教案时安排到具体环节。</p>
    <details className="lp-citations"><summary>本课证据来源（{artifact?.citations.length || 0}）</summary>{artifact?.citations.map((item) => <button key={item.source_id} onClick={() => openSource(item)}>{item.source_id} · {item.textbook} · {locationLabel(item)} ↗</button>)}</details>
    <Modal open={supplementsOpen} onCancel={() => setSupplementsOpen(false)} title="补充材料 · 不额外计入课时" footer={null} width={1000} destroyOnClose>
      <div className="lp-supplements"><p>以下内容尚未按环节绑定。应由教师安排在现有课时内，不能作为额外的计时页。</p>
        <section><h2>教学目标</h2>{artifact?.teaching_objectives.length ? <ol>{artifact.teaching_objectives.map((item, at) => <li key={at}>{item}</li>)}</ol> : <p>教学目标待补充。</p>}</section>
        <section><h2>教材比较</h2>{artifact?.textbook_differences.length ? artifact.textbook_differences.map((row, at) => <article key={at}><h3>{row.title || row.textbook || '教材表述'}</h3><p>{row.perspective || row.explanation || row.claim || '比较内容待补充'}</p>{citationLinks(row.source_ids || [])}</article>) : <p>暂无有依据的教材比较。</p>}</section>
        <section><h2>课堂问题</h2>{artifact?.classroom_questions.length ? <><ol>{artifact.classroom_questions.map((item, at) => <li key={at}>{item}</li>)}</ol><p className="lp-answer-gap">参考答案、提问目的和检查标准待教师补充，当前未生成独立答案。</p></> : <p>尚未提供课堂问题。</p>}</section>
      </div>
    </Modal>
    <Modal open={!!source} onCancel={() => setSource(null)} title="核对本课引用" footer={null} width={1050} destroyOnClose>
      {source && <div className="lp-source-detail"><div><small>{source.source_id} · {source.textbook} · {locationLabel(source)}</small><h3>{source.section_path?.slice(-1)[0] || source.chapter}</h3><blockquote>{reflowSource(source.quote)}</blockquote><p>{hasPdf(source) ? '此处保留引用摘录；完整上下文请查阅原页。' : '此处保留已解析的原文摘录与目录位置。'}</p></div>
        {hasPdf(source) ? <SourcePageViewer textbookId={source.textbook_id} title={source.textbook} page={page} totalPages={textbooks.find((book) => book.id === source.textbook_id)?.total_pages || Math.max(source.page_end || 1, page)} onPageChange={setPage} /> : <p className="lp-no-pdf">此教材未提供 PDF 原页，请核对左侧原文摘录及其目录位置。</p>}
      </div>}
    </Modal>
  </section>;
};
export default LessonPresenter;
