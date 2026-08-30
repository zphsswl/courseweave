import React, { useState } from 'react';
import { Alert, Button, Empty, Input, Radio, Select, Space, Spin, Tag, Typography, message } from 'antd';
import { BookOutlined, BranchesOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons';
import type { QueryResult, RagStatus, Textbook } from '../types';
import * as api from '../api/client';

const { TextArea } = Input;

interface Props {
  courseId: string;
  textbooks: Textbook[];
  ragStatus: RagStatus | null;
  onBuildIndex: () => void;
  isBuilding: boolean;
  compact?: boolean;
  readOnly?: boolean;
}

const RagPanel: React.FC<Props> = ({ courseId, textbooks, ragStatus, onBuildIndex, isBuilding, compact = false, readOnly = false }) => {
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<'all' | 'compare'>('all');
  const [selectedBooks, setSelectedBooks] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState('');

  const ask = async () => {
    if (question.trim().length < 2) return message.warning('请输入完整问题');
    if (mode === 'compare' && selectedBooks.length < 2) return message.warning('对比模式至少选择两本教材');
    setLoading(true);
    setError('');
    try {
      const response = await api.queryRag(
        question.trim(),
        courseId,
        mode,
        selectedBooks.length ? selectedBooks : undefined,
      );
      setResult(response.data);
    } catch (queryError: any) {
      setError(queryError?.response?.data?.detail || '检索失败');
    } finally {
      setLoading(false);
    }
  };

  const methodLabel = ragStatus?.method === 'bm25_vector' ? 'BM25 + 向量 + 图谱' : 'BM25 + 图谱';

  return (
    <div className={`evidence-rag ${compact ? 'compact-rag' : ''}`}>
      <section className="rag-index-strip">
        <div>
          <span className="eyebrow">EVIDENCE RETRIEVAL</span>
          <h3>教材证据问答</h3>
          <p>{ragStatus?.indexed ? `${methodLabel} · ${ragStatus.chunk_count} 个知识块` : ragStatus?.message || '索引尚未构建'}</p>
        </div>
        {!readOnly && <Button icon={<ReloadOutlined />} loading={isBuilding} onClick={onBuildIndex}>
          {ragStatus?.indexed ? '重建' : '构建索引'}
        </Button>}
      </section>

      {ragStatus?.status === 'stale' && <Alert type="warning" showIcon message="教材内容已变化，请重建索引" />}

      <section className="rag-compose">
        <Radio.Group value={mode} onChange={(event) => setMode(event.target.value)} buttonStyle="solid">
          <Radio.Button value="all"><BookOutlined /> 课程问答</Radio.Button>
          <Radio.Button value="compare"><BranchesOutlined /> 跨教材对比</Radio.Button>
        </Radio.Group>
        {mode === 'compare' && (
          <Select
            mode="multiple"
            maxTagCount="responsive"
            placeholder="选择至少两本教材"
            value={selectedBooks}
            onChange={setSelectedBooks}
            options={textbooks.map((book) => ({ value: book.id, label: book.title }))}
          />
        )}
        <TextArea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); ask(); } }}
          rows={4}
          placeholder={mode === 'compare' ? '例：这几本教材对“形成性评价”的定义和教学建议有哪些共同点与差异？' : '输入知识点或教学问题，回答会附带教材、章节、页码与原文证据。'}
        />
        <Button type="primary" size="large" block icon={<SendOutlined />} loading={loading} disabled={!ragStatus?.indexed} onClick={ask}>
          {mode === 'compare' ? '生成跨教材证据对比' : '从课程教材中查找答案'}
        </Button>
      </section>

      {error && <Alert type="error" showIcon message={error} />}
      {loading && <div className="rag-loading"><Spin /><span>正在融合关键词、语义与知识网络证据…</span></div>}

      {result && !loading && (
        <section className="rag-result">
          <div className="rag-result-head">
            <span>回答</span>
            <Space>
              <Tag>{result.answer_method === 'llm_grounded' ? '证据约束生成' : '原文证据回退'}</Tag>
              <Tag color="cyan">{result.citations.length} 条引用</Tag>
            </Space>
          </div>
          <Typography.Paragraph className="rag-answer">{result.answer}</Typography.Paragraph>
          <div className="rag-trace">
            检索路径：{result.retrieval_trace?.retrievers?.join(' + ') || 'BM25'}
            {typeof result.retrieval_trace?.graph_expansions === 'number' && ` · 图谱扩展 ${result.retrieval_trace.graph_expansions} 条`}
          </div>
          <div className="evidence-stack">
            {result.citations.map((citation, index) => (
              <article className="evidence-card" key={citation.chunk_id || index}>
                <div className="evidence-card-head">
                  <span className="evidence-id">{citation.source_id || `S${index + 1}`}</span>
                  <strong>{citation.textbook}</strong>
                  <span>{citation.chapter} · 第 {citation.page_start || citation.page}{citation.page_end && citation.page_end !== citation.page_start ? `–${citation.page_end}` : ''} 页</span>
                </div>
                {citation.section_path && citation.section_path.length > 1 && (
                  <div className="evidence-path">{citation.section_path.join(' › ')}</div>
                )}
                <blockquote>{citation.quote || result.source_chunks[index]}</blockquote>
                <div className="evidence-signals">
                  {(citation.retrievers || []).map((retriever) => <Tag key={retriever}>{retriever}</Tag>)}
                  {citation.chunk_id && <code>{citation.chunk_id}</code>}
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {!loading && !result && !error && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="每条答案都可以回到教材原文" />}
    </div>
  );
};

export default RagPanel;
