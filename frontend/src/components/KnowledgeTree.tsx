import React, { useEffect, useMemo, useState } from 'react';
import { Button, Empty, Input, Spin, Tag } from 'antd';
import {
  ArrowLeftOutlined,
  BookOutlined,
  CheckCircleFilled,
  DownOutlined,
  FileSearchOutlined,
  RightOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { Chapter, GraphData, GraphNode, Textbook } from '../types';

interface Props {
  textbook: Textbook;
  chapters: Chapter[];
  graphData: GraphData | null;
  loading: boolean;
  onBack: () => void;
  onSelectNode: (node: GraphNode) => void;
  onReviewChapters: () => void;
  onExtract: () => void;
}

interface ChapterGroup {
  key: string;
  title: string;
  pageStart: number;
  pageEnd: number;
  nodes: GraphNode[];
  rawCount: number;
}

const INITIAL_VISIBLE_NODES = 8;
const LOAD_MORE_STEP = 8;
const graphReady = (status: string) => ['completed', 'review'].includes(status);

const cleanText = (value: string = '') => value
  .replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')
  .replace(/\uFFFD+/g, ' ')
  .replace(/[\s\u2000-\u200f\u2028-\u202f\u205f\u3000]+/g, ' ')
  .trim();

const chapterIdentity = (value: string = '') => {
  const title = cleanText(value);
  if (/^(?:绪论|前言|序言)/u.test(title)) return 'intro';
  const match = title.match(/^第\s*([一二三四五六七八九十百〇零两\d]+)\s*章/u);
  return match ? `chapter-${match[1]}` : '';
};

const chapterTitleCandidate = (value: string = '') => {
  const title = cleanText(value);
  if (/^(?:绪论|前言|序言)/u.test(title)) return '绪论';
  const match = title.match(/^(第\s*[一二三四五六七八九十百〇零两\d]+\s*章)\s*(.*)$/u);
  if (!match) return '';
  const prefix = match[1].replace(/\s+/g, '');
  const suffix = match[2].replace(/^[\s:：·—-]+|[…。，；：、）)]+$/gu, '').trim();
  if (!suffix || suffix.length > 14 || /[；。！？]/u.test(suffix)) return prefix;
  return `${prefix} ${suffix}`;
};

const displayNode = (node: GraphNode): GraphNode | null => {
  const original = cleanText(node.label || '');
  if (original.length < 2 || original.length > 60) return null;
  if (/^\d+(?:[.,\s~-]+\d+)*\s*(?:cm|mm|kg|g|元|页|年|月|日)?[。，]?$/iu.test(original)) return null;

  if (node.granularity === 'section_topic') {
    const heading = original.match(/^(?:第[一二三四五六七八九十百〇零两\d]+节|[一二三四五六七八九十]+[、.．]|\d+[、.．])\s*(.{2,26})$/u);
    // New evidence-first extraction already stores a clean section name.
    // Legacy nodes may still include the numbering prefix, so support both.
    const label = cleanText(heading?.[1] || original).replace(/[。；：].*$/u, '').trim();
    if (label.length < 2 || label.length > 24 || /(?:cm|mm|kg|\d{2,})/iu.test(label)) return null;
    return { ...node, label, definition: original === label ? node.definition : original };
  }

  if (node.granularity !== 'core_concept') return null;
  if (original.length > 22 || /[。；：、]/u.test(original)) return null;
  if (/^(?:本章|临床|注意|可能|应当|应该|此|该|或|对|以|有助于|出现|诊断为|个月)/u.test(original)) return null;
  if (/(?:可发生|可能引起|注意勿|注意不要|受到损伤|易受损伤|患有|提示为|的病|疾病的)$/u.test(original)) return null;
  if (/^(?:临床病|不是病|流行病)$/u.test(original)) return null;
  return { ...node, label: original };
};

