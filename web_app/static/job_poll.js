/**
 * ジョブポーリング共通ユーティリティ。
 * generate.html / history_detail.html で共有する。
 */

function buildLogLine(msg, tag, time) {
  let resolvedTag = tag || 'info';
  if (msg.includes('スコア') && msg.includes('点')) {
    const scoreMatch = msg.match(/(\d+)点/);
    if (scoreMatch) {
      const scoreVal = parseInt(scoreMatch[1]);
      if (scoreVal >= 80) resolvedTag = 'score_ok';
      else if (scoreVal >= 70) resolvedTag = 'score_warn';
      else resolvedTag = 'score';
    }
  }
  const t = time ? String(time).slice(11, 19) || String(time).slice(0, 8) : '';
  const prefix = t ? `${esc(t)} [${esc(resolvedTag)}] ` : `[${esc(resolvedTag)}] `;
  let displayMsg = esc(msg);
  displayMsg = displayMsg.replace(/(\d+点)/g, '<strong style="font-size: 1.15em; text-decoration: underline; color: #fff;">$1</strong>');
  displayMsg = displayMsg.replace(/(スコア)/g, '<strong style="color: #fff;">$1</strong>');
  return `<div class="log-line log-${resolvedTag}">${prefix}${displayMsg}</div>`;
}

/** ジョブカードHTMLを生成する（generate.html / history_detail.html 共通） */
function buildJobCardHtml(job) {
  const statusCls = job.status === 'success' ? 'badge-ok' :
                    job.status === 'failed'  ? 'badge-ng' :
                    job.status === 'running' ? 'badge-running' : 'badge-warn';
  const t = (job.started_at || '').slice(0, 16).replace('T', ' ');
  const idShort = (job.job_id || '').slice(0, 8) + '…';
  return `<div class="card mt job-card status-${esc(job.status)}"
               data-status="${esc(job.status)}"
               data-type="${esc(job.type || '')}"
               data-job-id="${esc(job.job_id)}">
    <div class="job-header">
      <span class="job-type-badge">${esc(job.type || '')}</span>
      <span class="badge ${statusCls}">${esc(job.status)}</span>
      <span class="job-id-small">${esc(idShort)}</span>
      <span class="job-time">${esc(t)}</span>
    </div>
    <div class="job-progress">${esc(job.progress_text || '')}</div>
  </div>`;
}

/** ジョブカードを追加または更新する（generate.html / history_detail.html 共通） */
function updateJobCard(container, job) {
  let card = container.querySelector(`.job-card[data-job-id="${CSS.escape(job.job_id)}"]`);
  if (!card) {
    container.insertAdjacentHTML('beforeend', buildJobCardHtml(job));
    card = container.querySelector(`.job-card[data-job-id="${CSS.escape(job.job_id)}"]`);
  }

  card.className = card.className.replace(/\bstatus-\S+/, `status-${job.status}`);
  card.dataset.status = job.status;

  const badge = card.querySelector('.badge');
  if (badge) {
    badge.textContent = job.status;
    badge.className = 'badge ' + (
      job.status === 'success' ? 'badge-ok' :
      job.status === 'failed'  ? 'badge-ng' :
      job.status === 'running' ? 'badge-running' : 'badge-warn'
    );
  }

  const prog = card.querySelector('.job-progress');
  if (prog) prog.textContent = job.progress_text || '';

  let errEl = card.querySelector('.error-text');
  if (job.error) {
    if (!errEl) { errEl = document.createElement('div'); errEl.className = 'error-text'; prog && prog.after(errEl); }
    errEl.textContent = 'エラー: ' + job.error;
  } else if (errEl) errEl.remove();

  const logs = job.logs || [];
  if (logs.length > 0) {
    let details = card.querySelector('details');
    if (!details) {
      details = document.createElement('details');
      details.open = true;
      card.appendChild(details);
    }
    let summary = details.querySelector('summary');
    if (!summary) { summary = document.createElement('summary'); details.prepend(summary); }
    summary.textContent = `ログ詳細 (${logs.length}件)`;

    let logBox = details.querySelector('.log-box');
    if (!logBox) { logBox = document.createElement('div'); logBox.className = 'log-box'; details.appendChild(logBox); }

    const atBottom = details.open && (logBox.scrollHeight - logBox.clientHeight <= logBox.scrollTop + 80);
    logBox.innerHTML = logs.map(e => buildLogLine(e.message, e.tag, e.time)).join('');
    if (atBottom) logBox.scrollTop = logBox.scrollHeight;
  }
}

