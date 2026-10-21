import React, { useEffect, useState } from 'react';
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

  const run = async () => {
    setRunning(true);
    try { await onRun(); } finally { setRunning(false); }
  };

  const metricCard = (result: BenchmarkResult) => (
    <article className={`quality-metric ${scoreTone(result.score)}`} key={result.metric}>
      <div className="quality-metric-top">
        <span><CheckOutlined /></span>
        <strong>{result.metric === '引用准确率' ? '前三段证据相关率' : result.metric === '检索召回率' ? '固定题集检索命中率' : result.metric}</strong>
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
        <div><small>RETRIEVAL EVALUATION</small><h2>教材证据检索评测</h2><p>固定题集用于检查证据召回、相关性和拒答；不评判生成答案的事实正确性或课堂适用性。</p></div>
      </header>

      <section className="quality-suite-strip">
        <div><small>问题集</small><strong>{suite?.question_count ?? 420}</strong><span>道教师问题</span></div>
        <div><small>章节覆盖</small><strong>{suite?.chapter_count ?? 137}</strong><span>个一级章节</span></div>
        <div><small>跨教材</small><strong>{suite?.compare_count ?? 41}</strong><span>道对比题</span></div>
        <div><small>拒答检测</small><strong>{suite?.rejection_count ?? 40}</strong><span>道域外题</span></div>
        <Tag icon={<SafetyCertificateOutlined />} color="success">固定版本 {suite?.version || 'medical-teacher-v3'}</Tag>
      </section>

      {!results.length ? (
        <div className="quality-empty">
          {loading ? <Spin /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有本课程的评测结果" />}
          <p>420 题会读取当前课程索引，通常需要 1–2 分钟；运行期间请保持页面打开，不调用付费大模型。</p>
          {!readOnly && <Button type="primary" onClick={run} loading={running}>运行 {suite?.question_count ?? 420} 题评测</Button>}
        </div>
      ) : (
        <>
          <section className="quality-score-hero">
            <div><small>固定题集</small><strong>{suite?.question_count ?? 420}</strong><span> 题</span></div>
            <p>分项结果用于检索回归，不合成为教学质量分。引用相关性检查不等于逐条原页或语义审核。</p>
            {!readOnly && <Button onClick={run} loading={running}>重新评测</Button>}
          </section>
          <div className="quality-section-title"><span>教师问题指标</span><small>核心评测指标</small></div>
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
