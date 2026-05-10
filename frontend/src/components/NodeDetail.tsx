import React, { useState, useEffect } from 'react';
import { Drawer, Tag, Descriptions, Divider, List, Empty, Space, Typography, Tooltip, Input, Button, Spin, Alert } from 'antd';
import {
  LockOutlined,
  StarOutlined,
  ApartmentOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  MergeCellsOutlined,
  ScissorOutlined,
  CodeOutlined,
  TagOutlined,
  LinkOutlined,
  ExperimentOutlined,
  SendOutlined,
  LoadingOutlined,
  MessageOutlined,
} from '@ant-design/icons';
import type { GraphNode, Decision, QueryResult } from '../types';
import * as api from '../api/client';

const { Paragraph } = Typography;
const { TextArea } = Input;

interface Props {
  node: GraphNode | null;
  visible: boolean;
  onClose: () => void;
  decisions?: Decision[];
}

function getBookColor(bookId: string): string {
  const colors = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
    '#FFD93D', '#C084FC', '#FB923C',
  ];
  let hash = 0;
  for (let i = 0; i < bookId.length; i++) {
    hash = (hash << 5) - hash + bookId.charCodeAt(i);
    hash |= 0;
  }
  return colors[Math.abs(hash) % colors.length];
}

function getGranularityTag(granularity?: string) {
  const config: Record<string, { color: string; label: string }> = {
    chapter_topic: { color: 'geekblue', label: '章节主题' },
    section_topic: { color: 'purple', label: '大类' },
    core_concept: { color: 'green', label: '核心概念' },
    detail_fact: { color: 'orange', label: '细节事实' },
  };
  const c = granularity ? config[granularity] : null;
  if (!c) return null;
  return (
    <Tag color={c.color} icon={<TagOutlined />} style={{ fontSize: 11, lineHeight: '20px' }}>
      {c.label}
    </Tag>
  );
}

