# 共通作業スキル

このフォルダは、Codex・Claude Codeなど複数の作業エージェントで共有する手順の正本です。

| スキル | 用途 |
|---|---|
| `review-yukkurijidou-changes` | 差分・PR・直近コミットのレビューと、見つけた問題の修正・回帰テスト |
| `add-yukkurijidou-setting` | 設定項目の追加・変更（DB保存、設定画面、即時反映、秘密値、文書） |
| `audit-yukkurijidou-dependencies` | Pythonパッケージ、外部アプリ、SDモデル、ランタイムの依存監査 |
| `prepare-yukkurijidou-release` | 配布前のコード、文書、法務、テスト、exeビルド、Git確認 |

Claude Codeが自動認識する`.claude/skills/<名前>/SKILL.md`には、同名の共通スキル正本を読む指示だけを置きます。実際の手順を追加・修正するときは、このフォルダの正本だけを編集してください。