const prepareNodes = (nodes: GraphNode[]) => {
  const source = nodes.map(displayNode).filter((node): node is GraphNode => Boolean(node));
  const unique = new Map<string, GraphNode>();
  source.forEach((node) => {
    const key = node.label.replace(/[\s\p{P}]+/gu, '').toLocaleLowerCase();
    const current = unique.get(key);
    if (!current || (node.quality_score || 0) > (current.quality_score || 0)) unique.set(key, node);
  });
  return [...unique.values()].sort((a, b) => (
    Number(b.granularity === 'section_topic') - Number(a.granularity === 'section_topic')
    || (b.importance || 0) - (a.importance || 0)
    || (b.quality_score || 0) - (a.quality_score || 0)
  )).slice(0, 36);
};

const KnowledgeTree: React.FC<Props> = ({
  textbook,
  chapters,
  graphData,
  loading,
  onBack,
  onSelectNode,
  onReviewChapters,
  onExtract,
}) => {
  const [query, setQuery] = useState('');
  const [activeChapter, setActiveChapter] = useState('');
  const [view, setView] = useState<'overview' | 'chapter'>('overview');
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_NODES);

  const groups = useMemo<ChapterGroup[]>(() => {
    const nodes = graphData?.nodes || [];
    const ordered = [...chapters].sort((a, b) => (a.order_index || 0) - (b.order_index || 0));
    const chapterBuckets = new Map<string, { titles: Map<string, number>; pageStart: number; pageEnd: number }>();

    ordered.forEach((chapter) => {
      const key = chapterIdentity(chapter.title);
      const candidate = chapterTitleCandidate(chapter.title);
      if (!key || !candidate) return;
      const bucket = chapterBuckets.get(key) || {
        titles: new Map<string, number>(),
        pageStart: chapter.page_start || Number.MAX_SAFE_INTEGER,
        pageEnd: chapter.page_end || 0,
      };
      bucket.titles.set(candidate, (bucket.titles.get(candidate) || 0) + 1);
      bucket.pageStart = Math.min(bucket.pageStart, chapter.page_start || Number.MAX_SAFE_INTEGER);
      bucket.pageEnd = Math.max(bucket.pageEnd, chapter.page_end || chapter.page_start || 0);
      chapterBuckets.set(key, bucket);
    });

    nodes.forEach((node) => {
      const key = chapterIdentity(node.chapter);
      const candidate = chapterTitleCandidate(node.chapter);
      if (!key || !candidate || chapterBuckets.has(key)) return;
      chapterBuckets.set(key, {
        titles: new Map([[candidate, 1]]),
        pageStart: node.page_start || node.page || Number.MAX_SAFE_INTEGER,
        pageEnd: node.page_start || node.page || 0,
      });
    });

    const preparedGroups = [...chapterBuckets.entries()]
      .map(([key, bucket]) => {
        const chapterNodes = nodes.filter((node) => chapterIdentity(node.chapter) === key);
        const title = [...bucket.titles.entries()]
          .sort((a, b) => b[1] - a[1] || b[0].length - a[0].length)[0]?.[0] || '未命名章节';
        return {
          key,
          title,
          pageStart: bucket.pageStart === Number.MAX_SAFE_INTEGER ? 0 : bucket.pageStart,
          pageEnd: bucket.pageEnd,
          nodes: prepareNodes(chapterNodes),
          rawCount: chapterNodes.length,
        };
      })
      .filter((group) => group.nodes.length > 0 || group.key === 'intro')
      .sort((a, b) => a.pageStart - b.pageStart);
    const formalChapters = preparedGroups.filter((group) => group.key !== 'intro');
    return formalChapters.length ? formalChapters : preparedGroups;
  }, [chapters, graphData]);

  const defaultGroup = useMemo(() => (
    groups.find((group) => group.key !== 'intro' && group.nodes.length > 0)
    || groups.find((group) => group.nodes.length > 0)
    || groups[0]
  ), [groups]);

  useEffect(() => {
    if (!activeChapter || !groups.some((group) => group.key === activeChapter)) {
      setActiveChapter(defaultGroup?.key || '');
    }
  }, [activeChapter, defaultGroup, groups]);

  useEffect(() => setVisibleCount(INITIAL_VISIBLE_NODES), [activeChapter]);

  const currentGroup = groups.find((group) => group.key === activeChapter) || defaultGroup;
  const normalizedQuery = cleanText(query).toLocaleLowerCase();
  const searchGroups = useMemo(() => {
    if (!normalizedQuery) return [];
    return groups
      .map((group) => {
        const chapterMatches = group.title.toLocaleLowerCase().includes(normalizedQuery);
        return {
          ...group,
          nodes: chapterMatches ? group.nodes : group.nodes.filter((node) => (
            node.label.toLocaleLowerCase().includes(normalizedQuery)
            || cleanText(node.definition).toLocaleLowerCase().includes(normalizedQuery)
          )),
        };
      })
      .filter((group) => group.title.toLocaleLowerCase().includes(normalizedQuery) || group.nodes.length > 0);
  }, [groups, normalizedQuery]);

  const openChapter = (key: string) => {
    setActiveChapter(key);
    setQuery('');
    setView('chapter');
  };

  const totalNodes = graphData?.total_nodes ?? graphData?.nodes.length ?? 0;
  const hasLoadedKnowledge = Boolean(graphData?.nodes?.length);
  const knowledgeReady = graphReady(textbook.graph_status) || hasLoadedKnowledge;
  const workflowIncomplete = textbook.parse_status !== 'completed' || !knowledgeReady;

  return (
    <section className="tree-page flow-page">
      <div className="tree-toolbar">
        <div className="tree-title-group">
          <Button className="back-button" icon={<ArrowLeftOutlined />} onClick={onBack}>教材库</Button>
          <div>
            <div className="tree-title-line">
              <h1>{textbook.title}</h1>
              {knowledgeReady && (
                <Tag icon={<CheckCircleFilled />} color="success">
                  {textbook.graph_status === 'review' ? '知识结构已生成 · 可继续复核' : '知识结构已生成'}
                </Tag>
              )}
            </div>
            <p>{groups.length} 个主章节 · 已从 {totalNodes} 条原始记录整理出学习主线</p>
          </div>
        </div>
        <Input
          className="tree-search"
          allowClear
          prefix={<SearchOutlined />}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索章节或知识点"
        />
      </div>

      {knowledgeReady && textbook.structure_status === 'review' && (
        <div className="tree-notice">
          <span>历史教材已可查看；章节结构仍可在教材库中继续核对。</span>
          <Button type="link" onClick={onReviewChapters}>核对章节</Button>
        </div>
      )}

      {loading ? (
        <div className="tree-loading"><Spin size="large" /><span>正在整理教材知识流程…</span></div>
      ) : workflowIncomplete ? (
        <div className="workflow-empty">
          <span className="empty-symbol"><FileSearchOutlined /></span>
          <h2>知识流程还没有准备好</h2>
          <p>{textbook.parse_status !== 'completed' ? '请先在教材库解析教材。' : '教材已经解析，现在可以生成知识结构。'}</p>
          <Button type="primary" size="large" onClick={textbook.structure_status === 'confirmed' ? onExtract : onReviewChapters}>
            {textbook.structure_status === 'confirmed' ? '生成知识结构' : '返回教材库确认章节'}
          </Button>
        </div>
      ) : groups.length === 0 ? (
        <Empty description="这本教材暂时没有可展示的知识点" />
      ) : normalizedQuery ? (
        <div className="flow-workspace flow-search-workspace">
          <div className="flow-search-heading">
            <div><span className="flow-kicker">SEARCH PATH</span><h2>搜索“{cleanText(query)}”</h2></div>
            <p>{searchGroups.reduce((count, group) => count + group.nodes.length, 0)} 个匹配知识点</p>
          </div>
          {searchGroups.length ? (
            <div className="flow-search-groups">
              {searchGroups.map((group) => (
                <section className="flow-search-group" key={group.key}>
                  <button className="search-group-title" onClick={() => openChapter(group.key)}>
                    <span>{group.title}</span><RightOutlined />
                  </button>
                  <div className="search-node-grid">
                    {group.nodes.slice(0, 8).map((node) => (
                      <button key={node.id} onClick={() => onSelectNode(node)}>
                        <strong>{node.label}</strong><small>P.{node.page_start || node.page || '—'}</small>
                      </button>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          ) : <Empty description="没有找到匹配的章节或知识点" />}
        </div>
      ) : (
        <div className="flow-workspace">
          <div className="flow-viewbar">
            <div>
              <button className={view === 'overview' ? 'active' : ''} onClick={() => setView('overview')}>全书主线</button>
              <button className={view === 'chapter' ? 'active' : ''} onClick={() => setView('chapter')}>本章流程</button>
            </div>
            <p>{view === 'overview' ? '先看全书结构，再进入某章' : '按教学顺序阅读大节点，点击查看原文'}</p>
          </div>

          {view === 'overview' ? (
            <div className="book-flow-overview">
              <div className="flow-book-card">
                <span><BookOutlined /></span>
                <div><small>课程教材</small><strong>{textbook.title}</strong></div>
              </div>
              <div className="flow-entry-arrow"><DownOutlined /></div>
              <div className="chapter-roadmap">
                <div className="roadmap-spine" />
                {groups.map((group, index) => (
                  <button className={`roadmap-stop ${index % 2 === 0 ? 'left' : 'right'}`} key={group.key} onClick={() => openChapter(group.key)}>
                    <span className="roadmap-marker">{String(index + 1).padStart(2, '0')}</span>
                    <span className="roadmap-card">
                      <span className="roadmap-meta">第 {group.pageStart || '—'}–{group.pageEnd || group.pageStart || '—'} 页</span>
                      <strong>{group.title}</strong>
                      <span className="roadmap-concepts">
                        {group.nodes.slice(0, 4).map((node) => <i key={node.id}>{node.label}</i>)}
                      </span>
                      <span className="roadmap-action">查看 {group.nodes.length} 个知识点 <RightOutlined /></span>
                    </span>
                  </button>
                ))}
                <div className="roadmap-finish">完成全书主线</div>
              </div>
            </div>
          ) : currentGroup ? (
            <div className="chapter-flow-view">
              <header className="chapter-flow-heading">
                <button onClick={() => setView('overview')}><ArrowLeftOutlined /> 全书主线</button>
                <div>
                  <span className="flow-kicker">CHAPTER FLOW</span>
                  <h2>{currentGroup.title}</h2>
                  <p>共 {currentGroup.nodes.length} 个可用知识点，默认先呈现最重要的 {Math.min(INITIAL_VISIBLE_NODES, currentGroup.nodes.length)} 个。</p>
                </div>
              </header>
              <div className="chapter-flow-sequence">
                <div className="flow-terminal start"><span>START</span><strong>进入本章</strong></div>
                {currentGroup.nodes.slice(0, visibleCount).map((node, index) => (
                  <React.Fragment key={node.id}>
                    <span className="flow-arrow"><DownOutlined /></span>
                    <button className="flow-concept-card" onClick={() => onSelectNode(node)}>
                      <span className="flow-step">{String(index + 1).padStart(2, '0')}</span>
                      <span className="flow-concept-copy">
                        <small>{node.granularity === 'section_topic' ? '章节主题' : '核心知识点'}</small>
                        <strong>{node.label}</strong>
                        <p>{cleanText(node.definition) || '点击查看定义与教材原文'}</p>
                      </span>
                      <span className="flow-page-number">P.{node.page_start || node.page || '—'}</span>
                      <RightOutlined />
                    </button>
                  </React.Fragment>
                ))}
                {visibleCount < currentGroup.nodes.length ? (
                  <><span className="flow-arrow muted"><DownOutlined /></span><Button className="flow-load-more" onClick={() => setVisibleCount((count) => count + LOAD_MORE_STEP)}>继续展开后续 {Math.min(LOAD_MORE_STEP, currentGroup.nodes.length - visibleCount)} 个知识点</Button></>
                ) : (
                  <><span className="flow-arrow"><DownOutlined /></span><div className="flow-terminal finish"><span>END</span><strong>本章学习完成</strong></div></>
                )}
              </div>
            </div>
          ) : <Empty description="这一章没有可展示的知识点" />}
        </div>
      )}
    </section>
  );
};

export default KnowledgeTree;
