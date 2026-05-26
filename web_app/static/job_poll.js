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

function buildLogLine(msg, tag) {
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
  let displayMsg = escapeHtml(msg);
  displayMsg = displayMsg.replace(/(\d+点)/g, '<strong style="font-size: 1.15em; text-decoration: underline; color: #fff;">$1</strong>');
  displayMsg = displayMsg.replace(/(スコア)/g, '<strong style="color: #fff;">$1</strong>');
  return `<div class="log-line log-${resolvedTag}">${displayMsg}</div>`;
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
      htmlContent += buildLogLine(`[${job.type}] ${job.status}: ${job.progress_text}`, job.status);

      for (const entry of (job.logs || [])) {
        htmlContent += buildLogLine(entry.message, entry.tag);
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

  const isScrolledToBottom = logBox.scrollHeight - logBox.clientHeight <= logBox.scrollTop + 30;
  logBox.innerHTML = htmlContent;
  if (isScrolledToBottom) logBox.scrollTop = logBox.scrollHeight;

  return { allDone, hasFailed };
}
