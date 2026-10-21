import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

// Execute the real pure helpers from the TSX module. React rendering and parent
// callback/effect timing are covered by browser verification, not this harness.
const source = fs.readFileSync(new URL('../src/components/AgentWorkbench.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const clean = (value) => JSON.parse(JSON.stringify(value));
const books = ['a', 'b', 'c'].map((id) => ({ id, course_id: 'course-a' }));
const storageKey = 'courseweave:lesson-brief:course-a';
const delta = (chunkId, textbookId = 'c', courseId = 'course-a') => ({ chunkId, textbookId, courseId });
const intent = (items = [delta('s3'), delta('s4'), delta('s3')], intentId = 'collect-batch') => ({
  intentId, topic: '父级过期主题', boardId: 'stale-board', selectedChunkIds: ['stale-source'],
  textbookIds: ['c'], collectedEvidence: items,
});
const brief = () => ({
  courseId: 'course-a', dirty: true, appliedIntentId: 'before',
  value: { topic: '当前课堂主题', goal: '学生能比较三种条件', audience: '一年级护理',
    priorKnowledge: '已学基础结构', bookIds: ['a', 'b'], requirements: ['核心概念', '课堂提问'],
    duration: 50, questions: 4, focusTerms: ['形态'] },
  originContext: { topic: '当前课堂主题', textbookIds: ['a', 'b'], boardId: 'own-board',
    selectedChunkIds: ['s1'], supplementalChunkIds: ['s2'], sectionId: 'own-section' },
});

function setup() {
  const storage = new Map();
  const sandbox = {
    exports: {},
    require: (name) => name === '../api/lessonAgent' ? { normalizedArtifact: (value) => value } : {},
    localStorage: { getItem: (key) => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    Intl, Date, Set, Map, JSON,
  };
  vm.runInNewContext(compiled + '\nexports.testHelpers = { mergeCollectedEvidence, restoreBrief, freshBrief, conditionsFromRun, collectionOwner, ownedLessonContext, citationPresentation };', sandbox);
  return { storage, ...sandbox.exports.testHelpers };
}

test('collecting into an existing brief preserves teaching conditions and its own board', () => {
  const { mergeCollectedEvidence: merge } = setup();
  const current = brief(), before = clean(current);
  const next = merge(current, books, intent());
  assert.deepEqual(clean(next.value), { ...before.value, bookIds: ['a', 'b', 'c'] });
  assert.equal(next.originContext.boardId, 'own-board');
  assert.equal(next.originContext.sectionId, 'own-section');
  assert.equal(next.originContext.topic, current.value.topic);
  assert.deepEqual(clean(current), before);
});

test('all pending collections survive one merge and duplicate chunks do not multiply sources', () => {
  const { mergeCollectedEvidence: merge } = setup();
  const next = merge(brief(), books, intent());
  assert.deepEqual(clean(next.originContext.selectedChunkIds), ['s1']);
  assert.deepEqual(clean(next.originContext.supplementalChunkIds), ['s2', 's3', 's4']);
  assert.equal(merge(next, books, intent()), next);
  const repeated = merge(next, books, intent([delta('s3'), delta('s4')], 'another-intent'));
  assert.deepEqual(clean(repeated.originContext.supplementalChunkIds), ['s2', 's3', 's4']);
});

test('legacy single-object collection merges into selected sources when no board exists', () => {
  const { mergeCollectedEvidence: merge } = setup();
  const current = brief();
  current.originContext = { topic: current.value.topic, textbookIds: ['a', 'b'], selectedChunkIds: ['s1'] };
  const next = merge(current, books, intent(delta('legacy-source')));
  assert.equal(next.originContext.boardId, undefined);
  assert.deepEqual(clean(next.originContext.selectedChunkIds), ['s1', 'legacy-source']);
});

test('source and textbook limits reject the whole batch without partially changing conditions', () => {
  const { mergeCollectedEvidence: merge } = setup();
  const current = brief();
  current.originContext.selectedChunkIds = Array.from({ length: 47 }, (_, index) => 'source-' + index);
  current.originContext.supplementalChunkIds = [];
  const rejected = merge(current, books, intent());
  assert.match(rejected.collectionNotice, /48/);
  assert.deepEqual(clean(rejected.value), clean(current.value));
  assert.deepEqual(clean(rejected.originContext), clean(current.originContext));
  assert.equal(merge(current, books, intent([delta('s3')])).originContext.supplementalChunkIds.length, 1);
  const manyBooks = Array.from({ length: 13 }, (_, index) => ({ id: 'book-' + index, course_id: 'course-a' }));
  const atBookLimit = { ...brief(), value: { ...brief().value, bookIds: manyBooks.slice(0, 12).map((book) => book.id) } };
  const tooManyBooks = merge(atBookLimit, manyBooks, intent([delta('new-source', 'book-12')]));
  assert.match(tooManyBooks.collectionNotice, /12/);
  assert.deepEqual(clean(tooManyBooks.value), clean(atBookLimit.value));
});

test('a foreign-course entry prevents the batch from adding any source', () => {
  const { mergeCollectedEvidence: merge } = setup();
  const current = brief();
  const rejected = merge(current, books, intent([delta('s3'), delta('foreign-source', 'c', 'foreign-course')]));
  assert.match(rejected.collectionNotice, /课程/);
  assert.deepEqual(clean(rejected.value), clean(current.value));
  assert.deepEqual(clean(rejected.originContext), clean(current.originContext));
});

test('first collection seeds the question and every collected book without inheriting a stale board', () => {
  const { restoreBrief: restore } = setup();
  const next = restore('course-a', books, { ...intent([delta('s3', 'b'), delta('s4', 'c')]), topic: '首次问题主题' });
  assert.equal(next.value.topic, '首次问题主题');
  assert.deepEqual(clean(next.value.bookIds), ['b', 'c']);
  assert.equal(next.originContext.boardId, undefined);
  assert.deepEqual(clean(next.originContext.selectedChunkIds), ['s3', 's4']);
});

test('cached teaching conditions survive collection and refreshing an already applied intent is idempotent', () => {
  const { storage, restoreBrief: restore } = setup();
  const current = brief();
  storage.set(storageKey, JSON.stringify(current));
  const next = restore('course-a', books, intent());
  assert.equal(next.value.audience, current.value.audience);
  assert.equal(next.value.priorKnowledge, current.value.priorKnowledge);
  assert.equal(next.value.goal, current.value.goal);
  assert.equal(next.originContext.boardId, current.originContext.boardId);
  storage.set(storageKey, JSON.stringify(next));
  assert.deepEqual(clean(restore('course-a', books, intent())), clean(next));
});

test('consumed context is owned by the brief and excludes the frontend collection payload', () => {
  const { mergeCollectedEvidence: merge, ownedLessonContext: owned } = setup();
  const next = merge(brief(), books, intent());
  const result = owned(next);
  assert.equal(result.collectedEvidence, undefined);
  assert.equal(result.topic, '当前课堂主题');
  assert.equal(result.boardId, 'own-board');
  assert.deepEqual(clean(result.textbookIds), ['a', 'b', 'c']);
});

test('new blank lesson stays blank after consumed-context refresh and may collect the same source again', () => {
  const { storage, restoreBrief: restore, freshBrief: fresh, mergeCollectedEvidence: merge, ownedLessonContext: owned } = setup();
  const previouslyMerged = merge(brief(), books, intent());
  const consumed = { ...owned(previouslyMerged), intentId: 'collect-batch' };
  const blank = { ...fresh('course-a', books), dirty: true, appliedIntentId: 'collect-batch' };
  storage.set(storageKey, JSON.stringify(blank));
  assert.equal(restore('course-a', books, consumed).value.topic, '');
  const next = merge(blank, books, intent([delta('s3')], 'new-lesson-intent'));
  assert.deepEqual(clean(next.originContext.selectedChunkIds), ['s3']);
  assert.equal(next.originContext.boardId, undefined);
});

test('collecting while viewing a historical lesson reuses that lesson request and its own source context', () => {
  const { conditionsFromRun: fromRun, mergeCollectedEvidence: merge } = setup();
  const run = { course_id: 'course-a', result: { topic: '旧运行主题', goal: '运行目标', textbook_ids: ['a'], requirements: [],
    request: { topic: '选中教案主题', audience: '选中教案学生', prior_knowledge: '选中教案基础', duration_minutes: 60,
      question_count: 2, textbook_ids: ['a'], context: { board_id: 'run-board', selected_chunk_ids: ['run-source'] } } } };
  const before = clean(run);
  const next = merge(fromRun(run, 'course-a', 'before'), books, intent());
  assert.equal(next.value.topic, '选中教案主题');
  assert.equal(next.value.audience, '选中教案学生');
  assert.equal(next.value.priorKnowledge, '选中教案基础');
  assert.equal(next.value.duration, 60);
  assert.equal(next.originContext.boardId, 'run-board');
  assert.deepEqual(clean(next.originContext.selectedChunkIds), ['run-source']);
  assert.deepEqual(clean(next.originContext.supplementalChunkIds), ['s3', 's4']);
  assert.deepEqual(clean(run), before);
});

test('preview return defers collection until the explicitly selected historical lesson loads', () => {
  const { storage, restoreBrief: restore, collectionOwner: owner } = setup();
  const current = brief(), before = clean(current), pending = intent();
  storage.set(storageKey, JSON.stringify(current));
  const restored = restore('course-a', books, pending, 'run-b');
  assert.deepEqual(clean(restored), before);
  assert.equal(restored.appliedIntentId, 'before');
  assert.equal(owner(restored, 'run-b', null), null);
  assert.equal(owner(restored, 'run-b', { id: 'run-a', course_id: 'course-a' }), null);
  assert.equal(owner(restored, 'run-b', { id: 'run-b', course_id: 'foreign-course' }), null);
  assert.deepEqual(JSON.parse(storage.get(storageKey)), before);
});

test('cold preview collection uses B conditions and sources while retaining A for recovery', () => {
  const { storage, restoreBrief: restore, collectionOwner: owner, mergeCollectedEvidence: merge } = setup();
  const current = brief(), before = clean(current), pending = intent();
  storage.set(storageKey, JSON.stringify(current));
  const restored = restore('course-a', books, pending, 'run-b');
  const run = { id: 'run-b', course_id: 'course-a', result: { topic: 'B 主题', goal: 'B 目标', textbook_ids: ['b'], requirements: [],
    request: { audience: 'B 学情', prior_knowledge: 'B 先修知识', duration_minutes: 45, textbook_ids: ['b'],
      context: { board_id: 'b-board', selected_chunk_ids: ['b-source'] } } } };
  const base = owner(restored, 'run-b', run);
  assert.notEqual(base, null);
  const next = merge(base, books, pending);
  assert.equal(next.value.topic, 'B 主题');
  assert.equal(next.value.goal, 'B 目标');
  assert.equal(next.value.audience, 'B 学情');
  assert.equal(next.value.priorKnowledge, 'B 先修知识');
  assert.equal(next.value.duration, 45);
  assert.equal(next.originContext.boardId, 'b-board');
  assert.deepEqual(clean(next.originContext.selectedChunkIds), ['b-source']);
  assert.deepEqual(clean(next.originContext.supplementalChunkIds), ['s3', 's4']);
  assert.equal(next.appliedIntentId, pending.intentId);
  assert.deepEqual(JSON.parse(storage.get(storageKey)), before);
  assert.equal(owner(restored, null, run), restored);
});

test('a preview return without cached conditions does not seed or consume the queued question early', () => {
  const { restoreBrief: restore, collectionOwner: owner } = setup();
  const restored = restore('course-a', books, intent(), 'run-b');
  assert.equal(restored.value.topic, '');
  assert.equal(restored.appliedIntentId, undefined);
  assert.equal(restored.originContext, undefined);
  assert.equal(owner(restored, 'run-b', null), null);
});

test('PDF citations retain their real page range and original-page target', () => {
  const { citationPresentation: present } = setup();
  const source = { textbook_id: 'a', textbook: 'PDF教材', chapter: '第一章', page_start: 12, page_end: 14 };
  const result = present(source, [{ id: 'a', format: 'pdf', total_pages: 100 }]);
  assert.equal(result.location, 'PDF 12–14 页');
  assert.deepEqual(clean(result.page), { bookId: 'a', title: 'PDF教材', page: 12, total: 100 });
  assert.equal(present({ ...source, page_start: 0 }, [{ id: 'a', format: 'pdf' }]).page, null);
});

test('Word, text and unavailable books use source context without an image-page target', () => {
  const { citationPresentation: present } = setup();
  const source = { textbook_id: 'a', textbook: '非PDF教材', chapter: '第一章', section_path: ['第一章', '甲状腺'], page_start: 12, page_end: 14 };
  for (const format of ['doc', 'docx', 'txt', '']) {
    const result = present(source, [{ id: 'a', format, total_pages: 100 }]);
    assert.equal(result.location, '原文位置 · 第一章 / 甲状腺');
    assert.equal(result.page, null, format + ' must never enable the PDF image viewer');
  }
  assert.equal(present(source, []).page, null);
  assert.equal(present({ ...source, section_path: [] }, []).location, '原文位置 · 第一章');
});
