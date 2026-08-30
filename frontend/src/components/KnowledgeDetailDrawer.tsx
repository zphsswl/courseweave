import React, { useMemo } from 'react';
import { Drawer, Empty, Tag } from 'antd';
import { BookOutlined, CheckCircleFilled, CloseOutlined, LinkOutlined, ReadOutlined, RightOutlined, WarningOutlined } from '@ant-design/icons';
import type { GraphData, GraphEdge, GraphNode } from '../types';

interface Props {
  node: GraphNode | null;
  graphData: GraphData | null;
  onClose: () => void;
  onSelectRelated: (node: GraphNode) => void;
}

const safeText = (value: string = '') => value
  .replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')
  .replace(/\uFFFD+/g, ' ')
  .replace(/\s+/g, ' ')
  .trim();

const hasBrokenEncoding = (value: string = '') => /\uFFFD{2,}|[\u0000-\u0008\u000b\u000c\u000e-\u001f]/u.test(value);

const cleanKnowledgeName = (value: string = '') => safeText(value)
  .replace(/^第[一二三四五六七八九十百千\d]+章\s*/u, '')
  .replace(/^(?:第[一二三四五六七八九十\d]+节|[一二三四五六七八九十]+[、.)．]|\d+[、.)．])\s*/u, '')
  .replace(/(?:\.\s*){4,}.*$/u, '')
  .trim();

const concise = (value: string = '', max = 520) => {
  const text = safeText(value).replace(/(?:\.\s*){4,}/g, ' ');
  return text.length > max ? `${text.slice(0, max).replace(/[，、；:]?$/u, '')}…` : text;
};

const RELATION_LABELS: Record<string, string> = {
  contains: '包含', part_of: '属于', prerequisite: '前置知识', causes: '导致',
  equivalent_to: '同一概念', related_to: '相关主题', contrasts_with: '对照理解',
  applies_to: '应用于', supports: '支持', example_of: '例证',
};

const KnowledgeDetailDrawer: React.FC<Props> = ({ node, graphData, onClose, onSelectRelated }) => {
  const related = useMemo(() => {
    if (!node || !graphData) return [];
    const nodeMap = new Map(graphData.nodes.map((item) => [item.id, item]));
    return graphData.edges
      .filter((edge) => edge.source === node.id || edge.target === node.id)
      .sort((a, b) => Number(a.relation_type === 'contains') - Number(b.relation_type === 'contains') || b.confidence - a.confidence)
      .map((edge) => {
        const relatedId = edge.source === node.id ? edge.target : edge.source;
        const relatedNode = nodeMap.get(relatedId);
        if (!relatedNode || hasBrokenEncoding(relatedNode.label)) return { edge, node: undefined };
        const label = cleanKnowledgeName(relatedNode.label);
        if (label.length < 2 || label.length > 32 || relatedNode.granularity === 'chapter_topic' || /^(?:临床病|本章临床病)$/u.test(label)) {
          return { edge, node: undefined };
        }
        return { edge, node: { ...relatedNode, label } };
      })
      .filter((item): item is { edge: GraphEdge; node: GraphNode } => Boolean(item.node))
      .slice(0, 8);
  }, [graphData, node]);

  const sourceParagraph = safeText(node?.source_paragraph || '');
  const sourceBroken = hasBrokenEncoding(node?.source_paragraph || '');
  const displayLabel = cleanKnowledgeName(node?.label || '') || safeText(node?.label || '');
  const rawDefinition = concise(node?.definition || '', 300);
  const definition = rawDefinition && rawDefinition !== displayLabel && !/(?:\.\s*){4,}|…{2,}/u.test(node?.definition || '')
    ? rawDefinition
    : concise(sourceParagraph, 300);
  const lowQuality = displayLabel.length > 36
    || /[。！？；]/u.test(displayLabel)
    || !definition
    || !sourceParagraph
    || node?.evidence_status === 'invalid';

  return (
    <Drawer
      className="knowledge-drawer"
      title={null}
      width={520}
      open={Boolean(node)}
      onClose={onClose}
      destroyOnClose
      closable={false}
    >
      {node ? (
        <article className="knowledge-detail">
          <header>
            <button className="drawer-close" onClick={onClose} aria-label="关闭知识点详情"><CloseOutlined /></button>
            <span className="detail-kicker">KNOWLEDGE POINT</span>
            <h2>{displayLabel}</h2>
            <div className="detail-location">
              <BookOutlined /> {safeText(node.chapter) || '未标注章节'}
              <span>·</span>
              第 {node.page_start || node.page || '—'}{node.page_end && node.page_end !== node.page_start ? `–${node.page_end}` : ''} 页
            </div>
          </header>

          {lowQuality && (
            <div className="detail-quality-warning"><WarningOutlined /><span><strong>这条记录需要复核</strong><small>名称、定义或原文证据不够完整，建议重新生成知识树后再用于教学。</small></span></div>
          )}

          <section className="detail-section">
            <div className="detail-section-heading"><h3><ReadOutlined /> 核心解释</h3><Tag>{node.granularity === 'chapter_topic' ? '章节主题' : node.granularity === 'section_topic' ? '主题节点' : '核心概念'}</Tag></div>
            <p className="detail-definition">{definition || '当前记录没有足够清晰的解释，请以教材原文为准。'}</p>
          </section>

          <section className="detail-section evidence-section">
            <div className="detail-section-heading"><h3><BookOutlined /> 教材依据</h3>{node.evidence_status === 'verified' && <span className="verified-copy"><CheckCircleFilled /> 原文可追溯</span>}</div>
            {sourceBroken ? (
              <div className="evidence-warning">这段历史原文存在编码异常，建议重新解析教材后再核验。</div>
            ) : sourceParagraph ? (
              <blockquote>{concise(sourceParagraph)}</blockquote>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可追溯原文" />
            )}
            <div className="evidence-meta">
              <Tag color={node.evidence_status === 'verified' ? 'success' : 'default'}>
                {node.evidence_status === 'verified' ? '证据已核验' : '待核验'}
              </Tag>
              {node.category && <Tag>{node.category}</Tag>}
            </div>
          </section>

          {related.length > 0 && (
            <section className="detail-section">
              <h3><LinkOutlined /> 相关知识点</h3>
              <div className="related-list">
                {related.map(({ edge, node: relatedNode }) => (
                  <button key={edge.id} onClick={() => onSelectRelated(relatedNode)}>
                    <span>
                      <strong>{relatedNode.label}</strong>
                      <small><b>{RELATION_LABELS[edge.relation_type] || edge.relation_type}</b>{safeText(edge.description) ? ` · ${concise(edge.description, 110)}` : ''}</small>
                    </span>
                    <RightOutlined />
                  </button>
                ))}
              </div>
            </section>
          )}
        </article>
      ) : null}
    </Drawer>
  );
};

export default KnowledgeDetailDrawer;
