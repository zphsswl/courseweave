import React, { useEffect, useMemo, useState } from 'react';
import { Button, Empty, Spin, Tag } from 'antd';
import { CheckOutlined, ExperimentOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import type { BenchmarkResult, BenchmarkSuite } from '../types';
import * as api from '../api/client';


interface Props {
  results: BenchmarkResult[];
  loading: boolean;
  onRefresh: () => void;
  onRun: () => Promise<void>;
  readOnly?: boolean;
}

const scoreTone = (score: number) => score >= .8 ? 'good' : score >= .6 ? 'fair' : 'weak';

const BenchmarkPanel: React.FC<Props> = ({ results, loading, onRefresh, onRun, readOnly = false }) => {
  const [running, setRunning] = useState(false);
  const [suite, setSuite] = useState<BenchmarkSuite | null>(null);

  useEffect(() => {
    api.getBenchmarkSuite().then((response) => setSuite(response.data)).catch(() => setSuite(null));
  }, []);

  const teacherMetrics = results.filter((item) => item.category === 'teacher_questions');
  const systemMetrics = results.filter((item) => item.category !== 'teacher_questions');
  const average = useMemo(() => (
    teacherMetrics.length
      ? teacherMetrics.reduce((sum, item) => sum + item.score, 0) / teacherMetrics.length
      : 0
  ), [teacherMetrics]);

  const run = async () => {
    setRunning(true);
    try { await onRun(); } finally { setRunning(false); }
  };

  const metricCard = (result: BenchmarkResult) => (
    <article className={`quality-metric ${scoreTone(result.score)}`} key={result.metric}>
      <div className="quality-metric-top">
        <span><CheckOutlined /></span>
        <strong>{result.metric}</strong>
        <b>{Math.round(result.score * 100)}<small>%</small></b>
      </div>
      <div className="quality-meter"><i style={{ width: `${Math.max(2, result.score * 100)}%` }} /></div>
      <p>{result.description}</p>
    </article>
  );

  return (
    <div className="quality-lab">
      <header className="quality-lab-head">
        <span><ExperimentOutlined /></span>
        <div><small>EVIDENCE QUALITY LAB</small><h2>RAG 教师问题评测</h2><p>用固定问题集检查检索、引用、跨教材覆盖和拒答，不靠主观感受打分。</p></div>
      </header>

      <section className="quality-suite-strip">
        <div><small>问题集</small><strong>{suite?.question_count || 45}</strong><span>道教师问题</span></div>
        <div><small>跨教材</small><strong>{suite?.compare_count || 5}</strong><span>道对比题</span></div>
        <div><small>拒答检测</small><strong>{suite?.rejection_count || 5}</strong><span>道域外题</span></div>
        <Tag icon={<SafetyCertificateOutlined />} color="success">固定版本 {suite?.version || 'medical-teacher-v1'}</Tag>
      </section>

      {!results.length ? (
        <div className="quality-empty">
          {loading ? <Spin /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有本课程的评测结果" />}
          <p>首次运行会读取当前课程索引，通常需要几十秒，不调用付费大模型。</p>
          {!readOnly && <Button type="primary" onClick={run} loading={running}>运行 45 题评测</Button>}
        </div>
      ) : (
        <>
          <section className="quality-score-hero">
            <div><small>四项核心指标均值</small><strong>{Math.round(average * 100)}</strong><span>/ 100</span></div>
            <p>本分数只评价可验证的检索行为，不把语言流畅度当作准确性。</p>
            {!readOnly && <Button onClick={run} loading={running}>重新评测</Button>}
          </section>
          <div className="quality-section-title"><span>教师问题指标</span><small>面试演示重点</small></div>
          <section className="quality-metric-grid">{teacherMetrics.map(metricCard)}</section>
          {!!systemMetrics.length && <>
            <div className="quality-section-title"><span>系统基础指标</span><small>数据与证据健康度</small></div>
            <section className="quality-metric-grid compact">{systemMetrics.map(metricCard)}</section>
          </>}
        </>
      )}
      <footer className="quality-lab-foot">
        <Button icon={<ReloadOutlined />} onClick={onRefresh} loading={loading}>刷新结果</Button>
        <span>评测集不包含教材原文，可安全提交到 GitHub。</span>
      </footer>
    </div>
  );
};

export default BenchmarkPanel;
