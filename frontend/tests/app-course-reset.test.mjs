import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

// Run the real App callbacks with state setters so all entry paths share the
// same reset contract, including automatic recovery from an unavailable space.
const source = fs.readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const start = source.indexOf('  const changeCourse = useCallback(');
const end = source.indexOf('\n  const loadTextbooks', start);
assert.ok(start >= 0 && end > start, 'the shared App course callbacks must be found');
const compiled = ts.transpileModule(source.slice(start, end), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const clean = (value) => JSON.parse(JSON.stringify(value));
function setup(serverCourses = [{ id: 'a', textbook_count: 1 }, { id: 'course_default', textbook_count: 2 }]) {
  const state = { courses: clean(serverCourses), selectedCourseId: 'a', workspace: 'agent',
    selectedTextbook: { id: 'a-book' }, compareQuery: 'A课题', compareBookIds: ['a-book'],
    agentContext: { topic: 'A课题', textbookIds: ['a-book'], intentId: 'a-intent' },
    agentRunId: 'a-run', lessonRunId: 'a-lesson' };
  const targetContext = { topic: '默认空间课题', textbookIds: ['default-book'], intentId: 'default-intent' };
  const storage = new Map([['courseweave:current-preparation:course_default', targetContext]]);
  const sandbox = { exports: {}, selectedCourseId: state.selectedCourseId, useCallback: (callback) => callback,
    readLocal: (key, fallback) => storage.has(key) ? clean(storage.get(key)) : fallback,
    api: { getCourses: async () => ({ data: clean(serverCourses) }) }, message: { error: () => {} } };
  for (const key of Object.keys(state)) sandbox['set' + key[0].toUpperCase() + key.slice(1)] = (value) => {
    state[key] = typeof value === 'function' ? value(state[key]) : value;
  };
  vm.runInNewContext(compiled + '\nexports.handlers = { changeCourse, handleCourseDeleted, loadCourses };', sandbox);
  return { state, storage, targetContext, ...sandbox.exports.handlers };
}
function assertReset(state, target, context) {
  assert.equal(state.selectedCourseId, target);
  assert.equal(state.workspace, 'library');
  assert.equal(state.selectedTextbook, null);
  assert.equal(state.compareQuery, '');
  assert.deepEqual(clean(state.compareBookIds), []);
  assert.equal(state.agentRunId, '');
  assert.equal(state.lessonRunId, '');
  if (context) assert.deepEqual(clean(state.agentContext), context);
  else assert.equal(state.agentContext, undefined);
}
test('manual course switching restores only the target preparation and clears open run state', () => {
  const current = setup();
  current.changeCourse('course_default');
  assertReset(current.state, 'course_default', current.targetContext);
});
test('deleting the active space uses the same reset and preserves target cached conditions', () => {
  const current = setup();
  current.handleCourseDeleted('a');
  assertReset(current.state, 'course_default', current.targetContext);
  assert.deepEqual(current.state.courses.map((course) => course.id), ['course_default']);
  assert.deepEqual(current.storage.get('courseweave:current-preparation:course_default'), current.targetContext);
});
test('deleting another space leaves the active preparation and historical editor selection untouched', () => {
  const current = setup(), before = clean(current.state);
  current.handleCourseDeleted('course_default');
  assert.deepEqual(clean({ ...current.state, courses: before.courses }), before);
});
test('missing space recovery clears foreign run state and restores the chosen fallback preparation', async () => {
  const current = setup([{ id: 'other', textbook_count: 1 }, { id: 'course_default', textbook_count: 3 }]);
  await current.loadCourses();
  assertReset(current.state, 'course_default', current.targetContext);
});
test('an existing active space survives course refresh without resetting teacher edits', async () => {
  const current = setup(), before = clean(current.state);
  await current.loadCourses();
  assert.deepEqual(clean(current.state), before);
});
