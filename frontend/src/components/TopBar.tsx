import React, { useState, useEffect, useCallback } from 'react';
import { Button, Tag, Tooltip, Badge, Space, Spin, message } from 'antd';
import {
  DownloadOutlined,
  ShareAltOutlined,
  ThunderboltOutlined,
  BookOutlined,
  FileTextOutlined,
  CompressOutlined,
  ApartmentOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import type { RagStatus, ModelStatus, Diagnostics, CompressionStats } from '../types';
import * as api from '../api/client';

interface Props {
  textbooksCount: number;
  totalChars: number;
  compressionRatio: number;
  ragStatus: RagStatus | null;
  onExport: () => void;
  onIntegrate: () => void;
  onBuildRagIndex: () => void;
  isIntegrating: boolean;
  isBuildingRag: boolean;
  modelStatus: ModelStatus | null;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

const TopBar: React.FC<Props> = ({
  textbooksCount,
  totalChars,
  compressionRatio,
  ragStatus,
  onExport,
  onIntegrate,
  onBuildRagIndex,
  isIntegrating,
  isBuildingRag,
  modelStatus,
}) => {
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [compressionStats, setCompressionStats] = useState<CompressionStats | null>(null);
  const [textIntegrating, setTextIntegrating] = useState(false);

  useEffect(() => {
    api.getDiagnostics().then((res) => setDiagnostics(res.data)).catch(() => {});
  }, []);

  const fetchCompressionStats = useCallback(async () => {
    try {
      const res = await api.getCompressionStats();
      setCompressionStats(res.data);
    } catch {
      // Not available yet
    }
  }, []);

  useEffect(() => {
    fetchCompressionStats();
  }, [fetchCompressionStats]);

  // Refetch when integration completes
  useEffect(() => {
    if (!isIntegrating) fetchCompressionStats();
  }, [isIntegrating, fetchCompressionStats]);

  const handleTextIntegrate = async () => {
    setTextIntegrating(true);
    try {
      await api.runIntegration();
      message.success('文本整合完成');
      setTimeout(() => {
        fetchCompressionStats();
      }, 3000);
    } catch {
      message.error('文本整合失败');
    } finally {
      setTextIntegrating(false);
    }
  };

  const tc = compressionStats?.text_compression;
  const compressionBarColor = tc
    ? tc.ratio <= 0.3
      ? '#4ECDC4'
      : tc.ratio <= 0.4
        ? '#faad14'
        : '#f5222d'
    : '#4ECDC4';

  return (
    <div className="topbar">
      <div className="topbar-left">
        <div className="topbar-logo">M</div>
        <span className="topbar-title">MedEssence Agent · 七书归一</span>
        <div className="topbar-divider" />
        <div className="topbar-stats">
          <div className="topbar-stat">
            <BookOutlined className="topbar-stat-icon" />
            <span className="topbar-stat-label">教材</span>
            <span className="topbar-stat-value">{textbooksCount}</span>
          </div>
          <div className="topbar-stat">
            <FileTextOutlined className="topbar-stat-icon" />
            <span className="topbar-stat-label">总字符</span>
            <span className="topbar-stat-value">{totalChars.toLocaleString()}</span>
          </div>
          <div className="topbar-stat">
            <CompressOutlined className="topbar-stat-icon" />
            <span className="topbar-stat-label">压缩比</span>
            <span className="topbar-stat-value">
              {compressionRatio > 0 ? `${(compressionRatio * 100).toFixed(1)}%` : '--'}
            </span>
          </div>

          {/* Text Integration Compression Bar */}
          <div className="topbar-stat">
            <Tooltip
              title={
                tc
                  ? `原始字符: ${tc.original_chars.toLocaleString()} → 整合后: ${tc.integrated_chars.toLocaleString()}\n整合概念数: ${tc.integrated_concepts}`
                  : '尚未运行文本整合'
              }
            >
              <div className="compression-bar-container">
                <FileTextOutlined className="topbar-stat-icon" />
                <span className="compression-bar-label">整合压缩</span>
                {tc ? (
                  <>
                    <div className="compression-bar-track">
                      <div
                        className="compression-bar-fill"
                        style={{
                          width: `${Math.min(tc.ratio * 100, 100)}%`,
                          background: compressionBarColor,
                        }}
                      />
                    </div>
                    <span className="compression-bar-pct">{tc.ratio_pct}</span>
                  </>
                ) : (
                  <span className="topbar-stat-value" style={{ fontSize: 11, color: '#888' }}>
                    未运行
                  </span>
                )}
              </div>
            </Tooltip>
          </div>

          <div className="topbar-stat">
            <ThunderboltOutlined className="topbar-stat-icon" />
            <span className="topbar-stat-label">RAG</span>
            {ragStatus ? (
              <Tag
                color={ragStatus.indexed ? 'green' : 'default'}
                style={{ margin: 0, fontSize: 10, lineHeight: '18px', padding: '0 6px' }}
              >
                {ragStatus.indexed ? `已索引 ${ragStatus.chunk_count} 块` : '未索引'}
              </Tag>
            ) : (
              <span className="topbar-stat-value" style={{ fontSize: 11 }}>--</span>
            )}
          </div>
          <div className="topbar-stat">
            <RobotOutlined className="topbar-stat-icon" />
            <span className="topbar-stat-label">模型</span>
            {modelStatus ? (
              <Tooltip title={`${modelStatus.provider} / ${modelStatus.model} · ${modelStatus.api_key_configured ? 'API 已配置' : 'API 未配置'}`}>
                <Tag
                  color={modelStatus.api_key_configured ? 'green' : 'orange'}
                  style={{ margin: 0, fontSize: 10, lineHeight: '18px', padding: '0 6px' }}
                >
                  {modelStatus.api_key_configured ? (
                    <CheckCircleOutlined style={{ marginRight: 3 }} />
                  ) : (
                    <WarningOutlined style={{ marginRight: 3 }} />
                  )}
                  {modelStatus.provider}
                </Tag>
              </Tooltip>
            ) : (
              <span className="topbar-stat-value" style={{ fontSize: 11 }}>--</span>
            )}
          </div>
          {/* Diagnostics indicator */}
          {diagnostics && diagnostics.status !== 'healthy' && diagnostics.checks && diagnostics.checks.length > 0 && (
            <div className="topbar-stat">
              <Tooltip
                title={
                  <div>
                    {diagnostics.checks.map((c, i) => (
                      <div key={i} style={{ fontSize: 11, marginBottom: 2 }}>
                        {c.status === 'error' ? '■' : '▲'} {c.component}: {c.message || c.status}
                      </div>
                    ))}
                  </div>
                }
              >
                <span
                  style={{
                    display: 'inline-block',
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    background: diagnostics.status === 'error' ? '#f5222d' : '#faad14',
                    cursor: 'pointer',
                    marginLeft: 4,
                  }}
                />
              </Tooltip>
            </div>
          )}
        </div>
      </div>

      <div className="topbar-right">
        <Space size={6}>
          <Tooltip title="构建 RAG 知识库索引">
            <Button
              size="small"
              icon={isBuildingRag ? <LoadingOutlined /> : <ThunderboltOutlined />}
              onClick={onBuildRagIndex}
              loading={isBuildingRag}
              style={{
                color: '#fff',
                borderColor: 'rgba(255,255,255,0.25)',
                background: 'rgba(255,255,255,0.08)',
              }}
            >
              构建索引
            </Button>
          </Tooltip>

          <Tooltip title="运行多教材文本整合（新流程）">
            <Button
              size="small"
              icon={textIntegrating ? <LoadingOutlined /> : <FileTextOutlined />}
              onClick={handleTextIntegrate}
              loading={textIntegrating}
              style={{
                color: '#fff',
                borderColor: 'rgba(255,255,255,0.25)',
                background: 'rgba(255,255,255,0.08)',
              }}
            >
              文本整合
            </Button>
          </Tooltip>

          <Tooltip title="启动多教材知识整合">
            <Button
              size="small"
              icon={isIntegrating ? <LoadingOutlined /> : <ShareAltOutlined />}
              onClick={onIntegrate}
              loading={isIntegrating}
              type="primary"
              style={{ background: '#4ECDC4', borderColor: '#4ECDC4' }}
            >
              整合开始
            </Button>
          </Tooltip>

          <Tooltip title="导出整合报告">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={onExport}
              style={{
                color: '#fff',
                borderColor: 'rgba(255,255,255,0.25)',
                background: 'rgba(255,255,255,0.08)',
              }}
            >
              导出报告
            </Button>
          </Tooltip>
        </Space>
      </div>
    </div>
  );
};

export default TopBar;
