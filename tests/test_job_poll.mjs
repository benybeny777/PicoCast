import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../web_app/static/job_poll.js', import.meta.url), 'utf8');
function setup(fetch) {
  const timers = new Map();
  let sequence = 0;
  const context = {
    fetch, console: { error() {} },
    window: { WEB_JOB_MONITOR_ERROR: '[E-JOB-MONITOR] 状況を取得できません' },
    setTimeout(fn) { timers.set(++sequence, fn); return sequence; },
    clearTimeout(id) { timers.delete(id); },
    document: { createElement() { return { setAttribute() {} }; } },
  };
  runInNewContext(source, context);
  return { context, timers, async tick() {
    const [id, fn] = timers.entries().next().value;
    timers.delete(id);
    await fn();
  } };
}

test('通信待ち中に停止した監視は再開しない', async () => {
  const state = setup();
  let resolve;
  const poller = state.context.createBackoffPoller(() => new Promise(r => { resolve = r; }), 1, 10);
  const pending = state.tick();
  poller.stop();
  resolve(false);
  await pending;
  assert.equal(state.timers.size, 0);
});

test('停止済みのタイマーが呼ばれても状態取得しない', async () => {
  const state = setup();
  let calls = 0;
  const poller = state.context.createBackoffPoller(async () => { calls++; }, 1, 10);
  const callback = state.timers.values().next().value;
  poller.stop();
  await callback();
  assert.equal(calls, 0);
});

test('未完了は再監視し、完了で監視を止める', async () => {
  const state = setup();
  let calls = 0;
  state.context.createBackoffPoller(async () => ++calls === 2, 1, 10);
  await state.tick();
  assert.equal(state.timers.size, 1);
  await state.tick();
  assert.equal(state.timers.size, 0);
});

test('HTTP失敗と別ジョブや未知状態の応答を拒否する', async () => {
  for (const response of [
    { ok: false, status: 404 },
    { ok: true, json: async () => ({ job_id: 'other', status: 'success' }) },
    { ok: true, json: async () => ({ job_id: 'job', status: 'unknown' }) },
  ]) {
    const { context } = setup(async () => response);
    await assert.rejects(context.fetchJobStatus('job'));
  }
});

test('キャンセル要求失敗時は送信済み表示や完了処理を行わない', async () => {
  const source = readFileSync(new URL('../web_app/templates/generate.html', import.meta.url), 'utf8');
  const cancellation = source.match(/async function cancelGenerate\(\) \{[\s\S]*?\n\}/)[0];
  let finished = false;
  const logs = [];
  const context = {
    activeJobIds: ['job'], activeTab: 'tab',
    document: { getElementById() { return {}; } },
    fetch: async () => ({ ok: false, status: 500 }),
    showJobMonitorError() {},
    appendLog(message) { logs.push(message); },
    finishGenerate() { finished = true; },
  };
  runInNewContext(cancellation, context);
  await context.cancelGenerate();
  assert.equal(finished, false);
  assert.equal(logs.length, 1);
  assert.match(logs[0], /確認できません/);
});

test('通信失敗時は前回ログを保持し、復旧後にエラー表示を解除する', async () => {
  let failed = true;
  const { context } = setup(async () => {
    if (failed) throw new Error('通信失敗');
    return { ok: true, json: async () => ({ job_id: 'job', type: 'check', status: 'success', logs: [] }) };
  });
  let notice = null;
  let html = '前回のログ';
  const box = {
    scrollHeight: 100, clientHeight: 100, scrollTop: 0,
    querySelector() { return notice; },
    prepend(element) { notice = element; },
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; notice = null; },
  };
  let result = await context.updateJobLogs(['job'], box);
  assert.equal(result.allDone, false);
  assert.equal(html, '前回のログ');
  assert.match(notice.textContent, /E-JOB-MONITOR/);
  failed = false;
  result = await context.updateJobLogs(['job'], box);
  assert.equal(result.allDone, true);
  assert.equal(notice, null);
  assert.match(html, /success/);
});
