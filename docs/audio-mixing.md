# 音声mix（WP-R2-5）

`picocast_media::audio` は、話者音声の並べ替えと間、BGMのsidechain ducking、2pass loudnorm、ebur128による受入計測を担当する。実音源やDBへ暗黙にアクセスしない。`ChannelId`、導入済みツールの絶対パス、素材、設定、キャンセル通知、出力先を呼出時に渡す。

## APIと設定

- `MediaTools`：ffmpeg/ffprobeの絶対パス。両方とも通常ファイルであることを確認する。
- `SpokenClip`：素材パス、話者ID、本文、音声長ms。ffprobeで実際の長さと照合する。
- `AudioMixOptions`：sample rate/channel数、目標LUFS/True Peak/LRA、peak用headroom、許容LU差、線形/動的補正、duration許容差、素材数/長さ/filterサイズ上限、thread数、ducking設定、処理期限/出力上限。既定値は持たず、設定正本から明示注入する。
- `PauseProfile`：genre識別子、基本・読点・句点・改行・話者交代の間ms。同じ処理へ異なるprofileを渡し、ジャンル別の別実装を作らない。
- `mix`：`MixRequest` と `watch::Receiver<bool>` を受け、完成WAVとreportを一つのbundleとして公開する。
- `measure_audio` / `tool_versions`：後続の動画レンダー・QAでも利用できる計測と来歴の共通入口。

音量の受入設定は設計値の-14 LUFS、許容差1 LU以内、True Peak上限-1 dBTPとする。丸めとresampleを考慮するheadroomも明示設定する。fixtureでは0.2dBを使用する。中間・完成音声は24bit PCM WAVで、lossy codecによる再劣化を避け、動画エンコードへ引き渡す。

## 間とtimeline

`timeline` は各clipの `start_ms` / `end_ms` / `pause_after_ms` を生成し、字幕と同じ相対msで扱う。間は「基本＋末尾の句読点種別＋次話者への交代」で計算する。改行は句点より優先し、閉じ括弧直前の句読点も扱う。整数overflow、空本文/話者、空genre、上限超過は停止する。

台詞の途中にも間を挿入する場合は、音声合成前に `phrases` で句読点/改行単位へ分割し、その単位の音源を作る。小数点・桁区切りの数字は途中で切らない。すでに完成した一つの音源の内部へ、文字位置だけから無音を挿入することはしない。これは音声区間対応が不明な位置を推測して壊さないためであり、既存音源を渡す経路で内部句読点の間まで補正済みとは扱わない。

## 補正と計測

最初に各音源を指定sample rate/channel数へそろえ、設定した間を加えてconcatする。BGMは必要な長さだけloopし、声をsidechain信号として `sidechaincompress` で下げ、`amix normalize=0` で混ぜる。threshold/ratio/attack/releaseと声・BGM gainはすべて型付き設定から来る。

同じpremixに対し、1pass目でloudnormのinput I/TP/LRA/thresholdとtarget offsetを測り、2pass目へ渡す。`linear_normalization=false` は明示的な動的補正である。trueを指定したのにffmpegがdynamicへ切り替えた場合は停止し、黙って別modeを採用しない。

完成候補を `ebur128=peak=true` で再計測し、統合LUFSとTrue Peakの両方が受入設定に入ること、完成音源長がtimelineと一致することを確認する。無音等のinf/nan、欠けたJSON/summary、形式不正は失敗として扱う。

## 公開・中断・来歴

ffmpeg起動は `picocast_core::proc` だけを通り、各呼出しへ期限とstdout/stderr上限を渡す。キャンセル通知を受けたら所有futureを閉じ、既存procの子孫回収境界へ委ねる。キャンセル送信側を閉じた場合も中断する。

失敗はmix入口のfunnelでChannelId、工程（元音源probe・premix・1pass測定・2pass補正・ebur128受入・レポート・公開等）、原因コードをdebugログへ残す。入力/計測エラーの内部発生位置と、長さ不一致・音量不合格の数値も記録する。音源本文・個人パス・秘密値・スタックは利用者向けエラーへ含めない。

素材は読み取り専用入力として使い、`-n` で外部出力の置換も禁止する。中間と候補は出力先の同じ親にある専用TempDirで保持し、検証成功後だけ `fsutil::publish_new_directory` でbundleを排他的に確定する。既存出力は競合時も変更しない。失敗・中断時に完成出力先を公開しない。中間premixは公開前に削除する。

bundleの内容は `mix.wav` と `report.json`。report schema_version=1にはChannelId、UTC時刻、ffmpeg/ffprobe版、全mix/間設定、clipのms timeline、BGM有無、両passの測定、最終ebur128計測を保存する。素材の個人パスや本文をreportへ写さない。後続WP-R2-7はこの版付きreportと `AudioOutput` のパスを利用できる。

## 検証

通常の限定テスト：`cargo test -p picocast-media audio::tests --lib`。

実ツールのテストは通常はignoreし、導入済み実体を明示注入して実行する。以下の変数は受入テスト実行時の引数であり、製品設定ではない。読み取りは共通の `picocast_core::settings::validation_ffmpeg_path` だけを通し、絶対パスを要求する。

```powershell
$env:PICOCAST_TEST_FFMPEG = (Get-Command ffmpeg -ErrorAction Stop).Source
cargo test -p picocast-media audio::tests::installed_ffmpeg_three_second_mix_meets_lufs_peak_and_ducking --lib -- --ignored --nocapture
```

このPCのffmpeg 8.0.1で、1000Hzの声と200HzのBGM（各3秒の合成PCM）を使い、2pass補正後の-14±1 LUFS / True Peak<=-1 dBTP、BGM/声の周波数成分比<0.25、元2素材のbytes不変、既存出力不変、長さ不一致時の未公開を確認する。出力上限1byte、期限1ms、起動中のキャンセルでも完成出力を公開しないことを実プロセスで確認する。純粋テストでは句読点/改行/話者交代、数値検証、無音/壊れた計測の拒否、処理前キャンセルを確認する。

実話者の聴感品質、ジャンルごとの適切な間の値、長編、2秒以上の無音QAや区間別の声/BGM比QA、最終動画codec後の測定は未確認で、後続の設定・QA・レンダーで扱う。実ユーザー音源、実DB、有料API、ダウンロード、GitHub Actionsは使っていない。
