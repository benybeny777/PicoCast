---
name: import-picocast-data
description: PicoCastの旧Pythonデータをバックアップと検証を保ってRustへ取り込む依頼で使う。
---

# 旧データを取り込む

1. `HANDOFF.md`、`DESIGN_implementation_plan.md`のWP-R1-4とN30、`DESIGN_rust_rewrite.md`の移行設計を読み、稼働プロセスと移行対象を照合する。
2. 移行元のDB・マスターキー・生成物を保護し、SQLiteのオンラインバックアップから取り込む。秘密値を画面・ログ・Gitに出さず、暗号化方式とチャンネル境界を維持する。
3. 古いrunning記録は実プロセスと照合し、外部投稿の成否不明を自動再試行しない。コピーの件数・関連・整合性・復号を検証してから切り替える。
4. 元データを上書きせず、保管用`legacy/`も作らない。R5の切り替え検証まで旧コードを現位置に残し、不要コードだけをGit履歴で参照できる形で削除する。
5. 入口は `cargo xtask import-legacy --initialize|--settings|--channel --config <絶対パスJSON>`。設定形式と元/退避/宛先の重複拒否は `docs/legacy-import.md` を読む。元DB・元素材を直接CLIへ渡さず、退避コピーだけを指定する。型一覧・廃止設定・BGMコピー/測定尺を明示し、秘密値を設定JSONへ書かない。
6. 照合報告の `verified_with_holds` を不一致ゼロと取り違えない。未知表の専用写像・権利確認・自動運用の再承認など残る保留を記録する。同一コピーを再取り込みして冪等性を確認し、切り替えや影運用の受入とは区別する。検証はローカルのみで行い、GitHub Actionsは他プロジェクトを含め全面禁止。
