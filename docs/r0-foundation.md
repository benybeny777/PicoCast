# R0 共通基盤の実装と移行状況

正本: `DESIGN_rust_rewrite.md`。Rust の新規コードは `crates/` と `xtask/` に置く。Python の機能追加は行わない。

## 実装

- `picocast-core`: 検証付き `ChannelId`、UTC日時型と明示タイムゾーン、`AppError`、型・範囲付き設定、原子的保存と排他ファイル確保、HTTPの時間制限、プロセスの時間・出力制限、`channel_id` / `job_id` のログ文脈。
- Windows のプロセスは停止状態で起動し、所有する Job に登録してから再開する。失敗・時間切れでも所有ルートを回収する。Unix の process group は自己離脱やID再利用を完全には防げず、macOSの受入は未確認。
- `picocast-store`: WAL、外部キー、整合性検査、マイグレーション前のSQLiteオンラインバックアップ、トランザクション、チャンネル別の設定と秘密値。破損・復号失敗は停止し、空で作り直さない。
- 保存先は呼出側が指定した絶対データ親から `PicoCast` / `PicoCast-Dev` に分離する。SQLite待機とバックアップ単位は `StoreOptions` で明示する。
- 秘密値はAES-256-GCMとOS乱数で暗号化し、AADでチャンネルと種別の取り違えを拒否する。WindowsのマスターキーはDPAPIで保護する。旧PythonのAADなし暗号を取り込む処理はR1で実装する。非Windowsの永続キー保管は明示エラーで停止する。
- `xtask verify`: 整形・clippy・Rust単体テスト・ASTガード・UIのNodeテストを最後にまとめる。失敗後も残りを実行し、結果と非ゼロ終了コードを返す。UIがまだ無い場合のスキップは表示する。
- ガードは時刻・プロセス・HTTP・DB・書込み・環境変数・強制停止・画面文言を検査し、別名importと実テスト境界も確認する。Pythonの凍結コードは対象外。
- Rustは1.95.0と `Cargo.lock`、Pythonは3.12と `uv.lock` に固定する。Pythonロックの直接依存は、現在の3.11環境の実際の版を引き継いだ。GPUランタイムは追加しない。

## 移行と検証の境界

- GitHubは `benybeny777/PicoCast` へ改名し、originも更新済み。
- エディターのワークスペースは `PicoCast.code-workspace` に改名し、フォルダ表示名もPicoCastにした。
- Codexの画面操作はWindowsのアクセス拒否（0x80070005）で停止した。Codexのプロジェクト表示名・主フォルダは未変更。
- フォルダ名、Pythonの `legacy/` への移動、3.12環境への切替は未実施。実データと既存の3.11環境は保持している。
- 設定・metadata DBのオンラインバックアップ3件と、元の暗号化キー・旧認証ファイル・未コミット差分を `~/.codex/backups/picocast-r0/` に退避した。退避したDBの整合性はすべて確認した。内容はGitやログへ出さない。
- 事前確認では自動運用ONは0、Web/runnerプロセスは0。既存metadataに6月の `running` 記録が10件あるが、PIDの記録と対応プロセスが無いため、実行中の処理とは区別する。履歴は削除・キャンセルしない。
- `cargo xtask verify` は整形・clippy・走査ガード・単体テスト20件すべて成功した（core 7 / store 8 / guard 5）。Windows DPAPIの往復と既存キー保持、プロセスの正常終了・異常終了・時間切れ・出力超過、SQLiteのWALバックアップと破損保持を単体検証した。UIはまだ無いためNodeテストは明示スキップ。CI実行とmacOS実機は未確認。
- Pythonロックは準備段階で、稼働中の3.11環境を置換していない。`uv sync` は旧環境退避と移行の手順を満たしてから行う。
- フルドメインのDB、旧データ取込み、音声・動画生成、Tauri画面はR1以降。基盤があることと旧アプリの置換完了を混同しない。
