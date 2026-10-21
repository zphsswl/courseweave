import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DIRECTED, canvasEdges, canvasNodes, chunkConceptMap, conceptGroups,
  comparisonColumns, evidenceSelection, lessonPath, moveLessonGroup, sourceTitle, textbookColor, visibleConcepts,
} from '../src/components/crossbookModel.ts';

const passage = (id, key = undefined, overrides = {}) => ({
  id, chapter_id: 'chapter-a', chapter: '第二章 颈部', section_path: ['第二章 颈部', '（1）甲状腺'],
  title: '（1）甲状腺', source_heading: '（1）甲状腺', display_title: '甲状腺',
  title_origin: 'source_heading', ...(key ? { concept_key: key } : {}),
  page_start: 10, page_end: 11, quote: `${id} 的教材原文`, review_status: 'unreviewed', ...overrides,
});
const source = (id, book = 'book-a', key = undefined, overrides = {}) => ({
  ...evidenceSelection(passage(id, key), book, `教材 ${book}`), ...overrides,
});
const board = (selections = [], connections = [], overrides = {}) => ({
  id: 'board-a', course_id: 'course-a', topic: '甲状腺', textbook_ids: ['book-a', 'book-b'],
  revision: 1, selections, connections, ...overrides,
});
const result = (...groups) => ({ query: '甲状腺', method: 'lexical_only', groups });
const book = (id, ...items) => ({ textbook_id: id, title: `教材 ${id}`, items });
const link = (id, from, to, type = 'related_to', status = 'draft') => ({
  id, source_chunk_id: from, target_chunk_id: to, relation_type: type, status, reason: `${id} 的本课依据`,
});
const ids = (values) => values.map((value) => value.id);
const chunkIds = (values) => values.map((value) => value.chunk_id);
function freeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

test('same book/chapter source heading groups evidence while retaining ordered selected sources', () => {
  const data = result(book('book-a', passage('a1', 'heading:thyroid'), passage('a2', 'heading:thyroid')));
  const current = board([source('a2', 'book-a', 'heading:thyroid'), source('a1', 'book-a', 'heading:thyroid')]);
  const groups = conceptGroups(data, current);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].id, 'book-a:heading:thyroid');
  assert.deepEqual(chunkIds(groups[0].evidences), ['a1', 'a2']);
  assert.deepEqual(chunkIds(groups[0].selected), ['a2', 'a1']);
  assert.equal(groups[0].title, '甲状腺');
  assert.equal(groups[0].kind, 'source_heading');
  assert.equal(chunkConceptMap(groups).get('a1'), chunkConceptMap(groups).get('a2'));
});

test('book boundaries, different source keys and absent keys never merge matching labels', () => {
  const groups = conceptGroups(result(
    book('book-a', passage('a1', 'same-key'), passage('a2', 'other-key'), passage('a3'), passage('a4')),
    book('book-b', passage('b1', 'same-key')),
  ), board());
  assert.equal(groups.length, 5);
  assert.equal(new Set(ids(groups)).size, 5);
  assert.equal(groups.find((group) => group.evidences[0].chunk_id === 'a3').id, 'book-a:chunk:a3');
  assert.notEqual(chunkConceptMap(groups).get('a1'), chunkConceptMap(groups).get('b1'));
});

test('teacher titles change labels and provenance without changing or merging source identities', () => {
  const data = result(book('book-a', passage('a1', 'one'), passage('a2', 'two')));
  const before = conceptGroups(data, board());
  const selections = [source('a1', 'book-a', 'one', { teaching_title: '  教师统一显示名称  ' }),
    source('a2', 'book-a', 'two', { teaching_title: '教师统一显示名称' })];
  const after = conceptGroups(data, board(selections));
  assert.deepEqual(ids(after), ids(before));
  assert.equal(after.length, 2);
  assert.deepEqual(after.map((group) => group.title), ['教师统一显示名称', '教师统一显示名称']);
  assert.deepEqual(after.map((group) => group.kind), ['teacher', 'teacher']);
});

test('legacy evidence lacking metadata uses honest generic-heading fallback and stays chunk scoped', () => {
  const legacy = source('old', 'book-a', undefined, {
    concept_key: undefined, source_heading: undefined, display_title: undefined, title_origin: undefined,
    section_path: ['第二章 颈部', '2. 内容'],
  });
  assert.equal(sourceTitle(legacy, '甲状腺'), '甲状腺 · 原文片段');
  const [group] = conceptGroups(null, board([legacy]));
  assert.equal(group.kind, 'topic_excerpt');
  assert.equal(group.id, 'book-a:chunk:old');
  const actualHeading = { ...legacy, chunk_id: 'old-heading', section_path: ['第一章', '一、甲状腺'] };
  assert.equal(sourceTitle(actualHeading, '甲状腺'), '一、甲状腺');
});

