/**
 * Native Video Factory ライセンス発行・端末登録（Google Apps Script）
 *
 * 構成（スプレッドシートにバインドして使う。設置手順は ../README.md）:
 *   - importBoothOrders(): 時間主導トリガー。Gmail の BOOTH 購入通知を読み「注文」シートへ追記する。
 *   - onFormSubmit(e):     フォーム送信トリガー。注文番号を照合してキーを発行し、購入者へメール送信する。
 *   - doPost(e):           Web アプリ。署名を照合し端末登録・更新・解除・リセットを行う。
 *
 * キー形式は core/license_key.py と完全一致させること:
 *   "NVF1." + base64url(JSON) + "." + base64url(RSA-SHA256(base64url(JSON)))
 *
 * スクリプトプロパティ:
 *   LICENSE_PRIVATE_KEY : tools/license/license_tool.py genkey で作った秘密鍵 PEM（全文）
 */

// ── 設定（販売形態に合わせて編集する） ─────────────────────────
const CONFIG = {
  ORDER_SHEET: '注文',
  ISSUED_SHEET: '発行済み',
  DEVICE_SHEET: '端末',
  RESET_SHEET: 'リセット申請',
  DEVICE_LIMITS: { standard: 2, pro: 3 }, // エディション別の登録台数上限
  LEASE_DAYS: 30,             // オンライン証明書の有効日数
  RESET_LIMIT: 2,             // 暦年内に自動承認するリセット回数
  API_MAX_BYTES: 32768,       // API 本文の最大バイト数
  // BOOTH の購入通知メールを探す Gmail 検索式。実際の通知メールで件名・送信元を確認して調整する。
  BOOTH_MAIL_QUERY: 'from:booth.pm subject:注文 newer_than:30d',
  // 通知メール本文から注文番号を抜き出す正規表現（1つ目のキャプチャが注文番号）。実メールで要確認。
  ORDER_NUMBER_REGEX: /注文番号[:：]\s*(\d+)/,
  // 商品名 → 付与内容。本文に商品名が含まれていればその商品として扱う（上から順に判定）。
  PRODUCTS: [
    { match: 'Pro', edition: 'pro', packs: [] },
    { match: 'Standard', edition: 'standard', packs: [] },
    // パック例: { match: '都市伝説パック', edition: '', packs: ['urban_legend'] },
  ],
  UPDATE_MONTHS: 12,           // 無料アップデート期間（0 = 無期限）
  MAIL_SUBJECT: '【Native Video Factory】ライセンスキーのお知らせ',
  // フォームの質問タイトル（フォーム側と一致させる）
  FORM_ORDER_FIELD: '注文番号',
  FORM_EMAIL_FIELD: 'メールアドレス',
  FORM_NAME_FIELD: 'お名前',
};

const EDITION_RANK = { '': 0, standard: 1, pro: 2 };

// 注文: 注文番号 | 商品 | edition | packs | 受信日時 | メールID
// 発行済み: license_id | 注文番号 | メール | 購入者名 | edition | packs | 発行日 | 更新期限 | 失効 | メモ
const ISSUED_COLS = { lid: 0, order: 1, email: 2, buyer: 3, edition: 4, packs: 5, issued: 6, upd: 7, revoked: 8, memo: 9 };
const DEVICE_COLS = { lid: 0, mid: 1, registered: 2, renewed: 3, state: 4, version: 5 };

function sheet_(name) {
  const sh = SpreadsheetApp.getActive().getSheetByName(name);
  if (!sh) throw new Error('シートがありません: ' + name);
  return sh;
}

function rows_(name) {
  const values = sheet_(name).getDataRange().getValues();
  return values.slice(1); // 1行目は見出し
}

