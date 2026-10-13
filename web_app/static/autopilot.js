/* チャンネル別の自動運用設定と保留状況。フォーム編集中は入力を上書きしない。 */
let automationSnapshot = null;
let automationSaving = false;
const automationFields = {
  daily_shorts: 'auto-shorts', daily_longs: 'auto-longs', start_hour: 'auto-hour',
  min_score: 'auto-score', daily_paid_limit: 'auto-limit'
};
const automationStages = {
  analytics: '実績取得', topic: 'ネタ選定', script: '台本生成', generate: '音声・画像生成',
  render: '動画生成', review: '品質判定', upload: '投稿予約', analysis: '分析', complete: '完了'
};
const automationStates = { ready: '待機中', working: '処理中', held: '保留', complete: '完了', skipped: '終了' };

async function automationApi(url, body) {
  const response = await fetch(url, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  } : { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '設定内容を確認してください。');
  return data;
}

function automationMessage(message, error = false) {
  const box = document.getElementById('auto-message');
  box.textContent = message;
  box.className = error ? 'error-text' : 'hint';
}

async function refreshAutomation(fillForm) {
  try {
    const data = await automationApi('/api/autopilot');
    if (automationSnapshot && automationSnapshot.profile_id !== data.profile_id) {
      document.getElementById('auto-fields').disabled = true;
      throw new Error('チャンネルが切り替わりました。画面を再読み込みしてください。');
    }
    automationSnapshot = data;
    if (fillForm) {
      for (const [key, id] of Object.entries(automationFields)) document.getElementById(id).value = data.policy[key];
      document.getElementById('auto-enabled').checked = data.policy.enabled;
      document.getElementById('auto-fields').disabled = false;
    }
    const held = data.runs.some(run => run.state === 'held');
    document.getElementById('auto-state').textContent = data.policy.enabled ? (held ? '保留中 — 原因の確認が必要です' : '自動運用は有効です') : '自動運用は停止中です';
    document.getElementById('auto-usage').textContent = `今日の有料API: ${data.paid_calls_today} / ${data.policy.daily_paid_limit}回`;
    document.getElementById('auto-stop').disabled = !data.policy.enabled || automationSaving;
    const box = document.getElementById('auto-runs');
    if (!data.runs.length) { box.innerHTML = '<p>まだ運用記録はありません。設定を保存して有効化すると開始時刻以降に運用を始めます。</p>'; return; }
    box.innerHTML = `<table class="data-table"><thead><tr><th>運用日 / 種別</th><th>テーマ</th><th>工程 / 状態</th><th>確認</th></tr></thead><tbody>${data.runs.map(run => `<tr>
      <td>${esc(run.day)}<br>${run.video_type === 'shorts' ? 'Shorts' : 'Long'} ${run.ordinal + 1}本目</td>
      <td>${esc(run.topic || '選定待ち')}</td>
      <td>${esc(automationStages[run.stage] || run.stage)} / ${esc(automationStates[run.state] || run.state)}
        ${run.review ? `<p>${esc(String(run.review.score))}点 / ${esc(run.review.reason || '')}</p>` : ''}
        ${run.error ? `<p class="error-text">${esc(run.error)}</p>` : ''}</td>
      <td>${run.history_name ? `<a class="btn btn-xs" href="/history/${encodeURIComponent(run.history_name)}">成果物</a>` : ''}
        ${run.video_id ? `<a class="btn btn-xs" href="https://studio.youtube.com/video/${encodeURIComponent(run.video_id)}/edit" target="_blank" rel="noopener">YouTube Studio</a>` : ''}
        ${run.state === 'held' ? `<button class="btn btn-xs" data-dismiss-run="${esc(run.run_id)}">この枠を終了</button>` : ''}</td>
    </tr>`).join('')}</tbody></table>`;
  } catch (error) {
    console.error('自動運用状態取得に失敗しました', error);
    automationMessage(error.message, true);
  }
}

async function saveAutomation(event) {
  event.preventDefault();
  if (!automationSnapshot || automationSaving) return;
  const body = { profile_id: automationSnapshot.profile_id, enabled: document.getElementById('auto-enabled').checked };
  for (const [key, id] of Object.entries(automationFields)) body[key] = Number(document.getElementById(id).value);
  if (body.enabled && !confirm(`このチャンネルを自動運用します。\nShorts ${body.daily_shorts}本・Long ${body.daily_longs}本 / 日\n有料API上限 ${body.daily_paid_limit}回 / 日\n品質基準を満たす動画のYouTube投稿予約も自動で行います。\n有効にして保存しますか？`)) return;
  body.confirmed = body.enabled;
  automationSaving = true;
  try {
    await automationApi('/api/autopilot/settings', body);
    automationMessage('設定を保存しました。次の工程から新しい設定を確認します。');
    await refreshAutomation(true);
  } catch (error) {
    console.error('自動運用設定保存に失敗しました', error);
    automationMessage(error.message, true);
  } finally { automationSaving = false; document.getElementById('auto-stop').disabled = !automationSnapshot.policy.enabled; }
}

async function stopAutomation() {
  if (!automationSnapshot || automationSaving) return;
  automationSaving = true;
  try {
    await automationApi('/api/autopilot/settings', { ...automationSnapshot.policy,
      profile_id: automationSnapshot.profile_id, enabled: false, confirmed: false });
    automationMessage('自動運用を停止しました。実行中の処理にも停止を要求します。送信済みの投稿予約はYouTube Studioで確認してください。');
    await refreshAutomation(true);
  } catch (error) {
    console.error('自動運用停止に失敗しました', error);
    automationMessage(error.message, true);
  } finally { automationSaving = false; }
}

document.getElementById('auto-runs').addEventListener('click', async event => {
  const button = event.target.closest('[data-dismiss-run]');
  if (!button || !automationSnapshot) return;
  if (!confirm('原因と投稿結果を確認済みですか？\nこの枠を終了すると、このチャンネルの後続の自動運用を再開できます。成果物は残り、この枠を再生成・再投稿しません。')) return;
  button.disabled = true;
  try {
    await automationApi(`/api/autopilot/${encodeURIComponent(button.dataset.dismissRun)}/dismiss`, { profile_id: automationSnapshot.profile_id, confirmed: true });
    await refreshAutomation(false);
  } catch (error) {
    console.error('保留枠の終了に失敗しました', error);
    automationMessage(error.message, true);
    button.disabled = false;
  }
});

refreshAutomation(true);
const automationPoller = createBackoffPoller(async () => {
  await refreshAutomation(false);
  return false;
}, window.WEB_LOG_POLL_INTERVAL_MS, window.WEB_LOG_POLL_INTERVAL_MS);
window.addEventListener('pagehide', () => automationPoller.stop(), { once: true });
