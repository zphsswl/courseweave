import assert from 'node:assert/strict';
import test from 'node:test';
import { chapterValidation, normalizedChapters, textbookWorkflow } from '../src/components/textbookWorkflow.ts';

const book = (overrides = {}) => ({ id: 'book-a', title: '参考教材', format: 'pdf', parse_status: 'completed', graph_status: 'pending', structure_status: 'confirmed', ...overrides });
const chapter = (id, overrides = {}) => ({ id, title: id, page_start: 1, page_end: 10, level: 1, char_count: 100, ...overrides });

test('a readable book awaiting chapter confirmation points to review and still supports readonly reading', () => {
  const current = book({ structure_status: 'review' });
  assert.equal(textbookWorkflow(current).action, 'review');
  assert.equal(textbookWorkflow(current).actionLabel, '核对章节');
  assert.equal(textbookWorkflow(current, undefined, true).action, 'read');
});

test('failed parsing is explicitly failed and offers retry rather than waiting', () => {
  const state = textbookWorkflow(book({ parse_status: 'failed' }), { status: 'failed', type: 'parse', error: '源文件读取失败' });
  assert.equal(state.label, '解析失败');
  assert.equal(state.action, 'parse');
  assert.equal(state.actionLabel, '重试解析');
  assert.equal(state.detail, '源文件读取失败');
  const staleProcessing = textbookWorkflow(book({ parse_status: 'processing' }), { status: 'failed', type: 'parse', error: '解析任务失败' });
  assert.equal(staleProcessing.action, 'parse');
  assert.equal(staleProcessing.processing, false);
});

test('graph work and graph failure do not block reading already parsed material', () => {
  const active = textbookWorkflow(book({ graph_status: 'processing' }), { type: 'extract_graph', status: 'processing', total: 100, progress: 42, message: '整理证据' });
  assert.equal(active.action, 'read');
  assert.equal(active.progress, 42);
  assert.equal(active.processing, true);
  const failed = textbookWorkflow(book({ graph_status: 'failed' }), { type: 'extract_graph', status: 'failed', error: '模型暂不可用' });
  assert.equal(failed.action, 'read');
  assert.equal(failed.tone, 'error');
  assert.equal(failed.detail, '模型暂不可用');
});

test('running parse tasks disable reading while work with unknown totals never invents a percentage', () => {
  const state = textbookWorkflow(book(), { type: 'parse', status: 'pending', total: 0, progress: 0 });
  assert.equal(state.action, 'wait');
  assert.equal(state.progress, null);
  assert.equal(textbookWorkflow(book({ parse_status: 'processing' })).progress, null);
});

test('readonly unparsed books never offer a mutating primary action', () => {
  assert.equal(textbookWorkflow(book({ parse_status: 'pending' }), undefined, true).action, 'wait');
  assert.equal(textbookWorkflow(book({ parse_status: 'failed' }), undefined, true).action, 'wait');
});

test('chapter validation rejects empty, inverted and out of book page ranges', () => {
  assert.ok(chapterValidation([], 12).length);
  assert.match(chapterValidation([chapter('A', { page_start: 8, page_end: 7 })], 12).join(''), /结束页不能早于/);
  assert.match(chapterValidation([chapter('A', { page_end: 13 })], 12).join(''), /超出本教材/);
  assert.match(chapterValidation([chapter('A', { page_start: 1.5 })], 12).join(''), /正整数/);
});

test('chapter validation checks title, order and non-skipping hierarchy', () => {
  assert.match(chapterValidation([chapter('A', { title: ' ' })], 12).join(''), /填写目录标题/);
  assert.match(chapterValidation([chapter('A'), chapter('B', { level: 3 })], 12).join(''), /不能跳级/);
  assert.match(chapterValidation([chapter('A', { page_start: 5 }), chapter('B', { page_start: 1 })], 12).join(''), /早于上一项/);
});

test('chapter edits rebuild parent IDs and stable display order without changing the input', () => {
  const input = [chapter('A', { order_index: 7 }), chapter('B', { title: ' B ', level: 2, parent_id: 'stale' }), chapter('C', { level: 3 }), chapter('D', { page_start: 11, page_end: 20 })];
  const result = normalizedChapters(input);
  assert.deepEqual(result.map(({ parent_id }) => parent_id), ['', 'A', 'B', '']);
  assert.deepEqual(result.map(({ order_index }) => order_index), [0, 1, 2, 3]);
  assert.equal(result[1].title, 'B');
  assert.equal(input[1].parent_id, 'stale');
  assert.equal(input[1].title, ' B ');
});

test('child page ranges must remain inside parent while same-page boundaries are allowed', () => {
  assert.equal(chapterValidation([chapter('A'), chapter('B', { level: 2, page_start: 3, page_end: 10 }), chapter('C', { page_start: 10, page_end: 20 })], 20).length, 0);
  assert.match(chapterValidation([chapter('A'), chapter('B', { level: 2, page_end: 11 })], 20).join(''), /位于上一级/);
});