// ── BOOTH 購入通知の取り込み ───────────────────────────────
function importBoothOrders() {
  const known = new Set(rows_(CONFIG.ORDER_SHEET).map(r => String(r[5])));
  const orderSheet = sheet_(CONFIG.ORDER_SHEET);
  const threads = GmailApp.search(CONFIG.BOOTH_MAIL_QUERY, 0, 100);
  let unmatched = 0;
  threads.forEach(thread => thread.getMessages().forEach(msg => {
    if (known.has(msg.getId())) return;
    const body = msg.getPlainBody();
    const m = body.match(CONFIG.ORDER_NUMBER_REGEX);
    const product = CONFIG.PRODUCTS.find(p => body.indexOf(p.match) >= 0);
    if (!m || !product) {
      unmatched++;
      console.warn('購入通知を解析できません: messageId=' + msg.getId() + ' subject=' + msg.getSubject());
      return;
    }
    orderSheet.appendRow([m[1], product.match, product.edition, product.packs.join(','), msg.getDate(), msg.getId()]);
    known.add(msg.getId());
  }));
  if (unmatched > 0) {
    // 書式変更で取り込みが止まったことに気づけるよう販売者へ通知する
    MailApp.sendEmail(Session.getEffectiveUser().getEmail(),
      '[NVF] BOOTH購入通知の解析に失敗しました',
      unmatched + ' 件の通知メールを解析できませんでした。Code.gs の ORDER_NUMBER_REGEX / PRODUCTS を確認してください。');
  }
}

// ── フォーム受付 → キー発行 ─────────────────────────────────
function onFormSubmit(e) {
  const answers = e.namedValues;
  const orderNo = String((answers[CONFIG.FORM_ORDER_FIELD] || [''])[0]).trim();
  const email = String((answers[CONFIG.FORM_EMAIL_FIELD] || [''])[0]).trim();
  const buyer = String((answers[CONFIG.FORM_NAME_FIELD] || [''])[0]).trim();
  if (!orderNo || !email) throw new Error('注文番号またはメールアドレスが空です');

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const order = rows_(CONFIG.ORDER_SHEET).find(r => String(r[0]) === orderNo);
    if (!order) {
      MailApp.sendEmail(email, CONFIG.MAIL_SUBJECT,
        '注文番号 ' + orderNo + ' の購入を確認できませんでした。購入直後の場合は1時間ほど待ってから再度お申し込みください。');
      return;
    }
    const issued = rows_(CONFIG.ISSUED_SHEET);
    if (issued.some(r => String(r[ISSUED_COLS.order]) === orderNo)) {
      MailApp.sendEmail(email, CONFIG.MAIL_SUBJECT,
        '注文番号 ' + orderNo + ' のキーは発行済みです。再送が必要な場合はサポートへご連絡ください。');
      return;
    }
    // 同じメールアドレスの既存ライセンスがあれば、edition の上位とパックを合算して同じ license_id で再発行する
    const previous = issued.filter(r => String(r[ISSUED_COLS.email]).toLowerCase() === email.toLowerCase()
      && !r[ISSUED_COLS.revoked]);
    let edition = String(order[2] || '');
    const packs = new Set(String(order[3] || '').split(',').filter(Boolean));
    let lid = '';
    previous.forEach(r => {
      if (EDITION_RANK[r[ISSUED_COLS.edition]] > EDITION_RANK[edition]) edition = r[ISSUED_COLS.edition];
      String(r[ISSUED_COLS.packs] || '').split(',').filter(Boolean).forEach(p => packs.add(p));
      lid = lid || String(r[ISSUED_COLS.lid]);
    });
    if (!edition) {
      MailApp.sendEmail(email, CONFIG.MAIL_SUBJECT,
        'パックのみのご購入です。本体（Standard / Pro）購入時と同じメールアドレスでお申し込みください。');
      return;
    }
    lid = lid || Utilities.getUuid().replace(/-/g, '').slice(0, 16);
    const today = new Date();
    const payload = {
      v: 1, lid: lid, ed: edition, buyer: buyer,
      iat: isoDate_(today), upd: CONFIG.UPDATE_MONTHS > 0 ? isoDate_(addMonths_(today, CONFIG.UPDATE_MONTHS)) : '',
      packs: Array.from(packs),
    };
    const key = signKey_(payload);
    sheet_(CONFIG.ISSUED_SHEET).appendRow([lid, orderNo, email, buyer, edition, payload.packs.join(','),
      payload.iat, payload.upd, '', '']);
    MailApp.sendEmail(email, CONFIG.MAIL_SUBJECT,
      buyer + ' 様\n\nご購入ありがとうございます。以下のライセンスキーを、アプリの「設定 > 製品管理 > ライセンス」に貼り付けて登録してください。\n\n'
      + key + '\n\nエディション: ' + edition + (payload.packs.length ? '\nパック: ' + payload.packs.join(', ') : '')
      + '\n無料アップデート期限: ' + (payload.upd || '無期限') + '\n');
  } finally {
    try { SpreadsheetApp.flush(); } finally { lock.releaseLock(); }
  }
}

