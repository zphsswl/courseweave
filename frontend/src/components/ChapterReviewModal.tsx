import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Input, InputNumber, Modal, Select, Spin, message } from 'antd';
import { FileImageOutlined } from '@ant-design/icons';
import type { Chapter, Textbook } from '../types';
import * as api from '../api/client';
import SourcePageViewer from './SourcePageViewer';
import { chapterValidation, normalizedChapters } from './textbookWorkflow';
import './Teaching.css';

interface Props {
  textbook: Textbook | null;
  onClose: () => void;
  onConfirmed: () => void;
}

const ChapterReviewModal: React.FC<Props> = ({ textbook, onClose, onConfirmed }) => {
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [page, setPage] = useState(1);
  const [activeId, setActiveId] = useState('');
  const [showValidation, setShowValidation] = useState(false);
  const hasPdf = textbook?.format.toLowerCase() === 'pdf';
  // The server supplies this capability; absence never grants page-range editing.
  const rangeCapability = textbook as (Textbook & { chapter_range_editable?: boolean; chapter_range_edit_reason?: string }) | null;
  const rangesEditable = rangeCapability?.chapter_range_editable === true;
  const issues = useMemo(() => chapterValidation(chapters, textbook?.total_pages || 0), [chapters, textbook?.total_pages]);

  useEffect(() => {
    if (!textbook) return;
    let active = true;
    setLoading(true); setError(''); setChapters([]); setActiveId(''); setPage(1); setShowValidation(false);
    api.getChapters(textbook.id)
      .then(({ data }) => { if (active) { setChapters(data); setActiveId(data[0]?.id || ''); setPage(data[0]?.page_start || 1); } })
      .catch(() => { if (active) setError('章节读取失败，请重新加载后再确认。'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [textbook?.id, retry]);

  const patchChapter = (id: string, values: Partial<Chapter>) => {
    setChapters((current) => current.map((chapter) => chapter.id === id ? { ...chapter, ...values } : chapter));
  };

  const save = async () => {
    if (!textbook || loading || saving || error) return;
    setShowValidation(true);
    if (issues.length) return message.warning('请先修正标出的目录问题');
    setSaving(true);
    try {
      await api.updateChapterStructure(textbook.id, normalizedChapters(chapters), true);
      message.success('目录已核对，可以继续备课');
      onConfirmed();
      onClose();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '保存目录失败，请检查后重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      width={hasPdf ? 1160 : 820}
      open={Boolean(textbook)}
      title={`核对章节结构 · ${textbook?.title || ''}`}
      className="chapter-review-modal"
      okText="保存并确认目录"
      cancelText="稍后处理"
      onCancel={() => { if (!saving) onClose(); }}
      onOk={save}
      confirmLoading={saving}
      okButtonProps={{ disabled: loading || Boolean(error) || !chapters.length }}
      cancelButtonProps={{ disabled: saving }}
      maskClosable={!saving}
      keyboard={!saving}
    >
      <p className="chapter-review-intro">对照原页检查目录标题、层级和文件页序。一级目录包含其下的小节；同一页可以是前一章结尾和后一章开头。</p>
      {error && <Alert type="error" showIcon message={error} action={<Button onClick={() => setRetry((value) => value + 1)}>重新加载</Button>} />}
      {showValidation && !!issues.length && <Alert className="chapter-review-issues" type="error" showIcon message={`有 ${issues.length} 项需要修正`} description={<ul>{issues.slice(0, 6).map((issue) => <li key={issue}>{issue}</li>)}{issues.length > 6 && <li>其余问题会在修正后继续显示。</li>}</ul>} />}
      {loading ? <div className="chapter-review-loading"><Spin /> 正在读取目录…</div> : !error && (
        <div className={`chapter-review-layout ${hasPdf ? 'with-original' : ''}`}>
          <div className="chapter-review-edit-column">
            {!rangesEditable && <p className="chapter-range-note">{rangeCapability?.chapter_range_edit_reason || '页码范围目前不可编辑。可继续核对原页并修改标题、层级。'}</p>}
            <div className="chapter-review-list">
              {chapters.map((chapter, index) => (
                <article className={`chapter-review-entry ${activeId === chapter.id ? 'is-active' : ''}`} key={chapter.id}>
                  <header><span className="chapter-order">{String(index + 1).padStart(2, '0')}</span><label><span>目录标题</span><Input aria-label={`第 ${index + 1} 项目录标题`} value={chapter.title} disabled={saving} maxLength={300} onChange={(event) => patchChapter(chapter.id, { title: event.target.value })} /></label></header>
                  <div className="chapter-review-fields">
                    <label><span>目录层级</span><Select aria-label={`第 ${index + 1} 项目录层级`} value={chapter.level || 1} disabled={saving} onChange={(level) => patchChapter(chapter.id, { level })} options={['一级 · 章 / 单元', '二级 · 节', '三级 · 小节', '四级 · 条目', '五级 · 子条目', '六级 · 细目'].map((label, at) => ({ value: at + 1, label }))} /></label>
                    <label className="chapter-page-range"><span>{hasPdf ? 'PDF 文件页序' : '文件页序'}</span><div><InputNumber aria-label={`第 ${index + 1} 项起始页`} min={1} max={textbook?.total_pages || undefined} precision={0} value={chapter.page_start} disabled={saving || !rangesEditable} onChange={(value) => patchChapter(chapter.id, { page_start: value ?? 0 })} /><span>—</span><InputNumber aria-label={`第 ${index + 1} 项结束页`} min={1} max={textbook?.total_pages || undefined} precision={0} value={chapter.page_end} disabled={saving || !rangesEditable} onChange={(value) => patchChapter(chapter.id, { page_end: value ?? 0 })} /></div></label>
                    {hasPdf && <Button icon={<FileImageOutlined />} disabled={saving} className="chapter-open-page" onClick={() => { setActiveId(chapter.id); setPage(Math.max(1, Math.min(textbook?.total_pages || chapter.page_start || 1, chapter.page_start || 1))); }}>核对原页</Button>}
                  </div>
                </article>
              ))}
              {!chapters.length && <p className="chapter-range-note">当前没有可核对的目录，请先重新解析教材。</p>}
            </div>
          </div>
          {hasPdf && textbook && chapters.length > 0 && <SourcePageViewer textbookId={textbook.id} title={textbook.title} page={page} totalPages={textbook.total_pages} onPageChange={setPage} />}
        </div>
      )}
    </Modal>
  );
};

export default ChapterReviewModal;
