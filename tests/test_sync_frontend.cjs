const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

async function main() {
  const elements = new Map();
  const timers = new Map();
  let nextTimer = 0;
  let response = { sync: { running: false, pending: 0 } };
  let loads = 0;
  const context = vm.createContext({
    document: { querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {});
      return elements.get(selector);
    } },
    setTimeout(fn) { timers.set(++nextTimer, fn); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    AbortSignal, URL, console,
  });
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8').replace(/\ninit\(\);\s*$/, '');
  vm.runInContext(source, context);
  context.mockApi = async () => response;
  context.mockLoad = async () => { loads++; };
  vm.runInContext(`api = mockApi; loadOverview = mockLoad; renderStats = () => {};
    state.overview = {mirror: {sync: {running: false, pending: 0}}};
    startSyncStatusPoll();`, context);
  async function tick() {
    assert.equal(timers.size, 1, 'Only one global observer timer should exist');
    const [id, fn] = timers.entries().next().value;
    timers.delete(id);
    await fn();
  }
  response = { sync: { running: true, pending: 0 } };
  await tick();
  assert.equal(elements.get('#refreshBtn').disabled, true, 'An idle viewer observes another user starting sync');
  assert.equal(elements.get('#refreshBtn').textContent, '全站同步中...');
  for (let i = 0; i < 100; i++) await tick();
  assert.equal(timers.size, 1, 'Observation must continue beyond the old polling limit');
  const beforeFinish = loads;
  response = { sync: { running: false, pending: 0, lastFinishedJob: { finishedAt: '2026-09-30T15:00:00Z' } } };
  await tick();
  assert.equal(elements.get('#refreshBtn').disabled, false);
  assert.equal(loads, beforeFinish + 1, 'Finishing updates the observing user automatically');
  vm.runInContext(`state.overview.mirror.sync = {running: false, pending: 0,
    lastFinishedJob: {finishedAt: '2026-09-30T15:00:00Z'}};`, context);
  response.sync.lastFinishedJob.finishedAt = '2026-09-30T15:01:00Z';
  await tick();
  assert.equal(loads, beforeFinish + 2, 'A short job finishing between polls also updates viewers');
  console.log('Global synchronization UI checks passed.');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