// ── 端末登録 API（読み取りから更新まで同じロックで保護する） ──────
function apiError_(code) {
  const error = new Error('ライセンス API: ' + code);
  error.apiCode = code;
  return error;
}

function doPost(e) {
  let response;
  try {
    const body = e && e.postData && e.postData.contents;
    if (typeof body !== 'string' || Utilities.newBlob(body).getBytes().length > CONFIG.API_MAX_BYTES) {
      throw apiError_('invalid');
    }
    let request;
    try { request = JSON.parse(body); } catch (_) { throw apiError_('invalid'); }
    if (!request || Array.isArray(request) || typeof request !== 'object') throw apiError_('invalid');
    response = licenseRequest_(request, false);
  } catch (error) {
    // 外部入力・鍵・証明書・生端末 ID をログへ含めない。
    console.error('ライセンス API 失敗: ' + (error.apiCode || 'server'));
    response = { error: error.apiCode || 'server' };
  }
  return ContentService.createTextOutput(JSON.stringify(response)).setMimeType(ContentService.MimeType.JSON);
}

function licenseRequest_(request, offline) {
  if (!['activate', 'renew', 'deactivate', 'reset'].includes(request.action)) throw apiError_('invalid');
  const isKey = request.action === 'activate' || request.action === 'reset';
  const payload = verifySigned_(isKey ? request.license_key : request.activation, isKey ? 'NVF1' : 'NVA1');
  const mid = request.action === 'activate' ? request.machine_code : payload.mid;
  if (request.action !== 'reset' && (typeof mid !== 'string' || !/^[0-9a-f]{32}$/.test(mid))) throw apiError_('invalid');
  if (request.action === 'activate' && (typeof request.app_version !== 'string'
      || !/^[A-Za-z0-9.+_-]{1,64}$/.test(request.app_version))) throw apiError_('invalid');
  if (request.action === 'reset' && (typeof request.order_number !== 'string'
      || !/^[A-Za-z0-9_-]{1,128}$/.test(request.order_number))) throw apiError_('invalid');
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const records = rows_(CONFIG.ISSUED_SHEET).filter(r => String(r[ISSUED_COLS.lid]) === payload.lid);
    if (!records.length) throw apiError_('invalid');
    if (records.some(r => r[ISSUED_COLS.revoked])) throw apiError_('revoked');
    // 台帳に記録された付与内容以外を更新しない。上位版の再発行後も旧発行行は残す。
    if (!records.some(r => String(r[ISSUED_COLS.edition]) === payload.ed
        && String(r[ISSUED_COLS.buyer] || '') === payload.buyer
        && sheetDate_(r[ISSUED_COLS.upd]) === payload.upd
        && JSON.stringify(String(r[ISSUED_COLS.packs] || '').split(',').filter(Boolean).sort())
          === JSON.stringify(payload.packs.slice().sort()))) throw apiError_('invalid');
    const deviceSheet = sheet_(CONFIG.DEVICE_SHEET);
    const devices = rows_(CONFIG.DEVICE_SHEET);
    const active = devices.filter(r => String(r[DEVICE_COLS.lid]) === payload.lid && r[DEVICE_COLS.state] === '有効');
    const now = new Date();
    if (request.action === 'reset') {
      if (!records.some(r => String(r[ISSUED_COLS.order]) === request.order_number)) throw apiError_('invalid');
      const year = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy');
      const resets = rows_(CONFIG.RESET_SHEET).filter(r => String(r[0]) === payload.lid
        && Utilities.formatDate(new Date(r[1]), 'Asia/Tokyo', 'yyyy') === year);
      const automatic = resets.length < CONFIG.RESET_LIMIT;
      if (!automatic) {
        MailApp.sendEmail(Session.getEffectiveUser().getEmail(), '[NVF] 全端末リセットの手動承認が必要です',
          'リセット申請シートの対象 license_id: ' + payload.lid + ' を確認してください。キー・証明書はメールに含めていません。');
      }
      sheet_(CONFIG.RESET_SHEET).appendRow([payload.lid, now.toISOString(), automatic ? '自動' : '手動確認待ち']);
      if (automatic) devices.forEach((r, i) => {
        if (String(r[DEVICE_COLS.lid]) === payload.lid && r[DEVICE_COLS.state] === '有効') {
          deviceSheet.getRange(i + 2, DEVICE_COLS.state + 1).setValue('解除済み');
        }
      });
      if (!automatic) console.warn('ライセンス API: manual_review');
      return automatic ? { ok: true } : { error: 'manual_review' };
    }
    const index = devices.findIndex(r => String(r[DEVICE_COLS.lid]) === payload.lid && String(r[DEVICE_COLS.mid]) === mid);
    const current = index >= 0 ? devices[index] : null;
    if (request.action !== 'activate' && (!current || current[DEVICE_COLS.state] !== '有効')) throw apiError_('inactive');
    if (request.action === 'deactivate') {
      deviceSheet.getRange(index + 2, DEVICE_COLS.state + 1).setValue('解除済み');
      return { ok: true };
    }
    const limit = CONFIG.DEVICE_LIMITS[payload.ed];
    if (!Number.isInteger(limit) || limit < 1) throw new Error('台数上限の設定が不正です');
    if (request.action === 'activate' && (!current || current[DEVICE_COLS.state] !== '有効') && active.length >= limit) {
      console.warn('ライセンス API: limit');
      return { error: 'limit', devices: active.map(r => ({ mid: String(r[DEVICE_COLS.mid]).slice(-6), last_updated: r[DEVICE_COLS.renewed] })) };
    }
    const certificate = {
      // アプリは購入キーと証明書の付与内容の一致を検証する。上位版は新キーで登録する。
      v: 1, lid: payload.lid, ed: payload.ed, packs: payload.packs,
      buyer: payload.buyer, upd: payload.upd,
      mid: mid, iat: now.toISOString(),
      exp: offline ? '' : new Date(now.getTime() + CONFIG.LEASE_DAYS * 86400000).toISOString(),
    };
    // 署名失敗時に端末枠を消費しないため、シート更新前に署名する。
    const activation = signPayload_(certificate, 'NVA1');
    const row = [payload.lid, mid, current ? current[DEVICE_COLS.registered] : now.toISOString(),
      now.toISOString(), '有効', request.action === 'activate' ? request.app_version : current[DEVICE_COLS.version]];
    if (index >= 0) deviceSheet.getRange(index + 2, 1, 1, row.length).setValues([row]);
    else deviceSheet.appendRow(row);
    return { activation: activation, devices_registered: current && current[DEVICE_COLS.state] === '有効' ? active.length : active.length + 1, device_limit: limit };
  } finally {
    try { SpreadsheetApp.flush(); } finally { lock.releaseLock(); }
  }
}

