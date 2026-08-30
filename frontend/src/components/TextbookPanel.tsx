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

const graphReady = (book: Textbook) => ['completed', 'review'].includes(book.graph_status);

const getBookState = (book: Textbook) => {
  if (book.parse_status === 'processing') return { label: '正在解析', tone: 'working' };
  if (book.graph_status === 'processing') return { label: '正在生成知识树', tone: 'working' };
  if (book.parse_status === 'pending' || book.parse_status === 'failed') return { label: '等待解析', tone: 'next' };
  if (book.structure_status === 'review') return { label: '待确认章节', tone: 'review' };
  if (graphReady(book)) return { label: '知识树已生成', tone: 'ready' };
  if (book.structure_status === 'confirmed') return { label: '可生成知识树', tone: 'next' };
  return { label: '已解析', tone: 'neutral' };
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
    if (book.parse_status === 'pending' || book.parse_status === 'failed') return onParse(book.id);
    if (book.structure_status === 'review') return setReviewingBook(book);
    if (book.structure_status === 'confirmed' && !graphReady(book)) return onExtractGraph(book.id);
    return onSelect(book.id);
  };

  const primaryLabel = (book: Textbook) => {
    if (book.parse_status === 'processing' || book.graph_status === 'processing') return '处理中';
    if (book.parse_status === 'pending' || book.parse_status === 'failed') return '解析教材';
    if (book.structure_status === 'review') return '确认章节';
    if (book.structure_status === 'confirmed' && !graphReady(book)) return '生成知识树';
    return '打开知识树';
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
          <p>上传教材，确认章节，再生成一棵可以阅读和追溯的知识树。</p>
        </div>
        <div className="library-summary">
          <strong>{textbooks.length}</strong>
          <span>本教材</span>
          <i />
          <strong>{textbooks.filter(graphReady).length}</strong>
          <span>棵知识树</span>
        </div>
      </div>

      {readOnly ? (
        <div className="library-upload readonly-demo-note">
          <div className="upload-inline">
            <span className="upload-icon"><BookOutlined /></span>
            <div><strong>在线作品已加载原创示例教材</strong><small>可直接打开知识树、跨教材连接和教材问答；上传与重新解析请在本地运行。</small></div>
          </div>
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
              <small>支持 PDF、Markdown、TXT，单本教材上传后按步骤处理</small>
            </div>
            <Button type="primary" icon={<UploadOutlined />} loading={uploading}>选择教材</Button>
          </div>
        </Upload.Dragger>
      )}

      <div className="library-list-heading">
        <span>全部教材</span>
        <small>每本教材只显示当前需要完成的下一步</small>
      </div>

      {loading ? (
        <div className="library-loading"><Spin /><span>正在加载教材…</span></div>
      ) : textbooks.length === 0 ? (
        <Empty
          className="library-empty"
          image={<FileTextOutlined />}
          description={<span>还没有教材<br /><small>上传第一本教材开始构建知识树</small></span>}
        />
      ) : (
        <div className="textbook-list">
          {textbooks.map((book, index) => {
            const state = getBookState(book);
            const job = jobs[book.id];
            const jobWorking = job && (job.status === 'pending' || job.status === 'processing');
            const working = Boolean(jobWorking || book.parse_status === 'processing' || book.graph_status === 'processing');
            const progress = jobWorking
              ? job.total > 0 ? Math.max(6, Math.min(96, Math.round((job.progress / job.total) * 100))) : 8
              : working ? 35 : 100;
            const generatingGraph = job?.type === 'extract_graph' || book.graph_status === 'processing';
            const workingLabel = generatingGraph ? '正在生成知识树' : '正在解析教材';
            const deleting = deletingId === book.id;
            return (
              <article className="textbook-row" key={book.id}>
                <span className="book-index">{String(index + 1).padStart(2, '0')}</span>
                <span className="book-glyph"><BookOutlined /></span>
                <div className="book-main">
                  <div className="book-title-line">
                    <h2>{book.title}</h2>
                    <span className={`book-state ${working ? 'working' : state.tone}`}>
                      {!working && state.tone === 'ready' && <CheckCircleFilled />}
                      {working && <LoadingOutlined />}
                      {working ? workingLabel : state.label}
                    </span>
                  </div>
                  <p>
                    <span>{formatFileSize(book.file_size)}</span>
                    <span>{book.total_pages || '—'} 页</span>
                  </p>
                </div>
                <div className="book-row-actions">
                  <div className="book-primary-wrap">
                    <Button
                      className={`book-primary-action ${working ? 'processing' : ''}`}
                      type={state.tone === 'next' || state.tone === 'review' ? 'primary' : 'default'}
                      size="large"
                      disabled={working}
                      loading={deleting}
                      onClick={() => runPrimaryAction(book)}
                    >
                      <span>{working ? workingLabel : primaryLabel(book)}</span>
                      {!working && <RightOutlined />}
                      {working && (
                        <span className="action-progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
                          <i style={{ width: `${progress}%` }} />
                        </span>
                      )}
                    </Button>
                    {working && <small className="book-job-message">{job?.message || '任务正在启动'} · {progress}%</small>}
                  </div>
                  {!readOnly && <Dropdown
                    trigger={['click']}
                    menu={{
                      items: [
                        {
                          key: 'parse',
                          label: '重新解析教材',
                          disabled: working,
                          onClick: () => confirmForce('重新解析教材？', '现有章节与解析结果会被覆盖。', () => onParse(book.id, true)),
                        },
                        {
                          key: 'extract',
                          label: '重新生成知识树',
                          disabled: working || book.structure_status !== 'confirmed',
                          onClick: () => confirmForce('重新生成知识树？', '现有知识点与关系会被重新计算。', () => onExtractGraph(book.id, true)),
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
