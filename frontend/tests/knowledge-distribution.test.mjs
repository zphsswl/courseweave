import assert from 'node:assert/strict';
import test from 'node:test';
import { distributionBookTotals, distributionNodeOrder, distributionNodePathIds, distributionNodePaths, distributionNodeTitles } from '../src/components/knowledgeDistributionModel.ts';

const source = (id, overrides = {}) => ({
  id, chunk_id: id, textbook_id: 'book-a', textbook_title: '教材 A', chapter: '第一章', chapter_id: 'chapter-a',
  section_path: ['第一章', '第一节', '位置与形态'], section_path_ids: ['chapter-a', 'section-a', 'leaf-a'],
  page_start: 3, page_end: 4, quote: `${id} 的原文`, dimension: '未归类', note: '', ...overrides,
});
const group = (id, evidences = [source(id)], overrides = {}) => ({
  id, bookId: 'book-a', bookTitle: '教材 A', title: '甲状腺', kind: 'source_heading', evidences, selected: [], ...overrides,
});
const result = (...books) => ({ groups: books });
const response = (id, ids = [], overrides = {}) => ({ textbook_id: id, title: id, items: ids.map((id) => ({ id })), ...overrides });
const freeze = (value) => {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
};

test('source paths retain explicit hierarchy and module identities without inventing semantic relations', () => {
  const groups = [group('module-a')];
  assert.deepEqual(distributionNodePaths(groups).get('module-a'), ['第一章', '第一节', '位置与形态']);
  const keys = distributionNodePathIds(groups).get('module-a');
  assert.equal(keys.length, 3);
  assert.ok(keys[2].includes('leaf-a'));
  assert.equal(distributionNodePaths(groups).has('甲状腺'), false);
});

test('matching names in different books do not merge modules or directory branch identities', () => {
  const groups = [group('book-a:module'), group('book-b:module', [source('b', { textbook_id: 'book-b' })], { bookId: 'book-b', bookTitle: '教材 B' })];
  const keys = distributionNodePathIds(groups);
  assert.notEqual(keys.get('book-a:module')[0], keys.get('book-b:module')[0]);
  assert.deepEqual(distributionBookTotals(groups).map(({ moduleCount }) => moduleCount), [1, 1]);
});

test('same-label chapters with different explicit IDs remain different locations within one book', () => {
  const groups = [group('one'), group('two', [source('two', { chapter_id: 'chapter-other', section_path_ids: ['chapter-other', 'section-other', 'leaf-other'] })])];
  assert.deepEqual(distributionNodePaths(groups).get('one'), distributionNodePaths(groups).get('two'));
  assert.notEqual(distributionNodePathIds(groups).get('one')[0], distributionNodePathIds(groups).get('two')[0]);
});

test('modules spanning different leaves use the common source ancestor rather than the first leaf', () => {
  const groups = [group('one', [source('a'), source('b', { section_path: ['第一章', '第一节', '功能'], section_path_ids: ['chapter-a', 'section-a', 'leaf-b'] })])];
  assert.deepEqual(distributionNodePaths(groups).get('one'), ['第一章', '第一节']);
  assert.equal(distributionNodePathIds(groups).get('one').length, 2);
});

test('identical heading labels cannot extend common ancestry beyond mismatched explicit identities', () => {
  const groups = [group('one', [source('a'), source('b', { section_path_ids: ['chapter-a', 'different-section', 'different-leaf'] })])];
  assert.deepEqual(distributionNodePaths(groups).get('one'), ['第一章']);
  const uncertain = [group('one', [source('a'), source('b', { section_path_ids: [] })])];
  assert.deepEqual(distributionNodePaths(uncertain).get('one'), ['第一章']);
});

test('missing directory metadata never turns a teacher title or topic into an invented chapter', () => {
  const groups = [group('one', [source('a', { chapter: '', chapter_id: '', section_path: [], section_path_ids: [] })], { title: '教师起的新标题' })];
  assert.deepEqual(distributionNodePaths(groups).get('one'), []);
  assert.deepEqual(distributionNodePathIds(groups).get('one'), []);
});

