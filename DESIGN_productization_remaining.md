# 製品化 残タスク 進捗・引き継ぎ

このファイルは「製品化の残作業」を中断・再開可能にするための進捗メモ。
各タスクは独立してコミットする。中断時はこのファイルの「状態」を見れば続きから着手できる。

最終更新: 2026-06-04

## 方針・前提
- ユーザーは本ツールを実利用中。**現状の操作を壊さない**こと（成功パス・既存APIは不変、失敗時メッセージ・新規任意機能の追加が中心）。
- 後回し（着手不要）: ライセンス実キー署名検証 / 配布パッケージ(Nuitka) / 同梱ソフトのライセンス整理（個別DL方針）。
- 表記ルール: 「Stable Diffusion WebUI」のみ。「SD」略語・「Forge」単独禁止（`rg "SD WebUI|\bSD\b|Forge"` で確認）。
- テスト: `./.venv/Scripts/python.exe -m pytest -q`（基準: 366 passed, 1 skipped）。
- コミット規約: 日本語、末尾に `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。直接コミット可（PR不要）。ドキュメント(README/SPEC/CHANGELOG)も同時更新。

## タスク一覧と状態

### 1. 法務テンプレート（販売に必須）  状態: ✅ 完了
- legal/ に4文書＋README（要記入プレースホルダ）。READMEからリンク。
- **法務同意ゲート**も実装: `/setup` 冒頭に同意カード、`GET /legal/{doc}` で閲覧、`core/legal_consent.py` で状態管理、未同意は完了をブロック。`tests/test_legal_consent.py`。
- `legal/` に 利用規約.md / プライバシーポリシー.md / 特定商取引法に基づく表記.md / EULA.md をプレースホルダ付きで作成。
- 特商法は販売者の氏名・住所・電話・メール等が必要 → `<要記入>` プレースホルダにする。
- 生成物（Gemini/Stable Diffusion WebUI/VOICEVOX）の商用利用条件・各ソフトの規約順守を利用規約に明記。
- README/設定画面からリンク。

### 2. サポート導線  状態: 未着手
- config: `PRODUCT_SUPPORT_URL` / `PRODUCT_SUPPORT_EMAIL`（空=非表示）。
- 設定画面「製品管理」の診断パッケージ近くに「診断ZIPを作ってここへ送付」導線を表示。

### 3. 更新確認  状態: 未着手
- config: `PRODUCT_UPDATE_CHECK_URL`（空=無効・ネットワークアクセスしない）。
- `core/update_check.py`: URLからJSON `{"latest_version": "x.y.z", "url": "..."}` を取得し `build_app_version()` と比較。
- 設定画面「製品管理」に「更新を確認」ボタン＋結果表示。URL未設定なら「未設定」と表示しアクセスしない。

### 4. 初回セットアップ完了ゲートの必須チェック  状態: 未着手
- `core/setup_state.py` に `setup_readiness()` を追加。
- 必須（常時）: active profile 存在 / VOICEVOX 接続 / ffmpeg 利用可。
- `POST /api/settings/setup`（完了）で必須未達なら 422＋不足項目リストを返し完了をブロック。
- 注意: Google APIキーは必須にしない（手書き台本＋Stable Diffusion WebUIなら不要）。既に完了済みユーザーには影響しない（完了ボタン押下時のみ判定）。

### 5. ディスク空き容量の事前チェック（E-DISK 結線）  状態: 未着手
- config: `DISK_MIN_FREE_GB`（既定 2）。
- 生成・レンダー登録の preflight（`web_app/routes/api_generate.py` 等）で出力先ドライブの空きを確認し、閾値未満なら `E-DISK` で停止。
- `shutil.disk_usage(output_root)` を使用。閾値は控えめ（誤ブロック回避）。

### 6. エラー文言の残り（任意・継続）  状態: 部分対応
- 中央カタログ(`core/error_codes.py`)は整備済み。VOICEVOX/ffmpeg/Ollama は対処つき化済み。
- 残: パイプライン各所の生 `RuntimeError`/`Exception` を必要に応じ `AppError`(コード付き)へ。優先度低、影響範囲を確認しながら個別に。

## 完了済み（このセッション、push 済み 〜3b98ad8）
- 外部依存の導線 / エラー対処文言 / 購入動線UX / 起動自己回復 / クロスPC復元（パスフレーズ）
- Stable Diffusion WebUI 時 Ollama 必須化 / 表記統一 / 必須構成早見表（/setup・README）
