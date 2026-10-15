// 証明書更新の失敗を成功トーストにしないことを、実画面の処理で検証する。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const html = readFileSync(new URL('../web_app/templates/settings.html', import.meta.url), 'utf8');
const start = html.indexOf('async function runLicenseAction(');
const end = html.indexOf('async function saveLicenseActivation()', start);
assert.ok(start >= 0 && end > start);

for (const failure of [false, true]) {
  test(failure ? '更新失敗はエラー表示と入力維持' : '正常登録は成功表示と入力消去', async () => {
    const field = { value: 'test-input' };
    const button = { disabled: false };
    const toasts = [];
    let refreshes = 0;
    const context = vm.createContext({
      document: { querySelectorAll: () => [button], getElementById: () => field },
      licenseRequest: async () => ({ activation_error: failure ? { code: 'E-LICENSE-API', message: '通信失敗' } : {} }),
      showToast: (message, error) => toasts.push({ message, error }),
      loadProductStatus: async () => { refreshes++; },
    });
    vm.runInContext(html.slice(start, end), context);
    await context.runLicenseAction('/renew', {}, '更新成功', 'license-activation');
    assert.equal(toasts.length, 1);
    assert.equal(toasts[0].error, failure);
    assert.equal(field.value, failure ? 'test-input' : '');
    assert.equal(button.disabled, false);
    assert.equal(refreshes, 1);
  });
}
