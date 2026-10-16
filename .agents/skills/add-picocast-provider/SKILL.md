---
name: add-picocast-provider
description: PicoCastのRustプロバイダを追加し、契約・設定・費用ガード・偽実装と登録をそろえる依頼で使う。
---

# Rustプロバイダを追加する

1. `DESIGN_implementation_plan.md` §4.4と対象WP、`DESIGN_rust_rewrite.md`を読み、既存trait・登録先・設定の持ち主を検索する。新しい並列の登録表を作らない。
2. `ChannelId`と型付き設定を明示注入し、HTTP・時刻・プロセス・秘密値は既存の共通層を通す。失敗はカタログのコードで返し、別プロバイダへ無言で切り替えない。
3. 同じ契約検査を偽実装と本物へ適用し、キャンセル・タイムアウト・認証失敗・利用上限を確認する。有料実通信を既定にせず、利用者の指示または運用上の明確な必要を確認する。
4. LLMは `crates/picocast-ai` の `LlmProvider` / `ProviderContract` / `Gateway`へ追加する。`StageModel` / `GatewayOptions`で工程別モデル・入力サイズ・金額/トークン上限・再試行を明示する。Gatewayとプロバイダを同じ `ChannelId` に結び付け、異なるチャンネルの要求を送信前に拒否する。
5. 費用は `picocast-store::ai_cost` だけへ原子的に予約・精算する。送信結果や請求が不明な場合は予約を解放せず、再試行にも追加の予算確保を要求する。503も無条件に無課金と扱わない。
6. `picocast-testkit` の偽実装・合成録画を用い、限定確認はローカルで `cargo test --locked -p picocast-testkit --test gateway` を実行する。全体検証は変更がまとまった最後に行う。GitHub Actionsは全プロジェクトで全面禁止。
