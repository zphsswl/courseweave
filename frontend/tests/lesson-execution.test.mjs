import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/api/lessonAgent.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const clean = (value) => JSON.parse(JSON.stringify(value));
function setup() {
  const calls = [];
  const client = Object.fromEntries(['get', 'post', 'patch'].map((method) => [method, (...args) => { calls.push({ method, args }); return Promise.resolve({ data: {} }); }]));
  const sandbox = { exports: {}, require: () => ({ default: { create: () => client } }) };
  vm.runInNewContext(compiled, sandbox);
  return { ...sandbox.exports, calls };
}
const run = (result = {}, status = 'processing') => ({ id: 'run-a', course_id: 'course-a', status,
  result: { agent_version: 'lesson_agent_v3', textbook_ids: ['book-a'], execution_mode: 'model_driven', ...result } });
const question = { type: 'teacher_question', question: '这堂课应先讲哪部分？', options: ['位置形态', '功能调节'], request_id: 'question-1' };

test('historical UTC job dates and explicit-offset action dates represent the same instant', () => {
  const { parseLessonTimestamp: parse } = setup();
  assert.equal(parse('2026-10-28T13:29:00.123456').getTime(), parse('2026-10-28T21:29:00.123456+08:00').getTime());
  assert.equal(parse('2026-10-28T13:29:00Z').getTime(), parse('2026-10-28T13:29:00').getTime());
  assert.equal(parse('invalid'), null);
  assert.equal(parse(), null);
});

test('cancelled task no longer presents its unfinished checkpoint as still executing', () => {
  const { lessonExecution: execution } = setup();
  const result = execution(run({ trajectory: [
    { id: 'done', action: 'inspect_course', status: 'completed' },
    { id: 'inflight', action: 'query_rag', status: 'running' },
  ] }, 'cancelled'));
  assert.equal(result.trajectory[0].statusLabel, '已执行');
  assert.equal(result.trajectory[1].statusLabel, '已停止接收结果');
  assert.notEqual(result.trajectory[1].status, 'running');
  assert.equal(result.canCancel, false);
});

test('v3 displays actual loop order, repeated tools and rejected actions rather than the fixed plan', () => {
  const { lessonExecution: execution } = setup();
  const result = execution(run({ plan: [{ id: 'old-step', title: '固定阶段' }], trajectory: [
    { id: 'first', step: 1, action: 'search_evidence', summary: '检索位置形态', status: 'completed', observation: { evidence_count: 3 } },
    { id: 'second', step: 2, action: 'search_evidence', summary: '补查功能表述', status: 'running' },
    { id: 'third', step: 3, action: 'delete_book', summary: '无权限动作', status: 'rejected', error: '工具不在允许范围内' },
  ] }));
  assert.equal(result.mode, 'model_driven');
  assert.deepEqual(clean(result.trajectory.map((item) => item.id)), ['first', 'second', 'third']);
  assert.equal(result.trajectory[1].statusLabel, '执行中');
  assert.equal(result.trajectory[2].statusLabel, '已拒绝');
  assert.equal(result.trajectory[2].error, '工具不在允许范围内');
  assert.equal(result.budget.length, 0, 'trajectory length is not an invented budget counter');
});

test('evidence workflow is visibly downgraded while v2 remains an explicitly historical flow', () => {
  const { lessonExecution: execution } = setup();
  const evidence = execution(run({ execution_mode: 'evidence_workflow' }, 'completed'));
  assert.match(evidence.modeLabel, /降级/);
  assert.match(evidence.modeDescription, /不能据此声称/);
  const legacy = execution(run({ agent_version: 'course_agent_v2', execution_mode: 'model_driven' }, 'completed'));
  assert.equal(legacy.isV3, false);
  assert.equal(legacy.mode, 'legacy');
  assert.match(legacy.modeDescription, /不作为模型自主决策轨迹/);
  assert.equal(execution(run({ execution_mode: 'future_mode' })).mode, 'unknown');
});

test('teacher questions require a real question identifier and use respond rather than chapter resume', () => {
  const { lessonExecution: execution } = setup();
  const waiting = execution(run({ approval: question }, 'waiting_user'));
  assert.equal(waiting.canRespond, true);
  assert.equal(waiting.canResume, false);
  assert.equal(waiting.approval.requestId, 'question-1');
  assert.deepEqual(clean(waiting.approval.options), ['位置形态', '功能调节']);
  assert.equal(execution(run({ approval: { ...question, request_id: '' } }, 'waiting_user')).canRespond, false);
  assert.equal(execution(run({ approval: { ...question, question: '' } }, 'waiting_user')).canRespond, false);
  assert.equal(execution(run({ approval: question }, 'processing')).canRespond, false);
});

test('legacy chapter approval keeps resume and unknown approval never silently resumes', () => {
  const { lessonExecution: execution } = setup();
  const chapter = { type: 'chapter_review', textbooks: [{ id: 'book-a', title: '教材A' }] };
  assert.equal(execution(run({ approval: chapter }, 'waiting_user')).canResume, true);
  assert.equal(execution(run({ agent_version: 'v2', approval: { textbooks: chapter.textbooks } }, 'waiting_user')).canResume, true);
  const unknown = execution(run({ approval: { type: 'future_question', textbooks: chapter.textbooks } }, 'waiting_user'));
  assert.equal(unknown.approval.kind, 'unknown');
  assert.equal(unknown.canResume, false);
  assert.equal(unknown.canRespond, false);
});