test('chapter fallback is inserted only from source metadata, preserving repeated nested headings', () => {
  const groups = [group('one', [source('a', { chapter: '概述', chapter_id: 'intro', section_path: ['概述', '概述'], section_path_ids: ['intro', 'intro-section'] })]), group('two', [source('b', { section_path: ['位置与形态'], section_path_ids: ['leaf-a'] })])];
  assert.deepEqual(distributionNodePaths(groups).get('one'), ['概述', '概述']);
  assert.deepEqual(distributionNodePaths(groups).get('two'), ['第一章', '位置与形态']);
});

test('labels and branch keys stay deterministic under input permutation and teacher display edits', () => {
  const groups = [group('z', [source('z')]), group('a', [source('a')])];
  const renamed = groups.map((item) => ({ ...item, title: '改过的显示标题', selected: [...item.evidences] })).reverse();
  assert.deepEqual([...distributionNodePaths(groups)], [...distributionNodePaths(renamed)]);
  assert.deepEqual([...distributionNodePathIds(groups)], [...distributionNodePathIds(renamed)]);
  assert.deepEqual(distributionNodeOrder(groups), distributionNodeOrder(renamed));
});

test('stable layout input order follows explicit book scope and source page, never display title or selected status', () => {
  const groups = [group('late', [source('late', { page_start: 20 })]), group('b', [source('b', { textbook_id: 'book-b', page_start: 1 })], { bookId: 'book-b' }), group('early', [source('early', { page_start: 2 })])];
  assert.deepEqual(distributionNodeOrder(groups, ['book-b', 'book-a']), ['b', 'early', 'late']);
  assert.deepEqual(distributionNodeOrder([...groups].reverse(), ['book-b', 'book-a']), ['b', 'early', 'late']);
});

test('module count, retained passage count, selected count and retrieved passage pagination stay separate', () => {
  const groups = [group('one', [source('a'), source('b')], { selected: [source('b')] }), group('two', [source('retained')], { selected: [source('retained')] })];
  const [book] = distributionBookTotals(groups, result(response('book-a', ['a', 'b'], { total_matches: 9, has_more: true })), [{ id: 'book-a', title: '教材 A' }]);
  assert.deepEqual([book.moduleCount, book.evidenceCount, book.selectedModuleCount, book.selectedEvidenceCount], [2, 3, 2, 2]);
  assert.equal(book.loaded, 2);
  assert.equal(book.total, 9);
  assert.equal(book.loadState, 'partial');
  assert.equal(book.completeForQuery, false);
});

test('explicit book scope retains zero-hit and not-yet-loaded books without claiming all knowledge is loaded', () => {
  const books = distributionBookTotals([], result(response('book-a', [], { total_matches: 0, has_more: false })), [{ id: 'book-b', title: 'B' }, { id: 'book-a', title: 'A' }]);
  assert.deepEqual(books.map(({ id }) => id), ['book-b', 'book-a']);
  assert.deepEqual([books[0].loaded, books[0].total, books[0].loadState, books[0].completeForQuery], [0, null, 'not_loaded', false]);
  assert.deepEqual([books[1].loaded, books[1].total, books[1].loadState, books[1].completeForQuery], [0, 0, 'loaded', true]);
  assert.equal('allKnowledgeLoaded' in books[1], false);
});

test('unknown or inconsistent totals never claim complete query coverage', () => {
  for (const metadata of [{}, { total_matches: -1 }, { total_matches: 1.5 }, { total_matches: 0 }, { total_matches: 3, has_more: false }, { total_matches: 1, has_more: true }]) {
    const [book] = distributionBookTotals([], result(response('book-a', ['a'], metadata)));
    assert.equal(book.completeForQuery, false, JSON.stringify(metadata));
  }
  const [complete] = distributionBookTotals([], result(response('book-a', ['a'], { total_matches: 1, has_more: false })));
  assert.equal(complete.completeForQuery, true);
});

