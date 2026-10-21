import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { textbookColor } from './crossbookModel';
import './ConceptRelationCanvas.css';

export interface RelationCanvasNode {
  id: string;
  title: string;
  bookId: string;
  bookTitle: string;
  pageLabel: string;
  evidenceCount: number;
  selected: boolean;
  kind: 'source_heading' | 'source_subheading' | 'topic_excerpt' | 'teacher';
  isAnchor?: boolean;
}

export interface RelationCanvasEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  reason: string;
  status: 'draft' | 'confirmed';
  directed: boolean;
}

export interface ConceptRelationCanvasProps {
  topic: string;
  nodes: RelationCanvasNode[];
  edges: RelationCanvasEdge[];
  activeNodeId?: string;
  activeEdgeId?: string;
  view: 'explore' | 'lesson';
  onNodeClick: (id: string) => void;
  onEdgeClick: (id: string) => void;
  onFocus: (id: string) => void;
  onResetFocus: () => void;
  hiddenNodeCount?: number;
  onShowMore?: () => void;
}

interface Point { x: number; y: number }
interface PositionedNode extends Point { node: RelationCanvasNode }
interface BookGroup extends Point { id: string; title: string; count: number; width: number; height: number }
const CARD_WIDTH = 264;
const CARD_HEIGHT = 184;
const ROW_GAP = 28;
const MIN_ZOOM = .45;
const MAX_ZOOM = 1.6;
const kindLabels: Record<RelationCanvasNode['kind'], string> = {
  source_heading: '教材小节', source_subheading: '教材细目', topic_excerpt: '待命名材料', teacher: '教师讲授点',
};

// Positions follow the supplied evidence and book groups. No semantic edges are inferred here.
function arrangeNodes(nodes: RelationCanvasNode[], edges: RelationCanvasEdge[], wide: boolean) {
  const unique = nodes.filter((node, at) => nodes.findIndex((item) => item.id === node.id) === at);
  const anchor = unique.find((node) => node.isAnchor) || unique[0];
  if (!anchor) return { positioned: [] as PositionedNode[], groups: [] as BookGroup[], width: 740, height: 330, anchorId: '' };
  const linked = new Set(edges.flatMap((edge) => [edge.source, edge.target]));
  const groups = new Map<string, RelationCanvasNode[]>();
  unique.filter((node) => node.id !== anchor.id).forEach((node) => {
    const list = groups.get(node.bookId) || []; list.push(node); groups.set(node.bookId, list);
  });
  const columns = wide ? 2 : 1;
  const rightX = 432;
  const groupWidth = columns * CARD_WIDTH + (columns - 1) * 24;
  const positioned: PositionedNode[] = [{ node: anchor, x: 28, y: 88 }];
  const bookGroups: BookGroup[] = [];
  let top = 50;
  [...groups.entries()].sort(([, first], [, second]) => {
    const score = (items: RelationCanvasNode[]) => Number(items.some((node) => linked.has(node.id))) * 2 + Number(items.some((node) => node.selected));
    return score(second) - score(first);
  }).forEach(([id, items]) => {
    const ordered = [...items].sort((a, b) => Number(linked.has(b.id)) - Number(linked.has(a.id)) || Number(b.selected) - Number(a.selected));
    const rows = Math.ceil(ordered.length / columns);
    const height = 38 + rows * (CARD_HEIGHT + ROW_GAP) - ROW_GAP;
    bookGroups.push({ id, title: ordered[0].bookTitle || '教材来源', count: ordered.length, x: rightX - 12, y: top, width: groupWidth + 24, height });
    ordered.forEach((node, index) => positioned.push({ node, x: rightX + (index % columns) * (CARD_WIDTH + 24), y: top + 38 + Math.floor(index / columns) * (CARD_HEIGHT + ROW_GAP) }));
    top += height + 38;
  });
  return { positioned, groups: bookGroups, width: groups.size ? rightX + groupWidth + 28 : 740, height: Math.max(346, top + 8), anchorId: anchor.id };
}

