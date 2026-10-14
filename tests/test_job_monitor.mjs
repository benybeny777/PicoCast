import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const staticDir = new URL('../web_app/static/', import.meta.url);
function context(extra = {}) {
  const ctx = vm.createContext({console, ...extra});
  for (const name of ['app.js', 'job_poll.js']) {
    vm.runInContext(fs.readFileSync(new URL(name, staticDir), 'utf8'), ctx);
  }
  return ctx;
}
function dom() {
  return {addEventListener() {}, createElement() { return {className: '', textContent: ''}; }};
}

test('通信中に停止したポーラーは次のタイマーを登録しない', async () => {
  const timers = [];
  let resolve;
  const waiting = new Promise(r => { resolve = r; });
  const ctx = context({document: dom(), setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout() {}});
  const poller = ctx.createBackoffPoller(() => waiting, 1, 10);
  const running = timers.shift()();
  poller.stop();
  resolve(false);
  await running;
  assert.equal(timers.length, 0);
});

test('キャンセル失敗を成功表示で上書きせず全ジョブに要求する', async () => {
  const reports = [];
  const calls = [];
  const ctx = context({document: dom(), fetch: async url => {calls.push(url); return {ok: calls.length !== 1, status: 500};}});
  assert.equal(await ctx.requestJobCancellation(['first', 'second'], (...args) => reports.push(args)), false);
  assert.equal(calls.length, 2);
  assert.equal(reports.length, 1);
  assert.equal(reports[0][1], 'error');
});

test('要求受付は終了扱いにせず監視を続ける表示をする', async () => {
  const reports = [];
  const ctx = context({document: dom(), fetch: async () => ({ok: true})});
  assert.equal(await ctx.requestJobCancellation(['first'], text => reports.push(text)), true);
  assert.match(reports[0], /終了を確認中/);
  for (const name of ['generate', 'history_detail']) {
    const source = fs.readFileSync(new URL(`../web_app/templates/${name}.html`, import.meta.url), 'utf8');
    const body = source.match(/async function cancelGenerate\(\) \{([\s\S]*?)\n\}/)[1];
    assert.match(body, /requestJobCancellation/);
    assert.doesNotMatch(body, /finishGenerate/);
  }
});

test('HTTP失敗・別ジョブ・未知状態は完了として扱わない', async () => {
  const ctx = context({document: dom()});
  for (const response of [
    {ok: false, status: 404},
    {ok: true, json: async () => ({job_id: 'other', status: 'success'})},
    {ok: true, json: async () => ({job_id: 'target', status: 'unknown'})},
  ]) {
    ctx.fetch = async () => response;
    await assert.rejects(ctx.fetchJob('target'));
  }
});

test('通信失敗でも直前ログを維持し、復旧すると警告を消す', async () => {
  const children = [];
  const box = {innerHTML: '直前ログ', scrollHeight: 10, clientHeight: 10, scrollTop: 0,
    querySelector: () => children[0], appendChild: node => children.push(node)};
  const ctx = context({document: dom(), fetch: async () => {throw new Error('offline');}});
  const result = await ctx.updateJobLogs(['target'], box);
  assert.equal(result.allDone, false);
  assert.equal(box.innerHTML, '直前ログ');
  assert.match(children[0].textContent, /offline/);
  ctx.fetch = async () => ({ok: true, json: async () => ({job_id: 'target', status: 'success', logs: [{message: '復旧'}]})});
  assert.equal((await ctx.updateJobLogs(['target'], box)).allDone, true);
  assert.match(box.innerHTML, /復旧/);
  assert.doesNotMatch(box.innerHTML, /offline/);
});
