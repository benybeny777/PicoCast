# Python 3.12 のローカル実サンプル受入

`tools/python312_sample.py` は切替後の一回検証用 helper。既存の `ScriptParser`、`VoicevoxAPI` の query/synthesis、`native_renderer.render_native` を直接使う。通常の製品機能や生成入口には追加しない。

Ollama と VOICEVOX は実行担当が先に起動する。helper は起動・停止・モデルのダウンロードを行わない。指定モデルが `/api/tags` に無ければ停止する。通信先は固定の `127.0.0.1:11434` と `127.0.0.1:50021` だけで、環境プロキシ・リダイレクト・外部接続を拒否する。

共通 `oracle_environment.isolate(work_name="python312-sample")` を本番モジュールより先に呼び、実設定・実認証情報を読まない。架空チャンネルと合成 PNG を明示入力にし、`load_character_variants` だけを fixture の `CharacterVariantSet` に置き換える。Desktop・実 PSD の探索は行わない。レンダー・字幕・音声合成は置き換えない。

Ollama に JSON schema を渡し、ずんだもん・四国めたんの順に各 1 文だけ生成する。旧パーサーと字幕分割を通し、2 台詞に一致しなければ停止する。台本は新しい専用 `metadata.db` に保存し、`script.txt` は作らない。VOICEVOX は話者 3 / 2、`postPhonemeLength=0.5` を指定する。映像は CPU の `libx264` / `veryfast`、字幕はインストール済みの Yu Gothic、横の native 既定解像度 1920×1080 を使う。BGM は明示的になし。

出力は `temp/python312-sample/artifacts/` の新しい `run-*` に保存する。既存の実出力は参照・上書き・削除しない。専用領域のリンク・ジャンクションも拒否する。helper は調査用の失敗成果物を含めて保持するため、片付けは受入記録を確認後に専用領域だけを対象にする。

Windows PowerShell では次のように実行する。タイムアウトと生成上限は実行時に明示する。`--render-timeout` は ffmpeg 1 回ごとの秒数。長時間になる実受入は実行担当が Codex Process Jobs へ渡す。

```powershell
$sampleFfmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$sampleFfprobe = (Get-Command ffprobe -ErrorAction Stop).Source
.venv\Scripts\python.exe tools/python312_sample.py `
  --model qwen2.5:7b-instruct `
  --timeout 120 --render-timeout 180 --max-output-tokens 256 `
  --ffmpeg $sampleFfmpeg --ffprobe $sampleFfprobe `
  --font-file C:\Windows\Fonts\YuGothM.ttc `
  --output-root C:\00_PG\22_PicoCast\temp\python312-sample\artifacts
```

実通信の前に同じ引数へ `--fixture-check` を足せば、実パーサー・台本 DB 往復・Pillow の合成入力・応答検証・出力境界・上書き拒否・通信拒否だけを検査できる。このモードは HTTP と ffmpeg を呼ばず、`fixture-*` の `report.json` へ `real_acceptance=false` を残す。fixture 成功は実受入の成功に数えない。

実受入では ffprobe によって H.264 映像、音声、1920×1080、有効な正の尺、2 音声入力を確認する。`report.json` にモデル名、Python/Ollama/VOICEVOX/Pillow/ffmpeg/ffprobe の版、台詞数、解像度、尺、MP4 の SHA-256 を記録する。成功した実経路だけが `real_acceptance=true` になる。画質の目視・音声の試聴はこの機械検査と別に行う。

失敗時は `E-MIGRATION-SAMPLE` と専用ディレクトリだけを表示し、トレースは同じディレクトリの `debug.log` に残す。`failure.json` がある場合は未受入として原因を調べる。実設定・実データの修復や別モデルへの無言の切り替えは行わない。
