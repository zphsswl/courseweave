import React, { useEffect, useMemo, useState } from 'react';
import { Button, Checkbox, Input, message, Tooltip } from 'antd';
import {
  BookOutlined,
  CheckOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CompassOutlined,
  FileSearchOutlined,
  LoadingOutlined,
  LockOutlined,
  PlayCircleOutlined,
  RedoOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import * as api from '../api/client';
import type { AgentArtifactRow, AgentCitation, AgentRun, ModelStatus, Textbook } from '../types';


interface Props {
  courseId: string;
  courseTitle: string;
  textbooks: Textbook[];
  modelStatus: ModelStatus | null;
  onGoLibrary: () => void;
  readOnly?: boolean;
}

const FOCUS_OPTIONS = ['核心概念', '教材差异', '重点难点', '易混淆点', '课堂提问'];
const ACTIVE_STATUSES = new Set(['pending', 'processing']);

const statusLabel = (status: string) => ({
  pending: '等待执行',
  processing: 'Agent 执行中',
  waiting_user: '等待教师确认',
  completed: '已完成',
  failed: '执行失败',
}[status] || status);

const runTimeLabel = (value?: string | null) => {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
};

const stepIcon = (status: string) => {
  if (status === 'running') return <LoadingOutlined spin />;
  if (status === 'completed') return <CheckOutlined />;
  if (status === 'skipped') return <RightOutlined />;
  if (status === 'waiting') return <LockOutlined />;
  if (status === 'failed') return <CloseCircleOutlined />;
  return <span />;
};

const AgentWorkbench: React.FC<Props> = ({
  courseId,
  courseTitle,
  textbooks,
  modelStatus,
  onGoLibrary,
  readOnly = false,
}) => {
  const [topic, setTopic] = useState('');
  const [goal, setGoal] = useState('');
  const [requirements, setRequirements] = useState<string[]>(['核心概念', '教材差异', '重点难点']);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [currentRun, setCurrentRun] = useState<AgentRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [activeSource, setActiveSource] = useState('');

  const loadRuns = async (selectLatest = false) => {
    try {
      const response = await api.getAgentRuns(courseId);
      setRuns(response.data);
      if (selectLatest || !currentRun || currentRun.course_id !== courseId) {
        setCurrentRun(response.data[0] || null);
      }
    } catch {
      message.error('Agent 任务记录加载失败');
    }
  };

  useEffect(() => {
    const preferred = textbooks
      .filter((book) => ['completed', 'review'].includes(book.graph_status))
      .slice(0, 3)
      .map((book) => book.id);
    setTopic('');
    setGoal('');
    setRequirements(['核心概念', '教材差异', '重点难点']);
    setSelectedIds(preferred.length ? preferred : textbooks.slice(0, 2).map((book) => book.id));
    setCurrentRun(null);
    loadRuns(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  useEffect(() => {
    if (!currentRun || !ACTIVE_STATUSES.has(currentRun.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const response = await api.getAgentRun(currentRun.id);
        setCurrentRun(response.data);
        setRuns((items) => [response.data, ...items.filter((item) => item.id !== response.data.id)]);
      } catch {
        window.clearInterval(timer);
      }
    }, 1800);
    return () => window.clearInterval(timer);
  }, [currentRun?.id, currentRun?.status]);

  useEffect(() => {
    if (!currentRun?.result) return;
    const brief = currentRun.result;
    setTopic(brief.topic || '');
    setGoal(brief.goal || '');
    setRequirements(brief.requirements?.length ? brief.requirements : ['核心概念', '教材差异', '重点难点']);
    const availableIds = new Set(textbooks.map((book) => book.id));
    const historicalScope = (brief.textbook_ids || []).filter((id) => availableIds.has(id));
    if (historicalScope.length) setSelectedIds(historicalScope);
  }, [currentRun?.id, textbooks]);

  const artifact = currentRun?.result?.artifact || null;
  const quality = currentRun?.result?.quality || null;
  const citationMap = useMemo(
    () => new Map((artifact?.citations || []).map((item) => [item.source_id, item])),
    [artifact],
  );
  const activeCitation = citationMap.get(activeSource) || artifact?.citations?.[0] || null;

  useEffect(() => {
    setActiveSource(artifact?.citations?.[0]?.source_id || '');
  }, [artifact?.generated_at]);

  const toggleBook = (bookId: string) => {
    setSelectedIds((current) => {
      if (current.includes(bookId)) return current.filter((id) => id !== bookId);
      if (current.length >= 6) {
        message.info('一次 Agent 任务最多选择 6 本教材，以保证证据质量和生成速度');
        return current;
      }
      return [...current, bookId];
    });
  };

  const toggleRequirement = (value: string) => {
    setRequirements((current) => (
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
    ));
  };

  const startRun = async () => {
    const cleanTopic = topic.trim();
    if (cleanTopic.length < 2) return message.warning('请填写至少两个字的备课主题');
    if (!selectedIds.length) return message.warning('请至少选择一本教材');
    const cleanGoal = goal.trim() || `围绕“${cleanTopic}”生成可追溯的${selectedIds.length > 1 ? '跨教材' : '教材'}备课知识包`;
    setStarting(true);
    try {
      const response = await api.createAgentRun({
        course_id: courseId,
        topic: cleanTopic,
        goal: cleanGoal,
        textbook_ids: selectedIds,
        requirements,
      });
      setCurrentRun(response.data);
      setRuns((items) => [response.data, ...items.filter((item) => item.id !== response.data.id)]);
      message.success('任务已交给备课 Agent');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || 'Agent 任务启动失败');
    } finally {
      setStarting(false);
    }
  };

  const resumeRun = async () => {
    if (!currentRun) return;
    setResuming(true);
    try {
      const response = await api.resumeAgentRun(currentRun.id);
      setCurrentRun(response.data);
      message.success('教师确认已收到，Agent 继续执行');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '请先完成章节确认');
    } finally {
      setResuming(false);
    }
  };

  const retryRun = async () => {
    if (!currentRun) return;
    setResuming(true);
    try {
      const response = await api.retryAgentRun(currentRun.id);
      setCurrentRun(response.data);
      message.success('任务已重新进入队列');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '当前任务无法重试');
    } finally {
      setResuming(false);
    }
  };

  const sourceChips = (rows: AgentArtifactRow[]) => (
    rows.flatMap((row) => row.source_ids || []).filter((id, index, all) => all.indexOf(id) === index).map((id) => (
      <button key={id} className={activeSource === id ? 'active' : ''} onClick={() => setActiveSource(id)}>{id}</button>
    ))
  );

  const renderCitation = (citation: AgentCitation | null) => {
    if (!citation) return <div className="agent-evidence-empty"><FileSearchOutlined /><span>选择结论后的来源编号查看教材原文</span></div>;
    const page = citation.page_start === citation.page_end
      ? `第 ${citation.page_start} 页`
      : `第 ${citation.page_start}–${citation.page_end} 页`;
    return (
      <div className="agent-evidence-card">
        <div className="agent-evidence-id"><span>{citation.source_id}</span><small>VERIFIED SOURCE</small></div>
        <h4>《{citation.textbook}》</h4>
        <p className="agent-evidence-location">{citation.chapter} · {page}</p>
        {!!citation.section_path?.length && <p className="agent-evidence-path">{citation.section_path.join(' / ')}</p>}
        <blockquote>{citation.quote}</blockquote>
        <footer><SafetyCertificateOutlined /> 原文与物理页码已绑定</footer>
      </div>
    );
  };

  return (
    <section className="agent-page">
      <header className="agent-hero">
        <div className="agent-hero-copy">
          <span className="agent-orbit"><CompassOutlined /></span>
          <div>
            <small>COURSEWEAVE · AI 备课助手</small>
            <h1>输入备课主题，生成可核对的跨教材方案</h1>
            <p>自动整理核心知识、教材差异、讲解顺序和课堂问题；每条结论都附教材原文与页码，方便直接核对。</p>
          </div>
        </div>
        <div className="agent-runtime">
          <span className={modelStatus?.availability === 'available' ? 'online' : ''} />
          <div><small>MODEL RUNTIME</small><strong>{modelStatus?.availability === 'available' ? '模型可用' : '证据降级模式'}</strong></div>
          <i />
          <div><small>KNOWLEDGE SPACE</small><strong>{courseTitle}</strong></div>
        </div>
      </header>

      <div className="agent-layout">
        <aside className="agent-brief-panel">
          <div className="agent-panel-label"><span>01</span><div><strong>任务简报</strong><small>告诉 Agent 最终要交付什么</small></div></div>
          <label className="agent-field">
            <span>备课主题</span>
            <Input value={topic} onChange={(event) => setTopic(event.target.value)} maxLength={160} placeholder="例如：动脉粥样硬化" />
          </label>
          <label className="agent-field">
            <span>这次要解决什么 <small>可选</small></span>
            <Input.TextArea value={goal} onChange={(event) => setGoal(event.target.value)} maxLength={500} autoSize={{ minRows: 3, maxRows: 5 }} placeholder="例如：比较不同教材的病变分期，并生成 45 分钟课堂讲解顺序" />
          </label>
          <div className="agent-field">
            <span>关注内容</span>
            <div className="agent-focus-grid">
              {FOCUS_OPTIONS.map((item) => (
                <button key={item} className={requirements.includes(item) ? 'active' : ''} onClick={() => toggleRequirement(item)}>
                  {requirements.includes(item) && <CheckOutlined />}{item}
                </button>
              ))}
            </div>
          </div>
          <div className="agent-field agent-book-field">
            <span>证据范围 <small>{selectedIds.length} 本</small></span>
            <div className="agent-book-list">
              {textbooks.length ? textbooks.map((book) => {
                const ready = ['completed', 'review'].includes(book.graph_status);
                return (
                  <button key={book.id} className={selectedIds.includes(book.id) ? 'selected' : ''} onClick={() => toggleBook(book.id)}>
                    <Checkbox checked={selectedIds.includes(book.id)} tabIndex={-1} />
                    <span><strong>{book.title}</strong><small>{ready ? '知识树已就绪' : 'Agent 将检查并补齐'}</small></span>
                    <BookOutlined />
                  </button>
                );
              }) : <div className="agent-no-books">当前空间还没有教材</div>}
            </div>
          </div>
          <Button className="agent-run-button" type="primary" size="large" icon={<PlayCircleOutlined />} loading={starting} disabled={readOnly || !textbooks.length} onClick={startRun} block>
            {readOnly ? '在线查看已完成示例' : '交给 Agent 生成'}
          </Button>
          <p className="agent-guard-note"><LockOutlined /> {readOnly ? '公开作品不执行付费任务；右侧可查看完整轨迹、成果与证据。' : '章节结构和证据冲突仍由教师确认，Agent 不会自动发布。'}</p>
        </aside>

        <main className="agent-run-panel">
          <div className="agent-run-head">
            <div className="agent-panel-label"><span>02</span><div><strong>执行轨迹</strong><small>基于课程状态动态选择工具</small></div></div>
            {!!runs.length && (
              <select value={currentRun?.id || ''} onChange={(event) => setCurrentRun(runs.find((item) => item.id === event.target.value) || null)} aria-label="选择 Agent 历史任务">
                {runs.map((run) => {
                  const time = runTimeLabel(run.result?.created_at || run.updated_at || run.created_at);
                  return <option key={run.id} value={run.id}>{run.result?.topic || '未命名任务'} · {statusLabel(run.status)}{time ? ` · ${time}` : ''}</option>;
                })}
              </select>
            )}
          </div>

          {!currentRun ? (
            <div className="agent-empty-run">
              <span><ThunderboltOutlined /></span>
              <h2>准备好后，Agent 会在这里工作</h2>
              <p>它不会盲目重跑全部流程，而是先观察课程状态，再决定复用索引、补齐知识树或暂停等待确认。</p>
              <div><i>1</i><span><strong>Observe</strong><small>检查教材与索引状态</small></span><i>2</i><span><strong>Act</strong><small>按需调用已有工具</small></span><i>3</i><span><strong>Verify</strong><small>核验引用并自动补检索</small></span></div>
            </div>
          ) : (
            <>
              <div className={`agent-run-status ${currentRun.status}`}>
                <div>
                  <small>{statusLabel(currentRun.status)}</small>
                  <h2>{currentRun.result?.topic || '备课 Agent 任务'}</h2>
                  <p>{currentRun.message || currentRun.result?.goal}</p>
                </div>
                <strong>{Math.round(currentRun.progress || 0)}<small>%</small></strong>
                <span><i style={{ width: `${Math.max(2, currentRun.progress || 0)}%` }} /></span>
              </div>

              {currentRun.status === 'waiting_user' && currentRun.result?.approval && (
                <div className="agent-approval-card">
                  <span><LockOutlined /></span>
                  <div><small>HUMAN CHECKPOINT</small><h3>{currentRun.result.approval.title}</h3><p>{currentRun.result.approval.message}</p>
                    <ul>{currentRun.result.approval.textbooks.map((book) => <li key={book.id}>{book.title}</li>)}</ul>
                  </div>
                  <div><Button onClick={onGoLibrary}>去确认章节</Button>{!readOnly && <Button type="primary" loading={resuming} onClick={resumeRun}>已确认，继续</Button>}</div>
                </div>
              )}

              {currentRun.status === 'failed' && (
                <div className="agent-failure-card"><CloseCircleOutlined /><div><strong>任务没有完成</strong><p>{currentRun.error || '可以在问题处理后重新执行。'}</p></div>{!readOnly && <Button icon={<RedoOutlined />} loading={resuming} onClick={retryRun}>重新执行</Button>}</div>
              )}

              <div className="agent-step-list">
                {(currentRun.result?.plan || []).map((step, index) => (
                  <article key={step.id} className={`agent-step ${step.status}`}>
                    <div className="agent-step-rail"><span>{stepIcon(step.status)}</span>{index < currentRun.result.plan.length - 1 && <i />}</div>
                    <div><div><strong>{step.title}</strong><Tooltip title={step.tool}><em><ToolOutlined /> {step.tool}</em></Tooltip></div><p>{step.message || step.description}</p></div>
                  </article>
                ))}
              </div>
              {!!currentRun.result?.tools_used?.length && <div className="agent-tool-foot"><ToolOutlined /><span>本次已调用</span>{currentRun.result.tools_used.map((tool) => <code key={tool}>{tool}</code>)}</div>}
            </>
          )}
        </main>

        <aside className="agent-output-panel">
          <div className="agent-panel-label"><span>03</span><div><strong>交付成果</strong><small>结论、证据和质量门禁放在一起</small></div></div>
          {!artifact ? (
            <div className="agent-output-empty"><FileSearchOutlined /><h3>等待 Agent 交付</h3><p>完成后这里会出现教学目标、讲解顺序、教材差异、课堂问题和逐条原文证据。</p></div>
          ) : (
            <div className="agent-artifact">
              <div className="agent-artifact-title">
                <div><small>{artifact.generation_method === 'llm_grounded' ? 'MODEL + VERIFIED EVIDENCE' : 'EVIDENCE FALLBACK'}</small><h2>{artifact.title}</h2></div>
                {quality && <span className={quality.status}><strong>{quality.score}</strong><small>质量分</small></span>}
              </div>
              {quality && <div className="agent-quality-strip">{quality.checks.map((check) => <div key={check.id} className={check.passed ? 'passed' : ''}><span>{check.passed ? <CheckOutlined /> : <ClockCircleOutlined />}</span><small>{check.label}</small><strong>{check.value}</strong></div>)}</div>}
              <section className="agent-summary"><small>主题概览</small><p>{artifact.executive_summary}</p></section>
              {!!artifact.teaching_objectives.length && <section><small>教学目标</small><ol className="agent-objectives">{artifact.teaching_objectives.map((item, index) => <li key={`${item}-${index}`}><span>{index + 1}</span>{item}</li>)}</ol></section>}
              {!!artifact.knowledge_sequence.length && <section><small>讲解顺序</small><div className="agent-sequence">{artifact.knowledge_sequence.map((item, index) => <article key={`${item.title}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{item.title}</strong><p>{item.explanation}</p><footer>{sourceChips([item])}</footer></div></article>)}</div></section>}
              {!!artifact.common_ground.length && <section><small>教材共同结论</small><div className="agent-claim-list">{artifact.common_ground.map((item, index) => <article key={index}><CheckOutlined /><div><p>{item.claim}</p><footer>{sourceChips([item])}</footer></div></article>)}</div></section>}
              {!!artifact.textbook_differences.length && <section><small>教材侧重点与差异</small><div className="agent-difference-list">{artifact.textbook_differences.map((item, index) => <article key={index}><strong>{item.textbook}</strong><p>{item.perspective}</p><footer>{sourceChips([item])}</footer></article>)}</div></section>}
              {!!artifact.misconceptions.length && <section><small>易混淆点</small><div className="agent-misconception-list">{artifact.misconceptions.map((item, index) => <article key={index}><strong>{item.issue}</strong><p>{item.guidance}</p><footer>{sourceChips([item])}</footer></article>)}</div></section>}
              {!!artifact.classroom_questions.length && <section><small>课堂提问</small><ul className="agent-question-list">{artifact.classroom_questions.map((item, index) => <li key={`${item}-${index}`}><span>Q{index + 1}</span>{item}</li>)}</ul></section>}
              {!!artifact.unresolved_questions.length && <section className="agent-unresolved"><small>需要教师确认</small>{artifact.unresolved_questions.map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}</section>}
              <section className="agent-source-section"><div><small>证据档案</small><span>{artifact.citations.length} 条来源</span></div><div className="agent-source-tabs">{artifact.citations.map((item) => <button key={item.source_id} className={activeCitation?.source_id === item.source_id ? 'active' : ''} onClick={() => setActiveSource(item.source_id)}>{item.source_id}</button>)}</div>{renderCitation(activeCitation)}</section>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
};

export default AgentWorkbench;
