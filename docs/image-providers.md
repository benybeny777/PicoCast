# 画像プロバイダ（WP-R2-8）

`picocast-ai::image` と `image_contract` が、Gemini native画像と利用者が別途起動したStable Diffusion WebUIを扱う。画像も既存の `ProviderId` を使い、別の登録表は作らない。`StableDiffusionWebUi` は画像専用で、LLMの `StageModel` は明示的に拒否する。

## 境界とAPI

`ImageGateway` はChannelId、画像プロバイダ、検査器、`ImageOptions` を明示して作る。要求にもChannelId、モデル、画風profile、出力寸法、料金、設定hash、テンプレート版を渡す。profileやproviderの別チャンネルは送信前に拒否する。使用するチャンネルはStore上で有効である必要がある。

`ImageProviderContract<T: Transport>` は、既存の `HttpTransport` と同じTransport契約を使う。通信の実体はcore HTTPだけが所有し、応答容量・期限・redirect禁止を継承する。SDはloopbackのhttpだけを許し、共通のno_proxy clientを通す。Geminiは既存の公式endpoint定数だけにAPIキーを送る。キーはヘッダーに置き、URL queryに入れない。通信失敗はstatus等の分類だけを返し、URL・応答本文・秘密値をログや利用者エラーへ写さない。

画像結果は検査済みのbytesと来歴として返す。CAS登録・ファイル公開は呼出側の共通ストア/パイプラインが所有する。画像モジュールが実素材や設定ファイルを書き換えることはない。

## P5/P6：画風・seed・似せない指定

`StyleProfile` はchannel、版、画風文、negative、seed方針、LoRA、禁止固有名を持つ。型はserde保存可能で、チャンネル設定の正本から呼出側が注入する。通常の上書きに環境変数やファイル検索を使わない。

全生成に「既存作品・有名キャラクター・実在人物へ似せない」指示を追加する。禁止固有名が主題や画風文に入る要求は停止する。LoRAは名前と重みを型で確認し、独自用途の確認がないものを使わない。これは権利や非類似性を機械的に保証するものではない。

seedは固定、またはbaseとattemptごとのstepを明示する。overflowやAPIの整数範囲超過を拒否する。来歴は要求seedと応答の実seedを区別する。SDの実seedは一致を要求する。Geminiが実seedを返さない場合はNoneを保ち、再現性を保証した扱いにしない。GeminiにLoRAを指定しても無視せず、非対応として停止する。

## wire契約