test('duplicate passage records are counted once and books outside explicit scope are excluded', () => {
  const groups = [group('one', [source('a'), source('a')], { selected: [source('a'), source('a')] }), group('foreign', [source('f', { textbook_id: 'book-foreign' })], { bookId: 'book-foreign' })];
  const books = distributionBookTotals(groups, result(response('book-a', ['a', 'a'], { total_matches: 1 })), [{ id: 'book-a', title: 'A' }]);
  assert.equal(books.length, 1);
  assert.deepEqual([books[0].loaded, books[0].evidenceCount, books[0].selectedEvidenceCount], [1, 1, 1]);
});

test('foreign-book evidence cannot assign a module to the foreign source path and all helpers preserve input', () => {
  const groups = freeze([group('one', [source('a'), source('foreign', { textbook_id: 'book-b', chapter: '外部章节', section_path: ['外部章节'] })], { selected: [source('a')] })]);
  const before = JSON.stringify(groups);
  assert.deepEqual(distributionNodePaths(groups).get('one'), ['第一章', '第一节', '位置与形态']);
  assert.equal(distributionBookTotals(groups)[0].evidenceCount, 1);
  distributionNodePathIds(groups); distributionNodeOrder(groups);
  assert.equal(JSON.stringify(groups), before);
});

test('generic topic excerpts use the deepest meaningful source label, skipping numbered boilerplate', () => {
  const groups = [group('one', [source('a', { chapter: '第二章 颈部', section_path: ['第二章 颈部', '第一节 局部结构', '2. 内容', '本章正文'] })], { kind: 'topic_excerpt', title: '甲状腺 · 原文片段' })];
  assert.equal(distributionNodeTitles(groups).get('one'), '第一节 局部结构 · 相关原文');
});

test('excerpt titles fall back unchanged when all source headings are generic or unavailable', () => {
  for (const location of [
    { chapter: '概述', section_path: ['概述', '2.内容', '正文', '本章正文'] },
    { chapter: '第一章 概论', section_path: ['第一章 概论', '（二）正文'] },
    { chapter: '', section_path: [], section_path_ids: [] },
  ]) {
    const groups = [group('one', [source('a', location)], { kind: 'topic_excerpt', title: '甲状腺 · 原文片段' })];
    assert.equal(distributionNodeTitles(groups).get('one'), '甲状腺 · 原文片段');
  }
});

test('source headings, subheadings and teacher-assigned names are never rewritten', () => {
  const groups = ['source_heading', 'source_subheading', 'teacher'].map((kind) => group(kind, [source(kind)], { kind, title: `${kind} 的原有标题` }));
  groups.push(group('teacher-in-legacy-kind', [source('legacy')], { kind: 'topic_excerpt', title: '教师保留的标题', selected: [source('legacy', { teaching_title: '教师保留的标题' })] }));
  for (const item of groups) assert.equal(distributionNodeTitles(groups).get(item.id), item.title);
});

test('excerpt naming uses the common source ancestor, never one arbitrary leaf or a changed module identity', () => {
  const groups = freeze([group('module-a', [
    source('a', { chapter: '第二章 颈部', section_path: ['第二章 颈部', '位置'], section_path_ids: ['neck', 'position'] }),
    source('b', { chapter: '第二章 颈部', section_path: ['第二章 颈部', '功能'], section_path_ids: ['neck', 'function'] }),
  ], { kind: 'topic_excerpt', title: '甲状腺 · 原文片段' })]);
  const before = JSON.stringify(groups), titles = distributionNodeTitles(groups);
  assert.deepEqual([...titles], [['module-a', '第二章 颈部 · 相关原文']]);
  assert.equal(JSON.stringify(groups), before);
  assert.equal(groups[0].kind, 'topic_excerpt');
  assert.deepEqual(distributionNodeOrder(groups), ['module-a']);
});
