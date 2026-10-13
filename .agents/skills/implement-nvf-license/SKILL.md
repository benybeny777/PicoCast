---
name: implement-nvf-license
description: 端末固定ライセンス、証明書更新、Apps Script発行APIを実装・修正・引き継ぐ依頼で使う。
---

# 端末固定ライセンスを変更する

1. `HANDOFF.md`、`AGENTS.md`、`DESIGN_product_v2.md` の対象カードを読む。利用者が承認した範囲、未決定値、既存未コミット差分を確認する。
2. アプリ暗号処理、ライセンス状態管理、GAS発行、画面の担当を区別する。並行作業ではファイル所有とJSON形式を先に共有し、統合は主担当が行う。
3. `core/license_key.py` の共通署名処理、`core/machine_id.py` の端末コード、`core/secret_store.py` の既存DPAPIを使う。生端末ID・キー・証明書・HTTP応答本文をログやユーザー応答へ出さない。
4. 保存証明書の署名・端末・期限・購入キーとの権利一致を確認する。失効済みライセンスは旧証明書の再貼付けや同じ購入IDのキー再登録で復活させない。復号失敗は上位へ伝播する。
5. 更新失敗を設定画面へ表示する。期限内のみオフライン利用を許可し、期限切れ・端末不一致・検証不成立は体験版にする。登録解除は画面確認と `confirmed=true` を要求する。
6. GAS台数管理には `LockService` を使い、永続書き込みを `flush()` してからロックを解放する。署名失敗前に端末登録を変更しない。
7. 設定変更は `add-nvf-setting` の手順に従う。仕様・運用は `SPEC.md`、`README.md`、`tools/license/README.md` と `HANDOFF.md` に反映する。
8. `.venv/Scripts/python.exe -m pytest tests/test_machine_id.py tests/test_license_key.py tests/test_activation_crypto.py tests/test_license_activation.py tests/test_autopilot.py -q`、`node tests/test_license_gas.mjs --python .venv/Scripts/python.exe`、`node --test tests/test_license_ui.mjs` を実行する。関係するWebテストと全体テストも通す。
9. 実ブラウザーで状態・端末コード・手動登録のエラー表示を確認する。GAS実環境、メール、macOSはモック検証と区別して報告する。
10. オーナー移行は既存キーと秘密鍵だけで行う。鍵を生成し直さない。DBをリポジトリ外へ退避してから無期限証明書を登録し、Pro状態とWindows DPAPI保護を確認する。秘密値を表示しない。
11. 一時ファイルを `temp/<作業名>/` へまとめ、後始末する。目的に関係する差分のみコミット・pushし、対象PRの本文へカード・検証・未確認を記録する。