const NodeDetail: React.FC<Props> = ({ node, visible, onClose, decisions = [] }) => {
  const [nodeQuestion, setNodeQuestion] = useState('');
  const [nodeQueryLoading, setNodeQueryLoading] = useState(false);
  const [nodeQueryResult, setNodeQueryResult] = useState<QueryResult | null>(null);
  const [nodeQueryError, setNodeQueryError] = useState<string | null>(null);

  const handleNodeQuery = async () => {
    const q = nodeQuestion.trim();
    if (!q || !node) return;
    setNodeQueryLoading(true);
    setNodeQueryError(null);
    setNodeQueryResult(null);
    try {
      const res = await api.queryNodeRag(node.id, q);
      setNodeQueryResult(res.data);
    } catch (err: any) {
      setNodeQueryError(err?.response?.data?.detail || '查询失败，请稍后重试');
    } finally {
      setNodeQueryLoading(false);
    }
  };

  // Reset Q&A when node changes
  useEffect(() => {
    setNodeQuestion('');
    setNodeQueryResult(null);
    setNodeQueryError(null);
  }, [node?.id]);

  if (!node) {
    return (
      <Drawer
        title="节点详情"
        placement="right"
        width={400}
        onClose={onClose}
        open={visible}
      >
        <Empty description="未选择节点" />
      </Drawer>
    );
  }

  const impScore = node.importance || 3;
  const impColor = impScore >= 4 ? 'green' : impScore >= 2 ? 'orange' : 'red';

  const relatedDecisions = decisions.filter(
    (d) => d.affected_nodes?.includes(node.id)
  );

  return (
    <Drawer
      title={
        <Space>
          <ApartmentOutlined style={{ color: node.color || getBookColor(node.textbook) }} />
          <span>{node.label}</span>
          {node.teacher_locked && (
            <StarOutlined style={{ color: '#C084FC', fontSize: 14 }} />
          )}
          {node.is_merged && (
            <Tag color="blue" style={{ marginLeft: 4, fontSize: 10, lineHeight: '16px' }}>
              合并节点
            </Tag>
          )}
          {node.is_essence && (
            <Tag color="gold" style={{ marginLeft: 4, fontSize: 10, lineHeight: '16px' }}>
              精华概念
            </Tag>
          )}
        </Space>
      }
      placement="right"
      width={440}
      onClose={onClose}
      open={visible}
    >
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="概念名称">
          <span style={{ fontWeight: 600 }}>{node.label}</span>
        </Descriptions.Item>

        <Descriptions.Item label="类别">
          <Tag>{node.category || '概念'}</Tag>
        </Descriptions.Item>

        {/* Granularity */}
        <Descriptions.Item label="粒度层级">
          {getGranularityTag(node.granularity) || (
            <span style={{ color: '#999' }}>-</span>
          )}
        </Descriptions.Item>

        {/* Display level */}
        {node.display_level != null && (
          <Descriptions.Item label="显示层级">
            <span style={{ fontWeight: 500 }}>{node.display_level}</span>
          </Descriptions.Item>
        )}

        <Descriptions.Item label="来源教材">
          <Tag color={node.color || getBookColor(node.textbook)} style={{ color: '#fff' }}>
            {node.textbook}
          </Tag>
        </Descriptions.Item>

        <Descriptions.Item label="章节">
          <span style={{ fontSize: 12 }}>{node.chapter || '-'}</span>
        </Descriptions.Item>

        <Descriptions.Item label="页码范围">
          <span style={{ fontSize: 12 }}>
            {node.page_start != null && node.page_end != null
              ? `${node.page_start} - ${node.page_end}`
              : node.page
              ? `第 ${node.page} 页`
              : '-'}
          </span>
        </Descriptions.Item>

        <Descriptions.Item label="出现频次">
          <span style={{ fontWeight: 500 }}>{node.frequency || 1}</span>
        </Descriptions.Item>

        <Descriptions.Item label="重要度">
          <Tag color={impColor}>
            {impScore}/5
          </Tag>
          {impScore < 3 && (
            <span style={{ color: '#faad14', fontSize: 11, marginLeft: 6 }}>
              建议人工复核
            </span>
          )}
        </Descriptions.Item>

        {node.quality_score != null && (
          <Descriptions.Item label="质量评分">
            <Tooltip title={`质量评分: ${(node.quality_score * 100).toFixed(0)}%`}>
              <Tag color={node.quality_score >= 0.7 ? 'green' : node.quality_score >= 0.4 ? 'orange' : 'red'}>
                {(node.quality_score * 100).toFixed(0)}%
              </Tag>
            </Tooltip>
          </Descriptions.Item>
        )}

        <Descriptions.Item label="合并状态">
          {node.is_merged ? (
            <Tag color="blue">已合并</Tag>
          ) : (
            <Tag>独立</Tag>
          )}
        </Descriptions.Item>

        {node.is_essence != null && (
          <Descriptions.Item label="精华概念">
            {node.is_essence ? (
              <span><CheckCircleOutlined style={{ color: '#52c41a' }} /> 是</span>
            ) : (
              <span>否</span>
            )}
          </Descriptions.Item>
        )}

        <Descriptions.Item label="教师锁定">
          {node.teacher_locked ? (
            <span>
              <LockOutlined style={{ color: '#C084FC' }} /> 已锁定
            </span>
          ) : (
            '否'
          )}
        </Descriptions.Item>

        {/* Created by */}
        {node.created_by && (
          <Descriptions.Item label="创建来源">
            <Tag icon={<CodeOutlined />} color={node.created_by === 'demo_seed' ? 'orange' : 'cyan'}>
              {node.created_by === 'demo_seed' ? '种子数据' : node.created_by === 'real' ? '真实抽取' : node.created_by}
            </Tag>
          </Descriptions.Item>
        )}

        {/* Parent ID reference */}
        {node.parent_id && (
          <Descriptions.Item label="父节点 ID">
            <Space>
              <LinkOutlined style={{ color: '#888' }} />
              <span style={{ fontSize: 12, fontFamily: 'monospace', color: '#888' }}>
                {node.parent_id}
              </span>
            </Space>
          </Descriptions.Item>
        )}
      </Descriptions>

      {node.learning_objective && (
        <>
          <Divider>学习目标</Divider>
          <Paragraph style={{ fontSize: 13, color: '#555', background: '#f0f5ff', padding: 12, borderRadius: 6, borderLeft: '3px solid #45B7D1' }}>
            {node.learning_objective}
          </Paragraph>
        </>
      )}

      {/* Definition */}
      {node.definition && (
        <>
          <Divider>知识定义</Divider>
          <Paragraph style={{ fontSize: 13, color: '#333' }}>
            {node.definition}
          </Paragraph>
        </>
      )}

      {/* Source paragraph */}
      {node.source_paragraph && (
        <>
          <Divider>原文出处</Divider>
          <Paragraph
            style={{
              fontSize: 12,
              color: '#666',
              background: '#fafafa',
              padding: 12,
              borderRadius: 6,
              borderLeft: '3px solid #4ECDC4',
            }}
            ellipsis={{ rows: 6, expandable: true, symbol: '展开' }}
          >
            {node.source_paragraph}
          </Paragraph>
        </>
      )}

      {/* Related Integration Decisions */}
      {relatedDecisions.length > 0 && (
        <>
          <Divider>关联整合决策 ({relatedDecisions.length})</Divider>
          <List
            size="small"
            dataSource={relatedDecisions}
            renderItem={(d: Decision) => (
              <List.Item style={{ padding: '6px 0', fontSize: 12 }}>
                <Space direction="vertical" size={2} style={{ width: '100%' }}>
                  <Space>
                    {d.action === 'merge' && <MergeCellsOutlined style={{ color: '#1890ff' }} />}
                    {d.action === 'keep' && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
                    {d.action === 'remove' && <ScissorOutlined style={{ color: '#ff4d4f' }} />}
                    <span style={{ fontWeight: 500 }}>
                      {d.result_name || d.result_node}
                    </span>
                    <Tag color={d.action === 'merge' ? 'blue' : d.action === 'keep' ? 'green' : 'red'} style={{ fontSize: 10, lineHeight: '16px' }}>
                      {d.action === 'merge' ? '合并' : d.action === 'keep' ? '保留' : d.action === 'remove' ? '移除' : d.action}
                    </Tag>
                  </Space>
                  {d.reason && (
                    <span style={{ color: '#888', fontSize: 11 }}>{d.reason}</span>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </>
      )}

      {/* Aliases */}
      {node.aliases && node.aliases.length > 0 && (
        <>
          <Divider>同义词/别名</Divider>
          <Space wrap>
            {node.aliases.map((a: string, i: number) => (
              <Tag key={i} color="blue">{a}</Tag>
            ))}
          </Space>
        </>
      )}

      {/* Source sentences */}
      {node.source_sentences && node.source_sentences.length > 0 && (
        <>
          <Divider>
            <Space>
              <FileTextOutlined />
              原文语句 ({node.source_sentences.length})
            </Space>
          </Divider>
          <List
            size="small"
            dataSource={node.source_sentences}
            renderItem={(s: string) => (
              <List.Item style={{ padding: '6px 0', fontSize: 12 }}>
                {s}
              </List.Item>
            )}
          />
        </>
      )}

      {/* Node Q&A */}
      <Divider>
        <Space>
          <MessageOutlined />
          围绕此节点追问
        </Space>
      </Divider>
      <div style={{ marginBottom: 16 }}>
        <TextArea
          rows={2}
          placeholder="围绕此节点追问..."
          value={nodeQuestion}
          onChange={(e) => setNodeQuestion(e.target.value)}
          disabled={nodeQueryLoading}
          style={{ fontSize: 13, marginBottom: 8 }}
        />
        <Button
          type="primary"
          icon={nodeQueryLoading ? <LoadingOutlined /> : <SendOutlined />}
          onClick={handleNodeQuery}
          loading={nodeQueryLoading}
          disabled={nodeQueryLoading || !nodeQuestion.trim()}
          style={{ background: '#4ECDC4', borderColor: '#4ECDC4' }}
        >
          提问
        </Button>
      </div>

      {nodeQueryError && (
        <Alert
          message={nodeQueryError}
          type="error"
          showIcon
          closable
          onClose={() => setNodeQueryError(null)}
          style={{ marginBottom: 12, fontSize: 12 }}
        />
      )}

      {nodeQueryLoading && (
        <div style={{ textAlign: 'center', padding: 16 }}>
          <Spin />
          <span style={{ marginLeft: 8, color: '#888', fontSize: 12 }}>查询中...</span>
        </div>
      )}

      {nodeQueryResult && (
        <div className="rag-answer" style={{ fontSize: 13, lineHeight: 1.7, marginBottom: 12 }}>
          {nodeQueryResult.answer}
          {nodeQueryResult.citations && nodeQueryResult.citations.length > 0 && (
            <div style={{ marginTop: 8, borderTop: '1px solid #e0f5f2', paddingTop: 8 }}>
              <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>引用来源:</div>
              {nodeQueryResult.citations.map((cit, idx) => (
                <div key={idx} style={{ fontSize: 11, color: '#666', marginBottom: 2 }}>
                  [{cit.textbook}, {cit.chapter}, 第{cit.page}页] 相关度: {(cit.relevance_score * 100).toFixed(0)}%
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
};

export default NodeDetail;
