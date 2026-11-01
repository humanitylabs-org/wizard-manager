/* Lightweight state-machine coverage of the shipped loader, not a substitute
 * for the real DOM scroll/anchor tests in frontend.test.cjs (forum only). */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const start = source.indexOf('  async function loadOlder() {');
const end = source.indexOf('  async function refresh() {', start);
assert(start >= 0 && end > start, 'exercise the actual app loader');
function fixture(overrides = {}) {
  const anchor = { isConnected: true, top: 12, getBoundingClientRect() { return { top: this.top, bottom: this.top + 100 }; } };
  const calls = [], merged = [];
  const page = { enabled: true, jobs: [], messages: [{id: 902}], next_before: 902, has_older: true };
  const context = {
    activeProject: 'alpha', hasOlder: true, loadingOlder: false, connected: true,
    projectGeneration: 1, historyBefore: 952,
    scroller: { scrollTop: 0, getBoundingClientRect: () => ({top: 0}) },
    thread: { querySelectorAll: () => [anchor] },
    api: async url => { calls.push(url); return page; },
    merge: data => { merged.push(data); anchor.top += 500; },
    cacheConversation: () => {}, ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  return {context, calls, merged, page};
}
test('legacy global fixture cannot paginate: no selected project means no history request', async () => {
  const f = fixture({activeProject: null});
  await f.context.loadOlder();
  assert.equal(f.calls.length, 0);
  assert.equal(f.merged.length, 0);
});
test('selected project loads one older window and retains the existing reading anchor', async () => {
  const f = fixture({activeProject: 'alpha/space'});
  await f.context.loadOlder();
  assert.deepEqual(f.calls, ['api/state?project_id=alpha%2Fspace&before=952&limit=50']);
  assert.equal(f.merged[0], f.page);
  assert.equal(f.context.historyBefore, 902);
  assert.equal(f.context.scroller.scrollTop, 500);
  assert.equal(f.context.loadingOlder, false);
});
test('cached offline state, exhausted history and in-flight older requests do not paginate', async () => {
  for (const overrides of [{connected: false}, {hasOlder: false}, {loadingOlder: true}]) {
    const f = fixture(overrides);
    await f.context.loadOlder();
    assert.equal(f.calls.length, 0);
  }
});
test('older history is single-flight and a late response cannot cross a project switch', async () => {
  let release;
  const f = fixture({api: () => new Promise(resolve => { release = resolve; })});
  const pending = f.context.loadOlder();
  assert.equal(f.context.loadingOlder, true);
  await f.context.loadOlder();
  f.context.activeProject = 'beta'; f.context.projectGeneration++;
  f.context.loadingOlder = true; // A new project's request owns this flag now.
  release(f.page); await pending;
  assert.equal(f.merged.length, 0);
  assert.equal(f.context.historyBefore, 952);
  assert.equal(f.context.loadingOlder, true, 'old finally must not unlock the new request');
});
