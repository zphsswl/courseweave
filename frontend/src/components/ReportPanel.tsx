import React from 'react';
import { Button, Spin, Empty, Divider, Typography, Space, Tag, Descriptions } from 'antd';
import {
  ReloadOutlined,
  BookOutlined,
  FileTextOutlined,
  ApartmentOutlined,
  MergeCellsOutlined,
  ScissorOutlined,
  CompressOutlined,
  CheckCircleOutlined,
  NodeIndexOutlined,
  DeploymentUnitOutlined,
  PartitionOutlined,
} from '@ant-design/icons';
import type { ReportSummary } from '../types';

const { Text } = Typography;

interface Props {
  summary: ReportSummary | null;
  loading: boolean;
  onRefresh: () => void;
}

const ReportPanel: React.FC<Props> = ({ summary, loading, onRefresh }) => {
  if (loading && !summary) {
    return (
      <div className="loading-spinner">
        <Spin size="large" />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="empty-state">
        <Empty
          description="暂无整合报告"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          <span style={{ fontSize: 12, color: '#888' }}>
            运行「整合开始」以生成报告
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

  const tb = summary.textbooks;
  const kg = summary.knowledge_graph;
  const dec = summary.decisions;
  const rag = summary.rag;

  // Use real compression ratio from backend when available, fallback to calculated
  const compressionRatio = summary.compression_ratio != null
    ? summary.compression_ratio
    : kg ? (kg.total_nodes / Math.max((tb?.total_chars || 1) / 100, 1)) : 0;

  const stats = [
    {
      title: '教材总数',
      value: tb?.count || 0,
      icon: <BookOutlined />,
      color: 'green',
    },
    {
      title: '章节总数',
      value: summary.chapters?.total || 0,
      icon: <FileTextOutlined />,
      color: 'blue',
    },
    {
      title: '总字符数',
      value: (tb?.total_chars || 0).toLocaleString(),
      icon: <FileTextOutlined />,
      color: 'purple',
    },
    {
      title: '概念总数',
      value: kg?.total_nodes || 0,
      icon: <ApartmentOutlined />,
      color: 'teal',
    },
    {
      title: '合并决策',
      value: dec?.merge || 0,
      icon: <MergeCellsOutlined />,
      color: 'blue',
    },
    {
      title: '保留决策',
      value: dec?.keep || 0,
      icon: <CheckCircleOutlined />,
      color: 'green',
    },
    {
      title: '移除决策',
      value: dec?.remove || 0,
      icon: <ScissorOutlined />,
      color: 'red',
    },
    {
      title: '压缩比',
      value: summary.compression_ratio != null ? `${(summary.compression_ratio * 100).toFixed(1)}%` : `${compressionRatio.toFixed(1)}%`,
      icon: <CompressOutlined />,
      color: 'orange',
    },
  ];

  return (
    <div>
      <div className="panel-section">
        <div className="panel-section-title">
          <Space>
            <FileTextOutlined />
            <span>整合报告概览</span>
          </Space>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={onRefresh}
            loading={loading}
          >
            刷新
          </Button>
        </div>
        <div className="panel-section-subtitle">
          多教材知识整合结果统计
        </div>
      </div>

      <div className="stat-grid">
        {stats.map((stat, idx) => (
          <div key={idx} className={`stat-card ${stat.color}`}>
            <div className="stat-card-title">{stat.title}</div>
            <div className="stat-card-value">{stat.value}</div>
          </div>
        ))}
      </div>

      {/* Chapter/Section/Concept breakdown */}
      <div style={{ background: '#fafafa', borderRadius: 8, padding: 12, marginBottom: 12 }}>
        <div className="panel-section-title" style={{ marginBottom: 8 }}>
          <Space>
            <NodeIndexOutlined />
            <span>知识图谱构成</span>
          </Space>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Text style={{ fontSize: 12, color: '#888' }}>
            <DeploymentUnitOutlined style={{ marginRight: 4 }} />
            章节主题
          </Text>
          <Text style={{ fontSize: 12, fontWeight: 500 }}>
            {kg?.chapter_topics ?? '-'}
          </Text>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Text style={{ fontSize: 12, color: '#888' }}>
            <PartitionOutlined style={{ marginRight: 4 }} />
            大类
          </Text>
          <Text style={{ fontSize: 12, fontWeight: 500 }}>
            {kg?.section_topics ?? '-'}
          </Text>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Text style={{ fontSize: 12, color: '#888' }}>
            <ApartmentOutlined style={{ marginRight: 4 }} />
            核心概念
          </Text>
          <Text style={{ fontSize: 12, fontWeight: 500 }}>
            {kg?.core_concepts ?? '-'}
          </Text>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Text style={{ fontSize: 12, color: '#888' }}>总边数</Text>
          <Text style={{ fontSize: 12, fontWeight: 500 }}>
            {kg?.total_edges || 0}
          </Text>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Text style={{ fontSize: 12, color: '#888' }}>总节点数</Text>
          <Text style={{ fontSize: 12, fontWeight: 500 }}>
            {kg?.total_nodes || 0}
          </Text>
        </div>
      </div>

      <Divider style={{ margin: '12px 0' }} />

      <div className="panel-section">
        <div className="panel-section-title">
          <span>其他信息</span>
        </div>
        <div style={{ background: '#fafafa', borderRadius: 8, padding: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text style={{ fontSize: 12, color: '#888' }}>非合并节点数</Text>
            <Text style={{ fontSize: 12, fontWeight: 500 }}>
              {kg?.non_merged_nodes || 0}
            </Text>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text style={{ fontSize: 12, color: '#888' }}>合并节点数</Text>
            <Text style={{ fontSize: 12, fontWeight: 500 }}>
              {kg?.merged_nodes_count || 0}
            </Text>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text style={{ fontSize: 12, color: '#888' }}>RAG 知识块</Text>
            <Text style={{ fontSize: 12, fontWeight: 500 }}>
              {rag?.total_chunks || 0}
            </Text>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text style={{ fontSize: 12, color: '#888' }}>教师修正数</Text>
            <Tag color="blue" style={{ fontSize: 11 }}>
              {dec?.teacher_overrides || 0} 项修正
            </Tag>
          </div>
          {summary.compression_ratio != null && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <Text style={{ fontSize: 12, color: '#888' }}>后端压缩比</Text>
              <Tag color="orange" style={{ fontSize: 11 }}>
                {(summary.compression_ratio * 100).toFixed(2)}%
              </Tag>
            </div>
          )}
        </div>
      </div>

      <div style={{ background: '#f0fff4', border: '1px solid #d4edda', borderRadius: 8, padding: 12, marginTop: 8 }}>
        <Text style={{ fontSize: 12, color: '#155724' }}>
          共整合来自 <strong>{tb?.count || 0}</strong> 本教材的{' '}
          <strong>{kg?.total_nodes || 0}</strong> 个知识点，其中{' '}
          <strong>{dec?.merge || 0}</strong> 个合并决策，{' '}
          <strong>{dec?.remove || 0}</strong> 个移除决策，{' '}
          <strong>{dec?.teacher_overrides || 0}</strong> 个教师修正。
          节点保留率约 <strong>{summary.compression_ratio != null ? (summary.compression_ratio * 100).toFixed(1) + '%' : compressionRatio.toFixed(1) + '%'}</strong>
          {summary.compression_ratio != null && '（来自后端）'}。
        </Text>
      </div>
    </div>
  );
};

export default ReportPanel;
