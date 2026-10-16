# サムネイル3案の生成

WP-R2-9 の入口は `crates/picocast-pipeline/src/thumbnail.rs::generate`。AIと課金は既存の `picocast-ai`、合成と計測は `picocast-media/src/thumbnail.rs` が所有する。画像・文字の合成、縮小、文字組みを独自に複製しない。

## 入力とテンプレート

`ThumbnailRequest` はチャンネル、タイトル、出典本文、DBタイトルテンプレート用の `PromptContext`、`ThumbnailTemplate`、画像の `StyleProfile` / `ImageSpec` / `ImageBilling` / `ImageLimits`、設定hash、文字数と入力byte上限を受け取る。テンプレート・画風・任意キャラクターは同一チャンネルだけを許可する。画像寸法とテンプレートのキャンバス寸法も一致が必要。

タイトル用の既定テンプレートと最新版は `picocast-script::prompt::build(Kind::Title)` でDBから取得する。無効版や欠損を別テンプレートへ切り替えない。旧 `legacy-template-v1` の有効判定も同じ正本を使う。別のプロンプトレジストリは設けない。

`ThumbnailTemplate` は文字領域・配置・背景パネル色・キャラクター領域・描画上限・字幕と共通の `LayoutOptions` / `SubtitleRasterOptions`・縮小検査設定を持つ。`version` はこの配置設定の版。結果にはDBプロンプトのID/版と、画像の画風版・モデル・seed・request hash等も保存する。値は呼出側の型付き設定から明示注入し、本番の既定値をここへ埋め込まない。

## 生成と保留

1. 既存 `Gateway` の `Stage::Title` / strict schema で相異なる煽り文・背景指示・出典の連続引用をちょうど3案生成する。空文、制御文字、文字数超過、重複、出典にない引用を文脈検査で拒否する。schema/文脈違反の再生成は共通Gatewayの上限を使う。
2. 各案の背景を `ImageGateway` で生成する。チャンネル画風・似せない指定・seed/LoRA・画像技術検査・品質検査・再生成回数・課金予約は同じ境界を使う。画像品質で保留された場合、残りの案を生成しない。
3. 字幕と同じ `TextLayoutEngine::layout` と `rasterize_cue` で文字を実測・描画する。複数cueへ分割された場合は1枚に入らないため保留する。保持した全文と入力を照合し、途中省略や先頭cueだけの採用をしない。文字領域とキャラクター領域はキャンバス内に限定し、rasterのglyph/フチのclip拒否も維持する。キャラクターの合成と縮小には既存 `character::{composite_at,resize_premultiplied}` を使う。背景は完全不透明の同寸画像を要求する。
4. 原寸・縮小画像・文字の塗り部分だけのmaskを同じ描画から作る。縮小は縦横比を保ち、各行の実際に描かれた文字の高さと、塗り部分の画素について合成前背景に対する相対輝度コントラストの合格割合を測る。preview寸法、文字高下限、コントラスト比、合格割合、mask alpha閾値は `ReadabilityOptions` で注入する。最小文字高とコントラスト不足は保留する。数値検査に通った配置のはみ出し画素数は0。
5. 縮小PNGを画像入力付き共通 `Gateway` の `Stage::Review` へ送り、文字転記・読みやすさ・事実性・適切性・不確実性をstrict型で受ける。期待文字列を直接渡して復唱させず、画像からの転記と入力を呼出側で照合する。改行を除いた文字が一致しない場合、読めない場合、不確実な場合も保留する。
6. 全案が通った場合だけ `ThumbnailOutcome::Drafts` に3案を返す。途中保留の場合は `E-THUMBNAIL-HOLD` と候補index/工程理由を返し、部分的な候補を3案完成扱いで返さない。原画像・実素材・既存出力を変更しない。完成ファイルやDB資産の公開・登録は呼出側の既存保存境界で行う。

生成前・各候補開始時・合成後・完成時にキャンセルを確認する。AI内の中断、timeout、schema再生成、整数microsによる原子的な費用予約、不明請求の保持は共通Gatewayへ委譲する。独自の課金台帳や再試行loopは作らない。通常の最大呼出しはタイトル1回、背景3回、縮小Review3回であり、各Gateway内の明示された再生成/再試行上限は別途適用される。

`E-THUMBNAIL-SETTINGS` は配置/計測設定や画像契約の不正、`E-THUMBNAIL-INPUT` は生成入力/構造化候補の契約違反。内部の原因コード・工程・channel/request文脈は `tracing` に残し、秘密値・出典全文・画像本文をログへ出さない。

## 限定受入と未確認

`thumbnail_fixture.json` はmediaとpipelineの両方で使う合成設定。Windowsの明示指定したYu Gothic Boldを使い、合成背景・既存 `picocast-testkit::FakeProvider`・`FakeImageProvider` / `FakeImageInspector` で3案の全工程を確認する。

- `cargo test -p picocast-media thumbnail --lib`: 実測文字保持、PNG往復、はみ出し0、原背景不変、文字高不足、低コントラスト、領域不足、不透明画像契約、チャンネル/設定境界。
- `cargo test -p picocast-pipeline thumbnail --lib`: 3案完成、原子的費用台帳への7件記録、Review不合格と誤転記による残候補停止、事前キャンセル時の予約0件。
- `cargo clippy -p picocast-media -p picocast-pipeline --all-targets -- -D warnings` と `cargo xtask guard`。

実API、実人物/実素材、SD起動、GPU、モデル取得、GitHub Actionsは使用しない。合成fixtureと数値だけでは、本物の絵の類似性、煽りの妥当性、人が実際に読み取れることを証明できない。実VLMによる縮小検査自体も未受入。結果は常に `requires_human_selection=true` の選択候補であり、自動公開の合格判定として扱わない。WP-R2-12 のrevisionに結び付く総合QAカタログ、通知、投稿保留統合はこのWPの実装済み範囲に含めない。
