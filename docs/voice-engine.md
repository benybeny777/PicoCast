# Rust の読み補正・VOICEVOX

`picocast-voice` は共通辞書と Rust Sudachi による読み補正、VOICEVOX 合成、アクセント上書き、感情のスタイル選択、LLM へ渡す前の読み点検候補を担当する。依存は `core` と `store` までとし、Python や LLM は実行しない。台詞・音声本文を `Debug` やログへ出さない。

## Sudachi と既存辞書

公式 `WorksApplications/sudachi.rs` の **v0.6.11** をコミット `90fd6068c80c2fc3b63e0dbab0e341475bad4d8f` へ固定する。[公式 Cargo.toml](https://github.com/WorksApplications/sudachi.rs/blob/v0.6.11/Cargo.toml) の MSRV は Rust 1.74.1、ライセンスは Apache-2.0。プロジェクトの Rust 1.95 で利用する。

v0.7.0 は [公式変更履歴](https://github.com/WorksApplications/sudachi.rs/blob/v0.7.0/CHANGELOG.md#070-2026-09-18) にあるとおり旧 V0 形式のバイナリ辞書を読めない。既存の `SudachiDict-core 20260428` を変更・再取得せず流用するため、現在の SudachiPy と同じ v0.6.11 を選ぶ。非公式の crates.io 再配布は使用しない。

`SudachiPaths` の全パスを呼出側から指定する。

| フィールド | この Windows 環境で確認した既存ファイル |
|---|---|
| `system_dictionary` | `.venv/Lib/site-packages/sudachidict_core/resources/system.dic` |
| `resources_directory` | `.venv/Lib/site-packages/sudachipy/resources` |
| `configuration_file` | `.venv/Lib/site-packages/sudachipy/resources/sudachi.json` |

API は絶対パスだけを受け取り、辞書・設定ファイル・資源ディレクトリと `char.def` / `unk.def` / `rewrite.def` の存在を検査する。既定の資源探索へは進めない。埋込設定や別の辞書へ自動で切り替えない。辞書・モデルのダウンロード、辞書形式の変換、実設定の変更は行わない。上の `.venv` は流用元の例であり、製品側が暗黙に固定する保存先ではない。

## 読みと辞書

`ReadingNormalizer` は `ChannelId`、`ReadingPolicy`、`ReadingDictionary`、解析器を明示して作る。呼出時も同じチャンネルを指定する。字幕の原文は保持し、音声用の読みだけを返す。

- `Off`: 原文を返す。
- `Dictionary`: 長い語から置換し、同じ語では base を user より優先する。同じ長さの置換は注入した順序を維持する。
- `SafeAuto`: base の前処理置換後、Sudachi C モードで実解析する。user の語を優先し、動詞・形容詞・助詞・助動詞・記号や一文字の漢字を保持する。旧版と同じ条件の名詞だけをひらがなへ変換する。

辞書が無い `SafeAuto` や解析の失敗を単純置換へ降格しない。分割された表層の連結が入力に一致することも検査する。バッチが途中で失敗した場合は、そのバッチで得た未確定の自動学習をメモリに残さない。

共通 DB の `ReadingEntry` / `ReadingCandidate` は typed repository を通す。`ReadingDictionary::load` は読み辞書の base/user と候補を読み、未知の辞書種別を無言で捨てない。報告の `proposed_entries` / `proposed_candidates` を保存する操作は明示的な `persist_proposals` とする。既存の異なる読みを拒否し、既存のアクセントや候補の点検結果を自動学習で初期化しない。複数行を一括確定するトランザクション API ではないため、上位層は辞書編集・学習の保存を直列化する。

固有名詞・数詞・英字・未知語・読み欠損・安全条件外の語は `ReadingInspection` へ理由付きで返す。LLM による点検と候補の承認は後段の `pipeline` が行う。この層では LLM の回答を取得しない。

## 音声とアクセント

`VoicevoxSettings` に接続先、音量・速度、末尾音素長、文字数・応答容量の上限、末尾無音の長さと判定閾値を指定する。`CharacterStyles` は通常スタイル・感情からの対応・利用可能なスタイル ID を明示する。未知の感情や利用不能な ID は停止し、通常声へ切り替えない。

実 HTTP は `CoreVoiceTransport` → `picocast_core::http::request_bytes` を通す。ローカルエンジンには `local_only=true` と `CoreVoiceTransport::local(timeout)` を組み合わせ、loopback の IP リテラルへ限定して環境プロキシを無効にする。遠隔の明示構成には通常の `CoreVoiceTransport::new` を使う。有限タイムアウト、応答容量制限、リダイレクト拒否、エラー本文の破棄は共通 HTTP 層が所有する。

旧版と同様に `POST /audio_query?text=...&speaker=...` を送り、取得した JSON の `volumeScale` / `speedScale` / `postPhonemeLength` を明示値に変更して `POST /synthesis?speaker=...` へ渡す。移行時の末尾音素長は **0.5 秒**。その他のフィールドはエンジン応答を保持する。要求は `VoiceTransport` へ注入でき、testkit はネットワークなしの録画を返せる。

`AccentPlan` は版付きの句番号・アクセント位置で、`ReadingEntry.accent_json` に保存・再読込できる。上位層が対象の台詞に対応する plan を選び、合成要求へ明示する。上書き時は句番号・モーラ数・位置・重複を検査し、`/mora_data` で音高・音素長を再計算してから合成する。エンジンが指定したアクセントを維持していなければ停止する。句番号だけを無関係な台詞へ流用しない。

WAV は RIFF/WAVE の PCM 16 bit・mono/stereo を厳密に検査する。チャンク境界・長さ・整列・サンプルレートと合成 query の一致を検査し、破損や全無音を拒否する。末尾の既存無音を数え、指定の 0.5 秒に不足する分だけ追加する。すでに 0.5 秒以上あれば追加しない。容量の上限も追加後に適用する。保存は `fsutil` の新規ファイル専用 API を使い、既存出力を置換しない。

停止コードは `E-VOICE-DICTIONARY` / `READING` / `CHANNEL` / `CONFIG` / `STYLE` / `ACCENT` / `ENGINE` / `AUDIO`。利用者向けには対処手順付きの `AppError` を返す。

## 限定検証とローカル受入

```powershell
cargo test --locked -p picocast-voice --lib
cargo test --locked -p picocast-voice installed_sudachi_matches_reading_oracle --lib -- --ignored
```

通常の 7 テストは共通辞書、途中失敗時の学習取消、アクセント保存、録画要求、スタイル選択、破損 WAV、末尾無音の不足・一致・端数・ステレオ、チャンネル境界、新規保存だけを検査する。録画 fixture は旧 `VoicevoxAPI.generate_audio` を隔離し、HTTP 応答だけを合成した実行から採取した。実エンジンの出力録音とは区別する。

明示実行する辞書テストは、既存辞書を読み、旧 reading oracle の `safe_auto` と未知語の実解析を確認する。通常テスト内の `dictionary` oracle と合わせて両方が一致する。Windows の既存 `.venv` 配置を使う受入であり、通常テストが辞書を取得することはない。

実エンジン確認には有限の `examples/voicevox_smoke.rs` を使う。事前に実行担当が VOICEVOX を起動し、新しい専用出力先を指定する。

```powershell
$voiceRun = 'C:\00_PG\22_PicoCast\temp\voice-engine\' + [guid]::NewGuid().ToString('N')
cargo run --locked -p picocast-voice --example voicevox_smoke -- `
  --endpoint http://127.0.0.1:50021 --channel voice-smoke-fixture `
  --dictionary C:\00_PG\22_PicoCast\.venv\Lib\site-packages\sudachidict_core\resources\system.dic `
  --resources-directory C:\00_PG\22_PicoCast\.venv\Lib\site-packages\sudachipy\resources `
  --configuration-file C:\00_PG\22_PicoCast\.venv\Lib\site-packages\sudachipy\resources\sudachi.json `
  --text '身近な変化ね。' --speaker 2 --speed 1.2 --volume 2 `
  --tail-ms 500 --timeout-ms 15000 --max-query-bytes 262144 `
  --max-text-characters 256 --max-wave-bytes 8388608 `
  --silence-threshold 0 --minimum-noun-characters 2 `
  --output "$voiceRun\voice.wav" --report "$voiceRun\report.json" --log-root "$voiceRun\logs"
```

2026-10-16 の Windows 受入では、明示した全資源パスで旧 reading oracle が一致し、VOICEVOX 0.25.2 の speaker 2 が実合成に成功した。24,000 Hz・mono・45,536 frames・1.897333 秒・91,116 bytes、末尾無音 12,000 frames（0.5 秒）。証拠は `temp/voice-engine/rust-explicit-s2-8d871e0c90ab4e3eb4b92100681deb34/report.json`。実 DB・設定・鍵は読まず、Python runtime・有料 API・モデル取得・エンジン起動停止も使わない。先行した speaker 3 の合成確認は資源パス厳密化前の証拠なので、最終構成の証拠とは区別する。

実合成の機械検査は、利用者による試聴と発音評価を代替しない。macOS、遠隔エンジン、実エンジンのアクセント編集・感情スタイル別の聴感はこの受入の対象外。
