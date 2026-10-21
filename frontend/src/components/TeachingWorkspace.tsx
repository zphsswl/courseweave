import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Spin, message } from 'antd';
import { ArrowLeftOutlined, BranchesOutlined, FileImageOutlined, FullscreenExitOutlined, FullscreenOutlined, SearchOutlined, StarFilled, StarOutlined } from '@ant-design/icons';
import type { Textbook } from '../types';
import type { AgentLessonContext } from '../api/lessonAgent';
import { getTeachingBook, readLocal, searchTeachingBook, writeLocal } from '../api/teaching';
import type { TeachingBook, TeachingHit, TeachingSection } from '../api/teaching';
import SourcePageViewer from './SourcePageViewer';
import { reflowSource } from './sourceText';
import './Teaching.css';

interface Props { textbook: Textbook; onBack: () => void; onCompare: (term: string) => void; onPrepare?: (context: AgentLessonContext) => void }
interface Position { chapterId: string; sectionId: string; query: string; page: number; showSource: boolean; scroll: number }
const emptyPosition: Position = { chapterId: '', sectionId: '', query: '', page: 1, showSource: false, scroll: 0 };
const isFormal = (s: TeachingSection) => s.formal_section ?? /^第\s*[一二三四五六七八九十百千\d０-９]+\s*节/.test(s.title);
const isUnit = (s: TeachingSection) => s.navigation_unit ?? isFormal(s);
const rootsOf = (sections: TeachingSection[]) => sections.some((s) => typeof s.navigation_unit === 'boolean')
  ? sections.filter(isUnit)
  : sections.filter((s) => !s.parent_id || isFormal(s));
const sectionBlock = (sections: TeachingSection[], id: string) => {
  const start = sections.findIndex((s) => s.id === id);
  if (start < 0) return [];
  let end = start + 1;
  while (end < sections.length && sections[end].level > sections[start].level && !isFormal(sections[end]) && !(isUnit(sections[start]) && isUnit(sections[end]))) end++;
  return sections.slice(start, end);
};

const Highlight: React.FC<{ text: string; query: string }> = ({ text, query }) => {
  if (!query.trim()) return <>{text}</>;
  const parts = text.split(query.trim());
  return <>{parts.map((part, i) => <React.Fragment key={i}>{i > 0 && <mark>{query.trim()}</mark>}{part}</React.Fragment>)}</>;
};

