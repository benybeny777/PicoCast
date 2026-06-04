# 製品化 残タスク 進捗・引き継ぎ

このファイルは「製品化の残作業」を中断・再開可能にするための進捗メモ。
各タスクは独立してコミットする。中断時はこのファイルの「状態」を見れば続きから着手できる。

最終更新: 2026-06-04

## 再開手順（クレジット切れ時 / Codex 継続用）
1. `git log --oneline -15` で直近コミットを確認（最新の機能は下記「タスク一覧」参照）。
2. テスト基準: `./.venv/Scripts/python.exe -m pytest -q` が `385 passed, 1 skipped` 付近で緑。
3. 稼働中アプリへ反映するには Web UI の再起動が必要（起動時 lifespan で seed/移行が走る）。
4. 未完了の主タスク = 「タスク8の残: キャラクター設定UI」。下に実装メモあり。
5. ローカル `data/settings.db` は移行適用済み（character_profiles seed＋旧テンプレ strip 実行済み）。別環境では起動時に自動移行。

## 方針・前提
- ユーザーは本ツールを実利用中。**現状の操作を壊さない**こと（成功パス・既存APIは不変、失敗時メッセージ・新規任意機能の追加が中心）。
- 後回し（着手不要）: ライセンス実キー署名検証 / 配布パッケージ(Nuitka) / 同梱ソフトのライセンス整理（個別DL方針）。
- 表記ルール: 「Stable Diffusion WebUI」のみ。「SD」略語・「Forge」単独禁止（`rg "SD WebUI|\bSD\b|Forge"` で確認）。
- テスト: `./.venv/Scripts/python.exe -m pytest -q`（基準: 385 passed, 1 skipped）。
- コミット規約: 日本語、末尾に `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。直接コミット可（PR不要）。ドキュメント(README/SPEC/CHANGELOG)も同時更新。

## タスク一覧と状態

### 1. 法務テンプレート（販売に必須）  状態: ✅ 完了
- legal/ に4文書＋README（要記入プレースホルダ）。READMEからリンク。
- **法務同意ゲート**も実装: `/setup` 冒頭に同意カード、`GET /legal/{doc}` で閲覧、`core/legal_consent.py` で状態管理、未同意は完了をブロック。`tests/test_legal_consent.py`。
- `legal/` に 利用規約.md / プライバシーポリシー.md / 特定商取引法に基づく表記.md / EULA.md をプレースホルダ付きで作成。
- 特商法は販売者の氏名・住所・電話・メール等が必要 → `<要記入>` プレースホルダにする。
- 生成物（Gemini/Stable Diffusion WebUI/VOICEVOX）の商用利用条件・各ソフトの規約順守を利用規約に明記。
- README/設定画面からリンク。

### 2. サポート導線  状態: ✅ 完了
- config `PRODUCT_SUPPORT_URL` / `PRODUCT_SUPPORT_EMAIL`（空=非表示）。`GET /api/settings/product-info`。設定画面「製品管理」の診断パッケージ近くに表示。

(旧メモ)
- config: `PRODUCT_SUPPORT_URL` / `PRODUCT_SUPPORT_EMAIL`（空=非表示）。
- 設定画面「製品管理」の診断パッケージ近くに「診断ZIPを作ってここへ送付」導線を表示。

### 3. 更新確認  状態: ✅ 完了
- `core/update_check.py`（URL未設定=無効・無アクセス）。`POST /api/settings/check-update`。製品管理タブに「更新を確認」ボタン。`tests/test_update_check.py`。

(旧メモ)
- config: `PRODUCT_UPDATE_CHECK_URL`（空=無効・ネットワークアクセスしない）。
- `core/update_check.py`: URLからJSON `{"latest_version": "x.y.z", "url": "..."}` を取得し `build_app_version()` と比較。
- 設定画面「製品管理」に「更新を確認」ボタン＋結果表示。URL未設定なら「未設定」と表示しアクセスしない。

### 4. 初回セットアップ完了ゲートの必須チェック  状態: ✅ 完了
- `web_app/services/status_service.py:setup_readiness()`（active profile / VOICEVOX / ffmpeg）。`GET /api/settings/setup-readiness`。`POST /api/settings/setup` 完了時に未充足なら422。/setup 完了欄に「必須条件を確認」ボタン。Google APIキーは必須にしない。

(旧メモ)
- `core/setup_state.py` に `setup_readiness()` を追加。
- 必須（常時）: active profile 存在 / VOICEVOX 接続 / ffmpeg 利用可。
- `POST /api/settings/setup`（完了）で必須未達なら 422＋不足項目リストを返し完了をブロック。
- 注意: Google APIキーは必須にしない（手書き台本＋Stable Diffusion WebUIなら不要）。既に完了済みユーザーには影響しない（完了ボタン押下時のみ判定）。

### 5. ディスク空き容量の事前チェック（E-DISK 結線）  状態: ✅ 完了
- `core/disk_check.py:assert_enough_disk()`（`DISK_MIN_FREE_GB`、既定2GB、0で無効）。`api_generate` の単発/バッチ登録で未満なら 422(E-DISK)。setup_test は除外。`tests/test_disk_check.py`。
- 残: 必要ならレンダー専用エンドポイント（履歴からの再レンダー）にも結線可。

(旧メモ)
- config: `DISK_MIN_FREE_GB`（既定 2）。
- 生成・レンダー登録の preflight（`web_app/routes/api_generate.py` 等）で出力先ドライブの空きを確認し、閾値未満なら `E-DISK` で停止。
- `shutil.disk_usage(output_root)` を使用。閾値は控えめ（誤ブロック回避）。

### 6. エラー文言の残り（任意・継続）  状態: 部分対応
- 中央カタログ(`core/error_codes.py`)は整備済み。VOICEVOX/ffmpeg/Ollama は対処つき化済み。
- 残: パイプライン各所の生 `RuntimeError`/`Exception` を必要に応じ `AppError`(コード付き)へ。優先度低、影響範囲を確認しながら個別に。

### 7. Nuitka exe 配布  状態: 🔶 準備のみ完了（実ビルド未実施）
- `core/runtime_env.py`（is_frozen / app_base_dir）、secret_store/settings_store を exe フォルダ基準に anchor、app.py の runner を frozen 対応（`--run-runner`）、version 焼き込み、`build_exe.ps1`＋`BUILD.md`。
- 実ビルドは未実施（ユーザー選択: 準備のみ）。残課題は BUILD.md「既知の残課題」（出力先パス・隠れimport・コード署名・動作確認）。実行は `.\build_exe.ps1`。

### 8. キャラクター設定の分離（character_profiles）  状態: ✅ 完了（管理UIも実装済み）
- 管理UI: 設定画面「キャラクター設定」タブ＋`/api/character-profiles`（GET/PATCH/POST/DELETE）。有効/無効・各フィールド編集可。
- 残（さらに任意）: 「台本テンプレートごとにキャラセット選択」（prompt_templates に character_set 参照列を追加して compose で絞る）。現状は channel 単位の enabled。
- `core/character_profile_store.py`（table）/`core/character_profiles_seed.py`（seed＋compose＋移行）。台本テンプレからキャラ設定分離。
- 食べ物雑学堂(zunkami)=辛口相方めたん、都市伝説(zundamon_kowai)=お嬢様毒舌めたん。meetingは対象外。自動フォールバック禁止。
- 起動時に ensure＋strip 移行。ローカルDBは適用済み（seed＋strip 実行済み）。tests/test_character_profiles.py。
- 残（任意・実装メモ）: Web UIでキャラ設定を管理／選択。
  - API案: `web_app/routes/api_character_profiles.py` に GET `/api/character-profiles`（active profileの一覧）、PATCH `/api/character-profiles/{id}`（enabled/各フィールド更新）、POST 追加、DELETE。`core/character_profile_store` のCRUDをそのまま薄く公開。app.py に router 登録。
  - UI案: `settings.html` に「キャラクター設定」タブを追加。active profileのキャラを一覧表示し、enabledトグル＋各フィールド（role/tone_style/speaking_rules/forbidden_phrases/dialogue_rules）を編集保存。設定タブ切替の `switchTab('characters')` で読み込み。
  - 「台本テンプレートごとに選択」を厳密にやる場合: `prompt_templates` に `character_set` 参照列を足し、compose時にそのセットのキャラのみ合成する拡張が必要（現状は channel 単位で enabled を合成）。まずは channel 単位の有効/無効編集で足りる。

## 完了済み（このセッション、push 済み 〜3b98ad8）
- 外部依存の導線 / エラー対処文言 / 購入動線UX / 起動自己回復 / クロスPC復元（パスフレーズ）
- Stable Diffusion WebUI 時 Ollama 必須化 / 表記統一 / 必須構成早見表（/setup・README）
