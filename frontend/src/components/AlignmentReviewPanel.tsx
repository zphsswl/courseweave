import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import type Cytoscape from 'cytoscape';
import { Button, Checkbox, Empty, Input, Popover, Spin, Tag, message } from 'antd';
import {
  AimOutlined,
  ApartmentOutlined,
  BookOutlined,
  CheckCircleFilled,
  ExpandOutlined,
  ReloadOutlined,
  ScanOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { GraphData, GraphNode, Textbook } from '../types';
import * as api from '../api/client';

interface GraphGroup {
  id: string;
  title: string;
  color: string;
  node_count: number;
  linked_node_count?: number;
}

interface AlignmentGraphData extends GraphData {
  groups?: GraphGroup[];
  total_edges?: number;
  total_available_edges?: number;
  truncated?: boolean;
}

interface Props {
  courseId: string;
  textbooks: Textbook[];
  onGenerate?: (textbookIds: string[]) => Promise<void> | void;
  onGoLibrary?: () => void;
  generating?: boolean;
  refreshToken?: number;
  readOnly?: boolean;
}

const RELATION_LABELS: Record<string, string> = {
  equivalent_to: '同一概念', related_to: '主题相关', prerequisite: '前置知识',
  contrasts_with: '对照理解', broader_than: '上位概念', narrower_than: '下位概念',
  extends: '内容扩展', conflicts_with: '观点冲突',
};

const cleanText = (value: string = '') => value
  .replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')
  .replace(/(?:\.\s*){4,}/g, ' ')
  .replace(/…{2,}/g, ' ')
  .replace(/\s+/g, ' ')
  .trim();

const concise = (value: string = '', max = 180) => {
  const valueText = cleanText(value);
  return valueText.length > max ? `${valueText.slice(0, max).replace(/[，、；:]?$/u, '')}…` : valueText;
};

const usefulDefinition = (node?: GraphNode | null) => {
  if (!node) return '';
  const definition = concise(node.definition, 220);
  const label = cleanText(node.label);
  if (definition && definition !== label && !/(?:\.\s*){4,}|…{2,}/u.test(node.definition || '')) return definition;
  return concise(node.source_paragraph, 220);
};

const AlignmentReviewPanel: React.FC<Props> = ({
  courseId, textbooks, onGenerate, onGoLibrary, generating = false, refreshToken = 0, readOnly = false,
}) => {
  const cyRef = useRef<Cytoscape.Core | null>(null);
  const [selectedBookIds, setSelectedBookIds] = useState<string[]>([]);
  const [graph, setGraph] = useState<AlignmentGraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [focusNodeId, setFocusNodeId] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [themeQuery, setThemeQuery] = useState('');

  const readyBooks = useMemo(
    () => textbooks.filter((book) => ['completed', 'review'].includes(book.graph_status)),
    [textbooks],
  );
  const readyBookKey = readyBooks.map((book) => book.id).sort().join('|');
  const selectedBookKey = [...selectedBookIds].sort().join('|');
  const canGenerate = selectedBookIds.length >= 2;

  useEffect(() => {
    setSelectedBookIds(readyBooks.map((book) => book.id));
    setFocusNodeId('');
    setSelectedNodeId('');
  }, [courseId, readyBookKey]);

  const loadGraph = useCallback(async () => {
    if (selectedBookIds.length < 2) {
      setGraph(null);
      return;
    }
    setLoading(true);
    try {
      const response = await api.getAlignmentGraph(courseId, selectedBookIds);
      setGraph(response.data);
    } catch {
      setGraph(null);
      message.error('关联图加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [courseId, selectedBookKey]);

  useEffect(() => { loadGraph(); }, [loadGraph, refreshToken]);

  const groups: GraphGroup[] = graph?.groups || selectedBookIds.map((bookId, index) => {
    const book = readyBooks.find((item) => item.id === bookId);
    return {
      id: bookId, title: book?.title || '教材', color: ['#0D6657', '#C8733A', '#4E6E92'][index % 3],
      node_count: 0, linked_node_count: 0,
    };
  });

  const nodeMap = useMemo(() => new Map((graph?.nodes || []).map((node) => [node.id, node])), [graph]);
  const degreeMap = useMemo(() => {
    const degree = new Map<string, number>();
    (graph?.edges || []).forEach((edge) => {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
    });
    return degree;
  }, [graph]);

  const themes = useMemo(() => (graph?.nodes || [])
    .filter((node) => cleanText(node.label).length >= 2 && cleanText(node.label).length <= 28)
    // When the same theme occurs in multiple books, use the occurrence with
    // verified original evidence as the lens center. Degree alone could pick a
    // legacy synthetic summary and make the first dossier look untrustworthy.
    .sort((a, b) => (
      Number(b.evidence_status === 'verified') - Number(a.evidence_status === 'verified')
      || (degreeMap.get(b.id) || 0) - (degreeMap.get(a.id) || 0)
      || b.importance - a.importance
    ))
    .filter((node, index, all) => all.findIndex((item) => cleanText(item.label) === cleanText(node.label)) === index), [degreeMap, graph]);

  const filteredThemes = useMemo(() => {
    const query = cleanText(themeQuery).toLocaleLowerCase();
    return query ? themes.filter((node) => cleanText(node.label).toLocaleLowerCase().includes(query)) : themes;
  }, [themeQuery, themes]);

  useEffect(() => {
    if (!focusNodeId || !nodeMap.has(focusNodeId)) {
      const first = themes[0]?.id || '';
      setFocusNodeId(first);
      setSelectedNodeId(first);
    }
  }, [focusNodeId, nodeMap, themes]);

  const focusNode = nodeMap.get(focusNodeId) || null;
  const selectedNode = nodeMap.get(selectedNodeId) || focusNode;

  const localGraph = useMemo(() => {
    if (!graph || !focusNodeId) return { nodes: [], edges: [] };
    const connected = graph.edges
      .filter((edge) => edge.source === focusNodeId || edge.target === focusNodeId)
      .sort((a, b) => b.confidence - a.confidence)
      .slice(0, 16);
    const ids = new Set([focusNodeId]);
    connected.forEach((edge) => { ids.add(edge.source); ids.add(edge.target); });
    return { nodes: graph.nodes.filter((node) => ids.has(node.id)), edges: connected };
  }, [focusNodeId, graph]);

  const activeRelation = useMemo(() => {
    if (!focusNodeId || !selectedNodeId || focusNodeId === selectedNodeId) return null;
    return localGraph.edges.find((edge) => (
      (edge.source === focusNodeId && edge.target === selectedNodeId)
      || (edge.target === focusNodeId && edge.source === selectedNodeId)
    )) || null;
  }, [focusNodeId, localGraph.edges, selectedNodeId]);

  const evidenceSides = useMemo(() => {
    if (!activeRelation) return [];
    return [activeRelation.source_evidence, activeRelation.target_evidence].filter(Boolean);
  }, [activeRelation]);

  const elements = useMemo(() => {
    const nodes = localGraph.nodes.map((node) => ({
      data: {
        ...node,
        label: concise(node.label, 18),
        isFocus: node.id === focusNodeId ? 1 : 0,
        nodeColor: groups.find((group) => group.id === node.textbook_id)?.color || '#0D6657',
        nodeSize: node.id === focusNodeId ? 68 : 44 + Math.min((degreeMap.get(node.id) || 0) * 3, 14),
      },
    }));
    const edges = localGraph.edges.map((edge) => ({
      data: {
        ...edge,
        label: RELATION_LABELS[edge.relation_type] || '相关',
        edgeColor: edge.review_status === 'suggested' ? '#A8B3AE' : '#0D6657',
        edgeStyle: edge.review_status === 'suggested' ? 'dashed' : 'solid',
      },
    }));
    return [...nodes, ...edges];
  }, [degreeMap, focusNodeId, groups, localGraph]);

  const stylesheet = useMemo(() => ([
    { selector: 'node', style: {
      'background-color': 'data(nodeColor)', width: 'data(nodeSize)', height: 'data(nodeSize)',
      label: 'data(label)', color: '#17322B', 'font-family': '"Noto Serif SC", serif',
      'font-size': 11, 'font-weight': 700, 'text-wrap': 'wrap', 'text-max-width': 100,
      'text-valign': 'bottom', 'text-margin-y': 13, 'border-width': 4, 'border-color': '#F7F4EC',
      'overlay-opacity': 0, 'transition-property': 'width height border-width', 'transition-duration': '180ms',
    } },
    { selector: 'node[isFocus = 1]', style: {
      'background-color': '#D98745', 'border-color': '#F3D7B6', 'border-width': 7,
      'font-size': 13, 'text-margin-y': 16,
    } },
    { selector: 'node:selected', style: { 'border-color': '#102F27', 'border-width': 6 } },
    { selector: 'edge', style: {
      width: 1.5, 'line-color': 'data(edgeColor)', 'target-arrow-color': 'data(edgeColor)',
      'target-arrow-shape': 'triangle', 'curve-style': 'unbundled-bezier', 'control-point-distances': 28,
      'line-style': 'data(edgeStyle)', label: 'data(label)', color: '#65756F', 'font-size': 9,
      'text-background-color': '#FBFAF5', 'text-background-opacity': .94, 'text-background-padding': 3,
      'arrow-scale': .65, 'overlay-opacity': 0,
    } },
  ]), []);

  const bindCy = useCallback((cy: Cytoscape.Core) => {
    cyRef.current = cy;
    cy.off('tap', 'node');
    cy.on('tap', 'node', (event) => setSelectedNodeId(event.target.id()));
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !elements.length) return;
    window.setTimeout(() => {
      cy.layout({
        name: 'concentric', animate: true, animationDuration: 360, minNodeSpacing: 62,
        concentric: (node: Cytoscape.NodeSingular) => node.id() === focusNodeId ? 10 : 1,
        levelWidth: () => 1, startAngle: -Math.PI / 2,
      } as any).run();
      cy.fit(undefined, 74);
    }, 20);
  }, [elements, focusNodeId]);

  const toggleBook = (bookId: string) => setSelectedBookIds((current) => (
    current.includes(bookId) ? current.filter((id) => id !== bookId) : [...current, bookId]
  ));
  const chooseTheme = (nodeId: string) => { setFocusNodeId(nodeId); setSelectedNodeId(nodeId); };
  const generate = () => {
    if (!canGenerate) return message.warning('请至少选择两本已生成知识树的教材');
    onGenerate?.(selectedBookIds);
  };

  const bookPicker = (
    <div className="connection-book-picker">
      <div className="connection-picker-head"><div><strong>本次关联教材</strong><small>每本教材作为一个知识来源</small></div><button onClick={() => setSelectedBookIds(readyBooks.map((book) => book.id))}>全选</button></div>
      <div className="connection-picker-list">{readyBooks.map((book) => (
        <label key={book.id} className="connection-picker-item"><Checkbox checked={selectedBookIds.includes(book.id)} disabled={generating} onChange={() => toggleBook(book.id)} /><span><strong>{book.title}</strong><small>知识树已就绪</small></span></label>
      ))}</div>
      <div className="connection-picker-foot"><span>当前范围</span><strong>{selectedBookIds.length} 本教材</strong></div>
    </div>
  );

  const totalAvailable = groups.reduce((count, group) => count + group.node_count, 0);

  return (
    <div className="evidence-network">
      <header className="evidence-network-head">
        <div className="evidence-title"><span><ApartmentOutlined /></span><div><small>CONCEPT ATLAS</small><h2>跨教材主题网络</h2><p>先选择一个主题，再查看它在不同教材中的解释、延伸与证据。</p></div></div>
        <div className="evidence-actions">
          <Popover content={bookPicker} trigger="click" placement="bottomRight"><Button icon={<BookOutlined />} disabled={generating}>选择教材 · {selectedBookIds.length}</Button></Popover>
          {!readOnly && <Button type="primary" icon={<ScanOutlined />} loading={generating} disabled={!canGenerate} onClick={generate}>{graph?.edges.length ? '重新分析' : '生成关联'}</Button>}
        </div>
      </header>

      {readyBooks.length < 2 ? (
        <div className="connection-graph-empty"><BookOutlined /><h3>还需要一本已完成知识树的教材</h3><p>至少两本教材才能建立跨教材连接。</p><Button type="primary" onClick={onGoLibrary}>返回教材</Button></div>
      ) : !canGenerate ? (
        <div className="connection-graph-empty"><BookOutlined /><h3>请选择至少两本教材</h3><p>选择本次希望交叉查看的教材范围。</p></div>
      ) : loading ? (
        <div className="network-loading"><Spin /><span>正在读取教材连接…</span></div>
      ) : !graph?.edges.length ? (
        <div className="connection-graph-empty"><ApartmentOutlined /><h3>还没有可信的跨教材连接</h3><p>已找到 {totalAvailable} 个可用节点。{readOnly ? '在线示例不会修改关联数据。' : '点击生成后，系统只保留有双侧证据的关系。'}</p>{!readOnly && <Button type="primary" icon={<ScanOutlined />} onClick={generate}>生成关联</Button>}</div>
      ) : (
        <>
          <div className="network-coverage-note">
            <CheckCircleFilled />
            <span>
              <strong>{groups.length} 本教材 · {groups.reduce((sum, group) => sum + group.node_count, 0)} 个具体知识点</strong>
              已排除前言、绪论、目录和无可靠原文的节点；{graph.truncated ? `当前先展示最可信的 ${graph.total_edges || 0} 条连接` : `已加载全部 ${graph.total_available_edges ?? graph.total_edges ?? 0} 条连接`}。
            </span>
          </div>
          <section className="theme-lens">
            <div className="theme-lens-copy"><AimOutlined /><span><strong>主题镜头</strong><small>切换后只展示该主题的一层直接连接</small></span></div>
            <div className="theme-chips">{filteredThemes.slice(0, 10).map((node) => <button key={node.id} className={node.id === focusNodeId ? 'active' : ''} onClick={() => chooseTheme(node.id)}>{cleanText(node.label)}</button>)}</div>
            <Input allowClear prefix={<SearchOutlined />} value={themeQuery} onChange={(event) => setThemeQuery(event.target.value)} placeholder="查找主题" />
          </section>

          <div className="network-workbench">
            <section className="network-stage">
              <div className="network-stage-meta"><span><i />{focusNode ? cleanText(focusNode.label) : '当前主题'}</span><small>{localGraph.nodes.length} 个节点 · {localGraph.edges.length} 条直接连接</small></div>
              <CytoscapeComponent elements={elements} stylesheet={stylesheet as any} layout={{ name: 'preset' }} cy={bindCy} className="topic-cytoscape" minZoom={.45} maxZoom={1.8} />
              <div className="network-controls"><button onClick={() => cyRef.current?.fit(undefined, 74)}><ExpandOutlined /></button><button onClick={loadGraph}><ReloadOutlined /></button></div>
              <div className="network-source-legend">{groups.map((group) => <span key={group.id}><i style={{ background: group.color }} />{group.title}<small>{group.linked_node_count || 0}</small></span>)}</div>
            </section>

            <aside className="evidence-dossier">
              {selectedNode ? <>
                <div className="dossier-kicker"><span>{activeRelation ? 'RELATION EVIDENCE' : 'KNOWLEDGE EVIDENCE'}</span>{selectedNode.evidence_status === 'verified' && <Tag icon={<CheckCircleFilled />} color="success">原文可追溯</Tag>}</div>
                <h3>{cleanText(selectedNode.label)}</h3>
                <p className="dossier-location">{cleanText(selectedNode.textbook)} · {cleanText(selectedNode.chapter)} · P.{selectedNode.page_start || selectedNode.page || '—'}</p>
                <section><small>概念说明</small><p>{usefulDefinition(selectedNode) || '当前记录没有足够清晰的定义，建议重新生成知识树。'}</p></section>
                {activeRelation && focusNode && <section className="relation-rationale"><small>为什么连接</small><strong>{RELATION_LABELS[activeRelation.relation_type] || '主题相关'} · {Math.round(activeRelation.confidence * 100)}%</strong><p>{concise(activeRelation.why || activeRelation.description, 240) || `两本教材都讨论了“${cleanText(focusNode.label)}”相关内容。`}</p></section>}
                {activeRelation ? (
                  <section className="relation-evidence-pair">
                    <small>双侧教材证据</small>
                    <div className="relation-evidence-grid">
                      {evidenceSides.map((evidence: any, index) => (
                        <article key={`${evidence.node_id}-${index}`}>
                          <div><span>{index === 0 ? 'A' : 'B'}</span><strong>{cleanText(evidence.textbook)}</strong>{evidence.verified && <CheckCircleFilled />}</div>
                          <p>{cleanText(evidence.chapter)} · P.{evidence.page_start === evidence.page_end ? evidence.page_start : `${evidence.page_start}–${evidence.page_end}`}</p>
                          <blockquote>{concise(evidence.quote, 300) || '暂无可展示的原文证据'}</blockquote>
                        </article>
                      ))}
                    </div>
                  </section>
                ) : (
                  <section className="dossier-source"><small>当前教材原文</small><blockquote>{concise(selectedNode.source_paragraph, 360) || '暂无可展示的原文证据'}</blockquote></section>
                )}
              </> : <Empty description="点击一个节点查看概念与教材证据" />}
            </aside>
          </div>
        </>
      )}

      {generating && <div className="connection-generating-overlay"><Spin /><div><strong>正在核对跨教材关系</strong><span>系统会过滤无定义、无原文或名称不完整的节点</span></div></div>}
    </div>
  );
};

export default AlignmentReviewPanel;
