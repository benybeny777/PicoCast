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
