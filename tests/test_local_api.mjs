import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

function setup() {
  const calls = [];
  const window = {
    location: {href: 'http://127.0.0.1:58080/settings', origin: 'http://127.0.0.1:58080'},
    fetch: (...args) => {calls.push(args); return Promise.resolve('ok');},
  };
  vm.runInNewContext(fs.readFileSync('web_app/static/api.js', 'utf8'), {
    window, document: {querySelector: () => ({content: 'test-token'})}, URL, Request, Headers,
  });
  return {window, calls};
}

test('変更操作のJSON・FormData・Requestで本文とヘッダーを保つ', async () => {
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    const {window, calls} = setup();
    await window.fetch('/api/test', {method, headers: {'Content-Type': 'application/json'}, body: '{"confirmed":true}'});
    const request = calls[0][0];
    assert.equal(request.headers.get('X-PicoCast-Token'), 'test-token');
    assert.equal(request.headers.get('Content-Type'), 'application/json');
    assert.equal(await request.text(), '{"confirmed":true}');
    assert.equal(request.redirect, 'error');
  }
  const {window, calls} = setup();
  const form = new FormData();
  form.set('file', '画像');
  await window.fetch('/api/test', {method: 'POST', body: form});
  assert.equal((await calls[0][0].formData()).get('file'), '画像');
  await window.fetch(new Request(window.location.origin + '/api/test', {method: 'PATCH', body: '本文', headers: {'X-Custom': 'value'}}));
  assert.equal(await calls[1][0].text(), '本文');
  assert.equal(calls[1][0].headers.get('X-Custom'), 'value');
});

test('外部URLとGETにはトークンを付けない', async () => {
  const {window, calls} = setup();
  const init = {method: 'POST', body: '本文'};
  await window.fetch('https://example.com/test', init);
  assert.equal(calls[0][1], init);
  await window.fetch('/api/status');
  assert.equal(calls[1][0], '/api/status');
});
