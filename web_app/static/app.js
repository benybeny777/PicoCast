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
function pollJob(jobId, onUpdate, onDone, intervalMs = null) {
  const pollIntervalMs = intervalMs || window.WEB_JOB_POLL_INTERVAL_MS;
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
  }, pollIntervalMs);
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

/**
 * 読み違いの可能性（VOICEVOX の読みと辞書の読みの食い違い）の一覧を描画する。
 * 生成画面の読みチェックと、設定画面「よみがな辞書」で共用する。
 * @param {HTMLElement} container
 * @param {Array} findings - {word, voicevox_reading, expected_reading, text|example}
 * @param {function} onChanged - 登録・無視のあとに呼ぶ
 */
function renderReadingFindings(container, findings, onChanged) {
  if (!findings.length) {
    container.innerHTML = '<p class="hint">読み違いの可能性はありません。</p>';
    return;
  }
  container.innerHTML = `
    <table class="status-table">
      <tr><th>語</th><th>VOICEVOX の読み</th><th>正しい読み（ひらがな）</th><th>例文</th><th></th></tr>
      ${findings.map((f, i) => `
        <tr>
          <td><strong>${esc(f.word)}</strong></td>
          <td>${esc(f.voicevox_reading)}</td>
          <td><input type="text" class="form-input" data-i="${i}" value="${esc(f.expected_reading)}" style="width:140px"></td>
          <td class="hint" style="font-size:12px">${esc(f.text || f.example || '')}</td>
          <td style="white-space:nowrap">
            <button class="btn btn-xs btn-primary" data-act="accept" data-i="${i}">この読みで登録</button>
            <button class="btn btn-xs btn-secondary" data-act="dismiss" data-i="${i}">VOICEVOXの読みで正しい</button>
          </td>
        </tr>`).join('')}
    </table>`;
  container.querySelectorAll('button[data-act]').forEach(btn => {
    btn.onclick = async () => {
      const f = findings[Number(btn.dataset.i)];
      const accept = btn.dataset.act === 'accept';
      const reading = container.querySelector(`input[data-i="${btn.dataset.i}"]`).value.trim();
      const res = await fetch(`/api/reading-check/findings/${accept ? 'accept' : 'dismiss'}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(accept ? {word: f.word, reading} : {word: f.word, voicevox_reading: f.voicevox_reading}),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert('保存できませんでした: ' + (data.detail || res.status));
        return;
      }
      btn.closest('tr').remove();
      if (onChanged) onChanged();
    };
  });
}
