# AIゲートウェイ

`picocast-ai`の`Gateway`を、文章生成の共通入口とする。対象は企画・台本・タイトル・レビュー・画像プロンプトで、画像そのものの生成はWP-R2-8で接続する。別のプロバイダへ自動で切り替えない。

## 呼び出しとモデル

`ModelRegistry.stages`は`Stage`ごとに`StageModel`を持つ。プロバイダ、モデルID、入力・出力token上限、100万tokenあたりのマイクロ米ドル単価を設定正本から明示注入する。モデルIDや料金の組込み既定は設けない。

`Gateway::generate_json<T>(store, request, schema, cancel)`でJSON Schema検証とserde型変換を行う。`generate_json_checked<T,F>`では型変換後の文脈検査も同じ再試行範囲へ加える。JSON・型・文脈検査に失敗した場合だけ同じ要求を1回やり直し、2回目も不正なら`E-AI-SCHEMA`で停止する。

処理順序は、明示モデルの解決・実モデル一覧での存在確認、費用・token予算の確認、結果cacheの確認、生成、台帳への実績記録、来歴付与である。Geminiモデル一覧のページ続きを上限付きで読み、`generateContent`対応モデルだけを受け付ける。空設定や存在しないモデルを別モデルへ降格しない。

`GenerateRequest`はchannel_id、request_id、工程、本文、テンプレート版、設定hash、任意のproject/jobを明示する。Gatewayと全providerも作成時のChannelIdに固定し、不一致要求はモデル一覧通信より前に拒否する。別チャンネルのキー・cache・費用台帳を流用しない。`request_id`は呼出側が一意に発行する。同じIDの再送は費用予約で拒否する。`Generation<T>`は型付き結果、最後に成功した応答のusage、来歴、cache_hitを返す。失敗・再試行も含めた総費用は共通費用台帳を参照する。

本文のバイト上限は`GatewayOptions.max_prompt_bytes`でありtoken数と混同しない。入力tokenは事前に正確に算定できた扱いにせず、設定された最大量を予約して、応答の実usageで精算する。上限超過実績も保存してから停止する。完全なプロンプト文脈のtoken事前計数は未接続であり、有料本番受入ではモデル固有のtoken計数も確認する。

## 予算・再試行・中断

`GatewayOptions`の回数上限、timeout、指数バックオフの基底・上限、日次金額・token上限、本文バイト上限、開発版フラグ、有料通信許可は全て明示指定する。有料プロバイダには`allow_paid=true`と既知の正単価が必要である。偽プロバイダは開発版でだけ登録できる。

既存`cost_ledger`へ`Store::reserve_ai_cost`で各送信attemptの最大費用・tokenを原子的に確保する。別の私有台帳は作らない。成功時はusageで精算し、429や認証失敗など明示された非受理だけ費用0で記録する。503、送信状態が分からない接続断、timeout、cancel、usage欠損はUnknownとして予約を維持する。503再試行でも追加予約を必須にし、上限不足なら送らない。再起動や別connectionでも不明請求を空扱いしない。詳細は[費用台帳](ai-cost-ledger.md)を参照する。

共通再試行は429・503・接続断だけに限り、上限回数と指数バックオフを適用する。`Retry-After`の秒数・HTTP-dateを尊重する。指定待機が許容上限を超える場合は短縮して再送せず停止する。認証失敗、その他HTTPエラー、timeout、契約不正は通信再試行しない。

`Cancellation::pair()`のhandleをcancelすると、要求中・再試行待機中のfutureを中断する。送信中の要求は不明請求として予約を保持する。全要求に有限timeoutを設定する。

## プロバイダ契約と秘密値

`LlmProvider`、`Operation`、`ProviderOutput`が文章生成の共通契約である。`ProviderContract<T:Transport>`はGemini `generateContent`、OpenAI Responses、Ollama `generate`のwire変換を所有する。`ProviderLimits`で一覧ページ数とモデル件数を注入する。`HttpTransport`は`picocast_core::http::request_json`だけから通信し、本文サイズを制限する。HTTPSクラウドの接続先は公式endpointに固定し、Ollamaはloopbackだけ許可する。

秘密値は既存の暗号化storeから呼出側が読み、`Secret::from_bytes`で注入する。環境変数や平文設定を新正本にしない。`Secret`、本文入り要求、生成結果はDebugを実装しない。キーは認証headerだけへ渡し、URLのquery・argv・ログへ入れない。HTTPエラー本文は共通HTTP境界で破棄し、出力本文に認証値が含まれる場合も契約違反として止める。プロバイダ例外本文を利用者へ転送しない。

Geminiは`usageMetadata`のtotalからpromptを引き、thinkingを出力usageへ含める。OpenAIはResponsesのinput/output usageを採用し、未完了・拒否を成功として扱わない。Ollamaは非stream応答の完了理由とprompt/eval countを検証する。

## cacheと費用ゼロの検証

実HTTPは共通HTTP境界を通し、リダイレクトを追従しない。localhost・127.0.0.1・::1への要求は `http::local_client` を使い、環境変数やOSのproxyへ本文を転送しない。

`ResultCache`はパイプライン側のcache所有者へ接続する契約である。channel、モデル設定、本文、schema、テンプレート版、設定hashをcacheキーへ含め、再読取時にも来歴・schema・型・文脈を検査する。現時点で本番の永続cacheは接続していない。`NoCache`と、testkitの`MemoryCache`を利用できる。

`picocast-testkit`は`FakeProvider`と`ReplayTransport`を提供する。録画fixtureは公式契約を基に作った合成値で、実アカウント、実キー、利用者のプロンプト、実API録画を含めない。`ReplayTransport`は要求method・path・指定されたJSON本文を照合し、外部へ通信しない。

`cargo test -p picocast-testkit --test gateway`で3種のwire契約と偽実装、cache分離、予算、429/503/接続断、認証、schema/文脈再試行、中断、timeout、不明請求保持、秘密値非表示、Geminiページ続きを検証する。実通信と有料APIは実行していない。実サービス・現行モデル固有schema制約・料金・権限・長文文脈・音声/画像/動画/YouTubeの偽実装は各後続WPの受入範囲である。

## 公式契約の確認

2026-10-16に以下を照合した。料金・モデルIDをここから自動既定化しない。

- [OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create)と[構造化出力](https://developers.openai.com/api/docs/guides/structured-outputs)：`text.format`、output、usageと完了状態。
- [OpenAI models](https://developers.openai.com/api/reference/resources/models/methods/list)：利用可能モデル一覧。
- [Gemini generateContent](https://ai.google.dev/api/generate-content)と[Models](https://ai.google.dev/api/models)：JSON生成設定、usageMetadata、モデル一覧。
- [Ollama generate](https://docs.ollama.com/api/generate)と[tags](https://docs.ollama.com/api/tags)：非stream、schema、token実績、ローカル一覧。
- [jsonschema 0.58.6](https://docs.rs/jsonschema/0.58.6/jsonschema/)：MSRV1.85、MIT。外部HTTP/file参照機能を既定無効で採用した。
