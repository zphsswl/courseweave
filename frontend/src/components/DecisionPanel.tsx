import React, { useState, useEffect } from 'react';
import { Table, Tag, Button, Space, Spin, Empty, Tooltip, message, Modal, Select, Descriptions, Divider, Typography, List } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ScissorOutlined,
  ReloadOutlined,
  EditOutlined,
  LockOutlined,
  InfoCircleOutlined,
  WarningOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  NodeIndexOutlined,
  QuestionCircleOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import type { Decision, IntegrationResult } from '../types';
import * as api from '../api/client';

const { Paragraph, Text } = Typography;

interface Props {
  decisions: Decision[];
  loading: boolean;
  onUpdate: (id: string, data: Partial<Decision>) => Promise<void>;
  onRefresh: () => void;
}

const decisionColors: Record<string, string> = {
  merge: 'blue',
  keep: 'green',
  remove: 'red',
};

const decisionLabels: Record<string, string> = {
  merge: '合并',
  keep: '保留',
  remove: '移除',
};

const DecisionPanel: React.FC<Props> = ({ decisions, loading, onUpdate, onRefresh }) => {
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null);
  const [integrationResults, setIntegrationResults] = useState<IntegrationResult[]>([]);
  const [expandedIntegration, setExpandedIntegration] = useState(false);

  const handleAction = async (id: string, action: string) => {
    setActionLoading(id);
    try {
      await onUpdate(id, { action } as any);
      message.success(`决策已更新为「${decisionLabels[action] || action}」`);
    } catch {
      message.error('操作失败');
    } finally {
      setActionLoading(null);
    }
  };

  const handleRowClick = (record: Decision) => {
    setSelectedDecision(record);
    setDetailModalVisible(true);
  };

  // Reset expanded state and fetch integration results when modal opens for merge decisions
  useEffect(() => {
    if (!detailModalVisible) {
      setExpandedIntegration(false);
      setIntegrationResults([]);
    } else if (selectedDecision?.action === 'merge') {
      api.getIntegrationResults()
        .then(res => setIntegrationResults(res.data))
        .catch(() => setIntegrationResults([]));
    }
  }, [detailModalVisible, selectedDecision]);

  const matchingIntegration = selectedDecision?.action === 'merge'
    ? integrationResults.find(r => r.result_name === selectedDecision.result_name)
    : null;

  const fullIntegrationText = matchingIntegration
    ? (matchingIntegration.integrated_text || matchingIntegration.integrated_definition)
    : '';

  const columns = [
    {
      title: '概念',
      dataIndex: 'result_name',
      key: 'result_name',
      width: 120,
      ellipsis: true,
      render: (text: string, record: Decision) => (
        <Space>
          <span style={{ fontWeight: 500, cursor: 'pointer' }}>{text || record.result_node}</span>
          {record.teacher_override && (
            <LockOutlined style={{ color: '#C084FC', fontSize: 12 }} />
          )}
        </Space>
      ),
    },
    {
      title: '涉及节点',
      dataIndex: 'affected_nodes',
      key: 'affected_nodes',
      width: 100,
      render: (nodes: string[]) => (
        <span style={{ fontSize: 11, color: '#888' }}>{nodes?.length || 0} 个节点</span>
      ),
    },
    {
      title: '决策',
      dataIndex: 'action',
      key: 'action',
      width: 80,
      render: (type: string, record: Decision) => (
        <Tag color={decisionColors[type] || 'default'}>
          {decisionLabels[type] || type}
          {record.teacher_override && ' (教师)'}
        </Tag>
      ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      key: 'confidence',
      width: 80,
      render: (val: number) => (
        <Tag color={val >= 0.7 ? 'green' : val >= 0.4 ? 'orange' : 'red'}>
          {(val * 100).toFixed(0)}%
        </Tag>
      ),
    },
    {
      title: '原因',
      dataIndex: 'reason',
      key: 'reason',
      width: 140,
      ellipsis: true,
      render: (text: string) => (
        <Tooltip title={text} overlayStyle={{ maxWidth: 320 }}>
          <span style={{ fontSize: 11, color: '#666', cursor: 'pointer' }}>
            {text && text.length > 35 ? text.substring(0, 35) + '...' : text || '-'}
          </span>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_: any, record: Decision) => (
        <Space size={4}>
          <Tooltip title="接受合并">
            <Button
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={(e) => { e.stopPropagation(); handleAction(record.id, 'merge'); }}
              loading={actionLoading === record.id}
              disabled={record.action === 'merge' && record.teacher_override}
              style={{
                borderColor: record.action === 'merge' ? '#4ECDC4' : undefined,
                color: record.action === 'merge' ? '#4ECDC4' : undefined,
              }}
            >
              合并
            </Button>
          </Tooltip>
          <Tooltip title="保留独立">
            <Button
              size="small"
              icon={<CloseCircleOutlined />}
              onClick={(e) => { e.stopPropagation(); handleAction(record.id, 'keep'); }}
              loading={actionLoading === record.id}
              disabled={record.action === 'keep' && record.teacher_override}
            >
              保留
            </Button>
          </Tooltip>
          <Tooltip title="移除">
            <Button
              size="small"
              danger
              icon={<ScissorOutlined />}
              onClick={(e) => { e.stopPropagation(); handleAction(record.id, 'remove'); }}
              loading={actionLoading === record.id}
              disabled={record.action === 'remove' && record.teacher_override}
            >
              移除
            </Button>
          </Tooltip>
        </Space>
      ),
    },
  ];

  if (loading && decisions.length === 0) {
    return (
      <div className="loading-spinner">
        <Spin />
      </div>
    );
  }

  if (!loading && decisions.length === 0) {
    return (
      <div className="empty-state">
        <Empty description="暂无整合决策" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <span style={{ fontSize: 12, color: '#888' }}>
            运行「整合开始」以生成决策
          </span>
          <div style={{ marginTop: 8 }}>
            <Button size="small" onClick={onRefresh}>
              刷新
            </Button>
          </div>
        </Empty>
      </div>
    );
  }

  return (
    <div>
      <div className="panel-section">
        <div className="panel-section-title">
          <span>整合决策列表</span>
          <Button size="small" icon={<ReloadOutlined />} onClick={onRefresh} loading={loading}>
            刷新
          </Button>
        </div>
        <div className="panel-section-subtitle">
          共 {decisions.length} 条决策 · 点击行查看详情 · 点击操作按钮可修改整合策略
        </div>
      </div>

      <Table
        dataSource={decisions}
        columns={columns}
        rowKey="id"
        size="small"
        onRow={(record) => ({
          onClick: () => handleRowClick(record),
          style: { cursor: 'pointer' },
        })}
        pagination={{
          pageSize: 20,
          size: 'small',
          showTotal: (total) => `共 ${total} 条`,
        }}
        scroll={{ y: 'calc(100vh - 280px)' }}
        loading={loading && decisions.length > 0}
      />

      {/* Detail Modal */}
      <Modal
        title={
          <Space>
            <InfoCircleOutlined />
            <span>决策详情</span>
            {selectedDecision && (
              <Tag color={decisionColors[selectedDecision.action] || 'default'}>
                {decisionLabels[selectedDecision.action] || selectedDecision.action}
              </Tag>
            )}
          </Space>
        }
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={
          <Space>
            {selectedDecision && selectedDecision.teacher_override && (
              <Tag color="purple" icon={<LockOutlined />}>教师锁定</Tag>
            )}
            <Button onClick={() => setDetailModalVisible(false)}>关闭</Button>
          </Space>
        }
        width={560}
      >
        {selectedDecision && (
          <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
            {/* Basic info */}
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
              <Descriptions.Item label="结果概念">
                <span style={{ fontWeight: 600 }}>{selectedDecision.result_name || selectedDecision.result_node}</span>
              </Descriptions.Item>
              <Descriptions.Item label="涉及节点">
                <Space wrap>
                  {selectedDecision.affected_nodes?.map((nodeId) => (
                    <Tag key={nodeId} style={{ fontSize: 10, fontFamily: 'monospace' }}>
                      {nodeId.length > 20 ? nodeId.substring(0, 20) + '...' : nodeId}
                    </Tag>
                  )) || '-'}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="置信度">
                <Tag color={selectedDecision.confidence >= 0.7 ? 'green' : selectedDecision.confidence >= 0.4 ? 'orange' : 'red'}>
                  {(selectedDecision.confidence * 100).toFixed(0)}%
                </Tag>
              </Descriptions.Item>
            </Descriptions>

            {/* Reason */}
            <Divider style={{ margin: '8px 0' }}>
              <Space><FileTextOutlined />决策理由</Space>
            </Divider>
            <Paragraph
              style={{
                fontSize: 13,
                color: '#333',
                background: '#f6f8fa',
                padding: 12,
                borderRadius: 6,
                borderLeft: '3px solid #4ECDC4',
              }}
            >
              {selectedDecision.reason || '无详细理由'}
            </Paragraph>

            {/* Text Integration Compression for Merge Decisions */}
            {matchingIntegration && (
              <>
                <Divider style={{ margin: '8px 0' }}>
                  <Space><FileTextOutlined />文本整合压缩</Space>
                </Divider>
                <Descriptions column={1} size="small" bordered style={{ marginBottom: 12 }}>
                  <Descriptions.Item label="原始字符数">
                    {matchingIntegration.original_chars.toLocaleString()}
                  </Descriptions.Item>
                  <Descriptions.Item label="整合后字符数">
                    {matchingIntegration.integrated_chars.toLocaleString()}
                  </Descriptions.Item>
                  <Descriptions.Item label="压缩比">
                    <Tag
                      color={
                        matchingIntegration.compression_ratio <= 0.3
                          ? 'green'
                          : matchingIntegration.compression_ratio <= 0.4
                            ? 'orange'
                            : 'red'
                      }
                    >
                      {matchingIntegration.compression_pct}
                    </Tag>
                  </Descriptions.Item>
                </Descriptions>

                {/* Integrated text preview */}
                <Paragraph
                  style={{
                    fontSize: 12,
                    color: '#555',
                    background: '#f8fffe',
                    padding: 10,
                    borderRadius: 6,
                    border: '1px solid #e0f5f2',
                    lineHeight: 1.6,
                  }}
                >
                  {expandedIntegration
                    ? fullIntegrationText
                    : fullIntegrationText.length > 150
                      ? fullIntegrationText.substring(0, 150) + '...'
                      : fullIntegrationText
                  }
                </Paragraph>
                {fullIntegrationText.length > 150 && (
                  <Button
                    size="small"
                    type="link"
                    onClick={() => setExpandedIntegration(!expandedIntegration)}
                    style={{ padding: 0 }}
                  >
                    {expandedIntegration ? '收起' : '查看完整整合文本'}
                  </Button>
                )}
              </>
            )}

            {/* Evidence */}
            {selectedDecision.evidence && selectedDecision.evidence.length > 0 && (
              <>
                <Divider style={{ margin: '8px 0' }}>
                  <Space><FileTextOutlined />证据（带引证）</Space>
                </Divider>
                <List
                  size="small"
                  dataSource={selectedDecision.evidence}
                  renderItem={(item: string, idx: number) => (
                    <List.Item style={{ padding: '6px 0', fontSize: 12 }}>
                      <blockquote style={{
                        margin: 0,
                        padding: '6px 10px',
                        background: '#f9f9f9',
                        borderLeft: '3px solid #FFD93D',
                        borderRadius: 4,
                        color: '#555',
                        fontStyle: 'italic',
                        width: '100%',
                      }}>
                        "{item}"
                      </blockquote>
                    </List.Item>
                  )}
                />
              </>
            )}

            {/* Alternatives */}
            {selectedDecision.alternatives_considered && selectedDecision.alternatives_considered.length > 0 && (
              <>
                <Divider style={{ margin: '8px 0' }}>
                  <Space><ExperimentOutlined />备选方案</Space>
                </Divider>
                <List
                  size="small"
                  dataSource={selectedDecision.alternatives_considered}
                  renderItem={(item: string, idx: number) => (
                    <List.Item style={{ padding: '4px 0', fontSize: 12 }}>
                      <Space>
                        <Tag color="orange" style={{ fontSize: 10 }}>方案 {idx + 1}</Tag>
                        <span>{item}</span>
                      </Space>
                    </List.Item>
                  )}
                />
              </>
            )}

            {/* Risk */}
            {selectedDecision.risk && (
              <>
                <Divider style={{ margin: '8px 0' }}>
                  <Space><WarningOutlined />风险</Space>
                </Divider>
                <Paragraph style={{
                  fontSize: 12,
                  color: '#cf1322',
                  background: '#fff2f0',
                  padding: 10,
                  borderRadius: 6,
                  border: '1px solid #ffccc7',
                }}>
                  {selectedDecision.risk}
                </Paragraph>
              </>
            )}

            {/* Similarity breakdown */}
            {(selectedDecision.similarity_name || selectedDecision.similarity_definition || selectedDecision.similarity_context) && (
              <>
                <Divider style={{ margin: '8px 0' }}>
                  <Space><NodeIndexOutlined />相似度分析</Space>
                </Divider>
                <Descriptions column={1} size="small" bordered>
                  {selectedDecision.similarity_name && (
                    <Descriptions.Item label="相似度名称">
                      <Tag color="blue">{selectedDecision.similarity_name}</Tag>
                    </Descriptions.Item>
                  )}
                  {selectedDecision.similarity_definition && (
                    <Descriptions.Item label="相似度定义">
                      <Text style={{ fontSize: 12 }}>{selectedDecision.similarity_definition}</Text>
                    </Descriptions.Item>
                  )}
                  {selectedDecision.similarity_context && (
                    <Descriptions.Item label="相似度上下文">
                      <Text style={{ fontSize: 12, fontStyle: 'italic', color: '#666' }}>
                        "{selectedDecision.similarity_context}"
                      </Text>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </>
            )}

            {/* Decision effect */}
            {selectedDecision.decision_effect && (
              <>
                <Divider style={{ margin: '8px 0' }}>
                  <Space><TeamOutlined />决策影响</Space>
                </Divider>
                <Paragraph style={{
                  fontSize: 12,
                  color: '#333',
                  background: '#f0f5ff',
                  padding: 10,
                  borderRadius: 6,
                  border: '1px solid #d6e4ff',
                }}>
                  {selectedDecision.decision_effect}
                </Paragraph>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default DecisionPanel;
