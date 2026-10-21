import React, { useEffect, useState } from 'react';
import { Button, Input, Select } from 'antd';
import type { BoardConnection, BoardSelection, TeachingRelation } from '../api/teachingBoard';
import { DIMENSIONS, DIRECTED, RELATIONS, pageRange, sourceTitle } from './crossbookModel';
import type { ConceptGroup } from './crossbookModel';
import { reflowSource } from './sourceText';
import './ConceptEvidencePane.css';

export interface ConceptEvidencePaneProps {
  topic: string;
  concept: ConceptGroup | null;
  activeEvidenceId?: string;
  onEvidenceChange: (id: string) => void;
  onAdd: (source: BoardSelection) => void;
  onTitleChange: (title: string) => void;
  onNoteChange: (chunkId: string, note: string) => void;
  onDimensionChange: (chunkId: string, dimension: string) => void;
  onRemoveEvidence?: (chunkId: string) => void;
  onCompareWithAnchor: () => void;
  compareDisabledReason?: string;
  onOpenPage: (source: BoardSelection) => void;
  readOnly?: boolean;
  busy?: boolean;
  presenting?: boolean;
  showCompareAction?: boolean;
}

export interface RelationEvidencePaneProps {
  editing: BoardConnection;
  sources: BoardSelection[];
  onChange: (patch: Partial<BoardConnection>) => void;
  onSave: (status: 'draft' | 'confirmed') => void;
  onDelete: () => void;
  onCancel: () => void;
  onOpenPage: (source: BoardSelection) => void;
  readOnly?: boolean;
  busy?: boolean;
  presenting?: boolean;
}

const originLabel: Record<ConceptGroup['kind'], string> = {
  source_heading: '教材小节标题', source_subheading: '教材正文小标题', topic_excerpt: '待命名材料', teacher: '教师讲授标题',
};
const originalPath = (source: BoardSelection) => [...new Set([source.chapter, ...(source.section_path || [])].filter(Boolean))].join(' / ');

export function EvidenceQuote({ source, presenting = false, query = '', compact = false }: { source: BoardSelection; presenting?: boolean; query?: string; compact?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => setExpanded(false), [source.chunk_id, source.quote, presenting]);
  const quote = reflowSource(source.quote || '');
  const limit = compact ? 240 : presenting ? 280 : 320;
  const canExpand = quote.length > limit;
  // Highlight only a literal match. This does not imply the passage supports a conclusion.
  const needle = query.trim();
  const at = needle ? quote.indexOf(needle) : -1;
  const start = !expanded && at > limit / 2 ? Math.max(0, at - Math.floor(limit / 3)) : 0;
  const excerpt = expanded || !canExpand ? quote : `${start ? '…' : ''}${quote.slice(start, start + limit)}${start + limit < quote.length ? '…' : ''}`;
  const parts = needle ? excerpt.split(needle) : [excerpt];
  return <div className="ce-quote-wrap"><blockquote className="ce-quote">{quote ? parts.map((part, index) => <React.Fragment key={index}>{index > 0 && <mark>{needle}</mark>}{part}</React.Fragment>) : '当前材料没有可展示的原文，请打开原页核对。'}</blockquote>
    {canExpand && <button type="button" className="ce-text-button" aria-label={`${expanded ? '收起' : '展开'}${source.textbook_title}的原文摘录`} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '收起这段原文' : '展开这段原文'}</button>}
    {source.quote_truncated && <p className="ce-excerpt-note">此处为原文节选，完整上下文请查看教材原页。</p>}
  </div>;
}

