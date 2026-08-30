import React from 'react';
import { Button, Popover } from 'antd';
import { ApiOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ModelStatus } from '../types';


interface Props {
  status: ModelStatus | null;
  checking?: boolean;
  onCheck: () => void;
  probeEnabled?: boolean;
}

const LABELS: Record<string, string> = {
  available: '模型可用',
  unknown: '模型待检测',
  balance_insufficient: '余额不足 · 已降级',
  authentication_failed: '鉴权失败 · 已降级',
  unavailable: '模型不可用 · 已降级',
  degraded: '模型异常 · 已降级',
  not_configured: '未配置 · 证据模式',
};

const ModelAvailabilityBadge: React.FC<Props> = ({ status, checking = false, onCheck, probeEnabled = true }) => {
  const availability = status?.availability || 'unknown';
  const checkedAt = status?.last_checked_at
    ? new Date(status.last_checked_at).toLocaleString('zh-CN', { hour12: false })
    : '尚未检测';
  const content = (
    <div className="model-health-card">
      <div className="model-health-card-head">
        <span className={`model-health-signal ${availability}`}><i /><i /><i /></span>
        <div><small>MODEL RUNTIME</small><strong>{LABELS[availability]}</strong></div>
      </div>
      <dl>
        <div><dt>当前模型</dt><dd>{status ? `${status.provider} / ${status.model}` : '读取中'}</dd></div>
        <div><dt>最近检测</dt><dd>{checkedAt}</dd></div>
        <div><dt>运行方式</dt><dd>{status?.degraded ? status.fallback_mode : '大模型 + 原文证据'}</dd></div>
      </dl>
      <p>{status?.message || '正在读取模型运行状态'}</p>
      <Button icon={<ReloadOutlined />} loading={checking} onClick={onCheck} block>
        {probeEnabled ? '重新检测' : '刷新状态'}
      </Button>
    </div>
  );

  return (
    <Popover content={content} trigger="click" placement="bottomRight">
      <button className={`model-health-pill ${availability}`} aria-label={`模型状态：${LABELS[availability]}`}>
        <span className="model-health-dot" />
        <ApiOutlined />
        <span>{LABELS[availability]}</span>
      </button>
    </Popover>
  );
};

export default ModelAvailabilityBadge;
