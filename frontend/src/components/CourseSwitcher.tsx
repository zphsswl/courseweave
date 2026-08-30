import React, { useMemo, useState } from 'react';
import { Button, Input, Modal, Popover, Space, Typography, message } from 'antd';
import { DeleteOutlined, DownOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons';
import type { Course } from '../types';
import * as api from '../api/client';

const { TextArea } = Input;

interface Props {
  courses: Course[];
  selectedCourse: Course | null;
  onSelect: (courseId: string) => void;
  onCreated: (course: Course) => void;
  onDeleted: (courseId: string) => void;
  readOnly?: boolean;
}

const CourseSwitcher: React.FC<Props> = ({ courses, selectedCourse, onSelect, onCreated, onDeleted, readOnly = false }) => {
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Course | null>(null);
  const [query, setQuery] = useState('');
  const [title, setTitle] = useState('');
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');

  const filteredCourses = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    if (!keyword) return courses;
    return courses.filter((course) => (
      course.title.toLocaleLowerCase().includes(keyword)
      || course.subject?.toLocaleLowerCase().includes(keyword)
    ));
  }, [courses, query]);

  const create = async () => {
    if (!title.trim()) return message.warning('请填写空间名称');
    setSaving(true);
    try {
      const result = await api.createCourse({
        title: title.trim(),
        subject: subject.trim(),
        description: description.trim(),
        default_granularity: 'core',
      });
      onCreated(result.data);
      setCreateOpen(false);
      setSelectorOpen(false);
      setTitle('');
      setSubject('');
      setDescription('');
      message.success('知识空间已创建');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '知识空间创建失败');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.deleteCourse(deleteTarget.id);
      onDeleted(deleteTarget.id);
      setDeleteTarget(null);
      message.success('知识空间已删除');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '知识空间删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const selector = (
    <div className="space-menu">
      <div className="space-menu-head">
        <div><strong>知识空间</strong><span>{courses.length} 个</span></div>
        {!readOnly && <Button type="text" size="small" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建</Button>}
      </div>
      {courses.length > 5 && (
        <Input
          className="space-search"
          allowClear
          prefix={<SearchOutlined />}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索空间"
        />
      )}
      <div className="space-list" role="listbox" aria-label="知识空间列表">
        {filteredCourses.map((course) => (
          <div className={`space-option ${selectedCourse?.id === course.id ? 'active' : ''}`} key={course.id}>
            <button
              className="space-option-main"
              role="option"
              aria-selected={selectedCourse?.id === course.id}
              onClick={() => {
                onSelect(course.id);
                setSelectorOpen(false);
                setQuery('');
              }}
            >
              <span className="space-option-mark">{course.title.slice(0, 1)}</span>
              <span>
                <strong>{course.title}</strong>
                <small>{course.textbook_count || 0} 本教材{course.subject ? ` · ${course.subject}` : ''}</small>
              </span>
            </button>
            {!readOnly && course.id !== 'course_default' && (
              <button className="space-delete" aria-label={`删除${course.title}`} onClick={() => setDeleteTarget(course)}>
                <DeleteOutlined />
              </button>
            )}
          </div>
        ))}
        {filteredCourses.length === 0 && <div className="space-no-result">没有匹配的知识空间</div>}
      </div>
      <div className="space-menu-foot">{readOnly ? '在线示例为只读模式，可切换查看已有空间' : '默认空间不可删除；其他空间删除前会再次确认'}</div>
    </div>
  );

  return (
    <>
      <Popover
        content={selector}
        trigger="click"
        placement="bottomLeft"
        arrow={false}
        open={selectorOpen}
        onOpenChange={setSelectorOpen}
        overlayClassName="space-popover"
      >
        <button className="course-picker" aria-label="切换知识空间">
          <span className="course-picker-copy">
            <small>知识空间</small>
            <strong>{selectedCourse?.title || '选择空间'}</strong>
          </span>
          <span className="course-picker-count">{selectedCourse?.textbook_count || 0} 本</span>
          <DownOutlined />
        </button>
      </Popover>

      <Modal
        title="创建课程知识空间"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={create}
        confirmLoading={saving}
        okText="创建并进入"
        cancelText="取消"
      >
        <Space direction="vertical" size={14} style={{ width: '100%', paddingTop: 10 }}>
          <div>
            <Typography.Text strong>空间名称</Typography.Text>
            <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例：现代教育技术导论" maxLength={120} />
          </div>
          <div>
            <Typography.Text strong>学科</Typography.Text>
            <Input value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="例：教育学" maxLength={120} />
          </div>
          <div>
            <Typography.Text strong>课程目标</Typography.Text>
            <TextArea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} placeholder="说明面向的学习者与教学目标" maxLength={2000} />
          </div>
        </Space>
      </Modal>

      <Modal
        title={`删除“${deleteTarget?.title || ''}”？`}
        open={Boolean(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
        onOk={remove}
        confirmLoading={deleting}
        okText="确认删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <p className="space-delete-warning">
          删除后该空间及其 {deleteTarget?.textbook_count || 0} 本教材将不再显示。为避免误操作，底层数据会保留为归档状态。
        </p>
      </Modal>
    </>
  );
};

export default CourseSwitcher;