test('only extends and prerequisite arrows are directed; dangling and intra-group links are omitted', () => {
  const selections = [source('a1', 'book-a', 'one'), source('a2', 'book-a', 'one'), source('b', 'book-b', 'two')];
  const groups = conceptGroups(null, board(selections));
  const types = ['equivalent_to', 'extends', 'prerequisite', 'contrasts_with', 'conflicts_with', 'related_to'];
  const connections = types.map((type, index) => link(`edge-${index}`, 'b', 'a1', type, index % 2 ? 'confirmed' : 'draft'));
  connections.push(link('same-group', 'a1', 'a2'), link('missing', 'a1', 'missing'));
  const edges = canvasEdges(connections, groups);
  assert.deepEqual([...DIRECTED].sort(), ['extends', 'prerequisite']);
  assert.equal(edges.length, 6);
  assert.deepEqual(edges.map((edge) => edge.directed), [false, true, true, false, false, false]);
  assert.ok(edges.every((edge) => edge.source === 'book-b:two' && edge.target === 'book-a:one'));
  assert.equal(edges[1].status, 'confirmed');
  assert.equal(edges[1].reason, 'edge-1 的本课依据');
});

test('lesson group movement preserves internal evidence order and does not mutate the board', () => {
  const current = freeze(board([source('a2', 'book-a', 'a'), source('b', 'book-b', 'b'),
    source('a1', 'book-a', 'a'), source('c', 'book-a', 'c')]));
  const snapshot = structuredClone(current);
  const groups = conceptGroups(null, current);
  assert.deepEqual(ids(lessonPath(groups, current)), ['book-a:a', 'book-b:b', 'book-a:c']);
  const moved = moveLessonGroup(current, groups, 'book-a:a', 1);
  assert.deepEqual(chunkIds(moved.selections), ['b', 'a2', 'a1', 'c']);
  assert.deepEqual(ids(lessonPath(groups, moved)), ['book-b:b', 'book-a:a', 'book-a:c']);
  assert.deepEqual(current, snapshot);
  assert.equal(moveLessonGroup(current, groups, 'book-a:a', -1), current);
  assert.equal(moveLessonGroup(current, groups, 'missing', 1), current);
});

test('exploration retains every one-hop neighbor even when the candidate limit is smaller', () => {
  const selected = [source('anchor', 'book-a', 'anchor'), ...Array.from({ length: 5 }, (_, i) => source(`n${i}`, 'book-b', `n${i}`)),
    source('unrelated', 'book-c', 'unrelated')];
  const current = board(selected);
  const groups = conceptGroups(null, current);
  const connections = Array.from({ length: 5 }, (_, i) => link(`edge-${i}`, 'anchor', `n${i}`));
  const edges = canvasEdges(connections, groups);
  const visible = visibleConcepts(groups, edges, 'book-a:anchor', 2, 'explore');
  assert.equal(visible.length, 6);
  assert.deepEqual(ids(visible), ['book-a:anchor', ...Array.from({ length: 5 }, (_, i) => `book-b:n${i}`)]);
  assert.ok(edges.every((edge) => ids(visible).includes(edge.source) && ids(visible).includes(edge.target)));
});

test('a small default exploration favors another textbook before more passages from the anchor book', () => {
  const groups = conceptGroups(result(book('book-a', passage('a1', 'a1'), passage('a2', 'a2')),
    book('book-b', passage('b1', 'b1'), passage('b2', 'b2'))), board());
  assert.deepEqual(ids(visibleConcepts(groups, [], 'book-a:a1', 2, 'explore')), ['book-a:a1', 'book-b:b1']);
});

test('book filtering affects the visible projection only and lesson view retains selected groups', () => {
  const current = freeze(board([source('a', 'book-a', 'a'), source('b', 'book-b', 'b')]));
  const data = freeze(result(book('book-c', passage('unselected', 'c'))));
  const groups = freeze(conceptGroups(data, current));
  const edges = freeze(canvasEdges([link('ab', 'a', 'b')], groups));
  const snapshot = structuredClone({ current, data, groups, edges });
  const visible = visibleConcepts(groups, edges, 'book-a:a', 3, 'explore', 'book-c');
  assert.deepEqual(ids(visible), ['book-a:a', 'book-c:c']);
  assert.equal(groups.length, 3);
  assert.equal(edges.length, 1);
  assert.deepEqual(ids(visibleConcepts(groups, edges, 'book-a:a', 1, 'lesson')), ['book-a:a', 'book-b:b']);
  assert.deepEqual({ current, data, groups, edges }, snapshot);
});

