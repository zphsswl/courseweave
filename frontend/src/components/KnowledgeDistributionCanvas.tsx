import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ConceptRelationCanvasProps, RelationCanvasNode, RelationCanvasEdge } from './ConceptRelationCanvas';
import { textbookColor } from './crossbookModel';
import './KnowledgeDistributionCanvas.css';

export interface DistributionCanvasNode extends RelationCanvasNode {
  chapterPath?: string[];
  chapterPathIds?: string[];
  retrieved?: boolean;
}
export interface DistributionBookTotal {
  id: string; title: string; loaded: number; total?: number | null;
  loadState?: string;
}
export interface KnowledgeDistributionCanvasProps extends Omit<ConceptRelationCanvasProps, 'nodes' | 'view' | 'onFocus' | 'onResetFocus'> {
  nodes: DistributionCanvasNode[];
  view?: 'explore' | 'lesson';
  onFocus?: (id: string) => void;
  onResetFocus?: () => void;
  bookTotals?: DistributionBookTotal[];
  loading?: boolean;
  initialLayout?: 'orbit' | 'hierarchy';
}

type LayoutMode = 'orbit' | 'hierarchy';
interface Point { x: number; y: number }
interface BookGroup { id: string; title: string; nodes: DistributionCanvasNode[]; loaded?: number; total?: number | null; loadState?: string }
interface PlacedNode extends Point { node: DistributionCanvasNode; width: number; height: number }
interface PlacedBook extends Point { group: BookGroup; radius: number; left: number; top: number; width: number; height: number }
interface DistributionLayout { width: number; height: number; center: Point; books: PlacedBook[]; nodes: PlacedNode[] }
interface Transform extends Point { scale: number }
const NODE_W = 150;
const NODE_H = 82;
const BOOK_W = 184;
const BOOK_H = 74;
const MIN_SCALE = .06;
const MAX_SCALE = 1.8;
const originLabels: Record<DistributionCanvasNode['kind'], string> = {
  source_heading: '来源小节', source_subheading: '正文小标题', topic_excerpt: '原文片段', teacher: '教师讲授点',
};
const compareText = (a: string, b: string) => a.localeCompare(b, 'zh-CN', { numeric: true });
const clampScale = (scale: number) => Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));

function makeGroups(nodes: DistributionCanvasNode[], totals: DistributionBookTotal[]): BookGroup[] {
  const groups = new Map<string, BookGroup>();
  totals.forEach((book) => { if (!groups.has(book.id)) groups.set(book.id, { id: book.id, title: book.title, nodes: [], loaded: book.loaded, total: book.total, loadState: book.loadState }); });
  const known = new Set<string>();
  nodes.forEach((node) => {
    if (known.has(node.id)) return;
    known.add(node.id);
    if (!groups.has(node.bookId)) groups.set(node.bookId, { id: node.bookId, title: node.bookTitle, nodes: [] });
    groups.get(node.bookId)!.nodes.push(node);
  });
  return [...groups.values()].sort((a, b) => compareText(a.id, b.id)).map((book) => ({ ...book,
    nodes: [...book.nodes].sort((a, b) => compareText((a.chapterPathIds || a.chapterPath || []).join('/'), (b.chapterPathIds || b.chapterPath || []).join('/')) || compareText(a.pageLabel, b.pageLabel) || compareText(a.id, b.id)),
  }));
}

const overlaps = (a: Point & { width: number; height: number }, b: Point & { width: number; height: number }, gap = 16) =>
  Math.abs(a.x - b.x) < (a.width + b.width) / 2 + gap && Math.abs(a.y - b.y) < (a.height + b.height) / 2 + gap;

