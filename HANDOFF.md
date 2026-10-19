# 引き継ぎ（未マージ作業と再開方法）

最終更新: 2026-10-19（Rust事前点検・外部サービス管理の実装）

## 再開方法

1. `AGENTS.md` → 本書 → `DESIGN_implementation_plan.md` §5 → 対象WPの正本の順に読む。Rust移行では `.agents/skills/implement-picocast-r0/SKILL.md` も使う。
2. `git fetch origin`、ブランチ・PR・作業ツリー・実プロセスを照合する。別エージェントの作業と利用者の個人ファイルを巻き戻さない。
3. 依存を満たす最初の未完了WPに着手する。1 WP = 1ブランチ＋1 PRとし、設計の土台が未マージならそのブランチから派生し、PRのbaseも合わせる。明示指示なしにマージしない。
4. 修正中は必要な単体テストだけを実行し、全体検証は最後にまとめて `cargo xtask verify` で行う。PR本文に対象WP・変更・詳細設計・検証・未確認を記載する。

作業順・依存・完了条件の唯一の正本は [実装計画 §5](DESIGN_implementation_plan.md#5-作業パッケージwp)。旧T番号の重複タスク表は持たない。文書の変更だけで他WPのコードや本番移行が完了したとは扱わない。

## 次の作業

- **WP-R2-11のローカル検証**。`codex/wp-r2-11-preflight-services`でAPI・所有プロセス管理・loopback/ディスク点検を実装した。詳細は`docs/preflight-services.md`。検証結果を確認してから状態表を更新する。本番認証・実サービスの起動受入・画面との接続は未完了。次の独立した生成WPはWP-R2-12のQAゲート。

- **WP-R1-3・4・6の本番コピー受入** が残る。WP-R2-1〜10のAPIを実装し、今回の統合verifyはRust202成功/実ツール専用3件は別受入、clippy・整形・ガード・工程版・棚卸し642・オラクル12・カタログ152・文書リンクがすべて成功。次はWP-R2-11の事前点検/サービス管理、QA・同等性・費用制御と画面の接続。R2-6/7/10の実素材・性能条件はまだ未受入。
- **WP-R0-2** はPython3.12.13へ切り替え済み。旧新で同じ682件（681成功・1skip）と12オラクルが一致。ローカルLLM→VOICEVOX→旧nativeで1920x1080/4.6秒の実サンプル成功、PNG入力fixtureで日本語字幕も確認。旧 `.venv-311-backup` の削除は自動承認レビューにblocked by policyで拒否され未実行。別経路で迂回しない。DB/鍵の退避は保持。有料APIは使っていない。
- R1以降の全WPの状態と完了条件は実装計画を参照する。
- **GitHub Actionsは全プロジェクトで全面禁止（利用者指示）**。所有11リポジトリすべてenabled=falseを確認し、実行中は0件。PicoCastの実行中3件は中止済み。PicoAgent-Distributionに9月のqueued記録1件が残るが、通常/強制cancelともGitHubの409で拒否され、Actions無効設定で実行を抑止している。Codex・Claude・C:/00_PG共通ルールへ禁止を反映した。検証はこのPCだけで行う。

## 未マージのブランチとPR

| PR | ブランチ | base | 内容 |
|---|---|---|---|
| [#35](https://github.com/benybeny777/PicoCast/pull/35) | `codex/picoagent-job-monitoring` | `main` | Python旧版のチャンネル別自動運用 |
| [#36](https://github.com/benybeny777/PicoCast/pull/36) | `codex/license-v2-rebrand-design` | `codex/picoagent-job-monitoring` | Rust基盤・旧版安全化・移行設計 |
| [#38](https://github.com/benybeny777/PicoCast/pull/38) | `codex/wp-r0-3-logging` | `codex/wp-r0-1-doc-consistency` | 共通ログ・異常終了記録 |
| [#39](https://github.com/benybeny777/PicoCast/pull/39) | `codex/wp-r0-4-storage-safety` | `codex/wp-r0-3-logging` | 保存先の共通化と危険検出 |
| [#40](https://github.com/benybeny777/PicoCast/pull/40) | `codex/wp-r0-5-error-catalog` | `codex/wp-r0-4-storage-safety` | エラーカタログ・文書検査・スキル |
| [#41](https://github.com/benybeny777/PicoCast/pull/41) | `codex/wp-r1-1-migration-inventory` | `codex/wp-r0-5-error-catalog` | 全642項目の棚卸し |
| [#42](https://github.com/benybeny777/PicoCast/pull/42) | `codex/wp-r1-7-legacy-oracle` | `codex/wp-r1-1-migration-inventory` | 旧テスト隔離・比較契約 |
| [#43](https://github.com/benybeny777/PicoCast/pull/43) | `codex/wp-r1-2-domain-store` | `codex/wp-r1-7-legacy-oracle` | 38表のDB・型付きRepository |
| [#44](https://github.com/benybeny777/PicoCast/pull/44) | `codex/wp-r1-3-settings-import` | `codex/wp-r1-2-domain-store` | 旧設定・秘密値の照合取り込み |
| [#45](https://github.com/benybeny777/PicoCast/pull/45) | `codex/wp-r1-4-channel-import` | `codex/wp-r1-3-settings-import` | 動画履歴・素材の取り込み |
| [#46](https://github.com/benybeny777/PicoCast/pull/46) | `codex/wp-r1-6-import-cli` | `codex/wp-r1-4-channel-import` | バックアップ限定CLI・照合報告 |
| [#47](https://github.com/benybeny777/PicoCast/pull/47) | `codex/wp-r0-2-python312-switch` | `codex/wp-r1-6-import-cli` | 3.12切替手順・uv起動（実Apply前） |
| [#48](https://github.com/benybeny777/PicoCast/pull/48) | `codex/wp-r1-migration-safety` | `codex/wp-r0-2-python312-switch` | ローカル検証・全プロジェクトActions禁止・PSD/バックアップ・3.12実切替と実サンプル |
| [#49](https://github.com/benybeny777/PicoCast/pull/49) | `codex/wp-r2-1-ai-gateway` | `codex/wp-r1-migration-safety` | AI契約・チャンネル別費用予約 |
| [#50](https://github.com/benybeny777/PicoCast/pull/50) | `codex/wp-r2-2-script-engine` | `codex/wp-r2-1-ai-gateway` | 構造化台本・版付き保存 |
| [#51](https://github.com/benybeny777/PicoCast/pull/51) | `codex/wp-r2-3-voice-engine` | `codex/wp-r2-2-script-engine` | Rustの読みとVOICEVOX・実音声確認 |
| [#52](https://github.com/benybeny777/PicoCast/pull/52) | `codex/wp-r2-4-subtitle-layout` | `codex/wp-r2-3-voice-engine` | 実測字幕・表示時間・性質検査 |
| [#53](https://github.com/benybeny777/PicoCast/pull/53) | `codex/wp-r2-5-audio-mixing` | `codex/wp-r2-4-subtitle-layout` | 音声ミックス・実ffmpeg測定・R2文書同期 |
| [#54](https://github.com/benybeny777/PicoCast/pull/54) | `codex/wp-r1-retired-settings-safety` | `codex/wp-r2-5-audio-mixing` | 廃止秘密値の平文複製防止・実コピーの事前確認 |
| [#55](https://github.com/benybeny777/PicoCast/pull/55) | `codex/wp-r2-6-character-composition` | `codex/wp-r1-retired-settings-safety` | 立ち絵合成・音素時刻・PSDの厳格拒否 |
| [#56](https://github.com/benybeny777/PicoCast/pull/56) | `codex/wp-r2-7-timeline-render` | `codex/wp-r2-6-character-composition` | 字幕の実描画・背景演出・CPU動画・資源管理 |
| [#57](https://github.com/benybeny777/PicoCast/pull/57) | `codex/wp-r2-8-image-providers` | `codex/wp-r2-7-timeline-render` | 画像契約・検査上限・画像費用予約 |
| [#58](https://github.com/benybeny777/PicoCast/pull/58) | `codex/wp-r2-10-persistent-pipeline` | `codex/wp-r2-8-image-providers` | 永続DAG・リース・再開・工程版検査 |
| [#59](https://github.com/benybeny777/PicoCast/pull/59) | `codex/wp-r2-9-thumbnail-generation` | `codex/wp-r2-10-persistent-pipeline` | 実測レイアウトと縮小検査付きサムネ3案 |

WP-R0-1は [#37](https://github.com/benybeny777/PicoCast/pull/37)（`codex/wp-r0-1-doc-consistency` → `codex/license-v2-rebrand-design`）でレビュー待ち。#35と#36のマージ・base変更は別作業。既存PR #33・#34もこのWPでは変更しない。

## 移行前に残る確認

- Python実環境は3.12.13。uv.lockから構築し前後suite/実サンプルを確認した。旧3.11環境は削除拒否のため残る。証拠は `temp/python312-sample/artifacts/run-8dzzuz_0/report.json` とMP4。実PSD/GPUエンコーダ/有料生成の受入とは区別する。
- RustのフルドメインDB・取り込みAPIは実装済みだが、本番コピーでの受入は未実施。生成・YouTube・Tauri画面とログの画面/ジョブ接続は後続WP。NodeテストはUIが無いため明示スキップ。macOS実機は検証対象外。
- 実PSD2種の全11variantは不適格（最大差25/13）。途中のRGBA8丸めとDisplay P3 ICC変換順序が原因で、めたんの非表示口差分にはMULTIPLYもある。原本は不変、許容0・登録拒否を維持。原因の限定回帰7件が成功。raw/f32階層probeはdefaultだけ差0を確認した調査用で、本番の新方式・LUT・preset限定は採用していない。
- 旧版の隔離テストはPython3.11で661件成功・1skip。その後のツールテスト追加・Python3.12への切替後は同一ID/件数/skipを比較する。旧CIで発見したUTF-8/ffprobe依存は修正し関連98件成功。今後の検証はローカルだけで行う。
- テスト用一時領域 `temp/legacy-tests/session-f0csi71v` の削除は自動承認レビューに拒否されたため残っている。迂回して削除しない。Git管理・実データには含めない。
- `temp/r2-prs/` の一時PR本文削除も自動承認レビューのポリシー拒否で未実行。別経路で削除しない。
- 実バックアップ事前照合で孤立レコード（BGM1・認証情報5・投稿枠4）を検出。所属先を推測・自動転用せず保護する。出力約18.2GB/空き約18.9GBで退避＋CASの同時保持も足りないため、全件コピー受入は未実施。詳細は `docs/settings-import.md`。
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
| 検証場所 | このPCだけ。GitHub Actionsは他プロジェクトも含め全面禁止（2026-10-16）。無料枠を理由に再有効化しない |

## ローカルのリモート起動設定

`%LOCALAPPDATA%\ClaudeRemoteControl\Start-Project.ps1` と `Start-All.ps1` は、`PicoCast` 名で新フォルダを参照する。ログオンタスクは `Claude Remote Control - Projects`。`.claude/settings.local.json` の追加出力パスも新パスへ更新済み。接続URL・セッションIDは保存しない。現在の接続状態はプロセスとログで別途確認する。

## 秘密値の保護

既存のライセンス秘密鍵 `~/.nvf_license/private_key.pem` は再生成・上書きせず、Git・ログ・PRへ出さない。旧版のオーナー証明書や暗号化キーを、コード整理の対象に含めない。将来の移行では元データを読み取り専用で照合する。