const ConceptEvidencePane: React.FC<ConceptEvidencePaneProps> = ({
  topic, concept, activeEvidenceId, onEvidenceChange, onAdd, onTitleChange, onNoteChange, onDimensionChange, onRemoveEvidence,
  onCompareWithAnchor, compareDisabledReason, onOpenPage, readOnly = false, busy = false, presenting = false, showCompareAction = true,
}) => {
  if (!concept) return <aside className="concept-evidence-pane ce-empty"><span aria-hidden="true">◎</span><h2>先看清一段原文</h2><p>选择材料，查看教材里的目录位置、原文和原页。</p></aside>;
  const original = concept.evidences.find((source) => source.chunk_id === activeEvidenceId || source.id === activeEvidenceId) || concept.selected[0] || concept.evidences[0];
  if (!original) return <aside className="concept-evidence-pane ce-empty"><h2>{concept.title}</h2><p>此知识点尚无可核对的教材证据。</p></aside>;
  const selectedSource = concept.selected.find((source) => source.chunk_id === original.chunk_id);
  const source = selectedSource || original;
  const isSelected = Boolean(selectedSource);
  const teachingTitle = concept.selected.find((item) => item.teaching_title?.trim())?.teaching_title || '';
  const heading = source.source_heading || source.section_path?.slice(-1)[0] || source.chapter;
  return <aside className={`concept-evidence-pane ${presenting ? 'ce-presenting' : ''}`} aria-label="知识点教材证据">
    <header className="ce-pane-heading"><div className="ce-kicker"><span>{presenting ? '课堂原文' : '知识点与教材证据'}</span><span className={isSelected ? 'ce-selected-badge' : 'ce-candidate-badge'}>{isSelected ? '本段已选入' : '检索候选'}</span></div><h2>{concept.title}</h2><p className="ce-book-title">{concept.bookTitle} · {pageRange(source)}</p></header>
    {!presenting && <details className="ce-source-metadata"><summary>原目录与标题依据 · {originLabel[concept.kind]}</summary><div className={`ce-origin ${concept.kind === 'topic_excerpt' ? 'ce-origin-pending' : ''}`}>{originLabel[concept.kind]}</div>{concept.kind === 'topic_excerpt' ? <p className="ce-metadata-note">当前材料来自正文匹配，显示标题用于定位；选入本课后可以补上讲授标题。</p> : concept.kind === 'teacher' && <p className="ce-metadata-note">显示教师填写的讲授标题，教材原目录与原文保持可核对。</p>}<dl><dt>教材原目录</dt><dd>{originalPath(source) || '当前来源未提供完整目录路径'}</dd>{heading && heading !== source.section_path?.slice(-1)[0] && <><dt>来源小标题</dt><dd>{heading}</dd></>}</dl></details>}
    {concept.evidences.length > 1 && <label className="ce-field ce-evidence-picker"><span>本知识点的原文 <small>{concept.evidences.length} 段 · 已选 {concept.selected.length} 段</small></span><Select aria-label="切换本知识点原文" value={source.chunk_id} onChange={onEvidenceChange} options={concept.evidences.map((item, index) => ({ value: item.chunk_id, label: `${index + 1}. ${sourceTitle(item, topic)} · ${pageRange(item)}${concept.selected.some((selected) => selected.chunk_id === item.chunk_id) ? ' · 已选' : ''}` }))} popupMatchSelectWidth /></label>}
    <section className="ce-primary-evidence"><div className="ce-evidence-label"><span>教材原文</span><span>{pageRange(source)}</span></div><EvidenceQuote source={source} presenting={presenting} query={topic} /><Button className="ce-original-page" aria-label={`打开${source.textbook_title}${pageRange(source)}原页`} onClick={() => onOpenPage(source)} disabled={!source.page_start}>打开教材原页 ↗</Button></section>
    {!presenting && <><div className="ce-primary-actions">{showCompareAction && <><Button type="primary" block aria-label="与当前讲授点对照" disabled={busy || Boolean(compareDisabledReason)} onClick={onCompareWithAnchor}>与当前讲授点对照</Button>{compareDisabledReason && <p className="ce-action-hint">{compareDisabledReason}</p>}</>}{!readOnly && <><Button block aria-label={isSelected ? '本段已加入讲授路径' : '将当前段材料加入讲授路径'} disabled={busy || isSelected} onClick={() => onAdd(source)}>{isSelected ? '✓ 本段已加入讲授路径' : '将此段加入讲授路径'}</Button>{isSelected && onRemoveEvidence && <Button className="ce-remove-evidence" type="text" danger aria-label="将当前原文段移出本课及引用它的关系" title="移出此段，同时移除引用它的本课关系" disabled={busy} onClick={() => onRemoveEvidence(source.chunk_id)}>移出此段</Button>}</>}</div>
      {concept.selected.length > 0 && <section className="ce-teaching-notes"><header><h3>本课怎样讲</h3><span>标题属于知识点，备注属于当前段</span></header>{readOnly ? <>{teachingTitle && <p className="ce-saved-title">{teachingTitle}</p>}{isSelected && <><p className="ce-saved-note">{source.note || '本段尚未填写讲授备注。'}</p>{source.dimension && source.dimension !== '未归类' && <small className="ce-read-dimension">{source.dimension}</small>}</>}</> : <><label className="ce-field"><span>讲授标题 <small>本知识点统一使用</small></span><Input aria-label="本知识点讲授标题" maxLength={100} showCount value={teachingTitle} placeholder={concept.title} disabled={busy} onChange={(event) => onTitleChange(event.target.value)} /></label>{isSelected ? <><label className="ce-field"><span>当前这段怎样讲</span><Input.TextArea aria-label="当前原文段的讲授备注" maxLength={1000} showCount autoSize={{ minRows: 3, maxRows: 8 }} value={source.note || ''} placeholder="记录要补充的问题、与上一点的衔接，或提醒学生辨析的条件。" disabled={busy} onChange={(event) => onNoteChange(source.chunk_id, event.target.value)} /></label><details className="ce-dimension"><summary>教学维度 <span>{source.dimension || '未归类'}</span></summary><Select aria-label="当前原文段的教学维度" value={source.dimension || '未归类'} options={DIMENSIONS.map((value) => ({ value, label: value }))} disabled={busy} onChange={(value) => onDimensionChange(source.chunk_id, value)} /></details></> : <p className="ce-unselected-note">当前这段尚未选入本课。选入后可填写本段讲授备注与教学维度。</p>}</>}</section>}
    </>}
  </aside>;
};