test('legacy records normalize missing and unknown step fields without claiming completion', () => {
  const { lessonExecution: execution } = setup();
  const result = execution(run({ agent_version: 'v2', plan: [null, { id: 's1', title: '读取材料', status: 'skipped', message: '复用原文' }, { status: 'future' }] }));
  assert.equal(result.legacyPlan[1].summary, '复用原文');
  assert.equal(result.legacyPlan[1].statusLabel, '已复用');
  assert.equal(result.legacyPlan[2].statusLabel, '状态待核对');
  assert.equal(execution(run({ agent_version: 'unknown', plan: {} })).legacyPlan.length, 0);
});

test('stop is available only on cancellable v3 states and never restarts terminal runs', () => {
  const { lessonExecution: execution } = setup();
  for (const status of ['pending', 'processing', 'waiting_user']) assert.equal(execution(run({}, status)).canCancel, true);
  for (const status of ['completed', 'failed', 'cancelled']) assert.equal(execution(run({}, status)).canCancel, false);
  assert.equal(execution(run({ agent_version: 'v2' }, 'processing')).canCancel, false);
  assert.match(execution(run({ stop_reason: 'user_cancelled' }, 'cancelled')).stopReason, /教师已停止/);
});

test('budget preserves zero and actual over-limit counts without declaring lesson completion', () => {
  const { lessonExecution: execution } = setup();
  const budget = { max_steps: 4, steps_used: 5, max_rag_queries: 0, rag_queries_used: 0, max_drafts: 2, drafts_used: 1, elapsed_seconds: 12.75 };
  const result = execution(run({ budget, stop_reason: 'max_steps' }, 'completed'));
  assert.deepEqual(clean(result.budget), [
    { id: 'steps_used', label: '循环轮次', used: 5, max: 4 },
    { id: 'rag_queries_used', label: '教材检索', used: 0, max: 0 },
    { id: 'drafts_used', label: '教案尝试', used: 1, max: 2 },
  ]);
  assert.equal(result.elapsed, 12.75);
  assert.match(result.stopReason, /上限/);
  assert.equal('percent' in result, false);
  assert.equal('draftReady' in result, false);
});

test('unknown or malformed trajectory and budget fields fail closed without crashing old history', () => {
  const { lessonExecution: execution } = setup();
  const result = execution(run({ trajectory: [null, 'bad', { id: {}, step: -2, status: 'future_status', observation: ['bad'] }],
    budget: { steps_used: Number.NaN, max_steps: -3, max_drafts: '2', elapsed_seconds: Number.POSITIVE_INFINITY },
    approval: { type: 'teacher_question', question: {}, options: [null, { label: 'bad' }, '可用'], request_id: {} }, teacher_answers: {} }));
  assert.equal(result.trajectory.length, 3);
  assert.ok(result.trajectory.every((entry) => entry.status === 'unknown'));
  assert.equal(result.trajectory[2].step, null);
  assert.equal(result.budget.length, 0);
  assert.equal(result.elapsed, null);
  assert.equal(result.canRespond, false);
  assert.deepEqual(clean(result.approval.options), ['可用']);
  assert.deepEqual(clean(result.teacherAnswers), []);
  assert.doesNotThrow(() => execution({ status: 'completed', result: null }));
});

test('tool results show public facts and never dump arbitrary reasoning/provider payloads', () => {
  const { trajectoryObservation: observation } = setup();
  const lines = observation({ summary: '已找到三段原文', query: '甲状腺形态', evidence_count: 3, source_ids: ['S1', 'S2'],
    chain_of_thought: '隐藏推理', reasoning: '不应显示', provider_response: { content: '原始响应' }, count: -1 });
  assert.deepEqual(clean(lines), ['已找到三段原文', '检索词：甲状腺形态', '原文：3', '引用：S1、S2']);
  assert.doesNotMatch(lines.join(' '), /隐藏推理|不应显示|原始响应/);
  assert.deepEqual(clean(observation({ unknown: { nested: true } })), []);
});

test('teacher answer history keeps only public question, answer and time without changing inputs', () => {
  const { lessonExecution: execution } = setup();
  const input = run({ teacher_answers: [{ question: '先讲什么？', answer: '先讲位置', answered_at: '2026-10-28T12:00:00Z', reasoning: 'private' }, null] });
  Object.freeze(input.result.teacher_answers[0]); Object.freeze(input.result.teacher_answers); Object.freeze(input.result); Object.freeze(input);
  const result = execution(input);
  assert.deepEqual(clean(result.teacherAnswers), [{ question: '先讲什么？', answer: '先讲位置', answeredAt: '2026-10-28T12:00:00Z' }]);
  assert.equal(input.result.teacher_answers.length, 2);
});

test('respond and cancel call their own endpoints with bounded request identity and abort signal', async () => {
  const { respondLessonRun, cancelLessonRun, calls } = setup();
  const controller = new AbortController();
  await respondLessonRun('run/a', '先讲位置', 'question-1', controller.signal);
  await cancelLessonRun('run/a', controller.signal);
  assert.equal(calls[0].args[0], '/runs/run%2Fa/respond');
  assert.deepEqual(clean(calls[0].args[1]), { answer: '先讲位置', request_id: 'question-1' });
  assert.equal(calls[0].args[2].signal, controller.signal);
  assert.equal(calls[1].args[0], '/runs/run%2Fa/cancel');
  assert.deepEqual(clean(calls[1].args[1]), {});
  assert.equal(calls[1].args[2].signal, controller.signal);
  assert.ok(calls.every((call) => !call.args[0].endsWith('/resume')));
});
