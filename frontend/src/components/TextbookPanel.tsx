import React, { useCallback, useState } from 'react';
import {
  Upload,
  Button,
  Tag,
  Spin,
  message,
  Space,
  Typography,
  Tooltip,
  Progress,
  Popconfirm,
} from 'antd';
import {
  UploadOutlined,
  PlayCircleOutlined,
  ApartmentOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  LoadingOutlined,
  BookOutlined,
  ReloadOutlined,
  ExperimentOutlined,
} from '@ant-design/icons';
import type { UploadProps } from 'antd';
import type { Textbook, Job } from '../types';

const { Text } = Typography;

interface Props {
  textbooks: Textbook[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onUpload: (file: File) => Promise<any>;
  onParse: (id: string, force?: boolean) => void;
  onExtractGraph: (id: string, force?: boolean) => void;
  jobs: Record<string, Job>;
}

function formatFileSize(bytes: number): string {
  if (!bytes) return '--';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getStatusTag(parseStatus: string) {
  const config: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
    pending: { color: 'default', icon: <ClockCircleOutlined />, label: '待解析' },
    processing: { color: 'processing', icon: <LoadingOutlined />, label: '解析中' },
    completed: { color: 'success', icon: <CheckCircleOutlined />, label: '已解析' },
    failed: { color: 'error', icon: <ExclamationCircleOutlined />, label: '错误' },
  };
  const c = config[parseStatus] || config.pending;
  return (
    <Tag color={c.color} icon={c.icon} style={{ margin: 0, fontSize: 11, lineHeight: '20px', padding: '0 8px' }}>
      {c.label}
    </Tag>
  );
}

function getGraphStatusTag(graphStatus: string) {
  const config: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
    pending: { color: 'default', icon: <ClockCircleOutlined />, label: '待抽取' },
    processing: { color: 'processing', icon: <LoadingOutlined />, label: '抽取中' },
    completed: { color: 'success', icon: <CheckCircleOutlined />, label: '已抽取' },
    failed: { color: 'error', icon: <ExclamationCircleOutlined />, label: '错误' },
  };
  const c = config[graphStatus] || config.pending;
  return (
    <Tag color={c.color} icon={c.icon} style={{ margin: 0, fontSize: 10, lineHeight: '18px' }}>
      {c.label}
    </Tag>
  );
}

