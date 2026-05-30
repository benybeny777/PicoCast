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
      const res = await fetch(`/api/jobs/${jobId}`);
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
