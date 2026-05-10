import React, { useState, useEffect, useCallback } from 'react';
import { Tabs, message } from 'antd';
import TopBar from './components/TopBar';
import TextbookPanel from './components/TextbookPanel';
import GraphCanvas from './components/GraphCanvas';
import NodeDetail from './components/NodeDetail';
import DecisionPanel from './components/DecisionPanel';
import RagPanel from './components/RagPanel';
import TeacherChatPanel from './components/TeacherChatPanel';
import ReportPanel from './components/ReportPanel';
import BenchmarkPanel from './components/BenchmarkPanel';
import * as api from './api/client';
import type {
  Textbook,
  GraphData,
  GraphNode,
  Decision,
  RagStatus,
  ReportSummary,
  BenchmarkResult,
  Job,
  ModelStatus,
} from './types';
import './App.css';

const POLL_INTERVAL = 2000;

const App: React.FC = () => {
  /* =========================================================
     State
     ========================================================= */
  // Textbooks
  const [textbooks, setTextbooks] = useState<Textbook[]>([]);
  const [selectedTextbookId, setSelectedTextbookId] = useState<string | null>(null);
  const [textbooksLoading, setTextbooksLoading] = useState(false);

  // Graph
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [showIntegrated, setShowIntegrated] = useState(false);
  const [graphLoading, setGraphLoading] = useState(false);

  // Node detail
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [nodeDetailVisible, setNodeDetailVisible] = useState(false);

  // Decisions
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [decisionsLoading, setDecisionsLoading] = useState(false);

  // RAG
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null);
  const [ragBuilding, setRagBuilding] = useState(false);

  // Report
  const [reportSummary, setReportSummary] = useState<ReportSummary | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  // Model
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);

  // Benchmark
  const [benchmarkResults, setBenchmarkResults] = useState<BenchmarkResult[]>([]);
  const [benchmarkLoading, setBenchmarkLoading] = useState(false);

  // Jobs
  const [textbookJobs, setTextbookJobs] = useState<Record<string, Job>>({});
  const [integrating, setIntegrating] = useState(false);

  // Active right tab
  const [activeRightTab, setActiveRightTab] = useState('decisions');

  // Computed stats
  const totalTextbooks = textbooks.length;
  const totalChars = textbooks.reduce(
    (sum, tb) => sum + (tb.total_chars || 0),
    0
  );
  const compressionRatio = reportSummary?.textbooks?.total_chars
    ? (reportSummary?.knowledge_graph?.total_nodes || 0) / reportSummary.textbooks.total_chars
    : 0;

  /* =========================================================
     Data Loaders
     ========================================================= */
  const loadTextbooks = useCallback(async () => {
    setTextbooksLoading(true);
    try {
      const res = await api.getTextbooks();
      setTextbooks(res.data);
    } catch {
      message.error('加载教材列表失败');
    } finally {
      setTextbooksLoading(false);
    }
  }, []);

  const loadBookGraph = useCallback(async (bookId: string) => {
    setGraphLoading(true);
    try {
      const res = await api.getBookGraph(bookId);
      setGraphData(res.data);
      setShowIntegrated(false);
    } catch {
      message.error('加载知识图谱失败');
    } finally {
      setGraphLoading(false);
    }
  }, []);

  const loadIntegratedGraph = useCallback(async () => {
    setGraphLoading(true);
    try {
      const res = await api.getIntegratedGraph();
      setGraphData(res.data);
      setShowIntegrated(true);
    } catch {
      message.error('加载整合图谱失败');
    } finally {
      setGraphLoading(false);
    }
  }, []);

  const loadDecisions = useCallback(async () => {
    setDecisionsLoading(true);
    try {
      const res = await api.getDecisions();
      setDecisions(res.data);
    } catch {
      // Silent
    } finally {
      setDecisionsLoading(false);
    }
  }, []);

  const loadRagStatus = useCallback(async () => {
    try {
      const res = await api.getRagStatus();
      setRagStatus(res.data);
    } catch {
      // Silent
    }
  }, []);

  const loadReportSummary = useCallback(async () => {
    setReportLoading(true);
    try {
      const res = await api.getReportSummary();
      setReportSummary(res.data);
    } catch {
      // Silent
    } finally {
      setReportLoading(false);
    }
  }, []);

  const loadBenchmark = useCallback(async () => {
    setBenchmarkLoading(true);
    try {
      const res = await api.getBenchmarkResults();
      // Handle both array format and older { results: [...] } object format
      const data = res.data;
      if (Array.isArray(data)) {
        setBenchmarkResults(data);
      } else if (data && typeof data === 'object' && Array.isArray((data as any).results)) {
        setBenchmarkResults((data as any).results);
      } else {
        setBenchmarkResults([]);
      }
    } catch {
      // Silent
    } finally {
      setBenchmarkLoading(false);
    }
  }, []);

  const loadModelStatus = useCallback(async () => {
    try {
      const res = await api.getModelStatus();
      setModelStatus(res.data);
    } catch {
      // Silent
    }
  }, []);

  /* =========================================================
     Polling Helper
     ========================================================= */
  const pollJob = useCallback(
    (jobId: string, onComplete?: () => void): (() => void) => {
      const interval = setInterval(async () => {
        try {
          const res = await api.getJobStatus(jobId);
          setTextbookJobs((prev) => ({ ...prev, [jobId]: res.data }));

          if (res.data.status === 'completed') {
            clearInterval(interval);
            message.success('任务完成');
            if (onComplete) onComplete();
          } else if (res.data.status === 'failed') {
            clearInterval(interval);
            message.error(`任务失败: ${res.data.message || '未知错误'}`);
          }
        } catch {
          clearInterval(interval);
        }
      }, POLL_INTERVAL);

      return () => clearInterval(interval);
    },
    []
  );

  /* =========================================================
     Handlers
     ========================================================= */
  // Select textbook
  const handleSelectTextbook = useCallback(
    (id: string) => {
      setSelectedTextbookId(id);
      loadBookGraph(id);
    },
    [loadBookGraph]
  );

  // Upload
  const handleUpload = useCallback(
    async (file: File) => {
      await api.uploadTextbook(file);
      message.success(`教材上传成功`);
      loadTextbooks();
    },
    [loadTextbooks]
  );

  // Parse
  const handleParse = useCallback(
    (textbookId: string, force?: boolean) => {
      api
        .startParseJob(textbookId, force ?? false)
        .then((res) => {
          message.info(force ? '重新解析任务已启动' : '解析任务已启动');
          setTextbookJobs((prev) => ({ ...prev, [res.data.id]: res.data }));
          const cleanup = pollJob(res.data.id, () => {
            loadTextbooks();
          });
          return cleanup;
        })
        .catch(() => message.error('启动解析失败'));
    },
    [pollJob, loadTextbooks]
  );

  // Extract graph
  const handleExtractGraph = useCallback(
    (textbookId: string, force?: boolean) => {
      api
        .startExtractGraphJob(textbookId, force ?? false)
        .then((res) => {
          message.info(force ? '重新抽取任务已启动' : '图谱提取任务已启动');
          setTextbookJobs((prev) => ({ ...prev, [res.data.id]: res.data }));
          pollJob(res.data.id, () => {
            loadBookGraph(textbookId);
          });
        })
        .catch(() => message.error('启动图谱提取失败'));
    },
    [pollJob, loadBookGraph]
  );

  // Integrate
  const handleIntegrate = useCallback(() => {
    setIntegrating(true);
    api
      .startIntegrateJob()
      .then((res) => {
        message.info('整合任务已启动');
        const jobId = res.data?.id;
        if (!jobId) {
          setIntegrating(false);
          message.error('无法获取任务ID');
          return;
        }
        const interval = setInterval(async () => {
          try {
            const jobRes = await api.getJobStatus(jobId);
            if (jobRes.data.status === 'completed') {
              clearInterval(interval);
              setIntegrating(false);
              message.success('知识整合完成');
              loadIntegratedGraph();
              loadDecisions();
              loadReportSummary();
            } else if (jobRes.data.status === 'failed') {
              clearInterval(interval);
              setIntegrating(false);
              message.error(`整合失败: ${jobRes.data.message || '未知错误'}`);
            }
          } catch {
            clearInterval(interval);
            setIntegrating(false);
          }
        }, POLL_INTERVAL);
      })
      .catch(() => {
        setIntegrating(false);
        message.error('启动整合失败');
      });
  }, [loadIntegratedGraph, loadDecisions, loadReportSummary]);

  // Toggle graph view (single book <-> integrated)
  const handleToggleGraphView = useCallback(() => {
    if (showIntegrated) {
      if (selectedTextbookId) {
        loadBookGraph(selectedTextbookId);
      } else {
        message.info('请先选择一本教材');
      }
    } else {
      loadIntegratedGraph();
    }
  }, [showIntegrated, selectedTextbookId, loadBookGraph, loadIntegratedGraph]);

  // Node click
  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node);
    setNodeDetailVisible(true);
  }, []);

  // Decision update
  const handleDecisionUpdate = useCallback(
    async (id: string, data: Partial<Decision>) => {
      await api.updateDecision(id, data);
      message.success('决策已更新');
      loadDecisions();
    },
    [loadDecisions]
  );

  // Build RAG index
  const handleBuildRagIndex = useCallback(async () => {
    setRagBuilding(true);
    try {
      await api.buildRagIndex();
      message.success('RAG 索引构建完成');
      await loadRagStatus();
    } catch {
      message.error('构建 RAG 索引失败');
    } finally {
      setRagBuilding(false);
    }
  }, [loadRagStatus]);

  // Export
  const handleExport = useCallback(async () => {
    try {
      const res = await api.exportReport();
      const url = URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'MedEssence-整合报告.md');
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      message.success('报告导出成功');
    } catch {
      message.error('导出失败');
    }
  }, []);

  // Tab change
  const handleTabChange = useCallback(
    (key: string) => {
      setActiveRightTab(key);
      if (key === 'decisions') loadDecisions();
      if (key === 'report') loadReportSummary();
      if (key === 'benchmark') loadBenchmark();
    },
    [loadDecisions, loadReportSummary, loadBenchmark]
  );

  /* =========================================================
     Init
     ========================================================= */
  useEffect(() => {
    loadTextbooks();
    loadRagStatus();
    loadModelStatus();
  }, [loadTextbooks, loadRagStatus, loadModelStatus]);

  /* =========================================================
     Render
     ========================================================= */
  return (
    <div className="app">
      <TopBar
        textbooksCount={totalTextbooks}
        totalChars={totalChars}
        compressionRatio={compressionRatio}
        ragStatus={ragStatus}
        onExport={handleExport}
        onIntegrate={handleIntegrate}
        onBuildRagIndex={handleBuildRagIndex}
        isIntegrating={integrating}
        isBuildingRag={ragBuilding}
        modelStatus={modelStatus}
      />

      <div className="main-content">
        {/* Left Panel - Textbook Management */}
        <div className="left-panel">
          <TextbookPanel
            textbooks={textbooks}
            selectedId={selectedTextbookId}
            loading={textbooksLoading}
            onSelect={handleSelectTextbook}
            onUpload={handleUpload}
            onParse={handleParse}
            onExtractGraph={handleExtractGraph}
            jobs={textbookJobs}
          />
        </div>

        {/* Center Panel - Knowledge Graph */}
        <GraphCanvas
          graphData={graphData}
          loading={graphLoading}
          showIntegrated={showIntegrated}
          onNodeClick={handleNodeClick}
          onToggleView={handleToggleGraphView}
          textbookId={selectedTextbookId}
        />

        {/* Right Panel - Tabbed Tools */}
        <div className="right-panel">
          <Tabs
            activeKey={activeRightTab}
            onChange={handleTabChange}
            items={[
              {
                key: 'decisions',
                label: '整合决策',
                children: (
                  <DecisionPanel
                    decisions={decisions}
                    loading={decisionsLoading}
                    onUpdate={handleDecisionUpdate}
                    onRefresh={loadDecisions}
                  />
                ),
              },
              {
                key: 'rag',
                label: 'RAG 问答',
                children: (
                  <RagPanel
                    ragStatus={ragStatus}
                    onBuildIndex={handleBuildRagIndex}
                    isBuilding={ragBuilding}
                  />
                ),
              },
              {
                key: 'chat',
                label: '教师决策反馈',
                children: <TeacherChatPanel />,
              },
              {
                key: 'report',
                label: '整合报告',
                children: (
                  <ReportPanel
                    summary={reportSummary}
                    loading={reportLoading}
                    onRefresh={loadReportSummary}
                  />
                ),
              },
              {
                key: 'benchmark',
                label: 'Benchmark',
                children: (
                  <BenchmarkPanel
                    results={benchmarkResults}
                    loading={benchmarkLoading}
                    onRefresh={loadBenchmark}
                    onRun={async () => {
                      try {
                        await api.runBenchmark();
                        message.success('Benchmark 完成');
                        loadBenchmark();
                      } catch {
                        message.error('Benchmark 运行失败');
                      }
                    }}
                  />
                ),
              },
            ]}
          />
        </div>
      </div>

      {/* Node Detail Drawer */}
      <NodeDetail
        node={selectedNode}
        visible={nodeDetailVisible}
        onClose={() => setNodeDetailVisible(false)}
        decisions={decisions}
      />
    </div>
  );
};

export default App;
