---
name: prepare-yukkurijidou-release
description: yukkurijidouの配布・販売・exeビルド前に、実装、文書、法務文書、初期データ、テスト、依存、ビルド設定、Git差分をまとめて検証する。リリースしてよいか、販売前監査、配布物を作る、mainをきれいにしてpushする依頼で使う。
---

# yukkurijidou配布前検証

## 最初に読む

1. `AGENTS.md`、`BUILD.md`、README の「製品版MVP運用」「法務ドキュメント」「配布用 exe のビルド」節を読む。
2. `git status --short`、現在ブランチ、直近コミット、`origin` との差を確認する。
3. 既存変更を利用者または別エージェントの作業として扱い、巻き戻さない。

## 検証する

1. `python -m pytest -q` を実行する。
2. 依存を変更した場合は `audit-yukkurijidou-dependencies` の `packages` を行う。
3. 配布物に混ぜてはいけないものを確認する。
   - `config/SEED/prompt_packs/product/` にチャンネル固有の勝ちプロンプト・実績入りテンプレート・利用者固有データが無い（`AGENTS.md`）。
   - コード・テンプレート・同梱資産に特定チャンネル名・ハンドル・URL・秘密値が無い（`rg` で確認）。
   - `output/`、`dev/`、`data/settings.db`、`data/secret_master.key`、`.env`、トークン類が追跡されていない（`git ls-files` で確認）。
4. `legal/` の文書（利用規約・EULA・プライバシーポリシー・特定商取引法に基づく表記）が README・アプリ内の法務画面と食い違っていないか照合する。
5. Windows でビルドできる場合は `BUILD.md` の手順で `.\build_exe.ps1`（または `-Standalone`）を実行し、成果物の起動・`/setup`・生成1本を確認する。この環境で実行できない場合は未確認として書く。
6. `git diff --check` と、README・SPEC・MANUAL・BUILD.md の記載が実装と一致しているかを確認する。

## 判定する

- 実行していない確認を合格と書かない。
- 警告、保留、環境由来の未確認は理由と再確認方法を作業報告またはPR本文へ書く。
- 起動中のアプリのファイルロックでビルドできない場合、利用者のアプリを勝手に止めない。
- 変更と検証が完了したら `AGENTS.md` のとおり関連差分をコミットしてプッシュする。
