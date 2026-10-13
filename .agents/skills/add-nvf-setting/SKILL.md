---
name: add-nvf-setting
description: Native Video Factory の設定項目を追加・変更・削除し、config.py 定数、設定DB、設定画面、再起動なしの反映、秘密値保護、文書まで同期する依頼で使う。
---

# 設定項目を変更する

## 調査

1. `AGENTS.md` の「最重要運用ルール」（設定値ハードコード禁止・`.env` 禁止・即時反映）と「Web UI 作業時の注意点」を読む。
2. 設定キーを `rg` で `config/config.py`、`web_app/services/config_service.py`（`EDITABLE_CONFIG`）、`web_app/templates/settings.html`、`SPEC.md`、`README.md`、`MANUAL.md` から検索する。
3. 新しい画面・保存経路を作る前に、既存タブと `EDITABLE_CONFIG` の拡張で済むか確認する。

## 実装

1. 既定値を `config/config.py` に `_setting_value("KEY", "既定値")` で定義し、末尾に `# 説明` コメントを付ける。`os.environ` を正本にしない（`NVF_MASTER_KEY` と起動時一時フラグだけ例外）。
2. 利用者が画面で変える値は `EDITABLE_CONFIG` に追加する。開発者向けは `admin` 指定にし、販売版（`DEVELOPER_TOOLS_ENABLED=0`）で非表示・API拒否になることを確認する。
3. 保存は `core.settings_store` / `config_service.save_config()` 経由で DB に書き、`_apply_runtime_updates()` で `setattr(cfg, key, value)` と伝搬を行う。値をモジュール読込時にコピーしている箇所があれば、参照時に `config.KEY` を読む形へ直す。
4. APIキー・トークン・client_secrets は設定DBではなく `core.secret_store`（`encrypted_secrets`）に置く。画面・API・ログ・例外へ値を出さず、有無（bool）だけ返す。
5. パス設定はアプリ配下なら相対パス・`asset:` 参照、外部アプリ本体なら絶対パスを許容する。保存前に `sanitize_path_value()` を通す。
6. `WEB_UI_PORT` のように起動時固定の値は `EDITABLE_CONFIG` に入れない。画面に「再起動後に反映」と書かない。
7. 既存チャンネルへ既定値変更を効かせる必要がある場合（スケジュール枠など）は、DB マイグレーションを同じ作業で追加する。

## 文書

- `SPEC.md` の設定一覧（`設定 (config/config.py)` 節）へ同じ作業で反映する。利用者が日常的に触るなら `README.md` / `MANUAL.md` も更新する。

## 検証

1. 設定画面で初期値・変更・保存・再読込・再起動なしの反映を確認する（`./.venv/Scripts/python.exe -m web_app.app --open-browser`）。
2. 秘密値が画面・`data/settings.db:settings`・ログ・診断ZIP に平文で出ないことを確認する。
3. `./.venv/Scripts/python.exe -m pytest -q tests/test_web.py` と関係するテストを通す。
