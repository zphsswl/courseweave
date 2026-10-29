import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

// Exercise the actual UI async handlers. Controlled promises represent a server
// response arriving after another click or after the owner course/run changed.
const source = fs.readFileSync(new URL('../src/components/AgentWorkbench.tsx', import.meta.url), 'utf8');
const start = source.indexOf('  const continueRun = async');
const end = source.indexOf('\n  const validateDraft', start);
assert.ok(start >= 0 && end > start, 'the real continuation handlers must be found');
const compiled = ts.transpileModule(source.slice(start, end), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
function setup(overrides = {}) {
  const requests = [], accepted = [], removed = [], drafts = [], notices = [];
  let current = true, active = false, finished = 0;
  const request = (kind) => (...args) => new Promise((resolve, reject) => requests.push({ kind, args, resolve, reject }));
  const sandbox = { exports: {}, run: { id: 'run-a', course_id: 'course-a', status: 'waiting_user' }, readOnly: false,
    execution: { canRespond: true, canCancel: true, canResume: false, approval: { requestId: 'question-a' } },
    teacherAnswer: '  先讲位置与形态  ', answerKey: 'answer:course-a:run-a:question-a',
    beginMutation: () => { if (active) return null; active = true; return { controller: new AbortController(), valid: () => current }; },
    finishMutation: () => { active = false; finished++; },
    acceptRun: (next, expectedId) => { accepted.push({ next, expectedId }); return next.id === expectedId && next.course_id === 'course-a'; },
    respondLessonRun: request('respond'), cancelLessonRun: request('cancel'), resumeLessonRun: request('resume'), retryLessonRun: request('retry'),
    removeLocal: (key) => removed.push(key), setAnswerDraft: (draft) => drafts.push(draft),
    errorText: (_error, fallback) => fallback, cancelled: (error) => error?.name === 'AbortError',
    message: Object.fromEntries(['warning', 'error', 'success', 'info'].map((kind) => [kind, (text) => notices.push({ kind, text })])), ...overrides };
  vm.runInNewContext(compiled + '\nexports.actions = { continueRun, respondToTeacherQuestion, cancelRun };', sandbox);
  return { sandbox, requests, accepted, removed, drafts, notices, ...sandbox.exports.actions,
    switchOwner: () => { current = false; }, get finished() { return finished; } };
}
const response = (status = 'processing') => ({ id: 'run-a', course_id: 'course-a', status });

test('a repeated teacher submit sends one answer with its original question identity', async () => {
  const state = setup();
  const first = state.respondToTeacherQuestion();
  await state.respondToTeacherQuestion();
  assert.equal(state.requests.length, 1);
  assert.equal(state.requests[0].kind, 'respond');
  assert.deepEqual(state.requests[0].args.slice(0, 3), ['run-a', '先讲位置与形态', 'question-a']);
  state.requests[0].resolve({ data: response() }); await first;
  assert.deepEqual(state.removed, ['answer:course-a:run-a:question-a']);
  assert.equal(state.drafts[0].value, '');
  assert.equal(state.finished, 1);
});

test('teacher response arriving after switching owner cannot replace a run or clear its answer', async () => {
  const state = setup();
  const pending = state.respondToTeacherQuestion();
  state.switchOwner(); state.requests[0].resolve({ data: response() }); await pending;
  assert.equal(state.accepted.length, 0);
  assert.equal(state.removed.length, 0);
  assert.equal(state.drafts.length, 0);
  assert.equal(state.notices.length, 0);
});

test('a stale-question conflict keeps typed input and finishes the operation for a status refresh', async () => {
  const state = setup();
  const pending = state.respondToTeacherQuestion();
  state.requests[0].reject({ response: { status: 409 } }); await pending;
  assert.equal(state.removed.length, 0);
  assert.equal(state.drafts.length, 0);
  assert.match(state.notices[0].text, /问题已更新或已处理/);
  assert.equal(state.finished, 1);
});

test('an invalid or read-only teacher question cannot submit or fall back to chapter resume', async () => {
  for (const overrides of [{ readOnly: true }, { execution: { canRespond: false, canResume: false } }, { teacherAnswer: '   ' }]) {
    const state = setup(overrides);
    await state.respondToTeacherQuestion(); await state.continueRun('resume');
    assert.equal(state.requests.length, 0);
  }
});

test('stop uses the cancellation endpoint once and ignores a response after owner switching', async () => {
  const state = setup();
  const pending = state.cancelRun(); await state.cancelRun();
  assert.equal(state.requests.length, 1);
  assert.equal(state.requests[0].kind, 'cancel');
  state.switchOwner(); state.requests[0].resolve({ data: response('cancelled') }); await pending;
  assert.equal(state.accepted.length, 0);
  assert.equal(state.notices.length, 0);
});

test('a stop racing completed execution reports the returned state without claiming cancellation', async () => {
  const state = setup();
  const pending = state.cancelRun(); state.requests[0].resolve({ data: response('completed') }); await pending;
  assert.equal(state.accepted.length, 1);
  assert.match(state.notices[0].text, /最新执行状态/);
  assert.doesNotMatch(state.notices[0].text, /执行已停止/);
  assert.equal(state.removed.length, 0);
});

test('only an actual chapter-review wait uses the legacy resume action', async () => {
  const state = setup({ execution: { canRespond: false, canResume: true } });
  const pending = state.continueRun('resume');
  assert.equal(state.requests[0].kind, 'resume');
  state.requests[0].resolve({ data: response() }); await pending;
  assert.equal(state.accepted.length, 1);
});