// ── 署名 ─────────────────────────────────────────────────
function signKey_(payload) {
  return signPayload_(payload, 'NVF1');
}

function privateKey_() {
  const privateKey = PropertiesService.getScriptProperties().getProperty('LICENSE_PRIVATE_KEY');
  if (!privateKey) throw new Error('スクリプトプロパティ LICENSE_PRIVATE_KEY が未設定です');
  return privateKey;
}

function signPayload_(payload, prefix) {
  const payloadB64 = Utilities.base64EncodeWebSafe(JSON.stringify(payload), Utilities.Charset.UTF_8);
  return prefix + '.' + payloadB64 + '.' + signature_(payloadB64);
}

function signature_(payloadB64) {
  return Utilities.base64EncodeWebSafe(Utilities.computeRsaSha256Signature(payloadB64, privateKey_()));
}

function verifySigned_(text, prefix) {
  if (typeof text !== 'string' || text.length > CONFIG.API_MAX_BYTES) throw apiError_('invalid');
  const parts = text.replace(/\s/g, '').split('.');
  if (parts.length !== 3 || parts[0] !== prefix || !/^[A-Za-z0-9_-]+={0,2}$/.test(parts[1])
      || !/^[A-Za-z0-9_-]+={0,2}$/.test(parts[2])) throw apiError_('invalid');
  // PKCS#1 v1.5 の署名は決定的。同じ文字列への署名を比較する（パディング有無は正規化する）。
  if (signature_(parts[1]).replace(/=+$/, '') !== parts[2].replace(/=+$/, '')) throw apiError_('invalid');
  let data;
  try { data = JSON.parse(Utilities.newBlob(Utilities.base64DecodeWebSafe(parts[1])).getDataAsString('UTF-8')); }
  catch (_) { throw apiError_('invalid'); }
  if (!data || data.v !== 1 || typeof data.lid !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(data.lid)
      || !['standard', 'pro'].includes(data.ed) || !Array.isArray(data.packs)
      || !data.packs.every(p => typeof p === 'string' && /^[A-Za-z0-9_-]+$/.test(p))
      || new Set(data.packs).size !== data.packs.length || typeof data.buyer !== 'string'
      || typeof data.upd !== 'string' || typeof data.iat !== 'string') throw apiError_('invalid');
  if (prefix === 'NVA1' && (typeof data.mid !== 'string' || !/^[0-9a-f]{32}$/.test(data.mid)
      || typeof data.exp !== 'string' || (data.exp && !Number.isFinite(Date.parse(data.exp)))
      || !Number.isFinite(Date.parse(data.iat)))) throw apiError_('invalid');
  return data;
}

