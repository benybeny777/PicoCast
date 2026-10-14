---
name: implement-picocast-r0
description: PicoCastのRust共通基盤、検証ガード、改名とPython旧環境の移行を実装・再開する依頼で使う。
---

# Rust基盤と旧環境を移行する

1. `HANDOFF.md`、`DESIGN_rust_rewrite.md`、`docs/r0-foundation.md`、現在の差分を照合する。販売機能とPythonの新規機能は作らない。既存未コミット差分は保持する。
2. Rustの所有境界は `crates/picocast-core`、`crates/picocast-store`、`xtask` に分ける。チャンネルを `ChannelId` で明示し、設定・時刻・HTTP・プロセス・書込み・DBの持ち主を通す。禁止を解除して通すのではなく、共通部品へ集約する。
3. 修正中は確実に必要な単体テストのみ実行する。変更がまとまった最後に `cargo fmt --all` と `cargo xtask verify` を実行する。依存は `Cargo.lock` の `--locked` を使う。Windows実機・CI・macOSの確認を分けて記録する。
4. 改名と旧環境移行の前に、自動運用、実プロセス、metadataの未完了記録を照合する。古い `running` 表示だけで活動中と断定せず、PID・時刻・プロセスを確認する。履歴を消したり有料処理を自動再実行したりしない。
5. マスターキーと設定・metadata DBをリポジトリ外へ退避する。DBはSQLiteのオンラインバックアップを使い、WAL込みで整合性を確認する。未コミット差分も退避し、秘密値は画面・ログ・Gitへ出さない。
6. 実行中のCodexが使うフォルダを移すときは、参照先の更新とセッション再開を含む `DESIGN_rust_rewrite.md` §2.2 を満たす。旧名の別フォルダや新しいリポジトリを勝手に作って分岐させない。操作できないアプリ設定は未完了として正確に記録する。
7. Python版を `legacy/` へ移すときは、コード・素材・法務文書・data・output・環境を同じ基準で動くようまとめる。既存差分があるファイルの移動では、元のGit blobを移動先のindexに使い、既存の編集を勝手にコミットしない。
8. Python 3.12の環境を作る前に3.11環境を退避する。`uv sync --locked --group build` で再現する。起動スクリプトとスキルの作業ディレクトリを移行先へ合わせる。外部のVOICEVOX・SD・Ollama環境は変更しない。
9. 全体の確認は環境切替後に1回へまとめる。既存データを変更しないテストとサンプル確認を使い、必要な外部サービスが無い場合は実確認と扱わない。検証できるまで旧環境を消さない。
10. 関連差分だけをコミット・pushし、既存PRを更新する。R0の未完了部分と次の着手点をHANDOFFへ残す。R1以降は設計の着手条件に従う。
