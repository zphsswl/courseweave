import React from 'react';
import { Button, Spin, Empty, Card, Typography, Space, Tag, Tooltip, Divider, message } from 'antd';
import {
  ReloadOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  InfoCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import type { BenchmarkResult } from '../types';
import * as api from '../api/client';

const { Text, Title } = Typography;

interface Props {
  results: BenchmarkResult[];
  loading: boolean;
  onRefresh: () => void;
  onRun: () => Promise<void>;
}

function getScoreColor(score: number): string {
  if (score >= 0.8) return '#52c41a';
  if (score >= 0.6) return '#faad14';
  return '#f5222d';
}

function getScoreLabel(score: number): string {
  if (score >= 0.9) return '优秀';
  if (score >= 0.8) return '良好';
  if (score >= 0.6) return '一般';
  return '需改进';
}

function getScoreIcon(score: number) {
  if (score >= 0.8) return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
  if (score >= 0.6) return <WarningOutlined style={{ color: '#faad14' }} />;
  return <CloseCircleOutlined style={{ color: '#f5222d' }} />;
}

const BenchmarkPanel: React.FC<Props> = ({ results, loading, onRefresh, onRun }) => {
  const [running, setRunning] = React.useState(false);

  const handleRun = async () => {
    setRunning(true);
    try {
      await onRun();
    } catch {
      message.error('Benchmark 运行失败');
    } finally {
      setRunning(false);
    }
  };

  if (loading && results.length === 0) {
    return (
      <div className="loading-spinner">
        <Spin size="large" />
      </div>
    );
  }

  if (!loading && results.length === 0) {
    return (
      <div className="empty-state">
        <Empty
          description="暂无 Benchmark 数据"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          <span style={{ fontSize: 12, color: '#888' }}>
            点击下方按钮运行 Benchmark 评估
          </span>
          <div style={{ marginTop: 12 }}>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleRun}
              loading={running}
              style={{ background: '#4ECDC4', borderColor: '#4ECDC4' }}
            >
              运行 Benchmark
            </Button>
          </div>
          <div style={{ marginTop: 8 }}>
            <Button size="small" onClick={onRefresh}>
              刷新
            </Button>
          </div>
        </Empty>
      </div>
    );
  }

  const avgScore =
    results.length > 0
      ? results.reduce((sum, r) => sum + r.score, 0) / results.length
      : 0;

  return (
    <div>
      <div className="panel-section">
        <div className="panel-section-title">
          <Space>
            <ExperimentOutlined />
            <span>RAG 质量评估</span>
          </Space>
          <Space size={4}>
            <Button
              size="small"
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleRun}
              loading={running}
              style={{ background: '#4ECDC4', borderColor: '#4ECDC4' }}
            >
              运行 Benchmark
            </Button>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={onRefresh}
              loading={loading}
            >
              刷新
            </Button>
          </Space>
        </div>
        <div className="panel-section-subtitle">
          多维度评估 RAG 问答系统的准确性与完整性
        </div>
      </div>

      {/* Average score card */}
      <Card
        size="small"
        style={{
          marginBottom: 16,
          background: 'linear-gradient(135deg, #667eea, #764ba2)',
          color: '#fff',
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 11, opacity: 0.8 }}>综合评分</div>
          <div style={{ fontSize: 36, fontWeight: 700, margin: '4px 0' }}>
            {(avgScore * 100).toFixed(1)}
          </div>
          <div style={{ fontSize: 12, opacity: 0.8 }}>
            {getScoreLabel(avgScore)}
          </div>
        </div>
      </Card>

      {/* Individual metrics */}
      <div className="panel-section">
        <div className="panel-section-title">
          <span>各维度评分</span>
          <Text style={{ fontSize: 11, color: '#888' }}>{results.length} 项指标</Text>
        </div>
      </div>

      {results.map((result, idx) => (
        <Card
          key={idx}
          size="small"
          style={{ marginBottom: 10 }}
          bodyStyle={{ padding: '10px 14px' }}
        >
          <div style={{ marginBottom: 6 }}>
            <Space>
              {getScoreIcon(result.score)}
              <Text style={{ fontWeight: 500, fontSize: 13 }}>{result.metric}</Text>
              <Tooltip title={result.description}>
                <InfoCircleOutlined style={{ color: '#bbb', fontSize: 12, cursor: 'pointer' }} />
              </Tooltip>
            </Space>
          </div>

          <div className="benchmark-row" style={{ marginBottom: 4 }}>
            <div className="benchmark-bar-bg">
              <div
                className="benchmark-bar-fill"
                style={{
                  width: `${result.score * 100}%`,
                  background: `linear-gradient(90deg, ${getScoreColor(result.score)}, ${getScoreColor(result.score)}dd)`,
                }}
              />
            </div>
            <div className="benchmark-score" style={{ color: getScoreColor(result.score) }}>
              {(result.score * 100).toFixed(0)}
            </div>
          </div>

          <Text type="secondary" style={{ fontSize: 11 }}>
            {result.description}
          </Text>
        </Card>
      ))}

      <Divider style={{ margin: '12px 0' }} />

      {/* Legend */}
      <Space size={12} style={{ fontSize: 11, color: '#888' }}>
        <span>
          <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 4 }} />
          优秀 (≥80)
        </span>
        <span>
          <WarningOutlined style={{ color: '#faad14', marginRight: 4 }} />
          一般 (60-79)
        </span>
        <span>
          <CloseCircleOutlined style={{ color: '#f5222d', marginRight: 4 }} />
          需改进 (&lt;60)
        </span>
      </Space>
    </div>
  );
};

export default BenchmarkPanel;