const TextbookPanel: React.FC<Props> = ({
  textbooks,
  selectedId,
  loading,
  onSelect,
  onUpload,
  onParse,
  onExtractGraph,
  jobs,
}) => {
  const [uploading, setUploading] = useState(false);

  // Upload handler
  const handleUpload: UploadProps['customRequest'] = useCallback(
    async (options: any) => {
      const file = options.file as File;
      const onSuccess = options.onSuccess;
      const onError = options.onError;
      setUploading(true);
      try {
        await onUpload(file);
        onSuccess?.(undefined);
      } catch {
        onError?.(new Error('Upload failed'));
      } finally {
        setUploading(false);
      }
    },
    [onUpload]
  );

  const uploadProps: UploadProps = {
    customRequest: handleUpload,
    showUploadList: false,
    accept: '.pdf,.md,.txt',
    disabled: uploading,
  };

  // Find running job for a textbook
  const findJob = (textbookId: string): Job | undefined => {
    return Object.values(jobs).find(
      (j) =>
        (j.type === 'parse' || j.type === 'extract-graph') &&
        j.status === 'running' &&
        j.message?.includes(textbookId)
    );
  };

  return (
    <>
      <div className="left-panel-header">
        <span>
          <BookOutlined style={{ marginRight: 6 }} />
          教材管理
        </span>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {textbooks.length} 本
        </Text>
      </div>

      <div className="left-panel-content">
        {/* Upload area */}
        <div className="upload-card" style={{ marginBottom: 12 }}>
          <Upload.Dragger {...uploadProps}>
            <p className="ant-upload-drag-icon">
              <UploadOutlined style={{ fontSize: 28, color: '#4ECDC4' }} />
            </p>
            <p className="ant-upload-text" style={{ marginBottom: 4 }}>
              点击或拖拽上传教材
            </p>
            <p className="ant-upload-hint">支持 PDF / Markdown / TXT 格式</p>
          </Upload.Dragger>
        </div>

        {/* Loading */}
        {loading && (
          <div className="loading-spinner">
            <Spin size="small" />
            <span style={{ marginLeft: 8, color: '#888', fontSize: 12 }}>加载中...</span>
          </div>
        )}

        {/* Textbook list */}
        {!loading && textbooks.length === 0 && (
          <div className="empty-state" style={{ padding: '30px 16px' }}>
            <FileTextOutlined className="empty-state-icon" style={{ fontSize: 36 }} />
            <div className="empty-state-text">暂无教材</div>
            <Text type="secondary" style={{ fontSize: 11, marginTop: 4 }}>
              请上传教材文件开始使用
            </Text>
          </div>
        )}

        {!loading &&
          textbooks.map((tb) => (
            <div
              key={tb.id}
              className={`textbook-card ${selectedId === tb.id ? 'active' : ''}`}
              onClick={() => onSelect(tb.id)}
            >
              <div className="textbook-card-title">
                <span className="textbook-card-title-text">{tb.title}</span>
                {getStatusTag(tb.parse_status)}
              </div>

              <div className="textbook-card-meta">
                <span>{formatFileSize(tb.file_size)}</span>
                <span>{tb.total_pages ?? '--'} 页</span>
                <span>{tb.chapter_count ?? '--'} 章节</span>
              </div>

              {/* Graph status */}
              {tb.graph_status && tb.parse_status === 'completed' && (
                <div className="textbook-card-meta" style={{ marginTop: 2 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <ApartmentOutlined style={{ fontSize: 11 }} />
                    图谱状态: {getGraphStatusTag(tb.graph_status)}
                  </span>
                </div>
              )}

              <div className="textbook-card-actions">
                {/* Parse button (shown when pending/failed or always to allow re-parse) */}
                {(tb.parse_status === 'pending' || tb.parse_status === 'failed') && (
                  <Tooltip title="解析教材内容">
                    <Button
                      className="action-btn"
                      icon={<PlayCircleOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        onParse(tb.id);
                      }}
                    >
                      解析
                    </Button>
                  </Tooltip>
                )}

                {/* Re-parse: available after completed */}
                {tb.parse_status === 'completed' && (
                  <Popconfirm
                    title="重新解析将覆盖已有解析结果，确定继续？"
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      onParse(tb.id, true);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="确定"
                    cancelText="取消"
                  >
                    <Tooltip title="重新解析教材内容">
                      <Button
                        className="action-btn"
                        icon={<ReloadOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      >
                        重新解析
                      </Button>
                    </Tooltip>
                  </Popconfirm>
                )}

                {/* Extract graph (shown after parse) */}
                {(tb.parse_status === 'completed' && (!tb.graph_status || tb.graph_status === 'pending' || tb.graph_status === 'failed')) && (
                  <Tooltip title="提取知识图谱">
                    <Button
                      className="action-btn"
                      icon={<ApartmentOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        onExtractGraph(tb.id);
                      }}
                    >
                      提取图谱
                    </Button>
                  </Tooltip>
                )}

                {/* Re-extract: available after graph extraction completed */}
                {tb.graph_status === 'completed' && (
                  <Popconfirm
                    title="重新抽取将覆盖已有图谱结果，确定继续？"
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      onExtractGraph(tb.id, true);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                    okText="确定"
                    cancelText="取消"
                  >
                    <Tooltip title="重新抽取知识图谱">
                      <Button
                        className="action-btn"
                        icon={<ExperimentOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      >
                        重新抽取
                      </Button>
                    </Tooltip>
                  </Popconfirm>
                )}

                {tb.parse_status === 'processing' && (
                  <Tag color="processing" style={{ fontSize: 10 }}>
                    <LoadingOutlined /> 解析中...
                  </Tag>
                )}

                {tb.graph_status === 'processing' && (
                  <Tag color="processing" style={{ fontSize: 10 }}>
                    <LoadingOutlined /> 图谱抽取中...
                  </Tag>
                )}
              </div>
            </div>
          ))}
      </div>
    </>
  );
};

export default TextbookPanel;
