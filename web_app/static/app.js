/* 動画ファクトリー Web UI 共通スクリプト */

// スコアバッジの色付け（ページ読み込み時に自動適用）
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.score-badge[data-score]').forEach(el => {
    const s = parseInt(el.dataset.score, 10);
    if (!isNaN(s)) {
      if (s >= 80) el.classList.add('badge-ok');
      else if (s >= 70) el.classList.add('badge-warn');
      else el.classList.add('badge-ng');
    }
  });
});

/**
 * ジョブをポーリングしてステータスを更新する汎用関数。
 * @param {string} jobId
 * @param {function} onUpdate - (job) => void
 * @param {function} onDone - (job) => void
 * @param {number} intervalMs
 */
function pollJob(jobId, onUpdate, onDone, intervalMs = 2000) {
  const timer = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();
      if (onUpdate) onUpdate(job);
      if (['success', 'failed', 'cancelled'].includes(job.status)) {
        clearInterval(timer);
        if (onDone) onDone(job);
      }
    } catch (e) {
      // ネットワークエラーはサイレントに無視
    }
  }, intervalMs);
  return timer;
}

/**
 * ログエントリを DOM に追記する。
 * @param {HTMLElement} container
 * @param {string} message
 * @param {string} tag
 */
function appendLogEntry(container, message, tag = 'info') {
  const div = document.createElement('div');
  div.className = `log-line log-${tag}`;
  div.textContent = message;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

/**
 * HTML エスケープ
 */
function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
