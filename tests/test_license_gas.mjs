// GAS のサービスをメモリ上に置き換え、実鍵・実シート・実メールを使わず確認する。
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, writeFileSync, unlinkSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createContext, runInContext } from 'node:vm';
import { generateKeyPairSync, sign, verify } from 'node:crypto';

const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const properties = new Map([['LICENSE_PRIVATE_KEY', privateKey.export({ type: 'pkcs8', format: 'pem' })]]);
const sheets = new Map();
const mails = [];
const logs = [];
let locked = false;
let releases = 0;
function sheet(name) {
  const data = [['見出し']];
  const result = {
    data,
    getDataRange: () => ({ getValues: () => data.map(row => [...row]) }),
    appendRow: row => { assert.ok(locked); data.push([...row]); },
    getRange: (row, col) => ({
      setValue: value => { assert.ok(locked); data[row - 1][col - 1] = value; },
      setValues: values => { assert.ok(locked); data[row - 1] = [...values[0]]; },
    }),
  };
  sheets.set(name, result);
  return result;
}
for (const name of ['注文', '発行済み', '端末', 'リセット申請']) sheet(name);
const issued = sheets.get('発行済み').data;
issued.push(['license-test', '100', 'buyer@example.invalid', '購入者', 'standard', '', '2026-01-01', '', '', '']);
const context = createContext({
  console: { log: text => logs.push(text), warn: text => logs.push(text), error: text => logs.push(text) },
  PropertiesService: { getScriptProperties: () => ({ getProperty: name => properties.get(name), setProperty: (name, value) => properties.set(name, value) }) },
  SpreadsheetApp: { getActive: () => ({ getSheetByName: name => sheets.get(name) }), flush: () => assert.ok(locked) },
  LockService: { getScriptLock: () => ({ waitLock: () => { assert.equal(locked, false); locked = true; }, releaseLock: () => { locked = false; releases++; } }) },
  MailApp: { sendEmail: (...args) => mails.push(args) },
  Session: { getEffectiveUser: () => ({ getEmail: () => 'seller@example.invalid' }) },
  Utilities: {
    Charset: { UTF_8: 'utf-8' },
    base64EncodeWebSafe: data => Buffer.from(data).toString('base64').replace(/\+/g, '-').replace(/\//g, '_'),
    base64DecodeWebSafe: data => Buffer.from(data, 'base64url'),
    computeRsaSha256Signature: (data, pem) => sign('RSA-SHA256', Buffer.from(data), pem),
    newBlob: data => ({ getBytes: () => [...Buffer.from(data)], getDataAsString: () => Buffer.from(data).toString('utf-8') }),
    formatDate: (date, zone, format) => format === 'yyyy' ? String(date.getUTCFullYear()) : date.toISOString().slice(0, 10),
  },
  ContentService: { MimeType: { JSON: 'json' }, createTextOutput: content => ({ content, setMimeType() { return this; }, getContent() { return content; } }) },
});
runInContext(readFileSync(new URL('../tools/license/gas/Code.gs', import.meta.url), 'utf-8'), context);
const key = context.signKey_({ v: 1, lid: 'license-test', ed: 'standard', packs: [], buyer: '購入者', iat: '2026-01-01', upd: '' });
const request = value => JSON.parse(context.doPost({ postData: { contents: JSON.stringify(value) } }).content);
const activate = mid => request({ action: 'activate', license_key: key, machine_code: mid, app_version: '0.1.0' });
const mids = ['a'.repeat(32), 'b'.repeat(32), 'c'.repeat(32)];
function decoded(activation) {
  const [prefix, payload, signature] = activation.split('.');
  assert.equal(prefix, 'NVA1');
  assert.ok(verify('RSA-SHA256', Buffer.from(payload), publicKey, Buffer.from(signature, 'base64url')));
  return JSON.parse(Buffer.from(payload, 'base64url').toString('utf-8'));
}

assert.equal(request({ action: 'activate', license_key: key, machine_code: '生端末ID', app_version: '0.1' }).error, 'invalid');
assert.equal(request({ action: 'activate', license_key: key, machine_code: mids[0], app_version: '' }).error, 'invalid');
assert.equal(request({ action: 'activate', license_key: key.slice(0, -10) + 'corruption', machine_code: mids[0], app_version: '1' }).error, 'invalid');
assert.equal(request({ action: 'unknown' }).error, 'invalid');
assert.equal(JSON.parse(context.doPost({ postData: { contents: '{' } }).content).error, 'invalid');
assert.equal(request([]).error, 'invalid');
assert.equal(JSON.parse(context.doPost({ postData: { contents: ' '.repeat(40000) } }).content).error, 'invalid');
assert.equal(sheets.get('端末').data.length, 1);

const first = activate(mids[0]);
assert.equal(first.devices_registered, 1);
assert.equal(first.device_limit, 2);
const payload = decoded(first.activation);
assert.equal(payload.mid, mids[0]);
assert.equal(payload.lid, 'license-test');
assert.equal(Date.parse(payload.exp) - Date.parse(payload.iat), 30 * 86400000);
assert.equal(activate(mids[0]).devices_registered, 1);
assert.equal(sheets.get('端末').data.length, 2);
assert.equal(activate(mids[1]).devices_registered, 2);
const limit = activate(mids[2]);
assert.equal(limit.error, 'limit');
assert.deepEqual(limit.devices.map(device => device.mid), ['aaaaaa', 'bbbbbb']);
assert.ok(request({ action: 'renew', activation: first.activation }).activation);
assert.equal(request({ action: 'renew', activation: first.activation.replace('NVA1', 'NVF1') }).error, 'invalid');

// 秘密鍵取得の失敗は入力不正と区別し、端末枠を変更しない。
const savedKey = properties.get('LICENSE_PRIVATE_KEY');
properties.delete('LICENSE_PRIVATE_KEY');
assert.equal(activate(mids[2]).error, 'server');
properties.set('LICENSE_PRIVATE_KEY', savedKey);

assert.equal(request({ action: 'deactivate', activation: first.activation }).ok, true);
assert.equal(request({ action: 'renew', activation: first.activation }).error, 'inactive');
assert.equal(activate(mids[2]).devices_registered, 2);
assert.equal(activate(mids[0]).error, 'limit');
assert.equal(request({ action: 'reset', license_key: key, order_number: 'wrong' }).error, 'invalid');
assert.equal(sheets.get('リセット申請').data.length, 1);
for (let count = 0; count < 2; count++) {
  assert.equal(request({ action: 'reset', license_key: key, order_number: '100' }).ok, true);
  assert.equal(activate(mids[0]).devices_registered, 1);
}
assert.equal(request({ action: 'reset', license_key: key, order_number: '100' }).error, 'manual_review');
assert.equal(mails.length, 1);
assert.equal(sheets.get('端末').data[1][4], '有効');
// 年が変われば自動承認の枠が戻る。
for (const row of sheets.get('リセット申請').data.slice(1)) row[1] = '2000-01-01T00:00:00.000Z';
assert.equal(request({ action: 'reset', license_key: key, order_number: '100' }).ok, true);

properties.set('MANUAL_LICENSE_KEY', key);
properties.set('MANUAL_MACHINE_CODE', mids[0]);
context.issueOfflineActivation();
const offline = mails.at(-1)[2].split('\n\n').at(-1);
assert.equal(decoded(offline).exp, '');
assert.equal(mails.at(-1)[0], 'buyer@example.invalid');
assert.ok(request({ action: 'renew', activation: offline }).activation);

// 署名失敗がロック取得後に起きても、枠を消費せず必ずロックを解放する。
const signFunction = context.Utilities.computeRsaSha256Signature;
const beforeSigningFailure = JSON.stringify(sheets.get('端末').data);
context.Utilities.computeRsaSha256Signature = (...args) => {
  if (locked) throw new Error('署名サービスのテスト障害');
  return signFunction(...args);
};
assert.equal(activate(mids[1]).error, 'server');
assert.equal(JSON.stringify(sheets.get('端末').data), beforeSigningFailure);
assert.equal(locked, false);
context.Utilities.computeRsaSha256Signature = signFunction;

// 期限切れの証明書でも台帳が有効なら復旧できる。未登録の端末は署名だけで登録できない。
const expired = context.signPayload_({ ...payload, exp: '2000-01-01T00:00:00.000Z' }, 'NVA1');
assert.ok(request({ action: 'renew', activation: expired }).activation);
const unknownMachine = context.signPayload_({ ...payload, mid: 'd'.repeat(32) }, 'NVA1');
assert.equal(request({ action: 'renew', activation: unknownMachine }).error, 'inactive');
const invalidPayload = context.signPayload_({ ...payload, mid: '生端末ID' }, 'NVA1');
assert.equal(request({ action: 'renew', activation: invalidPayload }).error, 'invalid');

// Pro は3台。別ライセンスの枠を混同しない。
issued.push(['license-pro', '200', 'pro@example.invalid', 'Pro購入者', 'pro', 'testpack', '2026-01-01', '', '', '']);
const proKey = context.signKey_({ v: 1, lid: 'license-pro', ed: 'pro', packs: ['testpack'], buyer: 'Pro購入者', iat: '2026-01-01', upd: '' });
for (const mid of mids) {
  const result = request({ action: 'activate', license_key: proKey, machine_code: mid, app_version: '1.0' });
  assert.equal(result.device_limit, 3);
  assert.deepEqual(decoded(result.activation).packs, ['testpack']);
}
assert.equal(request({ action: 'activate', license_key: proKey, machine_code: 'd'.repeat(32), app_version: '1.0' }).error, 'limit');

// 台帳の付与内容が変更・欠損していたら古い証明書から上位権利を更新しない。
issued[1][4] = 'pro';
assert.equal(request({ action: 'renew', activation: first.activation }).error, 'invalid');
issued[1][4] = 'standard';
assert.ok(request({ action: 'renew', activation: first.activation }).activation);
// 同じ lid の別注文で失効していても、失効をすり抜けない。
issued.push([...issued[1]]);
issued.at(-1)[8] = '別注文の失効';
assert.equal(request({ action: 'renew', activation: first.activation }).error, 'revoked');
issued.pop();

issued[1][8] = '返金';
for (const action of ['renew', 'deactivate']) assert.equal(request({ action, activation: first.activation }).error, 'revoked');
assert.equal(activate(mids[0]).error, 'revoked');
assert.equal(request({ action: 'reset', license_key: key, order_number: '100' }).error, 'revoked');
assert.equal(locked, false);
assert.ok(releases > 10);
assert.ok(logs.every(text => !text.includes(key) && !text.includes(first.activation) && !text.includes('生端末ID')));
assert.equal(typeof context.doGet, 'undefined');
context.testIssueKey();
console.log('GAS ライセンス v2: 署名・台数・更新・解除・失効・年次リセット・入力検証・ロック・ログ確認 完了');

// 任意の実 Python 検証。公開鍵・一時テストキーだけを専用 temp に置き、終了時に削除する。
const pythonIndex = process.argv.indexOf('--python');
if (pythonIndex >= 0) {
  const fixtureDir = resolve('temp/license-v2');
  const fixturePath = resolve(fixtureDir, 'gas-interoperability.json');
  mkdirSync(fixtureDir, { recursive: true });
  writeFileSync(fixturePath, JSON.stringify({ public_key: publicKey.export({ type: 'spki', format: 'pem' }), key, activation: first.activation, offline }));
  try {
    const result = spawnSync(process.argv[pythonIndex + 1], ['-c', `
import json, sys
from pathlib import Path
from core.license_key import verify_license_key, verify_activation, encode_license_key, encode_activation, generate_key_pair, LicensePayload, ActivationPayload
data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
key = verify_license_key(data['key'], data['public_key'])
for name in ('activation', 'offline'):
    activation = verify_activation(data[name], data['public_key'])
    assert activation.license_id == key.license_id
    assert activation.edition == key.edition
    assert activation.buyer == key.buyer
    assert activation.packs == key.packs
    assert activation.updates_until == key.updates_until
    assert activation.machine_code == 'a' * 32
assert verify_activation(data['offline'], data['public_key']).expires_at == ''
private, public = generate_key_pair()
payload = LicensePayload('python-test', 'pro', 'Python購入者', '2026-01-01', '', ('testpack',))
activation = ActivationPayload('python-test', 'pro', 'Python購入者', '2026-01-01T00:00:00+00:00', '', ('testpack',), 'e' * 32, '2026-12-01T00:00:00+00:00')
print(json.dumps({'private_key': private, 'key': encode_license_key(payload, private), 'activation': encode_activation(activation, private)}, ensure_ascii=True))
`, fixturePath], { encoding: 'utf-8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
    assert.equal(result.status, 0, result.stderr);
    const python = JSON.parse(result.stdout);
    properties.set('LICENSE_PRIVATE_KEY', python.private_key);
    assert.equal(context.verifySigned_(python.key, 'NVF1').lid, 'python-test');
    assert.equal(context.verifySigned_(python.activation, 'NVA1').mid, 'e'.repeat(32));
    console.log('GAS → Python / Python → GAS: 実 RSA 署名・UTF-8・UTC日時・無期限証明書の相互互換確認 完了');
  } finally {
    properties.set('LICENSE_PRIVATE_KEY', savedKey);
    unlinkSync(fixturePath);
  }
}
