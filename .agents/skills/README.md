# 共通作業スキル

Codex・Claude Code など複数の作業エージェントで共有する手順の正本。PicoAgent（`20_PicoAgent/.agents/skills/`）の手順をこのリポジトリ向けに書き換えて移植した。

| スキル | 用途 |
|---|---|
| `add-nvf-setting` | 設定項目の追加・変更（config.py 定数、設定DB、設定画面、即時反映、秘密値、文書） |
| `review-nvf-changes` | 差分・直近コミットのレビューと、見つけた問題の修正・回帰テスト |
| `prepare-nvf-release` | 配布・販売前の監査（テスト、開発用表示の混入、ライセンス鍵、法務、ビルド、Git） |
| `audit-nvf-dependencies` | Python パッケージと外部ソフト（VOICEVOX / ffmpeg / Stable Diffusion WebUI / Ollama）の依存監査 |
| `add-picocast-provider` | Rustプロバイダの契約・設定・費用ガード（本体は対象WPで実装） |
| `add-picocast-qa-check` | QA検査の登録と合否例・保留の検証（WP-R2-12） |
| `update-picocast-golden` | 理由と品質差分を記録する基準更新（WP-R2-14） |
| `import-picocast-data` | バックアップを保った旧データ取り込み（WP-R1-4） |

Claude Code が自動認識する `.claude/skills/<名前>/SKILL.md` には、同名の正本を読む指示だけを置く。手順を追加・修正するときはこのフォルダの正本だけを編集する。
