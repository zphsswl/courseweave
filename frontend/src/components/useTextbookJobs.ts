import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api/client';
import type { Job } from '../types';

export function useTextbookJobs(courseId: string, onCompleted: () => void) {
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  const completed = useRef(onCompleted); completed.current = onCompleted;
  const seen = useRef<Record<string, string>>({});
  const owner = useRef(courseId);
  useEffect(() => { owner.current = courseId; seen.current = {}; setJobs({}); }, [courseId]);
  const track = useCallback((job: Job, bookId: string) => {
    seen.current[job.id] = job.status;
    setJobs((current) => ({ ...current, [bookId]: job })); setVersion((current) => current + 1);
  }, []);
  useEffect(() => {
    const controller = new AbortController(); let timer: number | undefined;
    const pull = async () => {
      try {
        const { data } = await api.getTextbookJobs(courseId, controller.signal);
        if (controller.signal.aborted || owner.current !== courseId) return;
        const next: Record<string, Job> = {}; let finished = false;
        for (const job of data) {
          const book = job.payload?.textbook_id;
          if (typeof book !== 'string') continue;
          next[book] = job;
          if (['pending', 'processing'].includes(seen.current[job.id]) && job.status === 'completed') finished = true;
          seen.current[job.id] = job.status;
        }
        setJobs(next); setError(''); if (finished) completed.current();
        if (data.some((job) => ['pending', 'processing'].includes(job.status))) timer = window.setTimeout(pull, 2000);
      } catch {
        if (!controller.signal.aborted) { setError('暂时无法读取教材处理状态，正在自动重试；后台任务会继续。'); timer = window.setTimeout(pull, 5000); }
      }
    };
    pull(); return () => { controller.abort(); if (timer) window.clearTimeout(timer); };
  }, [courseId, version]);
  return { jobs, track, error, refresh: () => setVersion((current) => current + 1) };
}