function sheetDate_(value) {
  // シートが yyyy-MM-dd を日付セルとして返す場合も、購入キーの日付と同じ書式へ戻す。
  return value instanceof Date ? isoDate_(value) : String(value || '');
}

function isoDate_(d) {
  return Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM-dd');
}

function addMonths_(d, months) {
  const r = new Date(d.getTime());
  r.setMonth(r.getMonth() + months);
  return r;
}

/** 手動テスト用: 秘密を実行ログへ出さず、テスト結果だけを返す。 */
function testIssueKey() {
  const key = signKey_({ v: 1, lid: 'test0000', ed: 'pro', buyer: 'テスト', iat: isoDate_(new Date()), upd: '', packs: [] });
  console.log('キー署名確認: ' + (verifySigned_(key, 'NVF1').lid === 'test0000'));
}

// テスト用プロパティを使う。実行は専用のテスト台帳で行う。
function testRequest_(action) {
  const properties = PropertiesService.getScriptProperties();
  const request = { action: action, license_key: properties.getProperty('TEST_LICENSE_KEY'),
    machine_code: properties.getProperty('TEST_MACHINE_CODE'), app_version: 'test',
    activation: properties.getProperty('TEST_ACTIVATION'), order_number: properties.getProperty('TEST_ORDER_NUMBER') };
  const result = JSON.parse(doPost({ postData: { contents: JSON.stringify(request) } }).getContent());
  if (result.activation) properties.setProperty('TEST_ACTIVATION', result.activation);
  console.log('確認結果: ' + (result.error || 'ok'));
}
function testActivate() { testRequest_('activate'); }
function testRenew() { testRequest_('renew'); }
function testDeactivate() { testRequest_('deactivate'); }
function testReset() { testRequest_('reset'); }

/** 販売者専用: 注文確認・台数上限を通して無期限証明書を登録メールへ送る。 */
function issueOfflineActivation() {
  const properties = PropertiesService.getScriptProperties();
  const request = { action: 'activate', license_key: properties.getProperty('MANUAL_LICENSE_KEY'),
    machine_code: properties.getProperty('MANUAL_MACHINE_CODE'), app_version: 'manual' };
  const result = licenseRequest_(request, true);
  if (result.error) throw apiError_(result.error);
  const payload = verifySigned_(request.license_key, 'NVF1');
  const issued = rows_(CONFIG.ISSUED_SHEET).filter(r => String(r[ISSUED_COLS.lid]) === payload.lid);
  MailApp.sendEmail(String(issued[issued.length - 1][ISSUED_COLS.email]), CONFIG.MAIL_SUBJECT,
    '手動アクティベーション証明書です。設定画面の手動アクティベーション欄へ貼り付けてください。\n\n' + result.activation);
  console.log('手動アクティベーション送信完了');
}