export const RelationEvidencePane: React.FC<RelationEvidencePaneProps> = ({ editing, sources, onChange, onSave, onDelete, onCancel, onOpenPage, readOnly = false, busy = false, presenting = false }) => {
  const a = sources.find((source) => source.chunk_id === editing.source_chunk_id);
  const b = sources.find((source) => source.chunk_id === editing.target_chunk_id);
  const directed = DIRECTED.has(editing.relation_type);
  const patch = (value: Partial<BoardConnection>) => onChange({ ...value, status: 'draft' });
  const sameSource = Boolean(a && b && a.chunk_id === b.chunk_id);
  const sameBook = Boolean(a && b && a.textbook_id === b.textbook_id);
  const invalidSides = !a || !b || sameSource || sameBook;
  const sideProblem = !a || !b ? '请选择两侧教材原文。' : sameSource ? '两侧不能使用同一段原文。' : sameBook ? '跨教材关系需要两本不同教材的原文。' : '';
  const reasonProblem = !editing.reason.trim();
  const directionText = editing.relation_type === 'prerequisite' ? 'A 是 B 的前置知识：先理解 A，再讲 B。' : editing.relation_type === 'extends' ? 'A 补充并扩展 B：箭头由补充材料 A 指向被补充的 B。' : '这是对称关系，交换 A / B 不改变关系含义，图中不显示方向箭头。';
  const options = sources.filter((source, at) => sources.findIndex((item) => item.chunk_id === source.chunk_id) === at).map((source) => ({ value: source.chunk_id, label: `${source.textbook_title} / ${sourceTitle(source, '')} · ${pageRange(source)}` }));
  return <aside className={`concept-evidence-pane ce-relation-pane ${presenting ? 'ce-presenting' : ''}`} aria-label="本课关系双侧证据">
    <header className="ce-pane-heading"><div className="ce-kicker"><span>本课教学关系</span><span className={editing.status === 'confirmed' ? 'ce-selected-badge' : 'ce-draft-badge'}>{editing.status === 'confirmed' ? '教师已确认' : '关系草稿'}</span></div><h2>{RELATIONS[editing.relation_type] || '教学关系'}</h2>{!presenting && <p>原文支持什么联系，需要结合适用条件核对。</p>}</header>
    {!presenting && <><div className="ce-relation-controls"><label className="ce-field"><span>关系类型</span><Select aria-label="本课教学关系类型" value={editing.relation_type} options={Object.entries(RELATIONS).map(([value, label]) => ({ value, label }))} disabled={readOnly || busy} onChange={(value: TeachingRelation) => patch({ relation_type: value })} /></label><Button className="ce-swap" aria-label="交换关系两侧原文" disabled={readOnly || busy || (!a && !b)} onClick={() => patch({ source_chunk_id: editing.target_chunk_id, target_chunk_id: editing.source_chunk_id })}>交换 A / B</Button></div><p className={`ce-direction-note ${directed ? 'is-directed' : ''}`}>{directionText}</p></>}
    <div className="ce-relation-sides">{[{ source: a, id: editing.source_chunk_id, side: 'A', field: 'source_chunk_id' }, { source: b, id: editing.target_chunk_id, side: 'B', field: 'target_chunk_id' }].map(({ source, id, side, field }) => <section className="ce-relation-side" key={side}><div className="ce-side-label"><span>{side}</span><strong>{source?.textbook_title || '待选教材原文'}</strong></div>{!presenting && <Select aria-label={`关系${side}侧原文`} value={id || undefined} placeholder="选择教材中的一段原文" options={options} disabled={readOnly || busy} onChange={(value) => patch({ [field]: value })} popupMatchSelectWidth />}{source ? <><h3>{sourceTitle(source, '')}</h3><p className="ce-side-path">{originalPath(source)} · {pageRange(source)}</p><EvidenceQuote source={source} presenting={presenting} /><Button aria-label={`打开关系${side}侧教材原页`} className="ce-original-page" onClick={() => onOpenPage(source)} disabled={!source.page_start}>打开 {side} 侧原页 ↗</Button></> : <p className="ce-source-gap">选择后显示这一侧的教材摘录与原页。</p>}</section>)}</div>
    <section className="ce-relation-reason"><h3>{presenting ? '这两处内容怎样衔接' : '为什么连接，有什么适用条件'}</h3>{readOnly || presenting ? <p className="ce-saved-note">{editing.reason || '尚未说明关系理由，不能据此确认教学联系。'}</p> : <Input.TextArea aria-label="教学关系理由与适用条件" value={editing.reason} maxLength={1000} showCount autoSize={{ minRows: 4, maxRows: 9 }} placeholder="分别说明 A 与 B 回答什么问题；差异由范围、条件还是侧重点造成，以及课堂怎样接着讲。" disabled={busy} onChange={(event) => patch({ reason: event.target.value })} />}</section>
    {!presenting && <><p className="ce-relation-caption">保存的是本课教学关系。两端原文无需预先选入；保存时会一并选入，并由服务器重新核对教材来源。</p>{sideProblem && <p className="ce-validation" role="status">{sideProblem}</p>}{!sideProblem && reasonProblem && !readOnly && <p className="ce-validation" role="status">确认前请补充关系理由与适用条件；暂不完整的判断可以先存为草稿。</p>}
      <div className="ce-relation-actions"><Button aria-label="返回知识点证据" onClick={onCancel} disabled={busy}>返回知识点</Button>{!readOnly && <><Button aria-label="保存本课关系草稿" disabled={busy || invalidSides} loading={busy} onClick={() => onSave('draft')}>保存草稿</Button><Button type="primary" aria-label="教师确认本课教学关系" disabled={busy || invalidSides || reasonProblem} loading={busy} onClick={() => onSave('confirmed')}>确认此关系</Button>{editing.id && <Button className="ce-delete-relation" type="text" danger aria-label="删除本课教学关系" disabled={busy} onClick={onDelete}>删除此关系</Button>}</>}</div></>}
  </aside>;
};

export default ConceptEvidencePane;
