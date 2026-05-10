import React, { useState, useEffect } from 'react';
import { Button, Tag, Tooltip, Badge, Space, Spin } from 'antd';
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
import type { RagStatus, ModelStatus, Diagnostics } from '../types';
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

  useEffect(() => {
    api.getDiagnostics().then((res) => setDiagnostics(res.data)).catch(() => {});
  }, []);
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
