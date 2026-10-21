import React, { useCallback, useState } from 'react';
import { Button, Dropdown, Empty, Modal, Spin, Upload, message } from 'antd';
import type { UploadProps } from 'antd';
import {
  BookOutlined,
  CheckCircleFilled,
  DeleteOutlined,
  FileTextOutlined,
  LoadingOutlined,
  MoreOutlined,
  RightOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import type { Job, Textbook } from '../types';
import ChapterReviewModal from './ChapterReviewModal';
import { textbookWorkflow } from './textbookWorkflow';
import './Teaching.css';

interface Props {
  textbooks: Textbook[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onUpload: (file: File) => Promise<any>;
  onParse: (id: string, force?: boolean) => void;
  onExtractGraph: (id: string, force?: boolean) => void;
  onDelete: (id: string) => Promise<void>;
  onConfirmStructure: () => void;
  jobs: Record<string, Job>;
  readOnly?: boolean;
}

const formatFileSize = (bytes: number) => {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
};

const TextbookPanel: React.FC<Props> = ({
  textbooks,
  loading,
  onSelect,
  onUpload,
  onParse,
  onExtractGraph,
  onDelete,
  onConfirmStructure,
  jobs,
  readOnly = false,
}) => {
  const [uploading, setUploading] = useState(false);
  const [reviewingBook, setReviewingBook] = useState<Textbook | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const upload: UploadProps['customRequest'] = useCallback(async ({ file, onSuccess, onError }: any) => {
    setUploading(true);
    try {
      await onUpload(file as File);
      onSuccess?.({});
    } catch (error) {
      onError?.(error);
    } finally {
      setUploading(false);
    }
  }, [onUpload]);

  const runPrimaryAction = (book: Textbook) => {
    const { action } = textbookWorkflow(book, jobs[book.id], readOnly);
    if (action === 'parse') return onParse(book.id);
    if (action === 'review') return setReviewingBook(book);
    if (action === 'read') return onSelect(book.id);
  };

  const confirmForce = (title: string, content: string, action: () => void) => {
    Modal.confirm({ title, content, okText: '继续', cancelText: '取消', onOk: action });
  };

  const confirmDelete = (book: Textbook) => {
    Modal.confirm({
      className: 'delete-book-confirm',
      centered: true,
      title: `删除《${book.title}》？`,
      content: (
        <div className="delete-book-copy">
          <p>教材文件、章节、知识树以及与其他教材的关联都会一并删除。</p>
          <small>此操作无法撤销，其他教材不会受到影响。</small>
        </div>
      ),
      okText: '确认删除',
      cancelText: '保留教材',
      okButtonProps: { danger: true },
      onOk: async () => {
        setDeletingId(book.id);
        try {
          await onDelete(book.id);
        } catch (error: any) {
          message.error(error?.response?.data?.detail || '教材删除失败，请重试');
          throw error;
        } finally {
          setDeletingId(null);
        }
      },
    });
  };

  return (
    <section className="library-page">
      <div className="library-heading">
        <div>
          <span className="section-kicker">TEXTBOOK LIBRARY</span>
          <h1>教材</h1>
          <p>阅读教材与原页，核对目录，再把需要的材料带入备课。</p>
        </div>
        <div className="library-summary">
          <strong>{textbooks.length}</strong>
          <span>本教材</span>
          <i />
          <strong>{textbooks.filter((book) => book.parse_status === 'completed').length}</strong>
          <span>本可阅读</span>
        </div>
      </div>

      {readOnly ? (
        <div className="library-upload readonly-demo-note">
          <div className="upload-inline">
            <span className="upload-icon"><BookOutlined /></span>
            <div><strong>在线示例已加载原创教材</strong><small>打开教材阅读、核对跨教材证据，或查看示例教案。</small></div>
          </div>
        </div>
      ) : textbooks.length > 0 ? (
        <div className="library-upload-compact">
          <div><strong>添加参考教材</strong><small>PDF、Markdown 或 TXT · 上传后可解析正文</small></div>
          <Upload accept=".pdf,.md,.txt" showUploadList={false} customRequest={upload} disabled={uploading}>
            <Button icon={<UploadOutlined />} loading={uploading}>{uploading ? '正在上传…' : '上传教材'}</Button>
          </Upload>
        </div>
      ) : (
        <Upload.Dragger
          className="library-upload"
          accept=".pdf,.md,.txt"
          showUploadList={false}
          customRequest={upload}
          disabled={uploading}
        >
          <div className="upload-inline">
            <span className="upload-icon">{uploading ? <LoadingOutlined /> : <UploadOutlined />}</span>
            <div>
              <strong>{uploading ? '正在上传教材…' : '拖入教材，或点击选择文件'}</strong>
              <small>支持 PDF、Markdown、TXT，上传后解析正文并核对目录</small>
            </div>
            <Button type="primary" icon={<UploadOutlined />} loading={uploading}>选择教材</Button>
          </div>
        </Upload.Dragger>
      )}

      <div className="library-list-heading">
        <span>全部教材</span>
          <small>解析完成即可阅读；目录核对后用于备课</small>
      </div>

      {loading ? (
        <div className="library-loading"><Spin /><span>正在加载教材…</span></div>
      ) : textbooks.length === 0 ? (
        <Empty
          className="library-empty"
          image={<FileTextOutlined />}
          description={<span>还没有教材<br /><small>上传主教材或参考书，开始准备一堂课</small></span>}
        />
      ) : (
        <div className="textbook-list">
          {textbooks.map((book, index) => {
            const job = jobs[book.id];
            const state = textbookWorkflow(book, job, readOnly);
            const working = state.processing;
            const deleting = deletingId === book.id;
            return (
              <article className="textbook-row" key={book.id}>
                <span className="book-index">{String(index + 1).padStart(2, '0')}</span>
                <span className="book-glyph"><BookOutlined /></span>
                <div className="book-main">
                  <div className="book-title-line">
                    <h2>{book.title}</h2>
                    <span className={`book-state ${state.tone}`}>
                      {!working && state.tone === 'ready' && <CheckCircleFilled />}
                      {working && <LoadingOutlined />}
                      {state.label}
                    </span>
                  </div>
                  <p>
                    <span>{formatFileSize(book.file_size)}</span>
                    <span>{book.total_pages || '—'} 页</span>
                  </p>
                  {state.detail && <p className={`book-workflow-detail ${state.tone === 'error' ? 'has-error' : ''}`} role={state.tone === 'error' ? 'alert' : undefined}>{state.detail}{working && state.progress !== null ? ` · ${state.progress}%` : ''}</p>}
                  {!!book.parse_warnings?.length && <details className="book-parse-warnings"><summary>{book.parse_warnings.length} 项正文与页码提示</summary><ul>{book.parse_warnings.map((warning, at) => <li key={at}>{warning}</li>)}</ul></details>}
                </div>
                <div className="book-row-actions">
                  <div className="book-primary-wrap">
                    <Button
                      className={`book-primary-action ${state.action === 'wait' ? 'processing' : ''}`}
                      type={state.tone === 'next' || state.tone === 'review' ? 'primary' : 'default'}
                      size="large"
                      disabled={state.action === 'wait'}
                      loading={deleting}
                      onClick={() => runPrimaryAction(book)}
                    >
                      <span>{state.actionLabel}</span>
                      {state.action !== 'wait' && <RightOutlined />}
                      {state.action === 'wait' && state.processing && state.progress !== null && (
                        <span className="action-progress-track" role="progressbar" aria-valuenow={state.progress} aria-valuemin={0} aria-valuemax={100}>
                          <i style={{ width: `${state.progress}%` }} />
                        </span>
                      )}
                    </Button>
                    {state.action === 'review' && <Button type="link" size="small" className="book-read-action" onClick={() => onSelect(book.id)}>先阅读正文</Button>}
                  </div>
                  {!readOnly && <Dropdown
                    trigger={['click']}
                    menu={{
                      items: [
                        { key: 'chapters', label: '核对章节结构', disabled: working || book.parse_status !== 'completed', onClick: () => setReviewingBook(book) },
                        {
                          key: 'parse',
                          label: '重新解析教材',
                          disabled: working,
                          onClick: () => confirmForce('重新解析教材？', '现有章节与解析结果会被覆盖。', () => onParse(book.id, true)),
                        },
                        {
                          key: 'extract',
                          label: ['completed', 'review'].includes(book.graph_status) ? '重新整理教材知识' : book.graph_status === 'failed' ? '重试知识整理' : '整理教材知识',
                          disabled: working || book.structure_status !== 'confirmed',
                          onClick: () => ['completed', 'review'].includes(book.graph_status)
                            ? confirmForce('重新整理教材知识？', '现有知识点与关系会被重新计算。', () => onExtractGraph(book.id, true))
                            : onExtractGraph(book.id, book.graph_status === 'failed'),
                        },
                        { type: 'divider' },
                        {
                          key: 'delete',
                          danger: true,
                          icon: <DeleteOutlined />,
                          label: '删除教材',
                          disabled: working || deleting,
                          onClick: () => confirmDelete(book),
                        },
                      ],
                    }}
                  >
                    <Button size="large" icon={<MoreOutlined />} loading={deleting} aria-label={`${book.title}更多操作`} />
                  </Dropdown>}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <ChapterReviewModal
        textbook={reviewingBook}
        onClose={() => setReviewingBook(null)}
        onConfirmed={() => {
          setReviewingBook(null);
          onConfirmStructure();
        }}
      />
    </section>
  );
};

export default TextbookPanel;