/** Deterministic book-local orbit. Increase the radius until real card rectangles clear each other. */
function localOrbit(count: number) {
  if (!count) return { points: [] as Point[], radius: 119 };
  let distance = 104;
  let points: Point[] = [];
  const offset = count === 1 ? Math.PI / 2 : count === 2 ? -Math.PI / 2 : -Math.PI / 2 + Math.PI / count;
  const safeRadius = Math.max(Math.hypot(BOOK_W / 2, BOOK_H / 2) + Math.hypot(NODE_W / 2, NODE_H / 2) + 24, count > 1 ? (Math.hypot(NODE_W, NODE_H) + 24) / (2 * Math.sin(Math.PI / count)) : 104);
  if (count > 12) distance = safeRadius;
  for (; distance <= safeRadius + 12; distance += 12) {
    points = Array.from({ length: count }, (_, index) => ({ x: Math.cos(offset + index * Math.PI * 2 / count) * distance, y: Math.sin(offset + index * Math.PI * 2 / count) * distance }));
    const cards = points.map((point) => ({ ...point, width: NODE_W, height: NODE_H }));
    const book = { x: 0, y: 0, width: BOOK_W, height: BOOK_H };
    if (cards.every((card, index) => !overlaps(card, book, 20) && cards.every((other, at) => at === index || !overlaps(card, other)))) break;
  }
  const radius = Math.max(119, ...points.map((point) => Math.hypot(Math.abs(point.x) + NODE_W / 2, Math.abs(point.y) + NODE_H / 2))) + 18;
  return { points, radius };
}

function arrangeOrbit(groups: BookGroup[]): DistributionLayout {
  const orbits = groups.map((book) => localOrbit(book.nodes.length));
  const largest = Math.max(137, ...orbits.map((orbit) => orbit.radius));
  const count = groups.length;
  const ring = count <= 1 ? 0 : Math.max(largest + 118, (largest * 2 + 58) / (2 * Math.sin(Math.PI / count)));
  const offset = count === 2 ? 0 : -Math.PI / 2 + (count === 4 ? Math.PI / 4 : 0);
  // Wider scopes use the available desktop width while preserving each book's local module ring.
  const horizontalStretch = count >= 4 ? 1.45 : 1;
  const centers = groups.map((_, index) => ({ x: Math.cos(offset + index * Math.PI * 2 / Math.max(1, count)) * ring * horizontalStretch, y: Math.sin(offset + index * Math.PI * 2 / Math.max(1, count)) * ring }));
  // A single-book scope still has a separate theme and textbook centre.
  if (count === 1) centers[0] = { x: largest + 150, y: 0 };
  const minX = Math.min(-100, ...centers.map((point, index) => point.x - orbits[index].radius)) - 42;
  const maxX = Math.max(100, ...centers.map((point, index) => point.x + orbits[index].radius)) + 42;
  const minY = Math.min(-74, ...centers.map((point, index) => point.y - orbits[index].radius)) - 42;
  const maxY = Math.max(74, ...centers.map((point, index) => point.y + orbits[index].radius)) + 42;
  const shift = (point: Point) => ({ x: point.x - minX, y: point.y - minY });
  const placedBooks: PlacedBook[] = groups.map((group, index) => ({ ...shift(centers[index]), group, radius: orbits[index].radius,
    left: centers[index].x - minX - orbits[index].radius, top: centers[index].y - minY - orbits[index].radius, width: orbits[index].radius * 2, height: orbits[index].radius * 2 }));
  return { width: maxX - minX, height: maxY - minY, center: shift({ x: 0, y: 0 }), books: placedBooks,
    nodes: groups.flatMap((book, index) => book.nodes.map((node, at) => ({ node, ...shift({ x: centers[index].x + orbits[index].points[at].x, y: centers[index].y + orbits[index].points[at].y }), width: NODE_W, height: NODE_H }))),
  };
}

function arrangeHierarchy(groups: BookGroup[]): DistributionLayout {
  const columns = Math.min(3, Math.max(1, groups.length));
  const columnWidth = 334;
  const rowHeights = Array.from({ length: Math.ceil(groups.length / columns) }, (_, row) => Math.max(210, ...groups.slice(row * columns, (row + 1) * columns).map((book) => 160 + book.nodes.length * 118)));
  const topOfRow = (row: number) => 152 + rowHeights.slice(0, row).reduce((sum, height) => sum + height + 34, 0);
  const width = columns * columnWidth + 64;
  const books: PlacedBook[] = groups.map((group, index) => {
    const x = 32 + columnWidth * (index % columns) + columnWidth / 2;
    const top = topOfRow(Math.floor(index / columns));
    return { group, x, y: top + 39, radius: 0, left: x - 150, top, width: 300, height: rowHeights[Math.floor(index / columns)] };
  });
  return { width, height: Math.max(430, 170 + rowHeights.reduce((sum, height) => sum + height + 34, 0)), center: { x: width / 2, y: 62 }, books,
    nodes: books.flatMap((book) => book.group.nodes.map((node, index) => ({ node, x: book.x + 7, y: book.top + 139 + index * 118, width: 242, height: 100 }))),
  };
}