/**
 * 指数バックオフ付きポーラー。setInterval の代わりに使う。
 * @param {Function} fn  非同期関数。true を返したらポーリング停止。
 * @param {number} initialMs  初期間隔(ms)
 * @param {number} maxMs      最大間隔(ms)
 * @returns {{ stop: Function }}
 */
function createBackoffPoller(fn, initialMs, maxMs) {
  let currentMs = initialMs;
  let elapsed = 0;
  let timer = null;
  let _running = false;
  let stopped = false;

  function _schedule() {
    if (stopped) return;
    timer = setTimeout(async () => {
      if (stopped) return;
      if (_running) { _schedule(); return; }
      _running = true;
      let done = false;
      try { done = await fn(); } finally { _running = false; }
      if (done || stopped) return;
      elapsed += currentMs;
      // 30秒経過後、上限に達するまで1.5倍ずつ伸ばす
      if (elapsed >= 30000 && currentMs < maxMs) {
        currentMs = Math.min(Math.round(currentMs * 1.5), maxMs);
      }
      _schedule();
    }, currentMs);
  }

  _schedule();
  return { stop: () => { stopped = true; if (timer) { clearTimeout(timer); timer = null; } } };
}

/** 全画面でHTTP・ジョブ識別子・状態の検証を共有する。 */
async function fetchJob(jobId) {
  const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {cache: 'no-store'});
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const job = await res.json();
  if (job.job_id !== jobId || !['queued', 'running', 'success', 'failed', 'cancelled'].includes(job.status)) {
    throw new Error('ジョブ情報が不正です。画面を再読み込みしてください');
  }
  return job;
}

/** 要求受付後も終了状態になるまで監視を続ける。 */
async function requestJobCancellation(jobIds, report) {
  let failed = false;
  for (const jobId of jobIds) {
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {method: 'POST'});
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      failed = true;
      report(`キャンセル要求を送れませんでした（${jobId.slice(0, 8)}）: ${e.message || e}`, 'error');
    }
  }
  if (!failed) report('キャンセル要求を送信しました。処理の終了を確認中です', 'warning');
  return !failed;
}

/**
 * @param {string[]} activeJobIds
 * @param {HTMLElement} logBox
 * @param {{ resultLabel?: (result: object) => string }} [options]
 * @returns {Promise<{ allDone: boolean, hasFailed: boolean }>}
 */
async function updateJobLogs(activeJobIds, logBox, options = {}) {
  const resultLabel = options.resultLabel || (r => r.message || '');
  let allDone = true;
  let hasFailed = false;
  let htmlContent = '';
  const errors = [];

  for (const jobId of activeJobIds) {
    try {
      const job = await fetchJob(jobId);
      // ジョブ種別とステータスをヘッダーとして表示（progress_text は最後のログ行と重複するので含めない）
      htmlContent += `<div class="log-job-header">[${esc(job.type)}] ${esc(job.status)}</div>`;

      for (const entry of (job.logs || [])) {
        htmlContent += buildLogLine(entry.message, entry.tag, entry.time);
      }
      if (!['success', 'failed', 'cancelled'].includes(job.status)) allDone = false;
      if (['failed', 'cancelled'].includes(job.status)) hasFailed = true;

      if (job.status === 'success' && job.result) {
        htmlContent += buildLogLine(`完了: ${resultLabel(job.result)}`, 'success');
      }
    } catch(e) {
      allDone = false;
      errors.push(`通信エラーのため再試行中（${jobId.slice(0, 8)}）: ${e.message || e}`);
    }
  }

  const isScrolledToBottom = logBox.scrollHeight - logBox.clientHeight <= logBox.scrollTop + 80;
  // 失敗した取得を空のログで上書きしない。復旧すると警告を除いて最新ログへ戻す。
  let warning = logBox.querySelector('.job-monitor-error');
  if (!errors.length) {
    logBox.innerHTML = htmlContent;
  } else {
    if (!warning) {
      warning = document.createElement('div');
      warning.className = 'job-monitor-error error-text';
      logBox.appendChild(warning);
    }
    warning.textContent = errors.join('\n');
  }
  if (isScrolledToBottom) logBox.scrollTop = logBox.scrollHeight;

  return { allDone, hasFailed };
}
