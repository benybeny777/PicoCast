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

## 画像と画像入力を追加する

- 画像生成は `picocast-ai/src/image.rs` の `ImageProvider` / `ImageGateway`、wireは `image_contract.rs::ImageProviderContract` を使う。別Gateway・登録表・課金台帳を作らない。`ProviderId` 追加時は全matchとLLM `StageModel` の支持範囲も照合し、画像専用providerをLLMへ誤登録しない。
- `StyleProfile` のチャンネル画風・negative・seed・LoRA・似せない固有名指定、`ImageOptions` / `ImageLimits` の枚数・byte・寸法・decode上限・timeout・再生成上限を明示注入する。技術検査と `ImageInspector` を両方通し、品質不足と判断不能は `ImageOutcome::Hold` とする。数値や偽実装だけで本物の絵の類似性・品質まで受入済みにしない。
- 画像入力付きLLMは既存 `Gateway::generate_json_with_images` と `InlineImage` / `MultimodalInput` を使う。既存のテキストAPIと同じ予算・中断・schema再試行・内容hash入りcache経路を使い、画像providerごとのwireを `image.rs` の共通変換へ集める。
- 枚数課金は `reserve_ai_image_cost` / `ImagesSucceeded`、トークン課金は既存 `reserve_ai_cost` / `Succeeded` を使う。不明請求を保持し、偽トークンで枚数課金を迂回しない。`docs/ai-cost-ledger.md` と `docs/image-providers.md` を実API契約に合わせて更新する。
- 公式一次資料で現行wireを確認し、`image_fixtures/` の合成録画と `image_fake::{FakeImageProvider,FakeImageInspector}` で受入する。限定確認はローカルの `cargo test --locked -p picocast-ai image --lib`、台帳変更時は `cargo test --locked -p picocast-store ai_cost --lib`。実API・課金・SD起動・GPU・モデル取得は作業の明示範囲を確認し、禁止された場合は実行しない。
