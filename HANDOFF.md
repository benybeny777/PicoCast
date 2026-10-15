# 引き継ぎ（未マージ作業と再開方法）

最終更新: 2026-10-16（WP-R0-1: 文書の整合）

## 再開方法

1. `AGENTS.md` → 本書 → `DESIGN_implementation_plan.md` §5 → 対象WPの正本の順に読む。Rust移行では `.agents/skills/implement-picocast-r0/SKILL.md` も使う。
2. `git fetch origin`、ブランチ・PR・作業ツリー・実プロセスを照合する。別エージェントの作業と利用者の個人ファイルを巻き戻さない。
3. 依存を満たす最初の未完了WPに着手する。1 WP = 1ブランチ＋1 PRとし、設計の土台が未マージならそのブランチから派生し、PRのbaseも合わせる。明示指示なしにマージしない。
4. 修正中は必要な単体テストだけを実行し、全体検証は最後にまとめて `cargo xtask verify` で行う。PR本文に対象WP・変更・詳細設計・検証・未確認を記載する。

作業順・依存・完了条件の唯一の正本は [実装計画 §5](DESIGN_implementation_plan.md#5-作業パッケージwp)。旧T番号の重複タスク表は持たない。文書の変更だけで他WPのコードや本番移行が完了したとは扱わない。

## 次の作業

- **WP-R0-4（保存先）・WP-R0-5（エラーカタログ）・WP-R1-1（棚卸し）** は統合・提出を進めている。続いてWP-R1-7（旧版テスト隔離とオラクル）とWP-R1-2（ドメインDB）に着手する。同じファイルの同時編集は避ける。
- **WP-R0-2（Python 3.12＋uvへの切り替え）** は、自動運用と予約投稿の無い時間帯に現位置で行う。切り替え直前の実プロセス確認とDBの再バックアップが必要。有料APIは明示指示または運用上の明確な必要がある場合だけ使う。
- R1以降の全WPの状態と完了条件は実装計画を参照する。

## 未マージのブランチとPR

| PR | ブランチ | base | 内容 |
|---|---|---|---|
| [#35](https://github.com/benybeny777/PicoCast/pull/35) | `codex/picoagent-job-monitoring` | `main` | Python旧版のチャンネル別自動運用 |
| [#36](https://github.com/benybeny777/PicoCast/pull/36) | `codex/license-v2-rebrand-design` | `codex/picoagent-job-monitoring` | Rust基盤・旧版安全化・移行設計 |

WP-R0-1は [#37](https://github.com/benybeny777/PicoCast/pull/37)（`codex/wp-r0-1-doc-consistency` → `codex/license-v2-rebrand-design`）でレビュー待ち。#35と#36のマージ・base変更は別作業。既存PR #33・#34もこのWPでは変更しない。

## 移行前に残る確認

- Pythonの実環境は3.11.9。3.12用の `pyproject.toml`・`.python-version`・`uv.lock` は準備済みだが、環境切り替えとサンプル受入は未実施。
- RustのフルドメインDB・旧データ取り込み・生成・YouTube・Tauri画面は未実装。共通ログのAPIは実装したが、本番画面・ジョブへの接続は後続WP。NodeテストはUIが無いため明示スキップ。macOS実機は検証対象外。
- 過去のPython全体確認は656件成功・1件skip。実設定の無い環境での20失敗・39エラーは旧記録であり、現在の全件再検証ではない。WP-R1-7で環境依存を隔離する。
- 設定・metadata DB3件、暗号化キー・認証情報・当時の未コミット差分の退避先は `~/.codex/backups/picocast-r0/`。過去の整合性確認を切り替え直前の再確認の代わりにしない。
- 6月の対応プロセスの無い `running` 記録10件は履歴として扱い、勝手に削除・キャンセル・再実行しない。取り込み時の区別はWP-R1-4。
- このチャットの参照先は `C:\00_PG\22_PicoCast`。アプリの保存済みプロジェクト登録・表示名は、現在のチャットの参照先と区別して確認する。
- `outputs/` は利用者の個人ファイル（生活リズム表）。コミット・削除しない。

## 決定事項

| 項目 | 決定 |
|---|---|
| 方針 | 販売・配布はせず、製品レベルの品質でRust＋Tauri＋素のJSへ作り直す |
| 旧コードの扱い | 保管用の `legacy/` と30日保管は撤回（2026-10-16利用者決定）。切り替えまでは現位置、検証後に不要コードを削除してGit履歴で参照。Git管理外のDB・生成物・認証情報は保護 |
| 改名後の作業 | フォルダ・GitHub・ワークスペースの改名は繰り返さない。Python 3.12への切り替えだけ別WPで行う |
| 影運用 | 2週間。チャンネル単位で切り替え、運用元を一元管理して二重投稿を拒否（N30） |
| 品質受入の30日 | Rust自動運用の受入期間。撤回した旧コードの30日保管とは別 |
| DBと保存先 | 1つの `picocast.db`。通常版PicoCastと開発版PicoCast-Devを分離（WP-R0-4） |
| ライセンス | Rust版では作らない。Python旧版の既存実装を維持し、拡張しない |
| BGM | 取り込み支援・自動選曲・ダッキング。内蔵ライブラリとローカルAI作曲は作らない |
| 多言語 | 日本語画面。言語別メタデータ・字幕をen / zh-Hans / koで、既定OFF・チャンネル単位ON |
| 対応OS | Windows。macOSは動く範囲で保つが実機検証対象外 |
| 通常の判断 | 利用者へ確認せず既定で決め、ここに記録。課金・公開・破壊的操作の境界はAGENTS.mdに従う |

## ローカルのリモート起動設定

`%LOCALAPPDATA%\ClaudeRemoteControl\Start-Project.ps1` と `Start-All.ps1` は、`PicoCast` 名で新フォルダを参照する。ログオンタスクは `Claude Remote Control - Projects`。`.claude/settings.local.json` の追加出力パスも新パスへ更新済み。接続URL・セッションIDは保存しない。現在の接続状態はプロセスとログで別途確認する。

## 秘密値の保護

既存のライセンス秘密鍵 `~/.nvf_license/private_key.pem` は再生成・上書きせず、Git・ログ・PRへ出さない。旧版のオーナー証明書や暗号化キーを、コード整理の対象に含めない。将来の移行では元データを読み取り専用で照合する。
