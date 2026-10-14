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
 * @param {function} onError - (error) => void。通信の失敗時に呼ぶ（ポーリングは続ける）。省略時はコンソールへ出す
 */
function pollJob(jobId, onUpdate, onDone, intervalMs = null, onError = null) {
  const pollIntervalMs = intervalMs || window.WEB_JOB_POLL_INTERVAL_MS;
  const reportError = onError || (e => console.warn(`ジョブ ${jobId} の状態を取得できません（再試行します）`, e));
  let fetching = false;
  const timer = setInterval(async () => {
    if (fetching) return;
    fetching = true;
    try {
      const job = await fetchJob(jobId);
      if (onUpdate) onUpdate(job);
      if (['success', 'failed', 'cancelled'].includes(job.status)) {
        clearInterval(timer);
        if (onDone) onDone(job);
      }
    } catch (e) {
      // 一時的な通信エラーは次の周期で再試行する。黙って捨てずに知らせる
      reportError(e);
    } finally {
      fetching = false;
    }
  }, pollIntervalMs);
  return timer;
}

/**
 * ジョブの状態を1行で表示し、成功したらページを再読み込みする（固定コメント・画像再生成・Analytics 更新で共用）。
 * @param {string} jobId
 * @param {HTMLElement} statusBox
 * @param {number} reloadDelayMs
 */
function pollJobStatus(jobId, statusBox, reloadDelayMs = null) {
  return pollJob(
    jobId,
    job => {
      const lastLog = job.logs && job.logs.length ? job.logs[job.logs.length - 1].message : '';
      statusBox.textContent = `[${job.status}] ${lastLog || job.progress_text || ''}`;
    },
    job => {
      if (job.status === 'success') {
        setTimeout(() => location.reload(), reloadDelayMs || window.WEB_SUCCESS_RELOAD_DELAY_MS);
      }
    },
    null,
    e => { statusBox.textContent = `通信エラーのため再試行中…（${e.message || e}）`; },
  );
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
  // null / undefined は空文字、数値の 0 は "0" のまま表示する。属性値に入れても壊れないよう引用符も変換する
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