const TeachingWorkspace: React.FC<Props> = ({ textbook, onBack, onCompare, onPrepare }) => {
  const storageKey = `courseweave:lecture:${textbook.id}`;
  const [position, setPosition] = useState<Position>(() => ({ ...emptyPosition, ...readLocal(storageKey, emptyPosition) }));
  const [data, setData] = useState<TeachingBook | null>(null);
  const pageLabel = (start: number, end: number) => data?.has_pdf ? `PDF ${start}${end > start ? `–${end}` : ''}` : '解析正文';
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [hits, setHits] = useState<TeachingHit[]>([]);
  const [hitTotal, setHitTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [focus, setFocus] = useState(false);
  const [large, setLarge] = useState(() => readLocal('courseweave:lecture-large', false));
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [term, setTerm] = useState('');
  const [expandedRoots, setExpandedRoots] = useState<string[]>([]);
  const [allDetails, setAllDetails] = useState(false);
  const [stars, setStars] = useState<string[]>(() => readLocal(`courseweave:favorites:${textbook.id}`, readLocal(`courseweave:priorities:${textbook.id}`, [])));
  const reader = useRef<HTMLDivElement>(null);
  const positionRef = useRef(position);
  positionRef.current = { ...position, scroll: positionRef.current.chapterId === position.chapterId && positionRef.current.sectionId === position.sectionId ? positionRef.current.scroll : position.scroll };

  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    getTeachingBook(textbook.id).then(({ data: book }) => {
      if (!active) return;
      setData(book);
      setPosition((current) => {
        const chapter = book.chapters.find((item) => item.id === current.chapterId);
        const section = chapter?.sections.find((item) => item.id === current.sectionId);
        return chapter ? { ...current, sectionId: section?.id || '', page: Math.min(Math.max(1, current.page), book.total_pages || 1) } : { ...current, chapterId: '', sectionId: '', scroll: 0 };
      });
    }).catch((e) => active && setError(e?.response?.data?.detail || '教材正文加载失败，请重试')).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [textbook.id, retry]);

  useEffect(() => { writeLocal(storageKey, positionRef.current); }, [position, storageKey]);
  useEffect(() => { writeLocal(`courseweave:favorites:${textbook.id}`, stars); }, [stars, textbook.id]);
  useEffect(() => { writeLocal('courseweave:lecture-large', large); }, [large]);
  useEffect(() => {
    if (!focus) return;
    const exit = (event: KeyboardEvent) => { if (event.key === 'Escape') setFocus(false); };
    window.addEventListener('keydown', exit);
    return () => window.removeEventListener('keydown', exit);
  }, [focus]);
  useEffect(() => () => { writeLocal(storageKey, { ...positionRef.current, scroll: reader.current?.scrollTop || positionRef.current.scroll }); }, [storageKey]);
  useEffect(() => {
    if (loading) return;
    const id = requestAnimationFrame(() => { if (reader.current) reader.current.scrollTop = position.scroll; });
    return () => cancelAnimationFrame(id);
    // 滚动位置只在切换内容或恢复工作区时应用。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [position.chapterId, position.sectionId, loading]);

  useEffect(() => {
    if (position.query.trim().length < 2) { setHits([]); setHitTotal(0); setSearchError(''); setSearching(false); return; }
    const controller = new AbortController();
    setSearching(true); setSearchError(''); setHits([]); setHitTotal(0);
    const timer = window.setTimeout(() => searchTeachingBook(textbook.id, position.query.trim(), controller.signal)
      .then(({ data: result }) => { if (!controller.signal.aborted) { setHits(result.items); setHitTotal(result.total); } })
      .catch((e) => { if (!controller.signal.aborted) setSearchError(e?.response?.data?.detail || '全文搜索失败，请稍后重试'); })
      .finally(() => { if (!controller.signal.aborted) setSearching(false); }), 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [position.query, textbook.id]);

  const chapter = data?.chapters.find((item) => item.id === position.chapterId);
  const section = chapter?.sections.find((item) => item.id === position.sectionId);
  const blocks = chapter && section ? sectionBlock(chapter.sections, section.id) : [];
  const sectionEndPage = blocks.length ? Math.max(...blocks.map((s) => s.page_end)) : section?.page_end || 1;
  const figures = blocks.flatMap((s) => s.figure_refs || []).filter((figure, i, all) => all.findIndex((other) => other.label === figure.label && other.page_number === figure.page_number) === i);
  const flattened = useMemo(() => data?.chapters.flatMap((item) => item.sections.map((s) => ({ chapter: item, section: s }))) || [], [data]);
  const navigation = section && isUnit(section) ? flattened.filter((item) => isUnit(item.section)) : flattened;
  const navigationIndex = navigation.findIndex((item) => item.section.id === section?.id);
  const nextIndex = section && isUnit(section) ? navigationIndex + 1 : navigationIndex + blocks.length;
  const totalSections = flattened.length;
  const formalCount = flattened.filter((item) => isFormal(item.section)).length;
  const unitCount = data?.chapters.reduce((sum, item) => sum + rootsOf(item.sections).length, 0) || 0;
  const unitLabel = formalCount && formalCount === unitCount ? '节' : '个目录单元';
  const chapterRoots = chapter ? rootsOf(chapter.sections) : [];
  const visibleOutline = chapterRoots.flatMap((root) => [root, ...(expandedRoots.includes(root.id) ? sectionBlock(chapter!.sections, root.id).slice(1) : [])]);
  const selectedStars = flattened.filter((item) => stars.includes(item.section.id));
  const openSection = (chapterId: string, value: TeachingSection, page?: number) => {
    positionRef.current = { ...positionRef.current, chapterId, sectionId: value.id, page: page || value.page_start || 1, scroll: 0 };
    setPosition(positionRef.current);
    setTerm('');
    setCatalogOpen(false);
    const sourceChapter = data?.chapters.find((c) => c.id === chapterId);
    const root = sourceChapter && rootsOf(sourceChapter.sections).find((r) => sectionBlock(sourceChapter.sections, r.id).some((s) => s.id === value.id));
    if (root && root.id !== value.id) setExpandedRoots((current) => [...new Set([...current, root.id])]);
  };
  const openHit = (hit: TeachingHit) => {
    const targetChapter = data?.chapters.find((item) => item.id === hit.chapter_id);
    const targetSection = targetChapter?.sections.find((item) => item.id === hit.section_id);
    if (targetChapter && targetSection) openSection(targetChapter.id, targetSection, hit.page_start);
    else message.warning('该搜索位置已变化，请刷新教材后重试');
  };
  const go = (offset: number) => {
    const target = navigation[offset > 0 ? nextIndex : navigationIndex - 1];
    if (target) openSection(target.chapter.id, target.section);
  };
  const toggleStar = (id: string) => setStars((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const compare = () => {
    const selection = window.getSelection()?.toString().trim();
    const sectionTopic = (section?.title || '').replace(/^第\s*[一二三四五六七八九十百千\d０-９]+\s*节\s*/, '').replace(/^[（(]?[一二三四五六七八九十\d]+[）).、．]\s*/, '').trim();
    const query = term.trim() || (selection && selection.length <= 80 ? selection : '') || position.query.trim() || sectionTopic;
    if (!query || query.length > 80 || /^(概述|概论|绪论|表面解剖|内容|正文|本章正文)$/.test(query)) {
      message.info('请输入具体知识点，再进行跨教材对照');
      return;
    }
    onCompare(query);
  };
  const prepare = () => {
    const topic = term.trim() || position.query.trim() || (section?.title || chapter?.title || '').replace(/^第\s*[一二三四五六七八九十百千\d０-９]+\s*[章节]\s*/, '').trim();
    onPrepare?.({ topic: topic.length >= 2 ? topic.slice(0, 80) : undefined, textbookIds: [textbook.id], sourceBookId: textbook.id, sectionId: section?.id, focusTerms: term.trim().length >= 2 ? [term.trim().slice(0, 80)] : [] });
  };

  if (loading) return <div className="page-loading"><Spin /> 正在读取教材正文与目录…</div>;
  if (error) return <section className="teaching-error"><Alert type="error" message={error} action={<Button onClick={() => setRetry(retry + 1)}>重试</Button>} /><Button onClick={onBack}>返回教材库</Button></section>;
  if (!data) return null;

  return (
    <section className={`teaching-workspace ${focus ? 'lecture-focus' : ''} ${large ? 'lecture-large' : ''} ${catalogOpen ? 'catalog-open' : ''}`}>
      <header className="teaching-header">
        <div className="teaching-title"><button className="text-link" onClick={onBack}><ArrowLeftOutlined /> 教材库</button><span className="teaching-overline">阅读教材</span><h1>{data.title}</h1></div>
        <div className="teaching-header-actions"><span>{data.chapters.length} 章 · {unitCount || totalSections} {unitLabel}</span><Button className="mobile-outline-toggle" onClick={() => setCatalogOpen(!catalogOpen)}>{catalogOpen ? '收起目录' : '目录 / 搜索'}</Button><Button onClick={() => setLarge(!large)} aria-pressed={large}>字号 {large ? 'A−' : 'A+'}</Button><Button icon={focus ? <FullscreenExitOutlined /> : <FullscreenOutlined />} onClick={() => setFocus(!focus)}>{focus ? '退出专注阅读' : '专注阅读'}</Button></div>
      </header>
      <div className="teaching-status"><span className="status-dot" /> {String(data.readiness.chapters_with_text ?? data.chapters.length)} 章正文可读 <i /> {data.has_pdf ? '原页与插图可查' : '当前教材无 PDF 原页'} <i /> 个人收藏保存在此浏览器</div>
      <div className="teaching-layout">
        <aside className="teaching-outline" aria-label="教材目录">
          <Input prefix={<SearchOutlined />} allowClear placeholder="输入知识点，搜索全书" value={position.query} onChange={(e) => setPosition({ ...position, query: e.target.value })} aria-label="搜索全书" />
          {position.query.trim().length >= 2 && (
            <div className="teaching-search-results" aria-live="polite">
              <div className="outline-label">{searching ? '正在搜索完整正文…' : `全文匹配 ${hitTotal} 处${hitTotal > hits.length ? ` · 显示前 ${hits.length} 处` : ''}`}</div>
              {searchError ? <p role="alert">{searchError}</p> : !searching && !hits.length ? <p>本次未检索到原文匹配。可缩短术语，或查看目录与教材原页。</p> : hits.map((hit) => <button className="teaching-hit" key={hit.id} onClick={() => openHit(hit)}><strong>{hit.title}</strong><small>{hit.chapter_title} · {pageLabel(hit.page_start, hit.page_end)}</small><span><Highlight text={hit.excerpt} query={position.query} /></span></button>)}
            </div>
          )}
          <button className={`outline-overview ${!chapter ? 'selected' : ''}`} onClick={() => setPosition({ ...position, chapterId: '', sectionId: '', scroll: 0 })}>全书概览 <span>{data.chapters.length} 章</span></button>
          <nav>{data.chapters.map((item, i) => <div className="outline-chapter" key={item.id}><button className={item.id === chapter?.id ? 'selected' : ''} onClick={() => setPosition({ ...position, chapterId: item.id, sectionId: '', page: item.page_start || 1, scroll: 0 })}><span>{String(i + 1).padStart(2, '0')}</span><strong>{item.title}</strong><small>{rootsOf(item.sections).length}</small></button>{item.id === chapter?.id && <div className="outline-sections">{visibleOutline.map((s) => <div className="outline-item" key={s.id}><button className={s.id === section?.id ? 'selected' : ''} style={{ paddingLeft: `${8 + Math.min(3, Math.max(0, s.level - 2)) * 10}px` }} onClick={() => openSection(item.id, s)}>{stars.includes(s.id) && <StarFilled />} {s.title}</button>{chapterRoots.some((r) => r.id === s.id) && sectionBlock(item.sections, s.id).length > 1 && <button className="outline-expand" aria-label={`${expandedRoots.includes(s.id) ? '收起' : '展开'}细目：${s.title}`} onClick={() => setExpandedRoots((current) => current.includes(s.id) ? current.filter((id) => id !== s.id) : [...current, s.id])}>{expandedRoots.includes(s.id) ? '−' : '+'}</button>}</div>)}</div>}</div>)}</nav>
        </aside>

        <div className={`teaching-content-area ${position.showSource && data.has_pdf ? 'with-source' : ''}`}>
          <div className="teaching-reader" ref={reader} onScroll={(e) => { const scroll = e.currentTarget.scrollTop; positionRef.current = { ...positionRef.current, scroll }; writeLocal(storageKey, positionRef.current); }}>
            {!chapter ? <>
              <div className="reader-eyebrow">全书概览</div><h2>从目录找到需要的材料</h2><p className="reader-intro">按章节阅读完整原文；打开小节后，可核对原页、收藏，或直接用这一节备课。</p>
              <div className={`chapter-table ${data.chapters.length > 12 ? 'many-chapters' : ''}`}>{data.chapters.map((item, i) => <article key={item.id}><button onClick={() => setPosition({ ...position, chapterId: item.id, sectionId: '', page: item.page_start || 1, scroll: 0 })}><span className="chapter-number">{String(i + 1).padStart(2, '0')}</span><div><h3>{item.title}</h3><p>{rootsOf(item.sections).slice(0, data.chapters.length > 12 ? 4 : 8).map((s) => s.title.replace(/^第[^节]+节\s*/, '')).join(' / ')}</p></div><span className="chapter-page">{rootsOf(item.sections).length} {rootsOf(item.sections).every(isFormal) ? '节' : '单元'}<br />{pageLabel(item.page_start, item.page_end)} →</span></button></article>)}</div>
              <section className="lesson-priorities"><h3><StarOutlined /> 我的收藏 <small>此浏览器保存</small></h3>{selectedStars.length ? selectedStars.map((item) => <button key={item.section.id} onClick={() => openSection(item.chapter.id, item.section)}>{item.chapter.title} / {item.section.title}<span>{pageLabel(item.section.page_start, item.section.page_end)} →</span></button>) : <p>打开常用小节，点击“收藏小节”，便于下次查阅。</p>}</section>
            </> : !section ? <>
              <div className="reader-eyebrow">章节目录 · {pageLabel(chapter.page_start, chapter.page_end)}</div><h2>{chapter.title}</h2><p className="reader-intro">共 {chapterRoots.length} 个主要条目，含 {chapter.sections.length} 个细目。星标表示个人收藏。</p><Button size="small" className="outline-detail-toggle" onClick={() => setAllDetails(!allDetails)}>{allDetails ? '收起细目' : '展开全部细目'}</Button>
              <div className="section-table">{(allDetails ? chapter.sections : chapterRoots).map((s) => <article key={s.id} style={{ paddingLeft: `${allDetails ? Math.min(3, Math.max(0, s.level - 2)) * 16 : 0}px` }}><Button type="text" icon={stars.includes(s.id) ? <StarFilled /> : <StarOutlined />} onClick={() => toggleStar(s.id)} aria-label={`${stars.includes(s.id) ? '取消收藏' : '收藏'}：${s.title}`} /><button onClick={() => openSection(chapter.id, s)}><strong>{s.title}</strong><span>{pageLabel(s.page_start, s.page_end)} →</span></button></article>)}</div>
            </> : <>
              <div className="reader-eyebrow">{chapter.title} / 原文小节 · {pageLabel(section.page_start, sectionEndPage)}</div>
              <h2>{section.title}</h2>
              <div className="reading-tools">{onPrepare && <Button type="primary" onClick={prepare}>用这一节备课 →</Button>}<Button icon={stars.includes(section.id) ? <StarFilled /> : <StarOutlined />} onClick={() => toggleStar(section.id)}>{stars.includes(section.id) ? '已收藏小节' : '收藏小节'}</Button>{data.has_pdf && <Button icon={<FileImageOutlined />} onClick={() => setPosition({ ...positionRef.current, showSource: !position.showSource })}>{position.showSource ? '收起原页' : '查看原页 / 插图'}</Button>}</div>
              <div className="teaching-body" onMouseUp={() => { const value = window.getSelection()?.toString().trim(); if (value && value.length <= 80) setTerm(value); }}>{blocks.map((block, blockIndex) => <div key={block.id}>{blockIndex > 0 && <h3 style={{ fontSize: `${Math.max(17, 25 - block.level)}px` }}>{block.title}{data.has_pdf && <button onClick={() => setPosition({ ...positionRef.current, page: block.page_start || 1, showSource: true })} className="body-page-link">PDF {block.page_start} ↗</button>}</h3>}{reflowSource(block.content).split(/\n\s*\n/).filter(Boolean).map((p, i) => <p key={i}><Highlight text={p} query={position.query} /></p>)}</div>)}</div>
              {!!figures.length && <div className="figure-links"><strong>文中插图</strong>{figures.map((figure, i) => <button key={`${figure.label}-${i}`} onClick={() => setPosition({ ...positionRef.current, page: figure.page_number, showSource: true })}>{figure.label} · PDF {figure.page_number} ↗</button>)}</div>}
              <div className="section-end"><span>本节原文结束</span><div><Button disabled={navigationIndex <= 0} onClick={() => go(-1)}>← 上一节</Button><Button disabled={nextIndex >= navigation.length} onClick={() => go(1)}>下一节 →</Button></div></div>
            </>}
          </div>
          {position.showSource && data.has_pdf && <SourcePageViewer textbookId={textbook.id} title={textbook.title} page={position.page} totalPages={data.total_pages} onPageChange={(page) => setPosition({ ...positionRef.current, page })} onClose={() => setPosition({ ...positionRef.current, showSource: false })} />}
          <footer className="teaching-bridge-bar"><BranchesOutlined /><div><strong>查阅其他教材的表述</strong><small>选中正文中的术语，或输入具体知识点</small></div><Input placeholder="输入要对照的知识点" value={term} onChange={(e) => setTerm(e.target.value)} onPressEnter={compare} aria-label="跨教材知识点" maxLength={80} /><Button onClick={compare}>跨教材对照 →</Button></footer>
        </div>
      </div>
    </section>
  );
};
export default TeachingWorkspace;
