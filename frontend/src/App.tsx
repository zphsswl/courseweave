import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Drawer, Dropdown, Upload, message } from 'antd';
import {
  BookOutlined,
  BranchesOutlined,
  CompassOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import CourseSwitcher from './components/CourseSwitcher';
import TextbookPanel from './components/TextbookPanel';
import TeachingWorkspace from './components/TeachingWorkspace';
import TeachingBridge from './components/CrossTextbookStudio';
import type { AgentLessonContext } from './api/lessonAgent';
import { getLessonRuns } from './api/lessonAgent';
import { readLocal, writeLocal } from './api/teaching';
import ModelAvailabilityBadge from './components/ModelAvailabilityBadge';
import * as api from './api/client';
import type {
  Course,
  Job,
  BenchmarkResult,
  ModelStatus,
  RagStatus,
  Textbook,
  Citation,
} from './types';
import './App.css';
import { useTextbookJobs } from './components/useTextbookJobs';

const FloatingRagAssistant = React.lazy(() => import('./components/FloatingRagAssistant'));
const BenchmarkPanel = React.lazy(() => import('./components/BenchmarkPanel'));
const AgentWorkbench = React.lazy(() => import('./components/AgentWorkbench'));
const LessonPresenter = React.lazy(() => import('./components/LessonPresenter'));

type Workspace = 'library' | 'tree' | 'compare' | 'agent' | 'lesson';

const initialWorkspace = () => {
  const saved = readLocal<{ course: string; book: string; view: Workspace; run?: string }>('courseweave:workspace', { course: 'course_default', book: '', view: 'library' });
  const params = new URLSearchParams(window.location.search);
  const view = params.get('view') || saved.view;
  return { course: params.get('course') || saved.course, book: params.get('book') || saved.book, run: params.get('run') || saved.run || '', view: (['tree', 'compare', 'agent', 'lesson'].includes(view) ? view : 'library') as Workspace };
};

const App: React.FC = () => {
  const [initial] = useState(initialWorkspace);
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState(initial.course);
  const [textbooks, setTextbooks] = useState<Textbook[]>([]);
  const [textbooksLoading, setTextbooksLoading] = useState(true);
  const [workspace, setWorkspace] = useState<Workspace>(initial.view);
  const [selectedTextbook, setSelectedTextbook] = useState<Textbook | null>(null);
  const [compareQuery, setCompareQuery] = useState('');
  const [compareBookIds, setCompareBookIds] = useState<string[]>([]);
  const [agentContext, setAgentContext] = useState<AgentLessonContext | undefined>(() => readLocal<AgentLessonContext | undefined>(`courseweave:current-preparation:${initial.course}`, undefined));
  const [lessonRunId, setLessonRunId] = useState(initial.run);
  const [agentRunId, setAgentRunId] = useState(initial.view === 'agent' ? initial.run : '');
  const [recentLesson, setRecentLesson] = useState<{ id: string; title: string } | null>(null);
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null);
  const [ragBuilding, setRagBuilding] = useState(false);
  const [ragOpen, setRagOpen] = useState(false);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [modelChecking, setModelChecking] = useState(false);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [benchmarkResults, setBenchmarkResults] = useState<BenchmarkResult[]>([]);
  const [benchmarkLoading, setBenchmarkLoading] = useState(false);
  const [publicDemoReadOnly, setPublicDemoReadOnly] = useState(false);
  const textbookRequest = useRef(0);
  const crossPrepare = useRef<(() => void) | null>(null);
  const registerCrossPrepare = useCallback((handler: (() => void) | null) => { crossPrepare.current = handler; }, []);

  const selectedCourse = useMemo(
    () => courses.find((course) => course.id === selectedCourseId) || null,
    [courses, selectedCourseId],
  );
  const pendingEvidenceCount = agentContext?.collectedEvidence ? Array.isArray(agentContext.collectedEvidence) ? agentContext.collectedEvidence.length : 1 : 0;
  const preparationSourceCount = new Set([...(agentContext?.selectedChunkIds || []), ...(agentContext?.supplementalChunkIds || [])]).size;
  const preparationScope = pendingEvidenceCount ? `${pendingEvidenceCount} 段待合并原文` : agentContext?.sectionId ? '已选小节' : preparationSourceCount ? `${preparationSourceCount} 段原文` : `${agentContext?.textbookIds?.length || 0} 本教材范围`;

  const changeCourse = useCallback((id: string) => {
    setWorkspace('library'); setSelectedTextbook(null); setCompareQuery(''); setCompareBookIds([]);
    setAgentContext(readLocal<AgentLessonContext | undefined>(`courseweave:current-preparation:${id}`, undefined));
    setAgentRunId(''); setLessonRunId(''); setSelectedCourseId(id);
  }, []);

  const handleCourseDeleted = useCallback((courseId: string) => {
    setCourses((current) => {
      const remaining = current.filter((course) => course.id !== courseId);
      if (selectedCourseId === courseId) {
        changeCourse(remaining.find((course) => course.id === 'course_default')?.id || remaining[0]?.id || 'course_default');
      }
      return remaining;
    });
  }, [selectedCourseId, changeCourse]);

  const loadCourses = useCallback(async () => {
    try {
      const response = await api.getCourses();
      setCourses(response.data);
      if (response.data.length) {
        const current = response.data.find((course) => course.id === selectedCourseId);
        const preferred = [...response.data].sort((a, b) => b.textbook_count - a.textbook_count)[0];
        if (!current) {
          changeCourse(preferred.id);
        }
      }
    } catch {
      message.error('课程加载失败，请刷新重试');
    }
  }, [selectedCourseId, changeCourse]);

  const loadTextbooks = useCallback(async () => {
    const requestId = ++textbookRequest.current;
    setTextbooksLoading(true);
    try {
      const response = await api.getTextbooks(selectedCourseId);
      if (requestId !== textbookRequest.current) return;
      setTextbooks(response.data);
      setSelectedTextbook((current) => (
        response.data.find((book) => book.id === current?.id) || (selectedCourseId === initial.course ? response.data.find((book) => book.id === initial.book) : null) || null
      ));
    } catch {
      if (requestId === textbookRequest.current) message.error('教材加载失败，请刷新重试');
    } finally {
      if (requestId === textbookRequest.current) setTextbooksLoading(false);
    }
  }, [selectedCourseId, initial]);

  const loadRagStatus = useCallback(async () => {
    try {
      const response = await api.getRagStatus(selectedCourseId);
      setRagStatus(response.data);
    } catch {
      setRagStatus(null);
    }
  }, [selectedCourseId]);

  const loadModelStatus = useCallback(async (probe = false) => {
    setModelChecking(probe);
    try {
      const response = probe ? await api.probeModel() : await api.getModelStatus();
      setModelStatus(response.data);
    } catch {
      setModelStatus(null);
    } finally {
      setModelChecking(false);
    }
  }, []);

  const loadBenchmarkResults = useCallback(async () => {
    setBenchmarkLoading(true);
    try {
      const response = await api.getBenchmarkResults(selectedCourseId);
      setBenchmarkResults(response.data);
    } finally {
      setBenchmarkLoading(false);
    }
  }, [selectedCourseId]);

  const runBenchmarkEvaluation = useCallback(async () => {
    setBenchmarkLoading(true);
    try {
      const response = await api.runBenchmark(selectedCourseId);
      setBenchmarkResults(response.data);
      message.success('教师问题评测完成');
    } catch {
      message.error('评测运行失败，请先确认课程已经建立索引');
      throw new Error('benchmark failed');
    } finally {
      setBenchmarkLoading(false);
    }
  }, [selectedCourseId]);

  const loadBookWorkspace = useCallback((book: Textbook) => {
    setSelectedTextbook(book);
    setWorkspace('tree');
  }, []);

  const { jobs: textbookJobs, track: trackJob, error: jobPollingError, refresh: refreshJobs } = useTextbookJobs(selectedCourseId, () => {
    loadTextbooks(); loadCourses(); loadRagStatus(); loadModelStatus();
  });

  const handleUpload = useCallback(async (file: File) => {
    const response = await api.uploadTextbook(file, selectedCourseId);
    message.success('教材已上传，下一步开始解析');
    await loadTextbooks();
    return response;
  }, [loadTextbooks, selectedCourseId]);

  const handleParse = useCallback(async (textbookId: string, force = false) => {
    try {
      const response = await api.startParseJob(textbookId, force);
      trackJob(response.data, textbookId);
      message.info('正在解析教材，完成后可核对章节');
    } catch {
      message.error('解析任务启动失败');
    }
  }, [trackJob]);

  const handleExtractGraph = useCallback(async (textbookId: string, force = false) => {
    try {
      const response = await api.startExtractGraphJob(textbookId, force);
      trackJob(response.data, textbookId);
      message.info('正在生成知识树');
    } catch {
      message.error('知识树生成任务启动失败');
    }
  }, [trackJob]);

  const handleDeleteTextbook = useCallback(async (textbookId: string) => {
    await api.deleteTextbook(textbookId);
    refreshJobs();
    if (selectedTextbook?.id === textbookId) {
      setSelectedTextbook(null);
      setWorkspace('library');
    }
    await Promise.all([loadTextbooks(), loadCourses(), loadRagStatus()]);
    message.success('教材及其知识树已删除');
  }, [loadCourses, loadRagStatus, loadTextbooks, selectedTextbook]);

  const handleBuildRagIndex = useCallback(async () => {
    setRagBuilding(true);
    try {
      await api.buildRagIndex(selectedCourseId);
      await loadRagStatus();
      message.success('教材问答已经可以使用');
    } catch {
      message.error('问答索引构建失败');
    } finally {
      setRagBuilding(false);
    }
  }, [loadRagStatus, selectedCourseId]);

  const handleExport = useCallback(async () => {
    try {
      const response = await api.exportReport(selectedCourseId);
      const url = URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'CourseWeave-课程报告.md';
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error('报告导出失败');
    }
  }, [selectedCourseId]);

  useEffect(() => {
    loadCourses();
    api.getHealth()
      .then((response) => setPublicDemoReadOnly(Boolean(response.data.public_demo_read_only)))
      .catch(() => setPublicDemoReadOnly(false));
    loadModelStatus(false);
  }, [loadCourses, loadModelStatus]);

  useEffect(() => {
    setSelectedTextbook(null);
    loadTextbooks();
    loadRagStatus();
  }, [selectedCourseId, loadRagStatus, loadTextbooks]);

  useEffect(() => {
    if (workspace === 'tree' && !selectedTextbook) return;
    if (!textbooks.length && textbooksLoading) return;
    const currentRun = workspace === 'agent' ? agentRunId : lessonRunId;
    writeLocal('courseweave:workspace', { course: selectedCourseId, book: selectedTextbook?.id || '', view: workspace, run: currentRun });
    const url = new URL(window.location.href);
    url.searchParams.set('course', selectedCourseId);
    url.searchParams.set('view', workspace);
    if (selectedTextbook && workspace !== 'library') url.searchParams.set('book', selectedTextbook.id);
    else url.searchParams.delete('book');
    if ((workspace === 'lesson' || workspace === 'agent') && currentRun) url.searchParams.set('run', currentRun);
    else url.searchParams.delete('run');
    window.history.replaceState(null, '', url);
  }, [workspace, selectedCourseId, selectedTextbook, textbooks.length, textbooksLoading, lessonRunId, agentRunId]);

  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') loadModelStatus(false); };
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener('focus', refresh);
    window.addEventListener('courseweave:model-status-changed', refresh);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', refresh); window.removeEventListener('courseweave:model-status-changed', refresh); };
  }, [loadModelStatus]);

  useEffect(() => { window.scrollTo(0, 0); }, [workspace, selectedCourseId]);
  useEffect(() => {
    if (workspace !== 'library') return;
    const controller = new AbortController(); setRecentLesson(null);
    getLessonRuns(selectedCourseId, controller.signal).then(({ data }) => {
      const recent = data.find((run) => run.course_id === selectedCourseId && (run.result.lesson_draft || run.result.artifact));
      if (!controller.signal.aborted && recent) setRecentLesson({ id: recent.id, title: (recent.result.lesson_draft || recent.result.artifact)?.title || recent.result.topic });
    }).catch(() => { /* The textbook library remains usable without history. */ });
    return () => controller.abort();
  }, [selectedCourseId, workspace]);

  const prepareLesson = (context: AgentLessonContext) => {
    const next = { ...context, intentId: crypto.randomUUID() };
    setAgentContext(next); writeLocal(`courseweave:current-preparation:${selectedCourseId}`, next); setAgentRunId(''); setWorkspace('agent');
  };
  const collectEvidence = (citation: Citation, question: string) => {
    if (!citation.chunk_id || !citation.textbook_id) return;
    const ownBook = textbooks.find((book) => book.id === citation.textbook_id);
    if (!ownBook) return message.warning('这条证据不属于当前课程，请重新查证');
    const pending = agentContext?.collectedEvidence ? Array.isArray(agentContext.collectedEvidence) ? agentContext.collectedEvidence : [agentContext.collectedEvidence] : [];
    const collected = [...pending.filter((item) => item.chunkId !== citation.chunk_id), { chunkId: citation.chunk_id, textbookId: citation.textbook_id, courseId: selectedCourseId }];
    if (collected.length > 48) return message.warning('已收集 48 段待合并原文，请先继续备课并整理材料');
    const selected = [...new Set([...(agentContext?.selectedChunkIds || []), ...(agentContext?.supplementalChunkIds || []), citation.chunk_id])];
    const next: AgentLessonContext = { ...agentContext, topic: agentContext?.topic || question.slice(0, 160), textbookIds: [...new Set([...(agentContext?.textbookIds || []), citation.textbook_id])], intentId: crypto.randomUUID(), collectedEvidence: collected };
    if (next.boardId) next.supplementalChunkIds = [...new Set([...(agentContext?.supplementalChunkIds || []), citation.chunk_id])];
    else next.selectedChunkIds = selected;
    setAgentContext(next);
    if (writeLocal(`courseweave:current-preparation:${selectedCourseId}`, next)) message.success('已收集原文，可在备课条件中核对使用');
    else message.warning('材料已加入当前页面，但本机暂存不可用，请在刷新前继续备课并保存');
  };
  const consumeCollectedEvidence = useCallback((intentId: string, owned: AgentLessonContext) => {
    setAgentContext((current) => {
      if (current?.intentId !== intentId) return current;
      const next = { ...owned, intentId };
      writeLocal(`courseweave:current-preparation:${selectedCourseId}`, next);
      return next;
    });
  }, [selectedCourseId]);
  const openAgent = () => {
    if (workspace === 'agent') return;
    if (workspace === 'compare' && crossPrepare.current) { crossPrepare.current(); return; }
    if (workspace === 'lesson') { setAgentRunId(lessonRunId); setWorkspace('agent'); return; }
    if (workspace === 'compare' && compareQuery.trim()) prepareLesson({ topic: compareQuery.trim(), textbookIds: compareBookIds });
    else if (workspace === 'tree' && selectedTextbook) {
      const position = readLocal<{ query?: string; sectionId?: string }>(`courseweave:lecture:${selectedTextbook.id}`, {});
      prepareLesson({ topic: position.query || undefined, textbookIds: [selectedTextbook.id], sourceBookId: selectedTextbook.id, sectionId: position.sectionId });
    } else setWorkspace('agent');
  };

  const openLibrary = () => {
    setWorkspace('library');
  };

  const uploadRequest = async ({ file, onSuccess, onError }: any) => {
    try {
      await handleUpload(file as File);
      onSuccess?.({});
    } catch (error) {
      onError?.(error);
    }
  };

  const moreItems = [
    ...(!publicDemoReadOnly ? [
      {
        key: 'index',
        label: ragStatus?.indexed ? '重建问答索引' : '构建问答索引',
        onClick: handleBuildRagIndex,
      },
      { key: 'export', label: '导出课程报告', onClick: handleExport },
    ] : []),
    {
      key: 'quality',
      label: '教材证据检索评测',
      onClick: () => {
        setQualityOpen(true);
        loadBenchmarkResults();
      },
    },
  ];

  return (
    <div className="app-shell">
      <header className="app-header">
        <button className="brand" onClick={openLibrary} aria-label="返回教材库">
          <span className="brand-mark">C</span>
          <span className="brand-name">CourseWeave</span>
        </button>

        <CourseSwitcher
          courses={courses}
          selectedCourse={selectedCourse}
          onSelect={changeCourse}
          onCreated={(course) => {
            setCourses((current) => [course, ...current]);
            changeCourse(course.id);
          }}
          onDeleted={handleCourseDeleted}
          readOnly={publicDemoReadOnly}
        />

        <nav className="primary-nav" aria-label="主要功能">
          <button className={workspace === 'library' || workspace === 'tree' ? 'active' : ''} onClick={() => setWorkspace(selectedTextbook ? 'tree' : 'library')}>
            <BookOutlined /> 教材
          </button>
          <button className={workspace === 'compare' ? 'active' : ''} onClick={() => setWorkspace('compare')}>
            <BranchesOutlined /> 跨教材
          </button>
          <button className={workspace === 'agent' || workspace === 'lesson' ? 'active' : ''} onClick={openAgent}>
            <CompassOutlined /> 备课 Agent
          </button>
          <button className={`mobile-ask-nav ${ragOpen ? 'active' : ''}`} onClick={() => setRagOpen(true)}>
            <SearchOutlined /> 问答
          </button>
        </nav>

        <div className="header-actions">
          <ModelAvailabilityBadge
            status={modelStatus}
            checking={modelChecking}
            onCheck={() => loadModelStatus(!publicDemoReadOnly)}
            probeEnabled={!publicDemoReadOnly}
          />
          <Button className="ask-button" icon={<SearchOutlined />} onClick={() => setRagOpen(true)}>
            向教材提问
          </Button>
          {workspace !== 'library' && !publicDemoReadOnly && (
            <Upload accept=".pdf,.md,.txt" showUploadList={false} customRequest={uploadRequest}>
              <Button type="primary" icon={<PlusOutlined />}>上传教材</Button>
            </Upload>
          )}
          <Dropdown menu={{ items: moreItems }} trigger={['click']}>
            <Button aria-label="更多操作" icon={<MoreOutlined />} />
          </Dropdown>
        </div>
      </header>

      <main className="workspace">
        {agentContext?.topic && workspace !== 'agent' && workspace !== 'lesson' && <div className="preparation-tray"><span><small>本机备课条件</small><strong>{pendingEvidenceCount ? '已收集教材证据' : agentContext.topic}</strong><em>{preparationScope}</em></span><Button size="small" onClick={() => { setAgentRunId(''); setWorkspace('agent'); }}>继续备课 →</Button></div>}
        {jobPollingError && <Alert className="workspace-status" type="warning" showIcon message={jobPollingError} action={<Button size="small" onClick={refreshJobs}>刷新状态</Button>} />}
        {workspace === 'library' && recentLesson && <div className="recent-lesson"><div><small>继续上次备课</small><strong>{recentLesson.title}</strong></div><Button onClick={() => { setAgentRunId(recentLesson.id); setWorkspace('agent'); }}>打开教案 →</Button>{!publicDemoReadOnly && <Button type="text" onClick={() => prepareLesson({ textbookIds: textbooks.slice(0, 2).map((book) => book.id) })}>新建一堂课</Button>}</div>}
        {workspace === 'library' && (
          <TextbookPanel
            textbooks={textbooks}
            selectedId={null}
            loading={textbooksLoading}
            onSelect={(id) => {
              const book = textbooks.find((item) => item.id === id);
              if (book) loadBookWorkspace(book);
            }}
            onUpload={handleUpload}
            onParse={handleParse}
              onExtractGraph={handleExtractGraph}
              onDelete={handleDeleteTextbook}
              onConfirmStructure={loadTextbooks}
            jobs={textbookJobs}
            readOnly={publicDemoReadOnly}
          />
        )}

        {workspace === 'tree' && selectedTextbook && (
          <TeachingWorkspace
            key={selectedTextbook.id}
            textbook={selectedTextbook}
            onBack={openLibrary}
            onCompare={(term) => { setCompareQuery(term); setWorkspace('compare'); }}
            onPrepare={prepareLesson}
          />
        )}

        {workspace === 'compare' && !textbooksLoading && (
          <TeachingBridge key={`${selectedCourseId}:${textbooks.length}`} courseId={selectedCourseId} textbooks={textbooks} sourceBook={selectedTextbook} initialQuery={compareQuery} onScopeChange={setCompareBookIds} onTopicChange={setCompareQuery} onPrepare={prepareLesson} onPrepareReady={registerCrossPrepare} readOnly={publicDemoReadOnly} onBack={() => setWorkspace(selectedTextbook ? 'tree' : 'library')} />
        )}

        {workspace === 'compare' && textbooksLoading && <div className="page-loading">正在恢复课程教材与对照位置…</div>}

        {workspace === 'tree' && !selectedTextbook && !textbooksLoading && <section className="teaching-error"><p>当前教材不存在或尚未加载，请返回教材库重新选择。</p><Button onClick={openLibrary}>返回教材库</Button></section>}

        {workspace === 'agent' && (
          <React.Suspense fallback={<div className="page-loading">正在加载备课 Agent…</div>}>
            <AgentWorkbench
              courseId={selectedCourseId}
              courseTitle={selectedCourse?.title || '当前知识空间'}
              textbooks={textbooks}
              modelStatus={modelStatus}
              onGoLibrary={openLibrary}
              readOnly={publicDemoReadOnly}
              context={agentContext}
              initialRunId={agentRunId}
              onOpenLesson={(id) => { setLessonRunId(id); setWorkspace('lesson'); }}
              onSelectedRunChange={setAgentRunId}
              onCollectedEvidenceConsumed={consumeCollectedEvidence}
            />
          </React.Suspense>
        )}

        {workspace === 'lesson' && (
          <React.Suspense fallback={<div className="page-loading">正在恢复本课教案…</div>}>
            <LessonPresenter key={lessonRunId} courseId={selectedCourseId} runId={lessonRunId} textbooks={textbooks} onBack={(validId) => { setAgentRunId(validId || ''); setWorkspace('agent'); }} />
          </React.Suspense>
        )}

      </main>

      <React.Suspense fallback={null}>
        <FloatingRagAssistant
          open={ragOpen}
          onOpenChange={setRagOpen}
          courseId={selectedCourseId}
          courseTitle={selectedCourse?.title || '当前知识空间'}
          textbooks={textbooks}
          ragStatus={ragStatus}
          onBuildIndex={handleBuildRagIndex}
          isBuilding={ragBuilding}
          preferredTextbookIds={workspace === 'compare' ? compareBookIds : selectedTextbook ? [selectedTextbook.id] : []}
          readOnly={publicDemoReadOnly}
          onCollectEvidence={collectEvidence}
        />
      </React.Suspense>

      <Drawer
        open={qualityOpen}
        onClose={() => setQualityOpen(false)}
        width={560}
        title={null}
        className="quality-drawer"
      >
        <React.Suspense fallback={<div className="page-loading">正在加载评测台…</div>}>
          <BenchmarkPanel
            results={benchmarkResults}
            loading={benchmarkLoading}
            onRefresh={loadBenchmarkResults}
            onRun={runBenchmarkEvaluation}
            readOnly={publicDemoReadOnly}
          />
        </React.Suspense>
      </Drawer>
    </div>
  );
};

export default App;
