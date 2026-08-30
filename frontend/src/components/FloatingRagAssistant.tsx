import React, { useEffect, useRef, useState } from 'react';
import { Button } from 'antd';
import {
  CloseOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  HolderOutlined,
  MessageOutlined,
  MinusOutlined,
} from '@ant-design/icons';
import type { RagStatus, Textbook } from '../types';
import RagPanel from './RagPanel';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  courseId: string;
  courseTitle: string;
  textbooks: Textbook[];
  ragStatus: RagStatus | null;
  onBuildIndex: () => void;
  isBuilding: boolean;
  readOnly?: boolean;
}

interface Geometry { x: number; y: number; width: number; height: number }

const initialGeometry = (): Geometry => {
  const width = Math.min(480, Math.max(360, window.innerWidth - 40));
  const height = Math.min(680, Math.max(500, window.innerHeight - 110));
  return { x: Math.max(16, window.innerWidth - width - 24), y: Math.max(78, window.innerHeight - height - 24), width, height };
};

const FloatingRagAssistant: React.FC<Props> = ({
  open,
  onOpenChange,
  courseId,
  courseTitle,
  textbooks,
  ragStatus,
  onBuildIndex,
  isBuilding,
  readOnly = false,
}) => {
  const [geometry, setGeometry] = useState<Geometry>(initialGeometry);
  const [minimized, setMinimized] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [mobile, setMobile] = useState(window.innerWidth <= 620);
  const gesture = useRef<null | { type: 'drag' | 'resize'; startX: number; startY: number; geometry: Geometry }>(null);
  const savedGeometry = useRef<Geometry>(geometry);

  useEffect(() => {
    const onResize = () => {
      setMobile(window.innerWidth <= 620);
      setGeometry((current) => ({
        ...current,
        x: Math.min(current.x, Math.max(8, window.innerWidth - current.width - 8)),
        y: Math.min(current.y, Math.max(70, window.innerHeight - current.height - 8)),
      }));
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    const move = (event: PointerEvent) => {
      if (!gesture.current) return;
      const deltaX = event.clientX - gesture.current.startX;
      const deltaY = event.clientY - gesture.current.startY;
      const start = gesture.current.geometry;
      if (gesture.current.type === 'drag') {
        const maxX = Math.max(8, window.innerWidth - start.width - 8);
        const maxY = Math.max(68, window.innerHeight - start.height - 8);
        setGeometry({
          ...start,
          x: Math.max(8, Math.min(maxX, start.x + deltaX)),
          y: Math.max(68, Math.min(maxY, start.y + deltaY)),
        });
      } else {
        setGeometry({
          ...start,
          width: Math.max(360, Math.min(window.innerWidth - start.x - 8, start.width + deltaX)),
          height: Math.max(420, Math.min(window.innerHeight - start.y - 8, start.height + deltaY)),
        });
      }
    };
    const stop = () => { gesture.current = null; };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    };
  }, []);

  const toggleMaximize = () => {
    if (maximized) {
      setGeometry(savedGeometry.current);
      setMaximized(false);
      return;
    }
    savedGeometry.current = geometry;
    setGeometry({ x: 18, y: 78, width: window.innerWidth - 36, height: window.innerHeight - 96 });
    setMinimized(false);
    setMaximized(true);
  };

  if (!open) {
    return (
      <button className="rag-launcher" onClick={() => onOpenChange(true)} aria-label="打开教材问答">
        <MessageOutlined />
        <span><strong>向教材提问</strong><small>答案附带原文证据</small></span>
      </button>
    );
  }

  const panelGeometry = mobile
    ? { left: 8, top: 72, width: window.innerWidth - 16, height: window.innerHeight - 80 }
    : { left: geometry.x, top: geometry.y, width: geometry.width, height: minimized ? 58 : geometry.height };

  return (
    <aside className={`floating-rag ${minimized ? 'minimized' : ''} ${maximized ? 'maximized' : ''}`} style={panelGeometry} aria-label="教材问答悬浮窗">
      <header
        className="floating-rag-header"
        onPointerDown={(event) => {
          if (mobile || maximized || (event.target as HTMLElement).closest('button')) return;
          gesture.current = { type: 'drag', startX: event.clientX, startY: event.clientY, geometry };
        }}
      >
        <span className="floating-drag"><HolderOutlined /></span>
        <span className="floating-rag-mark"><MessageOutlined /></span>
        <div>
          <strong>教材问答</strong>
          <small>{courseTitle || '当前知识空间'}</small>
        </div>
        <div className="floating-rag-controls">
          <Button type="text" size="small" icon={<MinusOutlined />} aria-label={minimized ? '展开问答窗' : '最小化问答窗'} onClick={() => setMinimized((value) => !value)} />
          {!mobile && <Button type="text" size="small" icon={maximized ? <FullscreenExitOutlined /> : <FullscreenOutlined />} aria-label={maximized ? '还原问答窗' : '放大问答窗'} onClick={toggleMaximize} />}
          <Button type="text" size="small" icon={<CloseOutlined />} aria-label="关闭问答窗" onClick={() => onOpenChange(false)} />
        </div>
      </header>
      {!minimized && (
        <div className="floating-rag-body">
          <RagPanel
            compact
            courseId={courseId}
            textbooks={textbooks}
            ragStatus={ragStatus}
            onBuildIndex={onBuildIndex}
            isBuilding={isBuilding}
            readOnly={readOnly}
          />
        </div>
      )}
      {!mobile && !minimized && !maximized && (
        <button
          className="floating-resize-handle"
          aria-label="拖动调整问答窗大小"
          onPointerDown={(event) => {
            event.preventDefault();
            gesture.current = { type: 'resize', startX: event.clientX, startY: event.clientY, geometry };
          }}
        />
      )}
    </aside>
  );
};

export default FloatingRagAssistant;
