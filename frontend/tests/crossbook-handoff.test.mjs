import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

// Execute the actual async component handler with controlled save completion.
// This covers navigation during a save without a browser or network dependency.
const source = fs.readFileSync(new URL('../src/components/CrossTextbookStudio.tsx', import.meta.url), 'utf8');
const start = source.indexOf('  const prepare = async () => {');
const end = source.indexOf('\n  useEffect(() => { onPrepareReady', start);
assert.ok(start >= 0 && end > start, 'the real crossbook prepare handler must be found');
const compiled = ts.transpileModule(source.slice(start, end), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const board = { id: '', selections: [{ chunk_id: 'a-source', dimension: '位置' }] };
function setup() {
  let resolveSave;
  const handoffs = [];
  const sandbox = {
    exports: {}, busy: false, loading: false, query: 'A课题', ids: ['a', 'b'], dirty: true, readOnly: false,
    sourceBook: { id: 'a' }, alive: { current: true },
    boardState: { boardRef: { current: board }, save: () => new Promise((resolve) => { resolveSave = resolve; }) },
    onPrepare: (context) => handoffs.push(context),
  };
  vm.runInNewContext(compiled + '\nexports.prepare = prepare;', sandbox);
  return { sandbox, handoffs, prepare: sandbox.exports.prepare, resolveSave: (value) => resolveSave(value) };
}
test('switching away during a board save cannot reopen Agent with the previous course sources', async () => {
  const state = setup();
  const pending = state.prepare();
  state.sandbox.alive.current = false;
  state.resolveSave({ ...board, id: 'saved-a' });
  await pending;
  assert.equal(state.handoffs.length, 0);
});
test('a mounted board hands off the saved identity and exact selected sources once', async () => {
  const state = setup();
  const pending = state.prepare();
  state.resolveSave({ ...board, id: 'saved-a' });
  await pending;
  assert.deepEqual(JSON.parse(JSON.stringify(state.handoffs)), [{
    topic: 'A课题', textbookIds: ['a', 'b'], boardId: 'saved-a', selectedChunkIds: ['a-source'], sourceBookId: 'a', focusTerms: ['位置'],
  }]);
});
test('a failed board save never hands off an unsaved board', async () => {
  const state = setup();
  const pending = state.prepare();
  state.resolveSave(null);
  await pending;
  assert.equal(state.handoffs.length, 0);
});
