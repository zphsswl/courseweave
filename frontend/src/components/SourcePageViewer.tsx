import React, { useEffect, useState } from 'react';
import { Button, InputNumber, Spin } from 'antd';
import { MinusOutlined, PlusOutlined } from '@ant-design/icons';
import { pageImageUrl } from '../api/teaching';

interface Props { textbookId: string; title: string; page: number; totalPages: number; onPageChange: (page: number) => void; onClose?: () => void }

const SourcePageViewer: React.FC<Props> = ({ textbookId, title, page, totalPages, onPageChange, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(100);
  useEffect(() => { setLoading(true); setFailed(false); }, [textbookId, page]);
  const maxPage = Math.max(page, totalPages || 1);
  return (
    <section className="source-viewer" aria-label="教材原页">
      <header>
        <strong>教材原页</strong>
        <span>{title}</span>
        {onClose && <Button size="small" className="source-close" onClick={onClose} aria-label="关闭原页">关闭 ×</Button>}
        <div className="source-page-controls">
          <Button size="small" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="上一原页">←</Button>
          <label>PDF <InputNumber size="small" min={1} max={maxPage} value={page} onChange={(value) => value && onPageChange(Math.max(1, Math.min(maxPage, value)))} /> / {totalPages || '—'}</label>
          <Button size="small" disabled={page >= maxPage} onClick={() => onPageChange(page + 1)} aria-label="下一原页">→</Button>
          <Button size="small" icon={<MinusOutlined />} disabled={zoom <= 60} onClick={() => setZoom(zoom - 20)} aria-label="缩小原页" />
          <Button size="small" icon={<PlusOutlined />} disabled={zoom >= 200} onClick={() => setZoom(zoom + 20)} aria-label="放大原页" />
        </div>
      </header>
      <small className="source-page-note">按 PDF 文件页序定位；书内印刷页码可能不同。图文以原页为准。</small>
      <div className="source-image-scroll">
        {loading && !failed && <div className="source-loading"><Spin /> 正在加载原页…</div>}
        {failed ? <p className="teaching-empty" role="alert">此原页暂不可用。请检查源 PDF 是否保留，或继续阅读已解析正文。</p> : (
          <img key={`${textbookId}-${page}`} src={pageImageUrl(textbookId, page)} alt={`${title} PDF 第 ${page} 页`} style={{ width: `${zoom}%` }} onLoad={() => setLoading(false)} onError={() => { setFailed(true); setLoading(false); }} />
        )}
      </div>
    </section>
  );
};
export default SourcePageViewer;
