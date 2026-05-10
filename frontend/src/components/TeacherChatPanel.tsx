import React, { useState, useRef, useEffect } from 'react';
import { Input, Button, Spin, Empty, Typography, message, Alert } from 'antd';
import {
  SendOutlined,
  RobotOutlined,
  UserOutlined,
  LoadingOutlined,
  MessageOutlined,
} from '@ant-design/icons';
import * as api from '../api/client';
import type { ChatMessage } from '../types';

const { TextArea } = Input;
const { Text } = Typography;

const TeacherChatPanel: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '您好！我是 MedEssence 教师助手。您可以向我询问关于整合决策的问题，例如：\n\n- "为什么将这两个概念合并？"\n- "请解释一下这个决策的置信度" \n- "能否修改某个概念的整合策略？"\n\n请告诉我您需要什么帮助。',
      timestamp: new Date().toISOString(),
    },
  ]);
  const [inputValue, setInputValue] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text) {
      message.warning('请输入消息');
      return;
    }

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');
    setSending(true);
    setError(null);

    try {
      const res = await api.sendChatMessage(text);
      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: res.data?.response || res.data?.detail || JSON.stringify(res.data),
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      const errMsg = err?.response?.data?.detail || err?.message || '发送失败，请稍后重试';
      setError(errMsg);
    } finally {
      setSending(false);
      // Focus input
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const formatTime = (ts: string) => {
    try {
      return new Date(ts).toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return '';
    }
  };

  return (
    <div className="chat-container">
      {/* Guidance hint */}
      <div
        style={{
          padding: '8px 12px',
          marginBottom: 8,
          fontSize: 12,
          color: '#888',
          background: '#f6f8fa',
          borderLeft: '3px solid #4ECDC4',
          borderRadius: 4,
          lineHeight: 1.6,
        }}
      >
        此面板用于修改整合决策。如需教材知识问答，请使用「教材问答」面板。
      </div>
      {/* Messages */}
      <div className="chat-messages">
        {messages.map((msg) => (
          <div key={msg.id} className={`chat-message ${msg.role}`}>
            <div>{msg.content}</div>
            <div
              className="chat-message-time"
              style={{
                textAlign: msg.role === 'user' ? 'right' : 'left',
                color: msg.role === 'user' ? 'rgba(255,255,255,0.7)' : undefined,
              }}
            >
              {formatTime(msg.timestamp)}
            </div>
          </div>
        ))}

        {sending && (
          <div className="chat-message assistant">
            <Spin size="small" />
            <span style={{ marginLeft: 8, fontSize: 12 }}>思考中...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error */}
      {error && (
        <Alert
          message={error}
          type="error"
          showIcon
          closable
          onClose={() => setError(null)}
          style={{ margin: '0 8px 8px', fontSize: 12 }}
        />
      )}

      {/* Input area */}
      <div className="chat-input-area">
        <TextArea
          ref={inputRef as any}
          rows={2}
          placeholder="输入您的问题..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending}
          style={{ flex: 1, fontSize: 13 }}
        />
        <Button
          type="primary"
          icon={sending ? <LoadingOutlined /> : <SendOutlined />}
          onClick={handleSend}
          loading={sending}
          disabled={sending}
          style={{
            height: 46,
            background: '#4ECDC4',
            borderColor: '#4ECDC4',
          }}
        >
          发送
        </Button>
      </div>
    </div>
  );
};

export default TeacherChatPanel;
