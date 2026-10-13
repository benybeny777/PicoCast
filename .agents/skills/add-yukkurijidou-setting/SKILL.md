---
name: add-yukkurijidou-setting
description: yukkurijidouへ設定項目を追加・変更・削除し、config.py既定値、DB保存、設定画面、再起動なしの即時反映、秘密値の暗号化保存、SPEC・README・テストまで同期する依頼で使う。
---

# yukkurijidouの設定を変更する

## 調査

1. `AGENTS.md` の「最重要運用ルール」（設定値・`.env` 禁止・`config.py` コメント）と「Web UI 作業時の注意点」（認証情報・即時反映）を読む。
2. 設定キーを `rg` で検索し、`config/config.py`、`web_app/services/config_service.py` の `EDITABLE_CONFIG`、`web_app/templates/settings.html`、`core/settings_store.py`、`SPEC.md` の「設定 (`config/config.py`)」節、README、MANUAL での扱いを確認する。
3. 新しい画面や保存経路を増やす前に、既存の `EDITABLE_CONFIG` のグループ・既存APIを拡張できるか確認する。

## 実装

1. 既定値を `config/config.py` の定数として置き、末尾に `# 説明` コメントを付ける。数値・閾値・パス・モデル名をソースへ散らさない。
2. 利用者が変える値は `EDITABLE_CONFIG` へ `key`・`type`・`label`・`default`・必要なら `min`/`max`/`allow_empty`/`group`/`admin` を申告する。アプリ起動時に固定される値（`WEB_UI_PORT` など）は載せない。
3. 保存は `core.settings_store` / `config_service` 経由で `data/settings.db` に行い、`_apply_runtime_updates()` の `setattr(cfg, key, value)` と `sys.modules` 伝搬で即時反映する。`os.environ[key] = value` や `.env` を保存先・反映手段にしない。UIに「再起動後に反映」と出さない。
4. APIキー・トークン・client_secrets などは設定キーにせず、`core.secret_store.save_secret()` / `load_secret()` / `has_secret()` で profile_id 単位の `encrypted_secrets` に保存する。APIレスポンスには有無（bool）だけを返し、値をログ・例外・画面へ出さない。
5. profile ごとに変わる値は channel profile 側の管理に置き、全体設定へ混ぜない。未設定時に特定チャンネルへフォールバックしない。
6. 外部アプリ本体のパスは絶対パスを許容し、アプリ配下・出力管理配下のパスは相対パスまたは `asset:` 参照で保存する（`AGENTS.md`）。
7. 不正値は黙って既定値へ落とさず、検証エラーとして返す。

## 文書

1. `SPEC.md` の設定節へキーの意味・既定値・範囲を同じ作業で反映する。保存・反映方式を変えた場合は SPEC の該当節も更新する。
2. 利用者が日常的に触るキーなら README と MANUAL も更新する。

## 検証

1. `python -m pytest tests/test_config.py tests/test_web.py -q` と、関係する単体テストを通す。秘密値なら `tests/test_secret_store.py`・`tests/test_secret_status_api.py` も通す。
2. 新しいキーについて、保存 → `cfg` 属性への即時反映 → 再読込で値が保たれることをテストで確かめる。
3. 秘密値は画面、APIレスポンス、ログ、例外文に平文で出ないことを確認する。
4. `git diff --check` を通す。
