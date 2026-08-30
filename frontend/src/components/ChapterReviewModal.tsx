import React, { useEffect, useState } from 'react';
import { Alert, Input, Modal, Select, Spin, message } from 'antd';
import type { Chapter, Textbook } from '../types';
import * as api from '../api/client';

interface Props {
  textbook: Textbook | null;
  onClose: () => void;
  onConfirmed: () => void;
}

const ChapterReviewModal: React.FC<Props> = ({ textbook, onClose, onConfirmed }) => {
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!textbook) return;
    setLoading(true);
    api.getChapters(textbook.id)
      .then((response) => setChapters(response.data))
      .catch(() => message.error('读取章节结构失败'))
      .finally(() => setLoading(false));
  }, [textbook]);

  const patchChapter = (id: string, values: Partial<Chapter>) => {
    setChapters((current) => current.map((chapter) => chapter.id === id ? { ...chapter, ...values } : chapter));
  };

  const save = async () => {
    if (!textbook || chapters.some((chapter) => !chapter.title.trim())) return message.warning('章节标题不能为空');
    setSaving(true);
    try {
      await api.updateChapterStructure(textbook.id, chapters, true);
      message.success('章节结构已确认，可以开始知识抽取');
      onConfirmed();
      onClose();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '保存章节结构失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      width={720}
      open={Boolean(textbook)}
      title={`核对章节结构 · ${textbook?.title || ''}`}
      okText="确认结构并解锁抽取"
      cancelText="稍后处理"
      onCancel={onClose}
      onOk={save}
      confirmLoading={saving}
    >
      <Alert
        type="info"
        showIcon
        message="知识点会沿用这里的章节层级与页码。请先纠正标题和层级，再开始抽取。"
        style={{ marginBottom: 12 }}
      />
      {loading ? <div className="chapter-review-loading"><Spin /></div> : (
        <div className="chapter-review-list">
          {chapters.map((chapter, index) => (
            <div className="chapter-review-row" key={chapter.id}>
              <span className="chapter-order">{String(index + 1).padStart(2, '0')}</span>
              <Input value={chapter.title} onChange={(event) => patchChapter(chapter.id, { title: event.target.value })} />
              <Select
                value={chapter.level || 1}
                onChange={(level) => patchChapter(chapter.id, { level })}
                options={[1, 2, 3, 4].map((level) => ({ value: level, label: `L${level}` }))}
              />
              <span className="chapter-pages">P.{chapter.page_start}–{chapter.page_end}</span>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
};

export default ChapterReviewModal;
