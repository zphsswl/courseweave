import type { Chapter, Job, Textbook } from '../types';

export interface TextbookWorkflow {
  label: string;
  tone: 'working' | 'next' | 'review' | 'ready' | 'error';
  action: 'parse' | 'review' | 'read' | 'wait';
  actionLabel: string;
  readable: boolean;
  processing: boolean;
  progress: number | null;
  detail: string;
}

/** The primary action follows the teacher's next step, independently of graph jobs. */
export function textbookWorkflow(book: Textbook, job?: Job, readOnly = false): TextbookWorkflow {
  const activeJob = job && ['pending', 'processing'].includes(job.status) ? job : undefined;
  const readable = book.parse_status === 'completed';
  const parsing = book.parse_status === 'processing' || activeJob?.type === 'parse';
  const processing = Boolean(activeJob || parsing || book.graph_status === 'processing');
  const progress = activeJob && activeJob.total > 0
    ? Math.max(0, Math.min(100, Math.round((activeJob.progress / activeJob.total) * 100))) : null;
  const base = { readable, processing, progress, detail: '' };
  if (book.parse_status === 'failed' || (job?.type === 'parse' && job.status === 'failed')) return { ...base, processing: false, progress: null, label: '解析失败', tone: 'error', action: readOnly ? 'wait' : 'parse', actionLabel: readOnly ? '暂不可阅读' : '重试解析', detail: job?.error || job?.message || '本次未能解析正文，请重新尝试' };
  if (parsing) return { ...base, label: '正在解析教材', tone: 'working', action: 'wait', actionLabel: '正在解析', detail: activeJob?.message || '完成后可阅读正文并核对目录' };
  if (!readable) return { ...base, label: '尚未解析', tone: 'next', action: readOnly ? 'wait' : 'parse', actionLabel: readOnly ? '暂不可阅读' : '解析教材', detail: '先解析正文，再核对目录与原页' };
  const needsReview = book.structure_status !== 'confirmed';
  const action = needsReview && !readOnly ? 'review' : 'read';
  const actionLabel = action === 'review' ? '核对章节' : '阅读教材';
  if (needsReview) return { ...base, action, actionLabel, label: '正文可读 · 目录待核对', tone: 'review', detail: '核对目录标题、层级和页码后，可用于生成备课材料' };
  if ((job?.status === 'failed' && job.type === 'extract_graph') || book.graph_status === 'failed') {
    return { ...base, processing: false, progress: null, action, actionLabel, label: '正文可读 · 知识整理未完成', tone: 'error', detail: job?.error || job?.message || '可以继续阅读；需要时可在更多操作中重试知识整理' };
  }
  if (processing) return { ...base, action, actionLabel, label: '正文可读 · 正在整理知识', tone: 'working', detail: activeJob?.message || '整理期间可以继续阅读教材' };
  return { ...base, action, actionLabel, label: '可用于备课', tone: 'ready', detail: '' };
}

/** Hierarchy is derived from the displayed order; stale parent IDs never survive a level edit. */
export function normalizedChapters(chapters: Chapter[]): Chapter[] {
  const stack: Chapter[] = [];
  return chapters.map((chapter, index) => {
    const level = chapter.level || 1;
    while (stack.length && (stack[stack.length - 1].level || 1) >= level) stack.pop();
    const next = { ...chapter, title: chapter.title.trim(), level, order_index: index, parent_id: stack[stack.length - 1]?.id || '' };
    stack.push(next);
    return next;
  });
}

export function chapterValidation(chapters: Chapter[], totalPages: number): string[] {
  if (!chapters.length) return ['没有可核对的章节，请重新读取或解析教材'];
  const issues: string[] = [];
  chapters.forEach((chapter, index) => {
    const prefix = `第 ${index + 1} 项`;
    if (!chapter.title.trim()) issues.push(`${prefix}：请填写目录标题`);
    if (!Number.isInteger(chapter.page_start) || !Number.isInteger(chapter.page_end) || chapter.page_start < 1 || chapter.page_end < chapter.page_start) issues.push(`${prefix}：起止页须为正整数，结束页不能早于起始页`);
    else if (totalPages > 0 && chapter.page_end > totalPages) issues.push(`${prefix}：页码超出本教材的 ${totalPages} 页`);
    const level = chapter.level || 1;
    if (level < 1 || level > 6 || !Number.isInteger(level)) issues.push(`${prefix}：请选择有效的目录层级`);
    else if ((index === 0 && level !== 1) || (index > 0 && level > (chapters[index - 1].level || 1) + 1)) issues.push(`${prefix}：目录层级不能跳级，请先设置上一级目录`);
    if (index > 0 && chapter.page_start < chapters[index - 1].page_start) issues.push(`${prefix}：起始页早于上一项目录，请核对教材顺序`);
  });
  const byId = new Map(normalizedChapters(chapters).map((chapter) => [chapter.id, chapter]));
  byId.forEach((chapter) => {
    const parent = byId.get(chapter.parent_id || '');
    if (parent && (chapter.page_start < parent.page_start || chapter.page_end > parent.page_end)) issues.push(`“${chapter.title}”：页码范围须位于上一级“${parent.title}”范围内`);
  });
  return issues;
}
