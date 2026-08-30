import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Drawer, Dropdown, Upload, message } from 'antd';
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
import KnowledgeTree from './components/KnowledgeTree';
import KnowledgeDetailDrawer from './components/KnowledgeDetailDrawer';
import ModelAvailabilityBadge from './components/ModelAvailabilityBadge';
import * as api from './api/client';
import type {
  Chapter,
  Course,
  GraphData,
  GraphNode,
  Job,
  BenchmarkResult,
  ModelStatus,
  RagStatus,
  Textbook,
} from './types';
import './App.css';

const AlignmentReviewPanel = React.lazy(() => import('./components/AlignmentReviewPanel'));
const FloatingRagAssistant = React.lazy(() => import('./components/FloatingRagAssistant'));
const BenchmarkPanel = React.lazy(() => import('./components/BenchmarkPanel'));
const AgentWorkbench = React.lazy(() => import('./components/AgentWorkbench'));
const POLL_INTERVAL = 2000;

type Workspace = 'library' | 'tree' | 'compare' | 'agent';

const App: React.FC = () => {
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState('course_default');
  const [textbooks, setTextbooks] = useState<Textbook[]>([]);
  const [textbooksLoading, setTextbooksLoading] = useState(false);
  const [workspace, setWorkspace] = useState<Workspace>('library');
  const [selectedTextbook, setSelectedTextbook] = useState<Textbook | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [textbookJobs, setTextbookJobs] = useState<Record<string, Job>>({});
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null);
  const [ragBuilding, setRagBuilding] = useState(false);
  const [integrating, setIntegrating] = useState(false);
  const [alignmentVersion, setAlignmentVersion] = useState(0);
  const [ragOpen, setRagOpen] = useState(false);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [modelChecking, setModelChecking] = useState(false);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [benchmarkResults, setBenchmarkResults] = useState<BenchmarkResult[]>([]);
  const [benchmarkLoading, setBenchmarkLoading] = useState(false);
  const [publicDemoReadOnly, setPublicDemoReadOnly] = useState(false);

  const selectedCourse = useMemo(
    () => courses.find((course) => course.id === selectedCourseId) || null,
    [courses, selectedCourseId],
  );

  const handleCourseDeleted = useCallback((courseId: string) => {
    setCourses((current) => {
      const remaining = current.filter((course) => course.id !== courseId);
      if (selectedCourseId === courseId) {
        setSelectedCourseId(remaining.find((course) => course.id === 'course_default')?.id || remaining[0]?.id || 'course_default');
      }
      return remaining;
    });
  }, [selectedCourseId]);

  const loadCourses = useCallback(async () => {
    try {
      const response = await api.getCourses();
      setCourses(response.data);
      if (response.data.length) {
        const current = response.data.find((course) => course.id === selectedCourseId);
        const preferred = [...response.data].sort((a, b) => b.textbook_count - a.textbook_count)[0];
        if (!current || (current.textbook_count === 0 && preferred.textbook_count > 0)) {
          setSelectedCourseId(preferred.id);
        }
      }
    } catch {
      message.error('课程加载失败，请刷新重试');
    }
  }, [selectedCourseId]);

  const loadTextbooks = useCallback(async () => {
    setTextbooksLoading(true);
    try {
      const response = await api.getTextbooks(selectedCourseId);
      setTextbooks(response.data);
      setSelectedTextbook((current) => (
        current ? response.data.find((book) => book.id === current.id) || current : current
      ));
    } catch {
      message.error('教材加载失败，请刷新重试');
    } finally {
      setTextbooksLoading(false);
    }
  }, [selectedCourseId]);

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

  const loadBookWorkspace = useCallback(async (book: Textbook) => {
    setSelectedTextbook(book);
    setSelectedNode(null);
    setWorkspace('tree');
    setGraphLoading(true);
    try {
      const [chapterResponse, graphResponse] = await Promise.all([
        api.getChapters(book.id),
        api.getBookGraph(book.id, { min_importance: 2, limit: 1200 }),
      ]);
      setChapters(chapterResponse.data);
      setGraphData(graphResponse.data);
    } catch {
      setGraphData(null);
      setChapters([]);
      message.error('知识树加载失败，请确认教材已经完成解析和抽取');
    } finally {
      setGraphLoading(false);
    }
  }, []);

  const pollJob = useCallback((jobId: string, textbookId: string, onComplete: () => void) => {
    const timer = window.setInterval(async () => {
      try {
        const response = await api.getJobStatus(jobId);
        setTextbookJobs((current) => ({ ...current, [textbookId]: response.data }));
        if (response.data.status === 'completed') {
          window.clearInterval(timer);
          message.success('处理完成');
          onComplete();
          loadModelStatus();
        } else if (response.data.status === 'failed') {
          window.clearInterval(timer);
          message.error(response.data.error || response.data.message || '处理失败，请重试');
        }
      } catch {
        window.clearInterval(timer);
      }
    }, POLL_INTERVAL);
  }, [loadModelStatus]);

  const handleUpload = useCallback(async (file: File) => {
    const response = await api.uploadTextbook(file, selectedCourseId);
    message.success('教材已上传，下一步开始解析');
    await loadTextbooks();
    return response;
  }, [loadTextbooks, selectedCourseId]);

  const handleParse = useCallback(async (textbookId: string, force = false) => {
    try {
      const response = await api.startParseJob(textbookId, force);
      setTextbookJobs((current) => ({ ...current, [textbookId]: response.data }));
      message.info('正在解析教材，完成后可核对章节');
      pollJob(response.data.id, textbookId, loadTextbooks);
    } catch {
      message.error('解析任务启动失败');
    }
  }, [loadTextbooks, pollJob]);

  const handleExtractGraph = useCallback(async (textbookId: string, force = false) => {
    try {
      const response = await api.startExtractGraphJob(textbookId, force);
      setTextbookJobs((current) => ({ ...current, [textbookId]: response.data }));
      message.info('正在生成知识树');
      pollJob(response.data.id, textbookId, async () => {
        await loadTextbooks();
        const book = textbooks.find((item) => item.id === textbookId);
        if (book && workspace === 'tree') loadBookWorkspace({ ...book, graph_status: 'completed' });
      });
    } catch {
      message.error('知识树生成任务启动失败');
    }
  }, [loadBookWorkspace, loadTextbooks, pollJob, textbooks, workspace]);

  const handleDeleteTextbook = useCallback(async (textbookId: string) => {
    await api.deleteTextbook(textbookId);
    setTextbookJobs((current) => {
      const next = { ...current };
      delete next[textbookId];
      return next;
    });
    if (selectedTextbook?.id === textbookId) {
      setSelectedTextbook(null);
      setSelectedNode(null);
      setGraphData(null);
      setChapters([]);
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

  const handleBuildConnections = useCallback(async (textbookIds: string[]) => {
    setIntegrating(true);
    try {
      const response = await api.startIntegrateJob(selectedCourseId, textbookIds);
      message.info(`正在分析 ${textbookIds.length} 组教材的知识关联`);
      await new Promise<void>((resolve, reject) => {
        const check = async () => {
          try {
            const status = await api.getJobStatus(response.data.id);
            if (status.data.status === 'completed') {
              resolve();
              return;
            }
            if (status.data.status === 'failed') {
              reject(new Error(status.data.error || status.data.message || '关联生成失败'));
              return;
            }
            window.setTimeout(check, POLL_INTERVAL);
          } catch (error) {
            reject(error);
          }
        };
        window.setTimeout(check, POLL_INTERVAL);
      });
      setAlignmentVersion((current) => current + 1);
      message.success('跨教材关联图已生成');
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '关联生成启动失败');
    } finally {
      setIntegrating(false);
    }
  }, [selectedCourseId]);

  const handleExport = useCallback(async () => {
    try {
      const response = await api.exportReport();
      const url = URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'CourseWeave-课程报告.md';
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error('报告导出失败');
    }
  }, []);

  useEffect(() => {
    loadCourses();
    api.getHealth()
      .then((response) => setPublicDemoReadOnly(Boolean(response.data.public_demo_read_only)))
      .catch(() => setPublicDemoReadOnly(false));
    loadModelStatus(false);
  }, [loadCourses, loadModelStatus]);

  useEffect(() => {
    setWorkspace('library');
    setSelectedTextbook(null);
    setSelectedNode(null);
    setGraphData(null);
    loadTextbooks();
    loadRagStatus();
  }, [selectedCourseId, loadRagStatus, loadTextbooks]);

  const openLibrary = () => {
    setWorkspace('library');
    setSelectedNode(null);
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
      label: 'RAG 质量评测',
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
          onSelect={setSelectedCourseId}
          onCreated={(course) => {
            setCourses((current) => [course, ...current]);
            setSelectedCourseId(course.id);
          }}
          onDeleted={handleCourseDeleted}
          readOnly={publicDemoReadOnly}
        />

        <nav className="primary-nav" aria-label="主要功能">
          <button className={workspace === 'library' || workspace === 'tree' ? 'active' : ''} onClick={openLibrary}>
            <BookOutlined /> 教材
          </button>
          <button className={workspace === 'compare' ? 'active' : ''} onClick={() => setWorkspace('compare')}>
            <BranchesOutlined /> 跨教材
          </button>
          <button className={workspace === 'agent' ? 'active' : ''} onClick={() => setWorkspace('agent')}>
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
          <KnowledgeTree
            textbook={selectedTextbook}
            chapters={chapters}
            graphData={graphData}
            loading={graphLoading}
            onBack={openLibrary}
            onSelectNode={setSelectedNode}
            onReviewChapters={openLibrary}
            onExtract={() => handleExtractGraph(selectedTextbook.id)}
          />
        )}

        {workspace === 'compare' && (
          <section className="task-page compare-page">
            <div className="task-heading">
              <div>
                <span className="section-kicker">CROSS-TEXTBOOK</span>
                <h1>跨教材知识连接</h1>
                <p>选择多本教材，直接查看按教材分组的关联知识节点。</p>
              </div>
            </div>
            <React.Suspense fallback={<div className="page-loading">正在加载关联图…</div>}>
              <AlignmentReviewPanel
                courseId={selectedCourseId}
                textbooks={textbooks}
                refreshToken={alignmentVersion}
                onGenerate={handleBuildConnections}
                onGoLibrary={openLibrary}
                generating={integrating}
                readOnly={publicDemoReadOnly}
              />
            </React.Suspense>
          </section>
        )}

        {workspace === 'agent' && (
          <React.Suspense fallback={<div className="page-loading">正在加载备课 Agent…</div>}>
            <AgentWorkbench
              courseId={selectedCourseId}
              courseTitle={selectedCourse?.title || '当前知识空间'}
              textbooks={textbooks}
              modelStatus={modelStatus}
              onGoLibrary={openLibrary}
              readOnly={publicDemoReadOnly}
            />
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
          readOnly={publicDemoReadOnly}
        />
      </React.Suspense>

      <KnowledgeDetailDrawer
        node={selectedNode}
        graphData={graphData}
        onClose={() => setSelectedNode(null)}
        onSelectRelated={setSelectedNode}
      />

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