test('all projections accept deeply frozen inputs and keep saved evidence and source metadata intact', () => {
  const current = freeze(board([source('a', 'book-a', 'a', { note: '教师备注', dimension: '结构与组成' })]));
  const data = freeze(result(book('book-b', passage('b', 'b'))));
  const seed = freeze({ id: 'book-c:seed', evidences: [source('seed', 'book-c', 'seed')], selected: [] });
  const snapshot = structuredClone({ current, data, seed });
  const groups = conceptGroups(data, current, seed);
  const edges = canvasEdges([link('ab', 'a', 'b')], groups);
  const nodes = canvasNodes(visibleConcepts(groups, edges, 'book-a:a', 10, 'explore'), 'book-a:a');
  assert.equal(groups.length, 3);
  assert.equal(groups.find((group) => group.id === 'book-a:a').selected[0].note, '教师备注');
  assert.equal(nodes.find((node) => node.id === 'book-a:a').pageLabel, 'PDF 10–11');
  assert.equal(nodes.filter((node) => node.isAnchor).length, 1);
  assert.deepEqual({ current, data, seed }, snapshot);
});

test('comparison columns preserve book boundaries, teacher notes and exact requested passage', () => {
  const current = freeze(board([source('a2', 'book-a', 'a', { note: '教师核对过的备注', teaching_title: '本课标题' })]));
  const data = freeze(result(book('book-a', passage('a1', 'a'), passage('a2', 'a')),
    book('book-b', passage('b1', 'b'))));
  const groups = freeze(conceptGroups(data, current));
  const before = structuredClone({ groups, current, data });
  const columns = comparisonColumns(groups, ['book-b', 'book-a', 'book-a'], { 'book-a': 'a1' }, 'explore');
  assert.deepEqual(columns.map((column) => column.bookId), ['book-b', 'book-a']);
  assert.equal(columns[1].source.chunk_id, 'a1');
  assert.equal(columns[1].conceptId, 'book-a:a');
  assert.equal(columns[1].sources.find((item) => item.chunk_id === 'a2').note, '教师核对过的备注');
  assert.deepEqual({ groups, current, data }, before);
});

test('comparison recovers stale passage selection and lesson view cannot expose unselected evidence', () => {
  const current = freeze(board([source('a2', 'book-a', 'a')]));
  const groups = freeze(conceptGroups(result(book('book-a', passage('a1', 'a'), passage('a2', 'a')),
    book('book-b', passage('b1', 'b'))), current));
  const columns = comparisonColumns(groups, ['book-a', 'book-b'], { 'book-a': 'removed' }, 'lesson');
  assert.deepEqual(chunkIds(columns[0].sources), ['a2']);
  assert.equal(columns[0].source.chunk_id, 'a2');
  assert.deepEqual(columns[1].sources, []);
  assert.equal(columns[1].source, undefined);
  const candidates = comparisonColumns(groups, ['book-a', 'book-b'], { 'book-a': 'foreign-b1' }, 'explore');
  assert.equal(candidates[0].source.chunk_id, 'a2');
  assert.equal(candidates[1].source.chunk_id, 'b1');
});

test('textbook colour is stable across result order and comparison changes', () => {
  const first = ['book-a', 'book-b', 'book-c'].map((id) => [id, textbookColor(id)]);
  const reversed = new Map(['book-c', 'book-b', 'book-a'].map((id) => [id, textbookColor(id)]));
  for (const [id, colour] of first) {
    assert.match(colour, /^#[a-f0-9]{6}$/);
    assert.equal(reversed.get(id), colour);
  }
});

test('a material selected from the path stays visible alongside all real graph neighbours', () => {
  const groups = freeze(conceptGroups(null, board([source('a', 'book-a', 'a'), source('b', 'book-b', 'b'), source('c', 'book-c', 'c')])));
  const edges = canvasEdges([link('ab', 'a', 'b')], groups);
  const visible = visibleConcepts(groups, edges, 'book-a:a', 2, 'explore', '', 'book-c:c');
  assert.deepEqual(ids(visible), ['book-a:a', 'book-b:b', 'book-c:c']);
  assert.ok(edges.every((edge) => ids(visible).includes(edge.source) && ids(visible).includes(edge.target)));
});