function edgeGeometry(source: PositionedNode, target: PositionedNode, index: number) {
  const sourceCenter = { x: source.x + CARD_WIDTH / 2, y: source.y + CARD_HEIGHT / 2 };
  const targetCenter = { x: target.x + CARD_WIDTH / 2, y: target.y + CARD_HEIGHT / 2 };
  if (Math.abs(source.x - target.x) < 10) {
    const left = Math.max(306, source.x - 76 - (index % 3) * 15);
    return { path: `M ${source.x} ${sourceCenter.y} C ${left} ${sourceCenter.y}, ${left} ${targetCenter.y}, ${target.x} ${targetCenter.y}`, label: { x: left - 12, y: (sourceCenter.y + targetCenter.y) / 2 } };
  }
  const towardRight = target.x > source.x;
  const a = { x: towardRight ? source.x + CARD_WIDTH : source.x, y: sourceCenter.y };
  const b = { x: towardRight ? target.x : target.x + CARD_WIDTH, y: targetCenter.y };
  const middle = (a.x + b.x) / 2;
  return { path: `M ${a.x} ${a.y} C ${middle} ${a.y}, ${middle} ${b.y}, ${b.x} ${b.y}`, label: { x: middle, y: (a.y + b.y) / 2 } };
}

const ConceptRelationCanvas: React.FC<ConceptRelationCanvasProps> = ({
  topic, nodes, edges, activeNodeId, activeEdgeId, view, onNodeClick, onEdgeClick, onFocus, onResetFocus, hiddenNodeCount = 0, onShowMore,
}) => {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [viewportWidth, setViewportWidth] = useState(800);
  const [zoom, setZoom] = useState(1);
  const [pairOnly, setPairOnly] = useState(false);
  const markerId = `relation-arrow-${useId().replace(/:/g, '')}`;
  useLayoutEffect(() => {
    const element = viewportRef.current; if (!element) return;
    const measure = () => setViewportWidth(element.clientWidth || 800);
    measure();
    const observer = new ResizeObserver(measure); observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const activeEdge = edges.find((edge) => edge.id === activeEdgeId);
  const anchorId = nodes.find((node) => node.isAnchor)?.id || nodes[0]?.id;
  const pairIds = activeEdge ? [activeEdge.source, activeEdge.target] : [anchorId, activeNodeId].filter((id): id is string => !!id);
  const canFocusPair = new Set(pairIds).size === 2;
  const displayedNodes = pairOnly && canFocusPair ? nodes.filter((node) => pairIds.includes(node.id)) : nodes;
  const layout = useMemo(() => arrangeNodes(displayedNodes, edges, viewportWidth >= 1100), [displayedNodes, edges, viewportWidth]);
  const bookColors = useMemo(() => new Map(nodes.map((node) => [node.bookId, textbookColor(node.bookId)])), [nodes]);
  const nodeMap = useMemo(() => new Map(layout.positioned.map((item) => [item.node.id, item])), [layout]);
  const actualEdges = useMemo(() => edges.filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target) && edge.source !== edge.target), [edges, nodeMap]);
  const edgeDrawings = useMemo(() => {
    const labels: Point[] = [];
    return actualEdges.map((edge, index) => {
      const geometry = edgeGeometry(nodeMap.get(edge.source)!, nodeMap.get(edge.target)!, index);
      // Keep the relation controls legible when several connections share a route.
      const label = { ...geometry.label };
      while (labels.some((at) => Math.abs(at.x - label.x) < 150 && Math.abs(at.y - label.y) < 48)) label.y += 48;
      label.y = Math.max(36, label.y); labels.push(label);
      return { edge, ...geometry, label };
    });
  }, [actualEdges, nodeMap, layout.height]);
  const canvasHeight = Math.max(layout.height, ...edgeDrawings.map(({ label }) => label.y + 36));
  const candidates = nodes.filter((node) => !node.selected).length;
  useEffect(() => setPairOnly(false), [topic, view]);
  const locateSelection = () => {
    const element = viewportRef.current;
    const node = nodeMap.get(activeNodeId || '') || nodeMap.get(layout.anchorId);
    if (!element || !node) return;
    element.scrollTo({ left: Math.max(0, (node.x + CARD_WIDTH / 2) * zoom - element.clientWidth / 2), top: Math.max(0, (node.y + CARD_HEIGHT / 2) * zoom - element.clientHeight / 2) });
  };
  useEffect(() => {
    const frame = requestAnimationFrame(locateSelection);
    return () => cancelAnimationFrame(frame);
    // Selection changes must reveal the card, including a card selected from the material path.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeNodeId, activeEdgeId, layout.anchorId, pairOnly, zoom, topic, view]);
  const changeZoom = (value: number) => setZoom(Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(value * 100) / 100)));
  const fit = () => {
    changeZoom(Math.min(1, (viewportWidth - 20) / layout.width));
    if (viewportRef.current) { viewportRef.current.scrollLeft = 0; viewportRef.current.scrollTop = 0; }
  };

  return <section className={`concept-relation-canvas cr-view-${view}`} aria-label={`${topic || '当前主题'}的教材知识点关系图`}>
    <div className="cr-toolbar">
      <div className="cr-canvas-caption"><strong>{view === 'lesson' ? '本课已记录的关系' : '材料关系图'}</strong><span>{displayedNodes.length} 个知识点 · {actualEdges.length} 条本课关系</span></div>
      <div className="cr-tools" aria-label="关系图显示工具">{view === 'explore' && <button type="button" onClick={onResetFocus} title="返回当前主题的全部材料">返回主题</button>}<button type="button" aria-pressed={pairOnly && canFocusPair} disabled={!canFocusPair} onClick={() => setPairOnly(!pairOnly)}>{pairOnly && canFocusPair ? '显示全部' : '聚焦两侧'}</button><button type="button" onClick={locateSelection} disabled={!nodes.length}>定位选中</button><div className="cr-zoom"><button type="button" aria-label="缩小关系图" onClick={() => changeZoom(zoom - .1)} disabled={zoom <= MIN_ZOOM}>−</button><output aria-live="polite">{Math.round(zoom * 100)}%</output><button type="button" aria-label="放大关系图" onClick={() => changeZoom(zoom + .1)} disabled={zoom >= MAX_ZOOM}>＋</button></div><button type="button" onClick={fit} title="适配当前宽度；可再放大阅读">适配</button></div>
    </div>
    <div className="cr-legend"><span><i className="cr-key-confirmed" />教师已确认</span><span><i className="cr-key-draft" />关系草稿</span>{candidates > 0 && <span><i className="cr-key-candidate" />检索候选 · 待选用</span>}<small>箭头仅表示有方向的关系</small></div>
    <div className="cr-viewport" ref={viewportRef} tabIndex={0} aria-label="关系图画布，可滚动查看；Tab键可逐项核对知识点和关系">
      {!nodes.length ? <div className="cr-empty"><span aria-hidden="true">◎</span><h3>{view === 'lesson' ? '本课还没有选用知识点' : '从当前讲授内容开始'}</h3><p>{view === 'lesson' ? '先核对教材证据，再把需要的知识点选入本课。' : '确定主题与教材后，检索到的知识点会按教材列在这里。'}</p></div> : <div className="cr-stage-size" style={{ width: layout.width * zoom, height: canvasHeight * zoom }}><div className="cr-stage" style={{ width: layout.width, height: canvasHeight, transform: `scale(${zoom})` }}>
        <div className="cr-anchor-label" style={{ left: 28, top: 50 }}>{view === 'lesson' ? '当前讲授起点' : '当前探索起点'}</div>
        {layout.groups.map((group) => <div className="cr-book-group" key={group.id} style={{ left: group.x, top: group.y, width: group.width, height: group.height, '--cr-book-color': bookColors.get(group.id) } as React.CSSProperties}><header><strong title={group.title}>{group.title}</strong><span>{group.count} 个知识点</span></header></div>)}
        <svg className="cr-lines" width={layout.width} height={canvasHeight} aria-hidden="true"><defs><marker id={markerId} markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M 0 0 L 9 4.5 L 0 9 Z" fill="context-stroke" /></marker></defs>{edgeDrawings.map(({ edge, path }) => <g key={edge.id} className={`cr-edge ${edge.status} ${activeEdgeId === edge.id ? 'is-active' : ''}`}><path className="cr-edge-hit" d={path} onClick={() => onEdgeClick(edge.id)} /><path className="cr-edge-stroke" d={path} markerEnd={edge.directed ? `url(#${markerId})` : undefined} /></g>)}</svg>
        {edgeDrawings.map(({ edge, label }) => <button type="button" key={edge.id} className={`cr-edge-label ${edge.status} ${activeEdgeId === edge.id ? 'is-active' : ''}`} style={{ left: label.x, top: label.y }} title={`${edge.label}：${edge.reason || '尚未填写关系理由'}`} aria-label={`${nodeMap.get(edge.source)?.node.title}与${nodeMap.get(edge.target)?.node.title}：${edge.label}，${edge.status === 'confirmed' ? '教师已确认' : '关系草稿'}。查看双侧证据`} aria-pressed={activeEdgeId === edge.id} onClick={() => onEdgeClick(edge.id)}><strong>{edge.label || '教学关系'}</strong><span>{edge.status === 'confirmed' ? '已确认' : '草稿'} · 核对证据</span></button>)}
        {layout.positioned.map(({ node, x, y }) => <article key={node.id} className={`cr-node ${node.selected ? 'is-selected' : 'is-candidate'} ${node.id === layout.anchorId ? 'is-anchor' : ''} ${node.id === activeNodeId ? 'is-active' : ''}`} style={{ left: x, top: y, width: CARD_WIDTH, height: CARD_HEIGHT, '--cr-book-color': bookColors.get(node.bookId) } as React.CSSProperties}>
          <button type="button" className="cr-node-main" aria-label={`${node.title}，《${node.bookTitle}》，${node.pageLabel}，${node.selected ? '已选入本课' : '检索候选'}。查看教材证据`} aria-pressed={node.id === activeNodeId} onClick={() => onNodeClick(node.id)}><span className="cr-node-top"><span>{kindLabels[node.kind]}</span><span className="cr-node-status">{node.selected ? '✓ 已选入本课' : '待选用'}</span></span><strong className="cr-node-title" title={node.title}>{node.title || '未命名知识点'}</strong><span className="cr-node-book" title={node.bookTitle}>{node.bookTitle}</span><span className="cr-node-location">{node.pageLabel || '页码待核对'}<span>{node.evidenceCount} 条原文 ↗</span></span></button>
          {view === 'explore' && <button type="button" className="cr-explore-node" onClick={() => onFocus(node.id)} aria-label={`以${node.title}为起点继续探索`}>{node.id === layout.anchorId ? '以此点刷新探索' : '从此点继续探索'} <span aria-hidden="true">→</span></button>}
        </article>)}
      </div></div>}
    </div>
    <footer className="cr-canvas-footer"><p>{candidates > 0 ? '候选按教材分组，未确认知识关系的材料不连线。' : '点击知识点核对原文，点击关系查看理由与双侧证据。'}{layout.width * zoom > viewportWidth + 5 ? ' 可在画布内左右滚动。' : ''}</p>{view === 'explore' && hiddenNodeCount > 0 && <button type="button" onClick={onShowMore} disabled={!onShowMore}>还有 {hiddenNodeCount} 个候选{onShowMore ? ' · 继续查看 →' : ' · 当前未展开'}</button>}</footer>
  </section>;
};

export default ConceptRelationCanvas;
