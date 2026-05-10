import React, { useState, useRef } from 'react';
import {
  Input,
  Button,
  Card,
  Tag,
  Space,
  Spin,
  Empty,
  Typography,
  Tooltip,
  Alert,
  message,
} from 'antd';
import {
  ThunderboltOutlined,
  SendOutlined,
  FileTextOutlined,
  BookOutlined,
  ReloadOutlined,
  LoadingOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import type { RagStatus, QueryResult, Citation } from '../types';
import * as api from '../api/client';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

interface Props {
  ragStatus: RagStatus | null;
  onBuildIndex: () => void;
  isBuilding: boolean;
}

const RagPanel: React.FC<Props> = ({ ragStatus, onBuildIndex, isBuilding }) => {
  const [question, setQuestion] = useState('');
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [expandedCitations, setExpandedCitations] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  const handleQuery = async () => {
    const q = question.trim();
    if (!q) {
      message.warning('请输入问题');
      return;
    }
    setQueryLoading(true);
    setError(null);
    setQueryResult(null);
    try {
      const res = await api.queryRag(q);
      setQueryResult(res.data);
      // Scroll to result
      setTimeout(() => {
        resultRef.current?.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || '查询失败，请检查 RAG 索引是否已构建';
      setError(errMsg);
    } finally {
      setQueryLoading(false);
    }
  };

  const toggleCitation = (idx: number) => {
    setExpandedCitations((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleQuery();
    }
  };

  return (
    <div>
      {/* RAG Status */}
      <div className="panel-section">
        <div className="panel-section-title">
          <Space>
            <ThunderboltOutlined />
            <span>RAG 知识库状态</span>
          </Space>
          <Button
            size="small"
            icon={isBuilding ? <LoadingOutlined /> : <ReloadOutlined />}
            onClick={onBuildIndex}
            loading={isBuilding}
          >
            {isBuilding ? '构建中...' : '构建索引'}
          </Button>
        </div>
        {ragStatus ? (
          <Card size="small" style={{ background: '#fafafa' }}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space>
                <Tag color={ragStatus.indexed ? 'green' : 'default'}>
                  {ragStatus.indexed ? '已索引' : '未索引'}
                </Tag>
                <span style={{ fontSize: 12, color: '#666' }}>
                  文档块: {ragStatus.chunk_count ?? 0}
                </span>
              </Space>
              <span style={{ fontSize: 12, color: '#666' }}>
                RAG 知识块: {ragStatus.chunk_count ?? 0}
              </span>
            </Space>
          </Card>
        ) : (
          <Card size="small" style={{ background: '#fafafa' }}>
            <div style={{ textAlign: 'center', padding: '8px 0' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                未检测到 RAG 索引，请先构建
              </Text>
            </div>
          </Card>
        )}
      </div>

      {/* Question Input */}
      <div className="panel-section">
        <div className="panel-section-title">
          <Space>
            <SearchOutlined />
            <span>知识问答</span>
          </Space>
        </div>
        <Space direction="vertical" style={{ width: '100%' }} size={8}>
          <TextArea
            rows={3}
            placeholder="请输入您的问题，例如：什么是糖尿病酮症酸中毒？"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={queryLoading}
          />
          <Button
            type="primary"
            icon={queryLoading ? <LoadingOutlined /> : <SendOutlined />}
            onClick={handleQuery}
            loading={queryLoading}
            disabled={!ragStatus?.indexed || isBuilding}
            block
            style={{ background: !ragStatus?.indexed ? undefined : '#4ECDC4', borderColor: '#4ECDC4' }}
          >
            {queryLoading ? '查询中...' : !ragStatus?.indexed ? '请先构建索引' : '发送问题'}
          </Button>
        </Space>
      </div>

      {/* Error */}
      {error && (
        <Alert
          message={error}
          type="error"
          showIcon
          closable
          style={{ marginBottom: 12, fontSize: 12 }}
        />
      )}

      {/* Result */}
      <div ref={resultRef}>
        {queryLoading && (
          <div className="loading-spinner">
            <Spin />
            <span style={{ marginLeft: 8, color: '#888', fontSize: 12 }}>正在查询知识库...</span>
          </div>
        )}

        {queryResult && (
          <>
            {/* Answer */}
            <div className="panel-section">
              <div className="panel-section-title">
                <Space>
                  <FileTextOutlined />
                  <span>回答</span>
                </Space>
                <Tag style={{ fontSize: 10 }}>
                  已检索 {queryResult.citations?.length || 0} 条引用
                </Tag>
              </div>
              <div className="rag-answer">{queryResult.answer}</div>
            </div>

            {/* Citations */}
            {queryResult.citations && queryResult.citations.length > 0 && (
              <div className="panel-section">
                <div className="panel-section-title">
                  <Space>
                    <BookOutlined />
                    <span>引用来源 ({queryResult.citations.length})</span>
                  </Space>
                </div>
                {queryResult.citations.map((cit, idx) => (
                  <div key={idx} className="citation-card">
                    <div
                      className={`citation-text ${expandedCitations.has(idx) ? 'expanded' : ''}`}
                    >
                      [{cit.textbook}, {cit.chapter}, 第{cit.page}页]
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                      <span className="citation-source">
                        {cit.textbook} / {cit.chapter}
                      </span>
                      <Tag color="green" style={{ fontSize: 10, lineHeight: '16px' }}>
                        相关度: {(cit.relevance_score * 100).toFixed(0)}%
                      </Tag>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Source Chunks */}
            {queryResult.source_chunks && queryResult.source_chunks.length > 0 && (
              <div className="panel-section">
                <div className="panel-section-title">
                  <Space>
                    <FileTextOutlined />
                    <span>原文片段 ({queryResult.source_chunks.length})</span>
                  </Space>
                </div>
                {queryResult.source_chunks.map((chunk, idx) => (
                  <div key={idx} className="citation-card">
                    <div
                      className={`citation-text ${expandedCitations.has(idx + 1000) ? 'expanded' : ''}`}
                      onClick={() => {
                        setExpandedCitations((prev) => {
                          const next = new Set(prev);
                          const key = idx + 1000;
                          if (next.has(key)) next.delete(key);
                          else next.add(key);
                          return next;
                        });
                      }}
                      style={{ cursor: 'pointer' }}
                    >
                      {chunk}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {!queryLoading && !queryResult && !error && (
          <div className="empty-state" style={{ padding: '24px 16px' }}>
            <SearchOutlined style={{ fontSize: 32, opacity: 0.3 }} />
            <div className="empty-state-text" style={{ marginTop: 8 }}>
              输入问题并发送以获取回答
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default RagPanel;
