/**
 * ジョブポーリング共通ユーティリティ。
 * generate.html / history_detail.html で共有する。
 */

function escapeHtml(str) {
  if (typeof str !== 'string') return str;
  return str.replace(/[&<>'"]/g, tag => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;'
  }[tag] || tag));
}

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
  const prefix = t ? `${escapeHtml(t)} [${escapeHtml(resolvedTag)}] ` : `[${escapeHtml(resolvedTag)}] `;
  let displayMsg = escapeHtml(msg);
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
  return `<div class="card mt job-card status-${escapeHtml(job.status)}"
               data-status="${escapeHtml(job.status)}"
               data-type="${escapeHtml(job.type || '')}"
               data-job-id="${escapeHtml(job.job_id)}">
    <div class="job-header">
      <span class="job-type-badge">${escapeHtml(job.type || '')}</span>
      <span class="badge ${statusCls}">${escapeHtml(job.status)}</span>
      <span class="job-id-small">${escapeHtml(idShort)}</span>
      <span class="job-time">${escapeHtml(t)}</span>
    </div>
    <div class="job-progress">${escapeHtml(job.progress_text || '')}</div>
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

  function _schedule() {
    timer = setTimeout(async () => {
      if (_running) { _schedule(); return; }
      _running = true;
      let done = false;
      try { done = await fn(); } finally { _running = false; }
      if (done) return;
      elapsed += currentMs;
      // 30秒経過後、上限に達するまで1.5倍ずつ伸ばす
      if (elapsed >= 30000 && currentMs < maxMs) {
        currentMs = Math.min(Math.round(currentMs * 1.5), maxMs);
      }
      _schedule();
    }, currentMs);
  }

  _schedule();
  return { stop: () => { if (timer) { clearTimeout(timer); timer = null; } } };
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

  for (const jobId of activeJobIds) {
    try {
      const res = await fetch(`/api/jobs/${jobId}`, {cache: 'no-store'});
      const job = await res.json();
      // ジョブ種別とステータスをヘッダーとして表示（progress_text は最後のログ行と重複するので含めない）
      htmlContent += `<div class="log-job-header">[${escapeHtml(job.type)}] ${escapeHtml(job.status)}</div>`;

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
    }
  }

  const isScrolledToBottom = logBox.scrollHeight - logBox.clientHeight <= logBox.scrollTop + 80;
  logBox.innerHTML = htmlContent;
  if (isScrolledToBottom) logBox.scrollTop = logBox.scrollHeight;

  return { allDone, hasFailed };
}