Geminiは `generateContent` に画像出力modalities、`generationConfig.responseFormat.image` のaspectRatio/imageSize、seedとmaxOutputTokensを送る。停止理由がSTOPの候補1件から、非thoughtのinlineData画像1枚だけを受ける。MIMEとbase64、modelVersion、usageを検査する。費用は共通のGemini usage解釈（totalTokenCount−promptTokenCountでthinkingも含む）と `StageModel::cost` を使う。[公式画像生成REST例](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)、[GenerationConfig API](https://ai.google.dev/api/generate-content)

SD WebUIは `txt2img` をbatch_size=1/n_iter=1で要求し、画像保存を無効にする。checkpoint、sampler、LoRAを事前照会し、未登録なら生成しない。要求後もcheckpoint hash・sampler・seedを照合し、WebUIが既定モデル等へ置き換えた結果を受理しない。response `images` とJSON文字列の `info` を解析し、versionも来歴に残す。[公式APIモデル](https://github.com/AUTOMATIC1111/stable-diffusion-webui/blob/master/modules/api/models.py)、[公式処理と生成info](https://github.com/AUTOMATIC1111/stable-diffusion-webui/blob/master/modules/processing.py)

両契約の合成wire録画は `src/image_fixtures/` に置く。実通信の記録ではなく、公式フィールドに沿った合成応答であり、画像本体もテストで作ったPNGを注入する。仕様は2026-10-16に一次資料で確認した。モデル名や価格の最新値はコードの既定値に固定しない。

## Q3：検査・再生成・保留

PNG/JPEGだけを受け、圧縮bytes、画像数、寸法、展開bytesの上限を先に検査する。MIME偽装や不正データは停止する。生成結果の寸法、透明率、画素の分散も検査し、空画像等を合格扱いにしない。

`GatewayImageInspector` は、既存LLM Gatewayの `generate_json_with_images` に画像を添付するadapterである。添付はGemini inlineData、OpenAI input_image、Ollama imagesに変換し、枚数・MIME・bytes・展開上限を検査する。画像の内容hashとMIMEをrequest/cache hashに含める。既存のJSON生成APIは空画像を使う同じ内部経路を呼び、費用・schema再試行・キャンセルを複製しない。

画像入力のwireも一次資料と照合した。[OpenAI画像入力](https://developers.openai.com/api/docs/guides/images-vision)、[Ollama公式generate API](https://github.com/ollama/ollama/blob/main/docs/api.md)

読取モデルは文字化け、手/顔、主題との関係を0〜100で採点し、類似性はclear/suspected/uncertainを返す。閾値は `ImageOptions` から明示する。不合格は最大 `max_regenerations+1` 枚まで生成し、上限到達時は `ImageOutcome::Hold` と `E-IMAGE-HOLD`、構造化された理由を返す。uncertainをclearへ降格させない。別providerへのフォールバックや、失敗した画像を採用する経路はない。

実画像の崩れ・無関係さ・非類似性の判定精度や法的な権利は、ここで証明していない。読取モデルの誤判定はあり得るため、実画品質の受入と必要な人手確認は別の工程である。

## 費用と中断

料金台帳は既存 `picocast-store::ai_cost` のcost_ledgerだけを使う。Gemini画像はtoken料金を明示し、生成前に入力/出力の最大費用・tokenを原子的に予約する。usage欠損・タイムアウト・キャンセル・503等の不明結果はUnknownとして予約を維持する。HTTP401/429等の明確な無課金拒否だけを解放し、画像側で無条件の通信再試行はしない。

SD/偽画像は `reserve_ai_image_cost` と `ImagesSucceeded` による枚数単位で記録する。架空のtokenを注入しない。台帳metadataの画像枚数は後方互換の任意フィールドとして追加し、既存token予約の意味を変えない。金額は整数micros、日次の金額上限はLLMと共通。画像とtokenの精算単位を取り違えた呼出しは拒否する。上限を超えた実績も過少計上を避けるため保存してから停止する。

画像検査の不合格は生成費用の取消しではない。各再生成に新しい予約を要求する。同じ送信IDの再送は拒否する。検査LLMの費用も既存Gatewayから同じ台帳へ記録する。送信後に中断しても請求不明の予約を消さない。

## 偽実装と確認範囲

`image_fake` の `FakeImageProvider` / `FakeImageInspector` は合成応答だけを返す。ImageGatewayはdevelopment明示時だけこれらを受け付ける。合成fixtureで、両providerのwire、画風/チャンネル/容量制限、検査の上限保留、画像添付LLM検査、既存予算・Unknown保持、認証/利用上限、中断/期限を検査する。

限定確認は `cargo test -p picocast-ai image --lib` と `cargo test -p picocast-store ai_cost --lib`。ガードとclippyもローカルで実行する。有料APIの実送信、SD起動、モデル取得、実素材変更、GitHub Actionsは行わない。

依存はimage 0.25.10（MSRV1.88、png/jpegのみ）とbase64 0.23.1（MSRV1.71、stdのみ）。いずれもMIT OR Apache-2.0で、workspaceのRust1.95範囲内。[image公式manifest](https://docs.rs/crate/image/0.25.10/source/Cargo.toml)、[base64公式manifest](https://docs.rs/crate/base64/0.23.1/source/Cargo.toml)