function membershipPath(from: Point, to: Point, hierarchy = false): string {
  if (hierarchy) return 'M ' + from.x + ' ' + from.y + ' C ' + from.x + ' ' + (from.y + 40) + ', ' + to.x + ' ' + (to.y - 40) + ', ' + to.x + ' ' + to.y;
  const middle = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
  return 'M ' + from.x + ' ' + from.y + ' Q ' + middle.x + ' ' + middle.y + ', ' + to.x + ' ' + to.y;
}

const KnowledgeDistributionCanvas: React.FC<KnowledgeDistributionCanvasProps> = ({
  topic, nodes, edges, activeNodeId, activeEdgeId, bookTotals = [], loading = false, initialLayout = 'orbit', view = 'explore', onNodeClick, onEdgeClick, onShowMore,
}) => {
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ pointer: number; start: Point; origin: Transform } | null>(null);
  const [mode, setMode] = useState<LayoutMode>(initialLayout);
  const [size, setSize] = useState({ width: 1000, height: 620 });
  const [transform, setTransform] = useState<Transform>({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState(false);
  const [focusedBook, setFocusedBook] = useState('');
  const [expanded, setExpanded] = useState(false);
  const markerId = 'distribution-arrow-' + useId().replace(/:/g, '');
  const groups = useMemo(() => makeGroups(nodes, bookTotals), [nodes, bookTotals]);
  const layout = useMemo(() => mode === 'orbit' ? arrangeOrbit(groups) : arrangeHierarchy(groups), [mode, groups]);
  const placed = useMemo(() => new Map(layout.nodes.map((node) => [node.node.id, node])), [layout]);
  const narrow = size.width < 620;
  const overview = !narrow && transform.scale < .55;
  // Overview labels use screen pixels; source modules retain their relative positions and sizes.
  const hubScale = overview ? 1 / transform.scale : 1;
  const fingerprint = groups.map((book) => book.id + ':' + book.nodes.map((node) => node.id).join(',')).join('|');
  const validEdges = edges.filter((edge) => placed.has(edge.source) && placed.has(edge.target) && edge.source !== edge.target);
  const relationDrawings = useMemo(() => {
    const labels: Point[] = [];
    return validEdges.map((edge, index) => {
      const a = placed.get(edge.source)!, b = placed.get(edge.target)!;
      const offset = (index % 5 - 2) * 30;
      const control = { x: layout.center.x + offset, y: layout.center.y + offset - 36 };
      const label = { x: a.x * .25 + control.x * .5 + b.x * .25, y: a.y * .25 + control.y * .5 + b.y * .25 };
      const anchor = { ...label };
      const obstacles = [...layout.nodes, ...layout.books.map((book) => ({ x: book.x, y: book.y, width: BOOK_W, height: BOOK_H })), { ...layout.center, width: 190, height: 92 }];
      for (let tries = 0; tries < 80 && (labels.some((other) => Math.abs(other.x - label.x) < 145 && Math.abs(other.y - label.y) < 44) || obstacles.some((node) => Math.abs(node.x - label.x) < node.width / 2 + 72 && Math.abs(node.y - label.y) < node.height / 2 + 22)); tries++) label.y += 42;
      labels.push(label);
      return { edge, label, anchor, path: 'M ' + a.x + ' ' + a.y + ' Q ' + control.x + ' ' + control.y + ', ' + b.x + ' ' + b.y };
    });
  }, [validEdges, placed, layout]);

  useLayoutEffect(() => {
    const element = viewport.current; if (!element) return;
    const measure = () => setSize({ width: element.clientWidth || 1000, height: element.clientHeight || 620 });
    measure(); const observer = new ResizeObserver(measure); observer.observe(element); return () => observer.disconnect();
  }, []);

  const fit = () => {
    const scale = clampScale(Math.min(1, (size.width - 64) / layout.width, mode === 'hierarchy' ? 1 : (size.height - (groups.length > 3 ? 104 : 40)) / layout.height));
    setTransform({ scale, x: (size.width - layout.width * scale) / 2, y: mode === 'hierarchy' ? 16 : (size.height - layout.height * scale) / 2 }); setFocusedBook('');
  };
  const zoom = (next: number) => setTransform((current) => {
    const scale = clampScale(next);
    return { scale, x: size.width / 2 - (size.width / 2 - current.x) / current.scale * scale, y: size.height / 2 - (size.height / 2 - current.y) / current.scale * scale };
  });
  const reveal = (point: Point, minimum = .9) => setTransform((current) => {
    const scale = Math.max(current.scale, minimum);
    return { scale, x: size.width / 2 - point.x * scale, y: size.height / 2 - point.y * scale };
  });
  const revealActive = () => {
    const edge = validEdges.find((item) => item.id === activeEdgeId);
    if (edge) {
      const a = placed.get(edge.source)!, b = placed.get(edge.target)!;
      const scale = clampScale(Math.min(1, (size.width - 90) / (Math.abs(a.x - b.x) + 280), (size.height - 60) / (Math.abs(a.y - b.y) + 160)));
      setTransform({ scale, x: size.width / 2 - (a.x + b.x) / 2 * scale, y: size.height / 2 - (a.y + b.y) / 2 * scale });
    } else { const node = placed.get(activeNodeId || ''); if (node) reveal(node); }
  };
  useEffect(() => { fit(); }, [mode, fingerprint, size.width, size.height]); // Geometry changes reset the overview; selecting a node does not.
  useEffect(() => {
    const element = viewport.current; if (!element) return;
    const wheel = (event: WheelEvent) => {
      if (narrow || (!event.ctrlKey && !event.metaKey)) return;
      event.preventDefault();
      setTransform((current) => {
        const scale = clampScale(current.scale * Math.exp(-event.deltaY * .006));
        const rect = element.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
        return { scale, x: x - (x - current.x) / current.scale * scale, y: y - (y - current.y) / current.scale * scale };
      });
    };
    element.addEventListener('wheel', wheel, { passive: false }); return () => element.removeEventListener('wheel', wheel);
  }, [narrow]);
  useEffect(() => {
    if (!expanded) return;
    const frame = requestAnimationFrame(() => viewport.current?.focus({ preventScroll: true }));
    const escape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || (event.target as Element)?.closest?.('[role="dialog"]')) return;
      // AntD portals may own Escape while focus remains on the underlying canvas.
      const dialogOpen = [...document.querySelectorAll('.ant-drawer-open, .ant-modal, [role="dialog"]')]
        .some((element) => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden');
      if (!dialogOpen) setExpanded(false);
    };
    window.addEventListener('keydown', escape);
    return () => { cancelAnimationFrame(frame); window.removeEventListener('keydown', escape); };
  }, [expanded]);

  const emptyLabel = (book: BookGroup) => view === 'lesson' ? '本课未选入' : book.loadState === 'not_loaded' ? '待检索' : book.loaded && book.loaded > 0 ? '暂无可见模块' : '本次未召回';
  const emptyDescription = (book: BookGroup) => view === 'lesson' ? '本课未选入材料，可切换检索候选查看教材原文。' : book.loadState === 'not_loaded' ? '待检索，完成检索后显示相关来源模块。' : book.loaded && book.loaded > 0 ? '已有匹配原文，当前范围尚无可见模块。' : '本次未召回原文，不代表没有相关知识。';
  const bookCaption = (book: BookGroup) => (book.loadState === 'not_loaded' ? '待检索 · ' : typeof book.loaded === 'number' ? '已载 ' + book.loaded + '/' + (typeof book.total === 'number' ? book.total : '未知') + ' 段匹配原文 · ' : '') + book.nodes.length + ' 个可见模块';
  const chooseNode = (node: PlacedNode) => { reveal(node); onNodeClick(node.node.id); };
  const chooseBook = (book: PlacedBook) => {
    const scale = clampScale(mode === 'orbit' ? Math.min(1.15, (size.width - 60) / book.width, (size.height - 45) / book.height) : 1);
    setTransform({ scale, x: size.width / 2 - book.x * scale, y: mode === 'orbit' ? size.height / 2 - book.y * scale : 25 - book.top * scale }); setFocusedBook(book.group.id);
  };
  const nodeButton = (item: PlacedNode, list = false) => <button key={item.node.id} type="button"
    className={'kd-module' + (item.node.selected ? ' is-selected' : '') + (activeNodeId === item.node.id ? ' is-active' : '') + (list ? ' kd-list-module' : '')}
    style={list ? { '--kd-book-color': textbookColor(item.node.bookId) } as React.CSSProperties : { left: item.x - item.width / 2, top: item.y - item.height / 2, width: item.width, height: item.height, '--kd-book-color': textbookColor(item.node.bookId) } as React.CSSProperties}
    title={item.node.title + ' · ' + item.node.bookTitle + ' · ' + item.node.pageLabel + (item.node.chapterPath?.length ? '\n来源路径：' + item.node.chapterPath.join(' / ') : '')}
    aria-label={item.node.title + '，《' + item.node.bookTitle + '》，' + item.node.pageLabel + '，' + (item.node.selected ? '本课材料' : item.node.retrieved === false ? '探索来源' : '检索来源模块') + '，点击核对原文'}
    aria-pressed={activeNodeId === item.node.id} onClick={() => list ? onNodeClick(item.node.id) : chooseNode(item)}>
    <span className="kd-module-type">{originLabels[item.node.kind]}{item.node.selected ? <i>✓ 本课</i> : item.node.retrieved === false ? <i>探索来源</i> : null}</span><strong>{item.node.title || '未命名来源模块'}</strong>
    {!list && mode === 'hierarchy' && !!item.node.chapterPath?.length && <span className="kd-module-directory" title={item.node.chapterPath.join(' / ')}>来源路径：{item.node.chapterPath.join(' / ')}</span>}
    <span className="kd-module-location">{item.node.pageLabel || '位置待核对'}<small>{item.node.evidenceCount} 段</small></span>
    {list && !!item.node.chapterPath?.length && <span className="kd-list-path">{item.node.chapterPath.join(' / ')}</span>}
  </button>;

  return <section className={'knowledge-distribution kd-layout-' + mode + (expanded ? ' kd-expanded' : '')} aria-label="多教材来源模块分布图" aria-busy={loading}>
    <header className="kd-heading"><div><span className="kd-eyebrow">教材 · 来源模块分布</span><h2>{topic || '本课知识空间'}</h2><p>{groups.length} 本教材 · {layout.nodes.length} 个当前可见模块 · {validEdges.length} 条本课关系</p></div>
      <div className="kd-controls">{!narrow && <><div className="kd-layout-switch" aria-label="分布布局"><button type="button" aria-pressed={mode === 'orbit'} onClick={() => setMode('orbit')}>环绕</button><button type="button" aria-pressed={mode === 'hierarchy'} onClick={() => setMode('hierarchy')}>来源路径</button></div><div className="kd-zoom"><button type="button" aria-label="缩小分布图" disabled={transform.scale <= MIN_SCALE} onClick={() => zoom(transform.scale / 1.2)}>−</button><output>{Math.round(transform.scale * 100)}%</output><button type="button" aria-label="放大分布图" disabled={transform.scale >= MAX_SCALE} onClick={() => zoom(transform.scale * 1.2)}>＋</button></div><button type="button" className="kd-tool" disabled={!activeNodeId && !activeEdgeId} onClick={revealActive}>定位选中</button><button type="button" className="kd-tool" onClick={fit}>适配全图</button></>}{narrow && <span className="kd-mobile-label">按教材分组查看</span>}{onShowMore && <button type="button" className="kd-tool" disabled={loading} title="展开更多匹配原文及其来源模块" onClick={onShowMore}>{loading ? '正在展开…' : '展开更多'}</button>}<button type="button" className="kd-tool kd-expand-tool" aria-pressed={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '退出专注' : '专注分布'}</button></div>
    </header>
    <div className="kd-legend"><span><i className="kd-key-ownership" />检索范围 / 来源归属</span><span><i className="kd-key-confirmed" />教师已确认关系</span><span><i className="kd-key-draft" />关系草稿</span><small>归属线不代表知识语义关系；箭头仅用于有方向的教师关系。</small></div>
    {!narrow && groups.length > 3 && <nav className="kd-book-index" aria-label="定位教材分布">{layout.books.map((book) => <button type="button" key={book.group.id} aria-pressed={focusedBook === book.group.id} onClick={() => chooseBook(book)} style={{ '--kd-book-color': textbookColor(book.group.id) } as React.CSSProperties}><i /><span>{book.group.title}</span><small>{book.group.nodes.length} 模块</small></button>)}</nav>}
    {loading && <div className="kd-loading" role="status"><i />正在整理已加载的教材来源…</div>}
    <div className={'kd-viewport' + (narrow ? ' kd-compact' : '') + (dragging ? ' is-dragging' : '')} ref={viewport} tabIndex={narrow ? undefined : 0} aria-label={narrow ? '教材模块列表' : '模块分布画布；拖动平移，Ctrl加滚轮缩放，方向键平移'}
      onPointerDown={(event) => { if (narrow || event.button !== 0 || (event.target as Element).closest('button, .kd-semantic-hit')) return; drag.current = { pointer: event.pointerId, start: { x: event.clientX, y: event.clientY }, origin: transform }; event.currentTarget.setPointerCapture(event.pointerId); setDragging(true); }}
      onPointerMove={(event) => { if (!drag.current) return; const current = drag.current; setTransform({ ...current.origin, x: current.origin.x + event.clientX - current.start.x, y: current.origin.y + event.clientY - current.start.y }); }}
      onPointerUp={(event) => { if (drag.current?.pointer !== event.pointerId) return; drag.current = null; setDragging(false); if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
      onPointerCancel={() => { drag.current = null; setDragging(false); }}
      onKeyDown={(event) => { if (event.target !== event.currentTarget || narrow) return; const deltas: Record<string, Point> = { ArrowLeft: { x: 50, y: 0 }, ArrowRight: { x: -50, y: 0 }, ArrowUp: { x: 0, y: 50 }, ArrowDown: { x: 0, y: -50 } }; if (deltas[event.key]) { event.preventDefault(); const delta = deltas[event.key]; setTransform((current) => ({ ...current, x: current.x + delta.x, y: current.y + delta.y })); } if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(transform.scale * 1.2); } if (event.key === '-') { event.preventDefault(); zoom(transform.scale / 1.2); } }}>
      {!groups.length ? <div className="kd-empty"><span aria-hidden="true">◎</span><h3>{loading ? '正在准备模块分布' : '先选一个课题与教材范围'}</h3><p>检索到的原文会按教材与来源模块组织在这里，点击模块即可核对证据。</p></div> : narrow ? <div className="kd-book-list">{layout.books.map((book) => <section key={book.group.id} style={{ '--kd-book-color': textbookColor(book.group.id) } as React.CSSProperties}><header><h3>{book.group.title}</h3><span>{bookCaption(book.group)}</span></header>{book.group.nodes.length ? layout.nodes.filter((node) => node.node.bookId === book.group.id).map((item) => nodeButton(item, true)) : <p className="kd-no-match">{emptyDescription(book.group)}</p>}</section>)}</div> : <div className={'kd-stage' + (overview ? ' kd-overview' : '')} style={{ width: layout.width, height: layout.height, transform: 'translate(' + transform.x + 'px,' + transform.y + 'px) scale(' + transform.scale + ')' }}>
        <svg className="kd-svg" width={layout.width} height={layout.height} aria-hidden="true"><defs><marker id={markerId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 Z" fill="context-stroke" /></marker></defs>
          {mode === 'orbit' && layout.books.length > 1 && <ellipse className="kd-theme-orbit" cx={layout.center.x} cy={layout.center.y} rx={Math.max(...layout.books.map((book) => Math.abs(book.x - layout.center.x)))} ry={Math.max(...layout.books.map((book) => Math.abs(book.y - layout.center.y)))} />}
          {layout.books.map((book) => <g key={book.group.id} style={{ '--kd-book-color': textbookColor(book.group.id) } as React.CSSProperties}>{mode === 'orbit' ? <><circle className="kd-book-halo" cx={book.x} cy={book.y} r={book.radius} /><circle className="kd-book-inner-ring" cx={book.x} cy={book.y} r={Math.max(85, book.radius - 42)} /></> : <rect className="kd-book-halo" x={book.left} y={book.top} width={book.width} height={book.height} rx="18" />}<path className="kd-membership kd-scope-line" d={membershipPath(layout.center, book, mode === 'hierarchy')} />{layout.nodes.filter((node) => node.node.bookId === book.group.id).map((node) => <path key={node.node.id} className="kd-membership" d={membershipPath(book, node, mode === 'hierarchy')} />)}</g>)}
          {relationDrawings.map(({ edge, path, anchor, label }) => <g key={edge.id}><path className="kd-semantic-hit" d={path} onClick={() => onEdgeClick(edge.id)} /><path className={'kd-semantic-line ' + edge.status + (activeEdgeId === edge.id ? ' is-active' : '')} d={path} markerEnd={edge.directed ? 'url(#' + markerId + ')' : undefined} />{anchor.y !== label.y && <path className="kd-relation-guide" d={'M ' + anchor.x + ' ' + anchor.y + ' L ' + label.x + ' ' + label.y} />}</g>)}
        </svg>
        <button type="button" className="kd-topic" style={{ left: layout.center.x, top: layout.center.y, transform: 'translate(-50%, -50%) scale(' + hubScale + ')' }} onClick={fit} title={(topic || '本课知识空间') + ' · 点击回到完整教材分布'}><span>{view === 'lesson' ? '本课材料主题' : '检索主题'}</span><strong>{topic || '本课知识空间'}</strong><small>{groups.length} 本教材 · {layout.nodes.length} 个模块</small></button>
        {layout.books.map((book) => <button type="button" key={book.group.id} className={'kd-book' + (focusedBook === book.group.id ? ' is-focused' : '') + (!book.group.nodes.length ? ' is-empty' : '')} style={{ left: book.x, top: overview && mode === 'orbit' ? book.top - 25 / transform.scale : book.y, width: overview ? 122 : BOOK_W, transform: 'translate(-50%, -50%) scale(' + hubScale + ')', '--kd-book-color': textbookColor(book.group.id) } as React.CSSProperties} title={book.group.title + ' · ' + bookCaption(book.group)} aria-label={book.group.title + '，' + bookCaption(book.group) + (!book.group.nodes.length ? '，' + emptyDescription(book.group) : '') + '。点击放大本教材分布'} onClick={() => chooseBook(book)}><strong>{book.group.title}</strong><small className="kd-book-caption">{bookCaption(book.group)}</small><small className="kd-book-overview">{book.group.nodes.length ? book.group.nodes.length + ' 个来源模块' : emptyLabel(book.group)}</small>{!book.group.nodes.length && <em>{emptyLabel(book.group)}</em>}</button>)}
        {layout.nodes.map((item) => nodeButton(item))}
        {relationDrawings.map(({ edge, label }) => <button type="button" key={edge.id} className={'kd-relation-label ' + edge.status + (activeEdgeId === edge.id ? ' is-active' : '')} style={{ left: label.x - 66, top: label.y - 19 }} aria-pressed={activeEdgeId === edge.id} title={edge.reason || '关系理由待核对'} aria-label={(placed.get(edge.source)?.node.title || '') + '与' + (placed.get(edge.target)?.node.title || '') + '：' + edge.label + '，' + (edge.status === 'confirmed' ? '教师已确认' : '关系草稿') + '。点击核对双侧证据'} onClick={() => onEdgeClick(edge.id)}><strong>{edge.label}</strong><small>{edge.status === 'confirmed' ? '教师已确认' : '关系草稿'}</small></button>)}
      </div>}
    </div>
    {narrow && !!validEdges.length && <details className="kd-mobile-relations"><summary>本课教学关系 · {validEdges.length} 条</summary>{validEdges.map((edge: RelationCanvasEdge) => <button type="button" key={edge.id} onClick={() => onEdgeClick(edge.id)}>{placed.get(edge.source)?.node.title} / {placed.get(edge.target)?.node.title}<strong>{edge.label} · {edge.status === 'confirmed' ? '教师已确认' : '草稿'}</strong></button>)}</details>}
    <footer className="kd-footer"><p>{narrow ? '窄屏按教材列出全部已加载模块。' : mode === 'hierarchy' ? '按教材列出模块及其来源路径，不代表完整教材目录。' : '点击教材簇放大，点击模块核对原文；拖动平移，Ctrl + 滚轮缩放。'} 分布仅反映当前可见来源，不能据此判断整本教材的知识覆盖。{expanded ? ' Esc 退出专注。' : ''}</p>{!narrow && transform.scale < .55 && <span>全局概览 · 放大教材簇可阅读模块</span>}</footer>
  </section>;
};
export default KnowledgeDistributionCanvas;
