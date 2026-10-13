---
name: prepare-nvf-release
description: Native Video Factory の配布・販売・リリース前に、テスト、開発用表示の混入、ライセンス鍵、法務文書、配布ビルド、文書、Git 差分をまとめて検証する。「リリースしてよいか」「販売前監査」「配布物を作る」依頼で使う。
---

# 配布前検証

## 最初に読む

1. `AGENTS.md`、`BUILD.md`、`DESIGN_productization_remaining.md` を読む。
2. `git status --short`、現在ブランチ、直近コミット、`origin` との差を確認する。既存変更は巻き戻さない。

## 検証する

1. `./.venv/Scripts/python.exe -m pytest -q` を通す（基準件数は `DESIGN_productization_remaining.md`）。JS テストがあれば `node --test tests/*.mjs`。
2. 開発用表示・開発用データの混入を確認する。
   - `DEVELOPER_TOOLS_ENABLED=0` で起動し、管理者設定タブ・開発者モードが出ないことを画面で確認する。
   - `rg -n "デバッグ用|後で削除|TODO|FIXME" web_app core workers` で販売物に残すべきでない表示を探す。
   - 表記ルール: `rg "SD WebUI|\bSD\b|Forge"` で「Stable Diffusion WebUI」以外の表記が無いこと。
3. ライセンス:
   - `core/license_public_key.py` が販売用の鍵ペアの公開鍵であること（`tools/license/license_tool.py verify <発行済みキー>` が通る）。
   - 秘密鍵（`~/.nvf_license/private_key.pem`）や発行済みキーがリポジトリ・配布物に入っていないこと（`git ls-files | rg -i "private_key|\.pem$"`）。
   - 未登録状態で体験版の制限（透かし・1チャンネル・1日3本・Analytics と自動運用の拒否）が効くこと。
4. 法務: `legal/` の `<要記入>` プレースホルダが埋まっていること（`rg "要記入" legal`）。`PRODUCT_PURCHASE_URL` / `PRODUCT_SUPPORT_*` / `PRODUCT_UPDATE_CHECK_URL` / `LICENSE_REVOCATION_CHECK_URL` の製品既定値を確認する。
5. 配布ビルド: `.\build_exe.ps1 -Standalone` で作り、別フォルダへコピーした成果物を起動して、初回セットアップ・法務同意・ライセンス登録・サンプル生成まで通す。`tools/`・`dev/`・`tests/`・`data/settings.db`・`output/` が成果物に含まれないことを確認する。
6. 文書: README / SPEC / MANUAL / CHANGELOG が今回の配布内容と一致すること。`git diff --check`。

## 判定する

- 実行していない確認を合格と書かない。
- 警告・保留・環境由来の未確認は、理由と再確認方法を報告に書き、リリース後も残る項目は `DESIGN_productization_remaining.md` へ移す。
- 起動中の利用者のアプリを勝手に止めない。ファイルロックでビルドできない場合は別の出力先で再検証する。
