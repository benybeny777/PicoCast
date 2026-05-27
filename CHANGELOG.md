# 変更履歴

このファイルには、運用や品質に影響する大きめの変更を残します。

書く目安:
- プロンプト方針を大きく変えた
- YouTube Analytics、アップロード、スケジュールなど運用フローを変えた
- 生成物の品質レビュー、尺チェック、NGワードなど判定基準を変えた
- GUIの主要ボタンや出力形式を変えた

細かい文言修正や見た目だけの軽微な変更は、必要な場合だけ書きます。

---

## 2026-05-28

### Stable Diffusion WebUI プロンプトを Ollama で日→英翻訳

- `core/image_generator.py` に `_translate_to_english_for_sd()` を追加。Stable Diffusion WebUI に送る前に日本語の背景描写を Ollama で英語プロンプトへ変換する。
- `config.py` に `OLLAMA_TRANSLATE_MODEL`（デフォルト `qwen3:8b`）を追加。`.env` / 設定画面から変更可能。
- Ollama 未起動時は `ensure_ollama_server()` で自動起動。翻訳失敗時は例外を伝播して停止（サイレントフォールバックなし）。

### 生成・再生成画面に画像エンジン選択を追加

- `/generate`・`/history/{name}` の再生成フォームに **画像エンジン**（Google AI / Stable Diffusion WebUI Forge）セレクタを追加。
- `/images` 画像再生成にも同エンジン選択と **縮小生成** チェックボックスを追加。
- スキーマ `ImageRegenerateRequest` に `sd_size_mode` フィールドを追加し、`image_service._run_regenerate` が `ImageGenerator` へ渡すよう対応。

### サイレントフォールバックをエラーに変更（`ImageGenerator`）

- `__init__`: `GOOGLE_API_KEY` 未設定で nanobanana エンジン選択時に `RuntimeError` を raise（従来: 警告 print → 無言スキップ）。
- `generate_background`: `self.client` が None のとき `return None` を廃止し `RuntimeError` を raise。

### Web UI 設定画面の改善

- 設定保存値をアプリ再起動なしで即時反映（`config_service._apply_runtime_updates()` が `setattr(cfg, ...)` + `sys.modules` 全走査で伝搬）。`WEB_UI_PORT` など起動時固定パラメータのみ例外。
- 保存成功・失敗をトースト通知で表示（従来のインライン `#save-status` テキストを廃止）。
- 「サービス状態」タブを設定画面から削除。サービス接続状態はダッシュボードで確認する。
- ナビゲーションの「画像」リンクを削除。画像確認は `/history/{name}` からリンクする。

### UI 表示から Stable Diffusion の略称「SD」を除去

- テンプレート・設定ラベル・コメント内の「SD WebUI Forge」→「Stable Diffusion WebUI Forge」、「SD生成」→「縮小生成」に統一。変数名・ファイル名は変更なし。

---

## 2026-05-27

### macOS向けWeb UI起動手順を追加

- macOS用の `start.command` を追加し、`.venv/bin/python -m web_app.app --open-browser --reload` でWeb UIを起動できるように整理
- `VOICEVOX_URL` / `VOICEVOX_PATH` を環境変数で上書き可能にし、Windows固定パスを既定値から外して手動起動前提に変更
- README / SPEC にWindowsとmacOSのセットアップ・起動手順を併記
- Web UIのナビゲーションに `画像` を追加し、画像確認・再生成画面へ直接移動できるよう修正

### SD WebUI Forge 用モデル管理機能を追加

- `core/sd_model_manager.py: SDWebUIModelManager` を新規追加。`assets/sd_webui/model_manifest.json` に基づきモデルのインストール確認・ダウンロード・SHA256検証を行う。
- `SD_WEBUI_MODEL` 設定時に画像生成前にモデルの準備（インストール確認 → 必要なら自動ダウンロード → `set_active_model()`）を実行するよう `core/image_generator.py` に `_prepare_sd_webui_model()` を追加した。`SD_WEBUI_MODEL` 未設定時はスキップ（現在のロード済みモデルを使う）。
- `StableDiffusionWebUIGenerator` に `get_models()`, `get_current_model()`, `set_active_model()`, `rescan_models()` を追加。SD WebUI API 経由でモデル情報取得・切り替えを実行する。
- `/sd-models` Web UI ページを追加。マニフェスト内モデルの状態・ダウンロード・使用切り替え・再スキャンを行える。
- `web_app/routes/api_sd_models.py` に REST API を追加。ダウンロードはバックグラウンドスレッドで実行しポーリング形式で進捗を確認する。
- 設定に `SD_WEBUI_ROOT`, `SD_MODEL_MANIFEST_PATH`, `AUTO_DOWNLOAD_SD_MODELS` を追加。設定画面から変更可能。
- 設定画面の SD WebUI ステータスにマニフェスト導入済み数を追加（SD_WEBUI_ROOT 設定時のみ）。
- 設定画面から `/sd-models` ページへのリンクを追加。
- `tests/test_sd_model_manager.py`, `tests/test_sd_model_service.py` を追加（合計 29 テスト）。

### 画像生成バックエンドに Stable Diffusion WebUI Forge を追加

- `IMAGE_BACKEND=sd_webui` を設定することで、Forge / AUTOMATIC1111互換APIから背景・サムネイルを生成できるようにした。
- `IMAGE_BACKEND=gemini`（デフォルト）のときは従来どおり Nano Banana / Gemini 画像生成を使う。
- 画像生成失敗時は別エンジンへ自動フォールバックせず、明示エラーで停止する（設計方針不変）。
- `core/sd_webui_generator.py: StableDiffusionWebUIGenerator` を新規追加。`POST /sdapi/v1/txt2img` で生成し、base64 PNG をファイル保存する。
- サムネイル生成も `IMAGE_BACKEND` に従うよう変更。背景と同じエンジンでサムネを生成する。
- GUIの「設定」画面のサービス確認に「SD WebUI Forge」ステータスを追加。`IMAGE_BACKEND=sd_webui` のとき接続OK/NG とロード中モデル名を表示する。
- 設定画面から `IMAGE_BACKEND` / `SD_WEBUI_*` を変更できるよう `config_service.py` に追加。
- `tests/test_sd_webui_generator.py` を追加（httpx monkeypatch によるモックテスト）。
- README / SPEC を更新し、Forge セットアップ手順・設定一覧・バックエンド切り替え表を追記した。

### Web UI画像スタイル選択肢の引用符表示を修正

- `.env` の `WEB_DEFAULT_IMAGE_STYLE` / `WEB_IMAGE_STYLE_CHOICES` に `'通常'` や `’通常’` のような引用符付き値が入っても、生成画面・履歴詳細画面のセレクトボックスには `通常` と表示するよう正規化
- 設定画面が `WEB_IMAGE_STYLE_CHOICES` の現在値を Python のタプル表現 `('通常', 'アニメ', '水彩')` として表示・保存し得る問題を修正し、正本の `通常,アニメ,水彩` で保存するよう変更
- 画像スタイル選択肢に引用符が混ざらないことをテストで固定

### 履歴再レンダー時のffmpegハング対策

- nativeレンダーのffmpeg実行を `-nostdin` + `stdin=DEVNULL` の非対話モードに統一し、履歴からの再作成で入力待ちによりジョブが固まらないよう修正
- `NATIVE_FFMPEG_TIMEOUT_SEC` / `NATIVE_FFPROBE_TIMEOUT_SEC` を追加し、ffmpeg / ffprobe が停止した場合にタイムアウトで失敗として上位へ伝播するよう修正
- Web UI設定画面から native ffmpeg / ffprobe タイムアウトを変更できるよう追加

### よみがな補正の依存関係とエラー処理を修正

- `requirements.txt` を追加し、`safe_auto` に必要な `sudachipy` / `sudachidict_core` を依存関係へ追加
- READMEのセットアップ手順を `pip install --upgrade -r requirements.txt` に統一し、依存漏れが起きないよう修正
- 読み補正の辞書パスを `config.py` の設定値へ移し、辞書JSON不正・候補保存失敗・SudachiPy解析失敗を無言でスキップしないよう修正
- 運用中に生成される `data/reading_dictionary_user.json` / `data/reading_candidates.json` をgitignore対象に追加
- `SPEC.md` のよみがな正規化説明を、廃止済みのOllama方式からSudachiPy + 自前辞書方式へ更新

### ComfyUI背景生成の失敗記録を修正

- `local_comfyui` の必要モデル確認を生成処理内へ移し、モデル不足で中止する場合も `_meta/image_generation.json` に `status=failed`、`error_message`、`fallback_used=false` を保存するよう修正
- `_meta/image_generation.json` は最新結果をトップレベルに保持しつつ、`entries[]` に生成試行履歴も追記する形式に整理
- ComfyUIモデルマニフェスト不正やSHA256検証時の読み取り失敗を無言で握りつぶさず、原因が分かる例外として扱うよう修正

### ネタ会議モードの改修（ShortLong・ミニ番組化 / Phase 1〜3）
- Web UIの「ネタ会議台本案プロンプト」を全面刷新し、2〜4分尺のプレミア公開・投票用ミニ番組として出力するよう変更
- プロンプト生成時に過去の動画タイトルと直近のAnalyticsデータをTSVで渡し、横展開や再挑戦の判断を含めてAIに候補ネタを出させる機能を追加 (Phase 2)
- 動画形式が「ネタ会議」の場合にShorts判定を外し、横画面の通常動画（Longルール）としてレンダリングするよう `_detect_is_shorts` を調整
- `_meta/metadata.txt` に複数行にわたる候補ネタの詳細データ（分類、冒頭1秒案、めたん判定など）を保存できるようパーサーを拡張
- 候補ネタのメタデータを解析し、後日の投票結果やShorts化への追跡用に `_meta/netakaigi.json` を新設して保存する処理を追加 (Phase 2/3)
- 候補は4〜5個とし、めたんによる「3秒でスワイプされる」等の制作側自虐メタツッコミを取り入れた台本構成を厳格化


### VOICEVOX読み補正の自前辞書移行とComfyUIモデル管理機能追加

- core/reading_normalizer.py: VOICEVOX読み間違い対策をLLM方式から、SudachiPy形態素解析と自前辞書を組み合わせた安全な補正方式へ刷新
- core/comfyui_model_manager.py: ComfyUI使用時のモデル導入状態チェック・半自動ダウンロード機能を追加
- web_app/routes/api_comfyui.py / web_app/templates/comfyui_models.html: Web UIにComfyUIモデル管理画面を追加
- core/image_generator.py: ComfyUI生成開始前に必須モデルの不足を検知し、安全に停止する機構を追加
- config.py: VOICE_READING_MODE、COMFYUI_ROOT_DIR 等の新設定を追加



### Local / ComfyUI 背景生成を追加

- 背景画像のみ `Nano Banana` / `Local / ComfyUI` をWeb UIから選択可能にした。サムネイル生成は当面 Nano Banana / Gemini を維持
- `assets/comfyui/presets.json` と workflow 雛形を追加し、用途別プリセット「背景（漫画風・標準）」「背景（資料風・写実）」「背景（難プロンプト用）」を定義
- `core/comfyui_client.py` と `core/local_prompt_adapter.py` を追加。ComfyUI API接続確認、workflow注入、完了待機、画像検証、ローカル向け背景プロンプト整形を実装
- ComfyUI未起動、workflow不正、checkpoint未設定/未配置、タイムアウト、出力画像不正では自動フォールバックせず、原因を表示して処理を中止する方針を明記
- `_meta/image_generation.json` に背景生成エンジン、プリセット、checkpoint、workflow、seed、prompt、negative_prompt、status、error_message、`fallback_used=false` を保存

### サービス診断表示を追加

- `112ef08`: Web UIのダッシュボード/設定画面に Ollama 接続状態、ffmpegバージョン、GPUエンコーダー表示を追加
- ダッシュボードは秘密ファイル名やAPIキー有無の羅列をやめ、Google AI / OpenAI / YouTubeアップロード / YouTube Analytics の連携状況表示に整理。実行環境の詳細確認は設定画面へ寄せた

### よみがな正規化のOllamaモデル確認を明確化

- `VOICE_READING_NORMALIZE_MODEL` の既定値を配置済み運用に合わせて `qwen2.5:7b-instruct` に変更
- よみがな正規化開始前にOllamaのモデル一覧を確認し、指定モデルが未配置の場合は `/api/chat` の404ではなく「モデル未配置」と分かるエラーで中止する

### 動画生成・レンダリングをワーカープロセスへ分離（メモリ解放）

- `worker_pipeline.py`: 新規。`run_pipeline` を別 Python プロセスで実行するスタンドアロンスクリプト。完了後プロセスが終了しOS レベルでメモリを解放する
- `worker_render.py`: 新規。`render_native_test` を別 Python プロセスで実行するスタンドアロンスクリプト
- `web_app/worker_runner.py`: 新規。上記 worker スクリプトを subprocess で起動し、stdout JSONL 進捗を `Job.logs` へ転送する共通ヘルパー。stdin への `"cancel\n"` でグレースフルキャンセル、15秒タイムアウト後に terminate
- `web_app/services/generation_service.py`: `from main import run_pipeline` をインプロセス呼び出しから `run_in_worker("worker_pipeline.py", ...)` に変更
- `web_app/services/render_service.py`: `render_native_test` 直接呼び出しから `run_in_worker("worker_render.py", ...)` に変更

### 視聴者維持率分析（Analytics画面）

- `core/youtube_analytics.py`: `fetch_audience_retention()` を追加。YouTube Analytics API の `elapsedVideoTimeRatio` ディメンションを使い、指定動画の秒単位維持率データを取得する
- `core/retention_analysis.py`: 新規。離脱ポイント（連続行で5pt以上の低下）・ループ可能性（audienceWatchRatio > 1.0）を検出し、自動コメントを生成する `analyze_retention()` を実装
- `web_app/routes/api_analytics.py`: `GET /api/analytics/retention?video_id=...&duration=...` エンドポイントを追加
- `web_app/templates/analytics.html`: Analytics一覧表で行を選択すると「維持率分析」ボタンが有効化され、モーダルで分析結果（テーブル・離脱ポイント・自動コメント）を表示。TSVコピー機能付き

### 固定コメント自動投稿（スロット時刻到達時）

- `web_app/services/auto_fixed_comment_service.py`: 新規。アプリ起動時にデーモンスレッドを起動し、YouTubeの公開スロット時刻（7/12/19/21時 JST）の5分後にのみ未投稿候補をチェックして自動投稿する。ローカルファイルで候補をスキャンしてから YouTube API を呼ぶ二段階チェックで無駄なAPI呼び出しを防ぐ
- `web_app/app.py`: FastAPI `lifespan` コンテキストマネージャーで起動時にウォッチャースレッドを開始
- `config.py`: `AUTO_FIXED_COMMENT_ENABLED` 設定を追加（デフォルト OFF）
- `web_app/services/config_service.py`: 設定画面の EDITABLE_CONFIG に「固定コメント 自動投稿」トグルを追加
- `web_app/templates/fixed_comment.html`: 自動投稿済みエントリに「自動」バッジ（badge-info）を表示。未確定の自動投稿中は「自動投稿中…」バッジを表示

### 固定コメント自動生成をめたん調テンプレートに変更

- `core/comment_templates.py`: 新規。四国めたん調（お嬢様口調・軽い毒舌）の固定コメントテンプレートを実装。タイトルからトピックを抽出し、`normal` / `topic_request` の2モードでランダム生成する `build_fixed_comment()` を提供
- `main.py`: 固定コメント生成を Gemini API 呼び出しから `build_fixed_comment()` のテンプレート生成へ変更。APIコスト削減および安定しためたん口調を実現

### 出力フォルダを開くボタンを追加

- 履歴詳細・履歴一覧に「フォルダを開く」ボタンを追加（Windows: `os.startfile`、Mac: `open`、Linux: `xdg-open`）
- `POST /api/history/{history_name}/open-folder` エンドポイントを追加

### 出力フォルダが開いている状態での再生成エラーを解消

- `main.py`: `os.replace(theme_dir, backup_dir)` が PermissionError で失敗した場合（Explorer でフォルダを開いている等）に `OutputDirectoryLockedError` を投げる代わり、警告ログを出して上書き生成を続行するよう変更
- バックアップ失敗時は `_existing_theme_backup = None` のまま処理を継続するため、背景再利用とサムネイルフォールバックはそのケースで無効化される

### 読み補正 ON 時の Ollama 未起動をエラー中止に変更

- `core/reading_normalizer.py`: `VOICE_READING_NORMALIZE_ENABLED = True` の状態で Ollama に接続できない場合、サイレントスキップせず `RuntimeError` を投げて生成を中止するよう変更
- API 呼び出し失敗時の `except Exception: pass` も削除し、エラーをそのまま上位に伝播させるよう変更

### Ctrl+C 即時終了を修正

- `web_app/job_manager.py`: `ThreadPoolExecutor` に `atexit.register(lambda: executor.shutdown(wait=False))` を追加し、Ctrl+C 時にワーカースレッドの終了を待たずに即退場するよう変更
- `web_app/worker_runner.py`: `atexit.register(_kill_all_workers)` で起動中のワーカープロセスツリーをシャットダウン時に強制終了するよう変更

## 2026-05-26

### 実尺チェックをよみがな正規化・音声生成後に移動

- `main.py`: VOICEVOX 音声生成ループ完了直後に全 WAV ファイルの合計秒数を計算し `duration_review()` で評価するよう変更
- Shorts で `needs_review`（< 35s または > 58s）の場合は MP4 化を中止して台本修正を促す
- 結果を `_meta/duration_review.json` に `"estimated": false` 付きで保存する
- `SPEC.md`: 実尺チェックのタイミングと停止条件を更新

### 履歴詳細の再生成ボタン修正

- `web_app/templates/history_detail.html`: 履歴名をURL/JavaScriptへ安全に埋め込むよう修正し、空白・記号入りの履歴名でも「全工程を再生成」「動画を再生成」が壊れないようにした
- `tests/test_web.py`: 記号入り履歴名の詳細画面で再生成用JavaScriptが壊れないことを確認するテストを追加
- `web_app/templates/logs.html`: 実行中ジョブのキャンセル操作が状態表示に見えないよう、ボタン文言を「中止する」に変更

### ネタ募集CTAの通算制御とAnalytics表示

- `core/cta_policy.py` / `web_app/services/generation_service.py`: Shortsの新規/横展開を既存出力から通算し、`TOPIC_REQUEST_CTA_EVERY_N`（既定5）本に1本だけ `ネタ募集CTA: 許可` を自動付与するよう変更
- `core/youtube_analytics.py` / `core/analytics_score.py` / `web_app/templates/analytics.html`: ネタ募集CTAの対象有無と理由をYouTube Analytics取得結果へ取り込み、Analytics画面とTSVで確認できるよう変更
- `README.md` / `SPEC.md` / `core/script_generation_prompt.txt` / `samples/prompt_parts/food/script_generation_prompt.txt`: 旧来の「同時生成5本以上で最大1本」記述を、通算5本に1本の運用へ更新
- `README.md`: `config.py` は共通の既定値、`.env` / 環境変数はローカル上書きとして優先される関係を明記
- `web_app/services/config_service.py`: Web UIで保存した非秘密設定を、可能な範囲で現在のWebプロセスへ即時反映するよう変更

### ドキュメント整合性整理

- `README.md`: 環境準備、APIキー/OAuth、日常操作手順をWeb UI前提で整理し、通常起動は `start.bat` 推奨であることを明記
- `README.md`: ユーザー向け注意事項から削除済み機能の説明を外し、現行運用に必要な注意へ整理
- `README.md`: 注意・制約事項を外部公開禁止、秘密情報、外部API費用など本当に注意が必要な項目に絞り込み
- `SPEC.md` / `AGENTS.md`: 起動手順の記述を `start.bat` 推奨に統一し、手動起動は補助導線として説明

### Web UI一本化・旧GUI/CLI廃止

- `gui.py`: 旧Tkinter GUIを削除し、操作入口をローカルWeb UIへ一本化
- `main.py`: 直接CLI生成入口を削除し、`run_pipeline()` をWeb UIから呼ぶ生成パイプラインとして維持
- `start.bat`: `python -m web_app.app --open-browser` 起動へ変更
- `web_app/templates/generate.html` / `web_app/schemas.py` / `web_app/services/generation_service.py`: Web生成画面に LongサムネAB、Long節約、SD生成、背景再利用を追加し、`run_pipeline()` へ渡すようにした
- `web_app/templates/history.html` / `web_app/routes/api_history.py`: 履歴から複数選択して `script.txt` ベースで再生成する導線を追加
- `config.py`: Web UIの既定画像スタイル、画像スタイル選択肢、生成オプション既定値、ジョブポーリング間隔を追加。認証情報以外のWeb設定を `config.py` に集約
- `config.py` / `web_app/services/config_service.py` / `web_app/templates/settings.html`: Web UI表示名、ジョブ成功後再読み込み、トースト表示時間、サービス確認タイムアウトを設定値化。設定画面には変更頻度が高い生成・表示・モデル設定を追加し、APIキー状態表示と変更欄を常に最下部へ移動
- `README.md` / `SPEC.md` / `AGENTS.md`: Web UI一本化後の起動方法、主要機能、設定、旧GUI/CLI廃止方針へ更新
- `README.md` / `SPEC.md`: 現状のWeb専用入口、依存パッケージ、Web生成オプション、履歴再生成API、`start.bat` 起動に合わせて説明を再整理

### よみがな正規化（VOICEVOX誤読対策）

- `core/reading_normalizer.py`: Ollama を使い、VOICEVOX に渡す前に全セリフチャンクを一括でよみがな変換。固有名詞・難読漢字等の誤読を防ぐ。Ollama未起動時は元テキストへフォールバックして生成継続
- `main.py`: 音声生成ループ前にバッチ変換を実行。VoicevoxAPI には変換後テキストを渡し、字幕マッチング用ファイル名は元テキストを維持
- `config.py`: `VOICE_READING_NORMALIZE_ENABLED` / `VOICE_READING_NORMALIZE_MODEL` / `VOICE_READING_NORMALIZE_OLLAMA_URL` を追加
- `web_app/services/config_service.py`: 上記3設定を設定画面の編集可能項目に追加（Ollamaモデル選択UI対応）

### Web UI 全般改善

- `web_app/templates/generate.html`: プロンプト生成機能追加（AI台本作成・Shortsタイトル案・Longタイトル案）、クリップボード自動コピー、目立つトースト通知
- `web_app/templates/upload.html`: 個別→チェックボックス複数選択で一括アップロードに変更
- `web_app/services/fixed_comment_service.py` / `web_app/templates/fixed_comment.html`: 固定コメント候補が `output/000_uploaded/` 配下のアップロード済み履歴と `_meta/metadata.txt` の固定コメントを参照するよう修正。`fixed_comment_pinned_at` のみ記録済みの動画も投稿済み扱いにした
- `web_app/templates/fixed_comment.html`: 投稿ボタンのインライン `onclick` を廃止し、引用符や `000_uploaded\...` を含む履歴名でもクリック処理が壊れないよう修正
- `web_app/routes/api_fixed_comment.py` / `web_app/templates/fixed_comment.html`: 固定コメント一覧の全行にYouTubeを開くボタンを表示し、手動投稿後に `fixed_comment_posted_at` を記録する「投稿済みにする」ボタンを追加
- `web_app/services/fixed_comment_service.py` / `web_app/templates/fixed_comment.html`: 固定コメント候補から予約中動画を除外し、YouTube上で存在しない動画・公開済み以外の動画を状態取得できる場合は非表示にした。公開日列を追加し、YouTubeリンクを通常サイズのボタンへ変更
- `web_app/routes/pages.py`: 固定コメント画面では投稿済み行もHTMLへ読み込み、「投稿済みも表示」チェックで切り替えられるよう修正
- `web_app/templates/images.html`: 背景画像のプロンプト表示・編集・保存機能追加（未保存でも再生成時に反映）
- `web_app/templates/images.html` / `web_app/static/app.css`: 画像確認 / 再生成画面のチェックボックスを画像左側の操作カラムへ移動し、再生成・保存・全選択操作を画像一覧の上へ配置して操作しやすくした
- `web_app/templates/settings.html`: 設定変更の保存・リセットボタンを設定フォーム上にも配置し、下までスクロールせず操作できるようにした
- `web_app/templates/history.html`: 履歴一覧に表示中の全選択・全解除ボタンを追加
- `web_app/templates/upload.html`: アップロード済み動画のYouTubeリンクを通常サイズのボタンへ変更
- `web_app/routes/pages.py` / `web_app/templates/base.html`: 静的CSS/JSに更新番号を付け、ブラウザキャッシュで古いレイアウトが残らないようにした
- `web_app/templates/settings.html`: APIキー変更をアコーディオン最下部に移動
- `web_app/templates/base.html`: 「画像」タブを削除（履歴詳細から遷移）
- `web_app/services/prompt_service.py`: プロンプト生成ロジックをWeb UI用に実装
- `web_app/services/image_service.py`: 背景プロンプト読み込み・保存・再生成時の上書き対応
- `web_app/services/history_service.py` / `upload_service.py` / `fixed_comment_service.py`: 履歴フォルダ参照を `safe_output_path()` 経由に統一し、Web UIの output/ 配下制限を徹底
- `web_app/services/config_service.py` / `secrets_service.py`: `.env` 書き込み値の改行混入を拒否し、許可外キーや秘密値のログ出力を防止
- `web_app/routes/api_prompt.py`: `/api/prompt/script`、`/api/prompt/title` エンドポイント追加
- `web_app/routes/api_images.py`: `POST /api/images/{name}/save-prompts` エンドポイント追加
- `web_app/routes/api_upload.py`: `POST /api/upload/batch` エンドポイント追加
- `web_app/services/secrets_service.py`: APIキー書き込み専用サービス（値はレスポンス/ログに含めない）
- `web_app/static/app.css`: lightbox、image-card object-fit、背景プロンプト行レイアウト追加
- `README.md` / `SPEC.md`: Web UIの既定ポート、API一覧、画像再生成の現状仕様、セキュリティ方針を現状へ更新

### native字幕のASSタグ修正

- `core/native_renderer.py`: テロップ・リアクションアイコンのASSアニメーションタグ末尾が余分な `}` を出力しないよう修正
- `tests/test_native_renderer.py`: テロップ・アイコンのASSタグ閉じを検証するテストを追加

---

## 2026-05-26 (Web UI追加)

### ローカルWeb UI全面追加

- `web_app/app.py`: FastAPI + Uvicorn によるローカルWeb UIを追加。`python web_app/app.py` または `python -m web_app.app` で起動。127.0.0.1のみバインド、外部公開なし
- `web_app/job_manager.py`: バックグラウンドジョブ管理。生成・チェック・アップロード・Analytics等をメモリ内でジョブ化。status/logs/cancel対応。将来DB移行しやすい構造
- `web_app/security.py`: output/配下のみアクセス可、パストラバーサル拒否、秘密ファイル読み取り禁止
- `web_app/schemas.py`: Pydantic リクエスト/レスポンススキーマ
- `web_app/services/`: 13サービス (status, config, secrets, history, generation, script_check, image, prompt, render, analytics, schedule, upload, fixed_comment)
- `web_app/routes/`: 13ルート (pages + 12 API)
- `web_app/templates/`: 12画面 (dashboard, generate, check, history, history_detail, images, analytics, schedule, upload, fixed_comment, settings, logs)
- `web_app/static/app.css, app.js`: ダークテーマUI、スコアバッジ色付け、ジョブポーリングユーティリティ
- `tests/test_web.py`: 23テスト追加。/health、ジョブ状態遷移、パストラバーサル、管理フォルダ除外、設定診断秘密値非返却、外部API不要起動テスト等
- 追加時点では既存Tkinter GUIと共存していたが、同日のWeb UI一本化で旧GUI/CLI導線は廃止

### 設定診断画面追加

- Web UIの `/settings` 画面: VOICEVOX接続、APIキー設定有無（値は非表示）、ffmpeg利用可否、各種設定値を診断表示

### ジョブ管理画面追加

- `/logs` 画面: バックグラウンドジョブのステータス・ログ一覧。実行中ジョブは5秒ごとに自動更新。失敗ログ・ログ詳細をアコーディオン表示

---

## 2026-05-26

### native Shorts軽量エフェクトを追加

- `config.py`: `NATIVE_ENABLE_MOTION_EFFECTS`、背景Ken Burns、キャラバウンス、ポップテロップ、シェイク、シェイク/アイコン上限、背景ズーム最大倍率の設定を追加
- `core/native_renderer.py`: Shortsの各セグメントに、背景のゆっくりズーム/パン、話者キャラの軽いバウンス、`テロップ:` 行のポップ表示、短いツッコミ/疑問場面の軽いシェイクと疑問/驚きアイコンを追加。ffmpegフィルタ失敗時は該当セグメントをエフェクトなしで再レンダーして継続する
- `README.md` / `SPEC.md`: nativeレンダラーの軽量エフェクト仕様と設定値を追記

### Shorts冒頭・サムネ・中盤の勝ち型を追加

- `core/prompt_parts/local/script_generation_prompt.txt` / `samples/prompt_parts/food/script_generation_prompt.txt`: 台本生成プロンプトに、Shortsの1行目フック公式、サムネ文字と1行目の連動公式、15〜25秒地点の第2驚き構造を追加
- `SPEC.md`: Shorts台本作成ルールに、1行目の結論優先、サムネ文字との連動、中盤の第2驚き配置を追記

### GUI補助ロジックの分離

- `core/gui_support.py`: GUIから、台本分割、アプリバージョン取得、VOICEVOX/ffmpeg疎通表示用チェック、ファイルハッシュ、Pillow画像読み込み補助を分離
- `core/generation_checks.py`: GUIから、生成前チェック、native推定尺計算、尺ステータス表示タグ判定を分離
- `gui.py`: 上記ヘルパーを使う薄い呼び出しに整理し、import時副作用なしの状態を維持。出力フォルダを開く処理を Windows/Mac/Linux 対応に変更
- `tests/test_gui_support.py`: 台本分割、生成前チェック、尺推定、尺タグ判定の軽いテストを追加

### コード整理・デッドコード削除・定数集約

- `core/opening_quality.py`: `local_opening_review()` のデフォルト引数 `render_engine="ymm4"` → `"native"` に修正。LLMプロンプト内で Long動画も `render_engine` を正しく渡すよう修正（従来は Long 時に "ymm4" が固定送信されていた）
- `main.py` / `gui.py`: `native_render=False` 分岐（YMM4尺チェック・Shorts尺表示）をデッドコードとして削除
- `config.py`: `TRANSITION_SEC` / `VOICE_TAIL_SAFETY_SEC` / `NATIVE_INTER_DIALOGUE_GAP_SEC` を追加。`main.py` / `native_renderer.py` のモジュール内定数定義を廃止してインポートに統一
- `core/native_renderer.py`: `INTER_DIALOGUE_GAP_SEC` → `NATIVE_INTER_DIALOGUE_GAP_SEC` に改名（`main.py` の YMM4用同名定数との混在を解消）
- `main.py`: native固定後に残っていた非native分岐と旧YMM4タイムライン構築処理を削除。素材生成は `script.txt` / `audio/` / `backgrounds/` 作成に専念し、MP4化は `core/native_renderer.py` に一本化
- `gui.py`: `native_render` 設定分岐を削除。import時にVOICEVOX/ffmpeg起動チェックを標準出力へ出す副作用を廃止し、GUI直接起動時だけ表示する関数へ分離
- `config.py`: 未使用になった旧YMM4用VOICE速度定数、`BGM_VOLUME`、`BGM_LAYER`、`TACHIE_PARAMS` を削除。VOICEVOX APIのデフォルト速度はnative Shorts本編速度を参照
- `core/timeline_editor.py` / `core/character_templates.json`: YMM4プロジェクト出力廃止後に未使用となった互換ヘルパーを削除
- 全Pythonファイル: 残存英語コメント・docstringを日本語化（`gui.py` 13件 / `main.py` 5件 / `analytics_score.py` ルール1〜7ラベル / `tests/test_refactor.py` ほか）
- `SPEC.md` / `AGENTS.md`: 削除済みのYMM4互換ヘルパー参照と旧VOICE/BGM設定名の説明を、native用設定名へ修正し、native MP4のみが最終出力であることと整合させた

## 2026-05-25 (13)

### テスト用ファイル置き場 `dev/` を追加・ルール化

- `.gitignore`: `dev/` を追加（開発用一時ファイルをgit管理外に隔離）
- `AGENTS.md`: テスト用ファイルは `dev/` フォルダへ置くルールを追記。`assets/` 直下へのテスト画像配置を禁止
- 既存の `assets/characters/expression_preview*.png` を `dev/` へ移動

## 2026-05-25 (12)

### Analytics チャンネル全体の登録者増減を追加

- `core/youtube_analytics.py`: `_fetch_channel_subscriber_totals()` を追加。dimension なし API でチャンネル全体の `subscribersGained` / `subscribersLost` を取得し `summary` に `channel_subscribers_gained` / `channel_subscribers_lost` / `channel_subscribers_net` を追加
- `gui.py`: アナリティクス一覧に `登録者増` / `登録者減` 列を追加（既存の `登録者増減` と並列表示）。サマリーバーにチャンネル全体登録者増減を `+gained -lost 純増net` 形式で表示。画面下部に旧チャンネル時代の注記ラベルを常時表示
- `core/analytics_score.py`: `build_performance_summary()` にチャンネル全体登録者増減と `ANALYTICS_CHANNEL_LEGACY_NOTE` を出力
- `config.py`: `ANALYTICS_CHANNEL_REMAKE_DATE = "2026-05-15"` / `ANALYTICS_CHANNEL_LEGACY_NOTE` を追加（旧インド広告時代の離脱注記）

## 2026-05-25 (11)

### Shorts 先頭サムネ保持フレーム数を設定値化

- `config.py`: `THUMBNAIL_HOLD_FRAMES_SHORTS`（デフォルト3、1〜5にクランプ、不正値は3へフォールバック）を追加
- `core/native_renderer.py`: Shorts先頭サムネセグメントを固定1フレームから `THUMBNAIL_HOLD_FRAMES_SHORTS / VIDEO_FPS` 秒に変更。ログに保持フレーム数と秒数を表示
- `main.py`: `render_info.json` の `native_renderer` に `thumbnail_hold_frames` / `thumbnail_hold_seconds` を追記
- 30fps で 3フレーム≒0.1秒、5フレーム≒0.167秒。1秒超の静止サムネは設定上不可

## 2026-05-25 (10)

### 表情PNG使用中の口パク・まばたきオーバーレイ干渉を修正

- `core/native_renderer.py`: `_using_expression_png()` を追加。話者が表情PNG（`expression` 指定あり・ファイル存在）で描画される場合、口パク差分オーバーレイと目閉じオーバーレイを両方無効化する
- 表情PNGはPSDから合成した専用口・目レイヤーを持つため、base.pngとの差分オーバーレイと重ねると二重口・二重目が生じていた問題を解消

## 2026-05-25 (9)

### Shorts キャラ倍率を Long と分離（重なりバグ修正）

- `config.py`: `CHARACTER_UPPER_BODY_SHORTS_SCALE=1.15` を追加。Shorts の縦画面（幅1080px）では Long 用の 1.55 倍だとキャラ同士が中央で大きく重なるため、Shorts 専用の小さい倍率を分離
- `core/native_renderer.py`: `CHARACTER_UPPER_BODY_MODE` 時の `char_scale` を portrait/landscape で切り替えるよう修正（portrait → `CHARACTER_UPPER_BODY_SHORTS_SCALE`、landscape → `CHARACTER_UPPER_BODY_SCALE`）
- `config.py`: `YMM4_TACHIE_PARAMS` の zoom 計算も Shorts / Long で別スケールを使うよう修正

## 2026-05-25 (8)

### native立ち絵の表情指定を追加

- `core/parser.py`: `ずんだもん(ノーマル)[驚き]: ...` のような角括弧表情を `expression` フィールドとして取得。既存の丸括弧VOICEVOXスタイルは維持
- `config.py` / `core/native_character_assets.py` / `core/native_renderer.py`: native立ち絵の表情PNG対応表を追加し、セリフ単位で表情ベース画像を切り替える。未知表情・素材未配置は警告して既定表情へフォールバック
- `core/prompt_parts/local/script_generation_prompt.txt`: 表情指定ルールを追加。`四国めたん(きょきょう)` のような新VOICEVOXスタイルは追加せず、声と画面表情を分離
- `README.md` / `SPEC.md`: 台本フォーマットと表情指定の仕様を追記
- `tests/test_parser_expressions.py` / `tests/test_native_renderer.py`: 表情パースとnativeフォールバックのテストを追加

## 2026-05-25 (7)

### vidIQ/Analytics高AVP型を台本生成プロンプトへ反映

- `core/prompt_parts/local/script_generation_prompt.txt`: 高AVP台本の型、低AVPの実失敗パターン禁止、1枚目背景VSA特化、再挑戦/品質改善版の改善理由、Shortsループ締めを追加
- 背景画像内のずんだもん/めたん描画を禁止し、native立ち絵と背景の役割を分離する方針を明記
- `SPEC.md`: 台本作成ルールに、1行目の数字/期間/場所入り結論型、低AVP型の禁止、VSA背景、再挑戦/品質改善版の目的欄強化を反映

## 2026-05-25 (6)

### YMM4プロジェクト出力廃止

- `main.py`: `run_pipeline()` を Shorts/Long とも native 固定にし、`.ymmp` 保存を行わないよう変更。完了メッセージは出力フォルダを返す形式に統一
- `gui.py`: 通常生成・履歴MP4化・アップロード候補確認を native MP4 前提に整理し、YMM4外部出力MP4の探索と移動処理を廃止
- `core/ymm4_renderer.py`: YMM4 GUI自動操作レンダラーを削除
- `core/native_renderer.py` / `docs/YMM_FREE_RENDERER.md`: 旧「YMMなし(test)」表記を native MP4 表記へ整理し、実験段階の古い設計メモを削除
- `config.py`: `DEFAULT_SHORTS_RENDER_ENGINE` / `GENERATE_YMM4_PROJECT` / `RENDER_WITH_YMM4` を deprecated 扱いにし、YMM4出力へ戻らない既定値に変更
- `README.md` / `SPEC.md` / `AGENTS.md`: YMM4確認用 `.ymmp` 生成ありの説明を削除し、ffmpeg/native MP4 を唯一の出力経路として記載

## 2026-05-25 (5)

### キャラ腰から上表示モード（native/YMM4共通）

- `config.py`: `CHARACTER_UPPER_BODY_MODE`(デフォルト ON) / `CHARACTER_UPPER_BODY_SCALE`(1.35) / `CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET`(250) / `CHARACTER_UPPER_BODY_LONG_Y_OFFSET`(300) を追加。`.env` で上書き可能
- `core/native_renderer.py`: `CHARACTER_UPPER_BODY_MODE=1` のとき native Shorts/Long でキャラを拡大し、Y座標を下方向へオフセットして腰から上が画面に映る構図にする
- `main.py`: `_TACHIE_BASE` → `TACHIE_PARAMS` の生成ロジックを変更。`CHARACTER_UPPER_BODY_MODE=1` のとき YMM4 のずんだもん/めたん立ち絵を同スケール・同オフセットで調整する
- `SPEC.md`: `CHARACTER_UPPER_BODY_*` 環境変数を追加

## 2026-05-25 (4)

### native/ffmpegレンダラー改善（音量・字幕・キャラ・実尺ログ）

- `core/native_renderer.py`: native出力のBGM音量を `NATIVE_BGM_VOLUME_DB=-20dB` で指定するよう変更（従来の `BGM_VOLUME` パーセント指定はYMM4専用に分離）
- `core/native_renderer.py`: native MP4生成後に ffprobe で実尺を取得し `📏 native実尺評価: Xs [理想/やや短い/OKだけど長め/警告/要確認]` をログ表示。`estimated_duration_sec` 引数があれば推定尺との差分も表示
- `core/native_renderer.py`: `_meta/render_info.json` に render_engine / actual_duration_sec / actual_duration_status / loudnorm_enabled / loudnorm_i/tp/lra を保存
- `gui.py`: native MP4生成時に推定尺を `render_native_test()` へ渡し、実尺との差分と `render_info.json` の `estimated_duration_sec` が埋まるよう変更。アップロード候補のスコア欄にも native 実尺を表示
- `core/native_renderer.py`: native Shorts のキャラ表示に `NATIVE_SHORTS_CHARACTER_SCALE`(デフォルト 1.05)を適用。`CHARACTER_UPPER_BODY_MODE=1` の場合は native Shorts/Long の腰から上表示モードを優先
- `core/native_renderer.py`: 字幕フチ幅を `NATIVE_SUBTITLE_OUTER_STROKE_WIDTH`(13) / `NATIVE_SUBTITLE_STROKE_WIDTH`(9) に変更（従来ハードコードの 12/8 より少し太め）、字幕帯高さに `NATIVE_SUBTITLE_PADDING_Y`×2 を加算
- `config.py` / `README.md` / `SPEC.md`: `NATIVE_BGM_VOLUME_DB` / `NATIVE_SHORTS_CHARACTER_SCALE` を追加

### YouTubeタグ共通タグ見直し（vidIQ分析に基づく）

- `core/youtube_metadata.py`: `VIDEO_DEFAULT_TAGS` の先頭を `ずんだもん,ゆっくり解説,VOICEVOX` に固定し、`食べ物 雑学 ショート`/`食べ物雑学`/`食べ物の歴史`/`VOICEVOX解説`/`トリビア` 等を追加。需要の低い `コンビニ 雑学`/`料理 歴史`/`面白い 雑学`/`食べ物` を削除
- `core/youtube_metadata.py`: 題材別タグルールを更新。アイス系・寿司系・飲み物系・お菓子系・調味料系を追加・整理
- `SPEC.md`: YouTubeタグポリシーの最新ルールを反映

## 2026-05-25 (3)

### native/ffmpeg音声にloudnormを追加

- `core/native_renderer.py`: native MP4の最終音声出力に `loudnorm=I=-15:TP=-1.5:LRA=6` を追加。BGM/VOICEミックス後、最終出力直前の音声だけに適用し、映像はコピーする
- `core/native_renderer.py`: native MP4出力後に ffmpeg `ebur128=peak=true` で音量解析し、Integrated loudness / LRA / True peak の要約をログ出力
- `config.py` / `README.md` / `SPEC.md`: `NATIVE_AUDIO_LOUDNORM_ENABLED` / `NATIVE_AUDIO_LOUDNORM_I` / `NATIVE_AUDIO_LOUDNORM_TP` / `NATIVE_AUDIO_LOUDNORM_LRA` を追加

### 外部APIモデル設定を点検・更新

- `config.py` / `README.md` / `SPEC.md`: ChatGPT生成前レビューの既定モデルを公式モデル一覧で確認できる `gpt-5.2` へ更新
- `config.py`: Gemini / Nano Banana のモデルIDを `.env` から上書きできるよう変更し、API側のモデル更新に追随しやすくした
- `core/image_generator.py`: Gemini画像生成リクエストに画像出力モダリティと縦横比設定を明示

### 生成前レビュー失敗時に一括生成を即停止

- `gui.py`: `run_pipeline()` が `❌` / `⏹` を返した場合、一括生成でも次の動画へ進まず即終了するよう変更。ChatGPT生成前レビューの接続失敗などを「要修正」ログだけで継続しない
- `core/opening_quality.py` / `gui.py`: 生成前スコアリング開始時にChatGPT生成前レビューのOpenAI接続を確認し、DNS失敗・認証失敗・API接続失敗時は生成開始前に即停止するよう変更
- `main.py`: 単発生成でもChatGPT生成前レビューの直前にOpenAI接続チェックを行い、失敗時はレビューAPI呼び出しに進まず停止するよう変更

### APIクライアントの明示解放を追加

- `core/youtube_uploader.py` / `core/youtube_analytics.py`: YouTube Data API / Analytics API の googleapiclient resource を処理後に `close()` するよう変更
- `core/ai_generator.py` / `core/image_generator.py`: Google GenAI クライアントに `close()` / context manager を追加
- `main.py` / `gui.py`: 短命の Gemini / Nano Banana 生成器を使用後に明示的に閉じるよう変更

### 作業ガイドと環境説明を更新

- `AGENTS.md` / `CLAUDE.md`: リソース明示解放、メモリ解放、認証情報の記載・コミット禁止を恒久ルールに追加
- `AGENTS.md` / `CLAUDE.md` / `README.md` / `SPEC.md`: YMM4 GUI自動操作を廃止済みとして、ffmpeg/native MP4を主経路、YMM4は確認用 `.ymmp` 生成までの説明に更新

### YouTubeソース化後のテストとドキュメントを整備

- `tests/test_upload_scheduler.py`: `rebalance_slots()` 系テストをYouTube予約一覧のモックに変更し、テスト実行時に実YouTube APIへアクセスしないよう修正
- `SPEC.md` / `README.md`: 中央 `upload_records.json` 前提の古い説明を、YouTube APIを予約・公開状態の正とする現行仕様へ更新

### ローカルスケジュール管理を完全廃止・YouTube をソースオブトゥルースに

**廃止**:
- `output/000_data/upload_records.json`（中央アップロード台帳）を廃止
- `save_upload_records()` / `upsert_upload_record()` を no-op 化
- スケジュールに関わるローカルファイル読み書きをすべて除去

**変更**:
- `core/upload_records.py`: `load_upload_records()` を出力フォルダ配下の `_meta/upload_record.json` をスキャンする実装に置き換え。各レコードに `_local_path` を付加して固定コメント書き戻し先を特定可能に
- `core/upload_scheduler.py`: `schedule_from_youtube()` / `_scheduled_entries_from_youtube()` を追加。`list_schedule()` / `rebalance_slots()` / `rebalance_slots_detailed()` / `count_rebalance_candidates()` を YouTube API ベースに切り替え
- `gui.py` スケジュールダイアログ: `build_rows()` を YouTube `get_channel_upload_video_statuses()` 直接参照に書き換え。ローカル台帳参照を廃止
- `gui.py` リバランスワーカー: ローカルレコード更新処理を全削除。YouTube 更新のみ実行
- `gui.py` 固定コメント候補収集: `_local_path` を使ってスレッドID書き戻し先を特定
- `gui.py` `_write_upload_record_data`: 中央ファイルパス宛の書き込みを no-op 化

**維持**:
- 動画ごとの `_meta/upload_record.json`（スコア・メタデータ）は引き続き書き込み
- Analytics は `load_upload_records()` 経由でフォルダスキャン結果を参照（関数シグネチャ変更なし）

---

## 2026-05-25 (2)

### アップロードスロット割り当てを YouTube 参照に変更

- `core/upload_scheduler.py`: `assign_slots_from_youtube(count, video_type)` を追加。YouTube チャンネルの予約投稿済み動画（private + 未来の publishAt）を取得し、同タイプの使用済みスロットとして扱う。YouTube API が失敗した場合のみローカルレコードにフォールバック
- `gui.py`: アップロード時のスロット割り当てを `assign_slots_from_youtube` に切り替え。ローカルの `upload_records.json` を空き枠判断に使わなくなったため、ローカル状態のズレによる重複スロットが発生しない
- `core/upload_records.py`: `upsert_upload_record` に重複スロット検出ログを追加（同タイプ・同 publish_at が別 video_id にある場合 WARNING）

---

## 2026-05-25

### ChatGPT生成前レビューのnative Shorts基準を修正

- `core/opening_quality.py`: ChatGPT生成前レビュープロンプトに `render_engine` を渡し、native Shortsでは「31行以上のみmust_fix / 24〜27行が理想」に修正。旧YMM4基準「21行以上=must_fix」は完全削除
- `core/opening_quality.py`: native Shorts かつ dialogue_count <= 28 の場合、ChatGPT応答に旧基準由来の「21行以上 must_fix」が返ってきても自動で除去するポストフィルタを追加
- `main.py`: `final_chatgpt_review()` に `render_engine=_render_engine` を渡すよう修正
- `core/opening_quality.py`: 冒頭1行目の食べ物名チェックを改善。タイトルが抽象的でも `FOOD_HINT_WORDS`（コーヒー・コーラ・牛乳等の飲み物含む）が初行に直接あればOKとした。N選型タイトルは代表食材1つあればOKで、全食材名列挙は不要に変更
- `SPEC.md`: 上記基準を反映

### native Shorts字幕のキャラ色フチを強化

- `core/native_renderer.py`: 半透明黒帯と白文字を維持したまま、ずんだもん/めたんのキャラ色内フチを太くし、黒外フチも少し太くして可読性を保ったまま話者色を見やすく調整
- `SPEC.md` / `docs/YMM_FREE_RENDERER.md`: native字幕の可読性方針と、現在のnative出力名・処理フローに合わせてドキュメントを更新

### 背景生成時のリファレンス画像渡しを廃止

- `main.py`: Long動画で1枚目の背景を2枚目以降のスタイル参照として渡していた処理を削除
- `gui.py`: 背景再生成時に別の既存背景をスタイル参照として渡していた処理を削除
- サムネイル生成でのキャラ画像渡しは引き続き有効

---

## 2026-05-23

### vidIQ方針を台本・タイトル案プロンプトへ反映

- `core/prompt_parts/local/script_generation_prompt.txt`: Shorts集中、冒頭1〜3行でタイトル核心回収、15〜30秒地点の二段フック、コメント誘発、3選/クイズ実験枠、SEO語はタイトルへ無理に入れない方針を追加
- `core/prompt_parts/local/title_dynamic_context_food.md` / `core/script_prompts.py`: タイトル案生成でShorts維持率・コメント率を優先し、LongはShorts実績ネタの深掘り候補に限定する方針を追加
- `core/youtube_metadata.py`: AIO/SEO補完用の共通タグを強化し、説明文のSEO補完文を冒頭側に入れるよう変更。ドリア/洋食系の題材別タグを追加
- `core/prompt_parts/local/script_generation_prompt.txt` / `core/script_prompts.py` / `core/ai_generator.py`: 説明文冒頭の自然文要約、固定コメントの要約1文+質問1文、Shorts冒頭1〜5秒で題材と結論を明文化するルールを追加
- `SPEC.md`: 台本作成ルールとタイトル案運用にvidIQ反映ルールを追記

### native Shortsのキャラ配置と字幕位置を調整

- `config.py`: Shortsのずんだもん/めたん立ち絵をやや大きめ・外側配置・下側クロップにし、腰から上が見える構図へ調整
- `core/native_renderer.py`: Shorts字幕を中央寄せにし、字幕フォントサイズを既存比40%拡大。通常字幕は白文字＋話者別の濃色内フチ（ずんだもん=濃緑、めたん=濃紫ピンク）＋黒外フチに変更し、必要時に半透明黒帯を背面へ出せるようにした。字幕を少し下げ、環境変数で `NATIVE_SUBTITLE_FONT_SCALE` / `NATIVE_SUBTITLE_ALIGNMENT_SHORTS` / `NATIVE_SUBTITLE_Y_OFFSET_SHORTS` / `NATIVE_SUBTITLE_BOX_SHORTS` / `NATIVE_SUBTITLE_BOX_OPACITY_SHORTS` / キャラ余白を調整可能に変更

### アップロード公開時刻の同タイプ重複を詰め直しで解消

- `core/upload_scheduler.py`: `rebalance_slots_detailed()` が `video_id` に加えて upload_records のレコード番号を返し、同時刻・同タイトル・video_idなしの重複でも対象レコードを特定できるように変更
- `core/upload_scheduler.py`: スロット詰め直し時、`generation_kind` が入っている動画（横展開・品質改善版・再挑戦など）を同タイプ内で優先して早い枠へ割り当てるように変更
- `gui.py`: スロット詰め直し適用時にレコード番号を使って `output/000_data/upload_records.json` を直接更新。`video_id` がない場合もローカルの予約時刻は詰め直す
- Shorts と Long は従来通り同時刻を許容。同タイプ内（Shorts同士 / Long同士）の同時刻重複を解消する
- `tests/test_upload_scheduler.py`: Shorts / Long の同時刻重複と video_id なし重複のテストを追加

### native MP4生成後に実尺チェックを追加

- `gui.py`: `render_native_test()` 完了後に `duration_review()` で実尺を判定し、`━━ 実尺チェック XX.X秒 / [ラベル] ━━` 形式でログ表示（ideal→緑 / warning→黄 / needs_review→赤）
- 判定結果を `_meta/duration_review.json`（`source: native_mp4`）に保存
- 完了メッセージにも判定ラベルを追記

### 5/16以前の音切れリスク動画をAnalyticsで品質改善版候補化

- `core/analytics_score.py`: 2026-05-16以前の公開動画に `audio_cutoff_risk` を付与し、実績シグナルがある Shorts / ShortLong の action に `音切れ改善候補` を補足
- Analytics TSV / GUI一覧 / タイトル案プロンプトの実績データヘッダーに `audio_cutoff_risk` を追加
- タイトル案プロンプトに、音切れリスク動画をネタ弱いと即断せず「品質改善版」候補として扱う指示を追加
- `tests/test_analytics_score.py`: 音切れリスク境界日、候補付与条件、TSV列のテストを追加

### native MP4の先頭フレームにサムネイル挿入・固定ファイル名で上書き

- `core/native_renderer.py`: Shorts の native MP4 先頭1フレームに `thumbnails/thumbnail.png` を挿入（Long は挿入しない）
- `core/native_renderer.py`: native MP4出力名を `{履歴フォルダ名}_native.mp4` に固定。タイムスタンプなし・再生成時は上書き
- native MP4化前に `_native_test` の古い中間ファイルを削除し、再生成画像を使った出力になるように整理
- `gui.py`: 画像再生成時に対象画像を上書きし、更新時刻も明示的に更新

### アップロードスケジュール画面に公開済み動画の YouTube 公開日時を表示

- `gui.py`: `📅 スケジュール` 画面に公開済み動画（直近90日）を追加表示。日時列は YouTube 側の `published_at`（API同期値）を使用
- 状態フィルタ追加: すべて / 予定 / 公開済
- 公開済み行を緑色で表示。カウント表示に「公開済 N 件 (直近90日・YouTube同期値)」を追加

### 投稿テンプレート終盤のCTA記述を修正

- `core/prompt_parts/local/script_generation_prompt.txt`: 投稿テンプレートの「終盤: 真相 → オチ → 他動画誘導 → 登録誘導」を「真相 → オチ → 冒頭キーワードに戻す」へ修正し、Shortsループ優先ルールと完全に整合

### Shorts CTAルールとレス読み上げ風ルールを整理

- `core/prompt_parts/local/script_generation_prompt.txt`: Shorts理想構成に残っていた「他動画誘導・登録・高評価誘導を2〜3行に凝縮」という古いCTA記述を削除
- Shortsはループ締めまたはコメント誘導を優先し、CTAは1種類だけに統一（Shorts CTA構成節も同様に整合）
- 品質改善版・再挑戦ではネタ募集CTAを原則使わない方針を明記
- レス読み上げ風の濃度をShorts 2〜4割、Long 1〜2割へ調整し、下品なネットスラングは禁止に整理

### 台本プロンプト: 掛け合い品質・強めツッコミルール追加

- `core/prompt_parts/local/script_generation_prompt.txt`: ずんだもんを「2chまとめレス読み上げ風」、四国めたんを「視聴者の違和感・疑問・反論を強めに代弁するツッコミ役」に再定義
- 掛け合い品質ルール新設: めたんの意味のない相槌・驚き専用フレーズを禁止リストに追加
- ずんだもん推奨型（「昔の人「〇〇やん」」「現代人「なんで？」」「なお、原因は〇〇」「結果、〇〇扱い」）を追加
- めたん推奨型（「犯人そっちですの？」「急に雑ですわ」「完全に巻き添えですわ」等）を追加
- BAD/GOOD台本例（トマト・カップ麺）を追加してモデルの学習容易性を高める
- Shorts/Long 濃度分け: Shorts=3〜5割（冒頭・原因・オチで積極的に使う）/ Long=1〜2割（自然な会話に寄せる）を明記
- 禁止事項に「めたんの意味のない相槌禁止 / 情報が進まない掛け合い禁止」を追記
- 自己チェック項目に掛け合い品質5項目を追加

### 画像SD生成モードを追加（GUIチェックボックス）

- `core/image_generator.py`: `sd_size_mode=True` で `SD_SIZE_IMAGE_SCALE`（デフォルト0.5）倍サイズで生成し元サイズに拡大してセット
- `config.py`: `SD_SIZE_IMAGE_SCALE` 環境変数を追加（デフォルト0.5）
- `gui.py`: 「SD生成」チェックボックス追加（デフォルトOFF）。生成・画像確認再生成・サムネイル再生成の全パスに伝播
- `main.py`: `run_pipeline()` / `regenerate_thumbnail_only()` に `sd_size_mode` パラメータを追加

### data_wait動画にもAI分析コメントを出すように変更

- `core/analytics_score.py`: 実績サマリーに data_wait 件数と注目動画を追加
- `core/analytics_score.py`: Analytics保存JSONに `start_date` / `end_date` / `summary` を保存し、実績サマリーに対象期間・取得日時を表示
- `gui.py`: Analyticsの「AI分析用にコピー」に、data_wait動画へ暫定評価コメントを必ず入れる指示を追加
- `gui.py`: Analytics画面の取得結果表示に対象期間を追加
- `core/script_prompts.py`: タイトル案プロンプトで data_wait 動画にも「暫定横展開候補」「要追跡」「判断保留」などの短い評価コメントを書くよう明記

---

## 2026-05-22（続き4）

### Shorts台本文字数ガイドラインをnative速度に合わせて更新

- `core/prompt_parts/local/script_generation_prompt.txt`
  - 尺計算式を旧YMM4式（×0.11＋×1.2）→ native式（÷3.75＋×0.25）に更新
  - 1セリフは原則11〜15文字、平均11.5文字以上を維持するルールに更新
  - Shorts nativeでは24〜27行、本文280〜330文字を目標にし、260文字未満は禁止
  - 10文字以下の短文は最大4行まで、7文字以下は原則禁止
- `SPEC.md`: 台本作成ルール・Shorts セリフ数・尺計算式を同様に更新
- `gui.py` / `main.py`: `_estimate_duration` / `_estimate_script_duration` の `native_render` パラメータを削除し、Shorts=native速度/Long=YMM4速度で分岐

---

## 2026-05-22（続き3）

### アナリティクス・アップロード記録に render_engine を追加

- `core/analytics_score.py`: `to_tsv()` の列に `render_engine` を追加（`genre_group` の直後）
- `gui.py` `_write_upload_record`: `_meta/render_info.json` を読み込み `render_engine` フィールドをアップロード記録に保存
  - アップロード後のアナリティクス画面の TSV にも自動反映

---

## 2026-05-22（続き2）

### Shorts本番レンダリングをffmpeg/nativeへ移行

- **Shorts生成のデフォルトをnativeに変更**
  - `DEFAULT_SHORTS_RENDER_ENGINE = "native"` (config.py / ENV上書き可)
  - `run_pipeline(native_render=None)` がShortsを検出すると自動でnativeに切り替わる
  - 通常の「生成」ボタンがShortsをnativeで出力するようになった（YMMなし専用ボタン不要）
  - YMM4プロジェクト生成は継続（保険・確認・再編集用）
  - `RENDER_WITH_YMM4 = False` でYMM4本番書き出しをデフォルト無効化
- **GenerationReport.native_render_used** を追加し、GUIがnativeレンダリングを自動トリガー
- **出力ファイル名を `video_native.mp4` に変更**（旧: `{folder名}_native_test.mp4`。2026-05-23に `{フォルダ名}_native.mp4` 固定へ再変更）
- **アップロード優先順位を更新**: 履歴フォルダ内の最新 MP4 を選択（固定ファイル名のため常に1本）
- **冒頭速度切り替えをline_countモードに変更**（native Shorts）
  - 旧: フレーム上の5秒経過で切り替え
  - 新: 冒頭3行（`VOICE_INTRO_FAST_LINES=3`）がintro速度、4行目以降がbody速度
- **render_info.json を `_meta/` に保存**（render_engine・voice_speed・ymm4_project_generated）
- **native prompt追加**: script_generation_prompt.txt に「native/ffmpeg Shortsルール」と「展開密度ルール」を追記
- **native生成ログにmax_silenceを追加**
- **config.py に追加した定数**:
  - `NATIVE_SHORTS_INTRO/BODY_VOICE_SPEED_MIN/MAX` (許容範囲)
  - `NATIVE_MIN/DEFAULT/SCENE_CHANGE/MAX_NORMAL/WARNING_SILENCE` (無音設定)
  - `YMM4_SHORTS/LONG_INTRO/BODY_VOICE_SPEED` (明示エイリアス)
  - `VOICE_INTRO_FAST_MODE` / `VOICE_INTRO_FAST_LINES`

---

## 2026-05-22（続き）

### ffmpeg nativeレンダラー: エンジン別安定条件・音声速度分離

- `config.py`: YMM4とnativeで音声速度定数を分離
  - `NATIVE_SHORTS_BODY_VOICE_SPEED=1.25` / `NATIVE_SHORTS_INTRO_VOICE_SPEED=1.40`
  - `NATIVE_LONG_BODY_VOICE_SPEED=1.20` / `NATIVE_LONG_INTRO_VOICE_SPEED=1.40`
  - すべて `.env` で上書き可能（`NATIVE_SHORTS_BODY_VOICE_SPEED` 等）
  - 既存の YMM4 速度定数（`VOICE_SPEED_SCALE_SHORTS` 等）は変更なし
- `config.py`: native Shorts のセリフ数しきい値を追加
  - 理想: 22〜28行 / warning: 29〜30行 / must_fix: 31行以上
- `core/opening_quality.py`: `local_opening_review` に `render_engine` 引数を追加
  - `render_engine="ymm4"`: 21行以上 → must_fix（従来通り）
  - `render_engine="native"`: NATIVE_SHORTS_LINES_* に従う
- `main.py`: `run_pipeline` に `native_render` 引数を追加
  - `_render_engine` を派生し `local_opening_review` へ渡す
  - native では推定尺による停止をスキップし参考ログのみ表示
  - 音声速度は native/YMM4 の定数から分岐して選択
- `core/native_renderer.py`: `render_native_test` に `voice_speed_intro/body` 引数を追加
  - 完了時に語り速度（chars/sec）・台本量・速度判定・台本量判定を含む詳細ログを出力
- `gui.py`: 生成前スコアゲートと render_native_test 呼び出しをエンジン対応
  - `_run_generation_score_gate` が `native_render` を受け取り `render_engine` を渡す
  - `render_native_test` に `voice_speed_intro/body` を config 定数から渡す
- 各種コードレビュー修正（Codexリファクタ引き継ぎ）:
  - `image_generator.py`: 重複行削除・不要な `gc.collect()` 除去
  - `youtube_uploader.py`: `_close_media_upload` (no-op) を削除し `del media` に置換
  - `core/cta_policy.py`: Long目次のフードハードコード fallback を削除
  - `build_rebalanced_entries` 戻り値型アノテーションを `list[tuple]` に修正

---

## 2026-05-22

### Shortsループ優先・CTA制御・Long目次の運用反映

- 台本生成プロンプトに、Shortsは他動画誘導よりループ視聴を優先する方針を追加。
- Shorts本編の「次回は」「他の動画も見て」「チャンネル登録お願いします」系を生成前レビューで警告するように変更。
- `core/cta_policy.py` を追加し、「ネタ募集CTA: 許可 / 禁止」をアプリ側で付与。
  - Shortsのみ対象。
  - 生成区分が `新規` / `横展開` の場合のみ候補。
  - 現行仕様ではShorts新規/横展開の通算5本に1本だけ許可。
  - 品質改善版、再挑戦は原則禁止。
- ネタ募集CTAを許可した場合、固定コメントが未指定ならネタ募集用固定コメントを自動差し込み。
- Longでは関連動画誘導、vidIQタイトル調整、説明欄YouTubeチャプター追加を許可。
- Longアップロード時、説明欄にチャプターがなければ `チャプター:` 行または既定章立てから `【目次】` を自動追加。
- `_meta/cta_policy.json` と `_meta/youtube_metadata.json` にCTA/Long方針を保存。
- テスト `tests/test_cta_policy.py` を追加。

---

## 2026-05-21

### YouTube同期・出力パス整理・台帳一元化・バグ修正

**アーキテクチャ変更 (commit 7be08a7)**:

- スケジュール管理を `upload_schedule_*.json` から `upload_records.json` 台帳ベースに移行
  - `schedule_from_records()` が `publish_status == "scheduled"` のレコードから派生ビューを生成
  - `sync_schedule_from_youtube()` で YouTube API を正としてローカル台帳を更新。チャンネル全件取得失敗時は既知 video_id のみでフォールバック
  - `rebalance_slots()` は変更リストを返すだけで書き込みを行わない（呼び出し側が YouTube + upload_records を更新）
  - 旧 `upload_schedule_*.json` は `output/000_legacy/` に退避
- 出力ディレクトリを整理
  - `output/000_data/` : `upload_records.json` / `uploaded_titles.txt`
  - `output/000_analytics/` : Analytics スコア JSON / TSV
  - `output/000_legacy/` : 旧スケジュールファイル退避
  - `core/output_paths.py` で絶対パスを集約。`config.py` の ENV 変数で変更可能
  - 旧パス (`output/upload_records.json` 等) は初回アクセス時に自動移行
- GUI のスケジュール画面を `upload_records` 由来の表示に統一
  - Analytics ウィンドウで閉じた後に `render()` が呼ばれて落ちる問題を `winfo_exists()` チェックで修正
  - API ステータス確認の多重実行を `_schedule_sync_running` フラグで抑制
  - リバランス時の移動内容をログ出力

**レビュー修正**:

- `schedule_from_records`: 同一スロットに重複レコードがあった場合、`setdefault` で黙って捨てていたのを `logging.warning` を出す明示判定に変更
- `save_upload_records`: `migrate_root_file` が内部で `ensure_output_dirs` を呼ぶため、直後の冗長な `os.makedirs` を削除
- `infer_video_type`: duration による Shorts 推定閾値を 180s → 60s に修正（YouTube 公式 Shorts 上限に合わせる）
- `rebalance_slots`: docstring を「変更リストを返すだけ・書き込みを行わない」と明記
- `sync_schedule_from_youtube` のフォールバック時にログを追加
- `_schedule_sync_running` フラグのレース修正: `sync_worker` と `detect_manual_published` でフラグのチェック・セットをスレッド起動前（メインスレッド）に移動

---

### vidIQ固定タグ更新・MP4なしアップロード候補除外・プロンプト改善

- `core/youtube_metadata.py` を追加し、vidIQキーワード分析に基づく YouTube タグ生成を一元化。
  - 共通タグに `食べ物 雑学`、`雑学 ショート`、`ゆっくり解説 食べ物`、`VOICEVOX解説`、`コンビニ 雑学`、`お菓子 雑学` などを採用。
  - `食べ物 豆知識` / `食べ物豆知識`、アニメ・漫画・ゲーム雑学、都市伝説、怖い話系タグを除外。
  - 寿司/サーモン、コンビニ/ファミチキ、お菓子、マック、トマト、コーラ、カレー等の題材別タグを自動追加。
  - タグ欄を500文字以内に調整し、実際に使ったタグを `_meta/youtube_metadata.json` に保存。
- `YouTubeアップ` の履歴選択画面で、アップロード可能な `.mp4` がない履歴を表示しないように変更。
- タイトル案プロンプトを更新。
  - 毒・危険視・薬だった系、袋・容器・穴・形・名前の理由、寿司/魚の価値逆転・名前の罠を優先。
  - viewsだけでなく平均視聴率・平均視聴時間・高評価率・登録者増を重視。
  - `雑学 ショート` などのSEO語はタグ・説明欄で補完し、タイトル本文へ不自然に入れないルールを追加。
- 台本生成プロンプトに「スワイプ率対策：ネタ入口パワー判定」を追加。
  - 台本化前に、ネタ名・タイトル・サムネ・冒頭1秒で見たくなるかを判定。
  - 弱い場合は名前の罠、昔と今の真逆、正体ズレ、袋・容器・包装など具体物へ切り口変更する。

---

## 2026-05-20（続き5）

### キャラ設定強化・冒頭パターン・尺判定更新・character_pattern/genre_group 追加

**台本生成プロンプト** (`core/script_generation_prompt.txt` および `local/` 版):
- キャラクタールール更新: ずんだもん=視聴者代表（驚き・疑問役）、めたん=食べ物裏側オタク気質として定義を追加
- 新セクション「冒頭話者パターン」: 外食チェーン/コンビニ/ファストフード/ファミレス/スイーツ/商品開発ではめたん冒頭を許可
- 新セクション「ギャグ制限ルール」: ギャグ・ツッコミは最大2回、冒頭の引き or ラストのオチのみ
- Shorts尺ルール更新: 理想42-48秒 / 許容39-50秒 / 51秒以上は警告 / 53秒以上は出し直し
- タイトルルール強化: 伝統/由来/歴史/本当の理由を避けるワードとして追記、感情動詞型（嫌われていた/出せなかった等）を追加
- フォーマットにキャラパターン/ジャンルフィールドを追加（local/はGit管理外）

**コード変更**:
- `core/parser.py`: キャラパターン/ジャンル の正規表現・META_TYPES・パース処理追加
- `core/analytics_score.py`: Shorts尺判定を42-48s理想/39-50s許容/51-52s警告/53s+needs_reviewに更新。to_tsvにcharacter_pattern/genre_group列追加
- `core/opening_quality.py`: 尺判定閾値を同様に更新。ChatGPT事前チェックの停止閾値を39s未満または53s超に変更
- `core/script_prompts.py`: TSVヘッダーにcharacter_pattern/genre_group追加
- `core/upload_records.py`, `core/youtube_analytics.py`: character_pattern/genre_group の記録・参照を追加
- `gui.py`: アップロード時・metadata.txt読み込み時にcharacter_pattern/genre_group保存。アナリティクスウィンドウにキャラパターン/ジャンル列追加。スケジュールウィンドウに生成区分/キャラ列追加

---

## 2026-05-20（続き4）

### 台本生成プロンプト: 冒頭3秒ルール（知的好奇心型）追加

- `core/script_generation_prompt.txt` および `core/prompt_parts/local/script_generation_prompt.txt` に新セクション「冒頭3秒ルール（知的好奇心型）」を追加。
  - 冒頭3行の型を定義: 1行目=意外な事実を断言、2行目=視聴者の疑問をめたんが代弁、3行目=理由・仕組みの入口
  - 「今日は〇〇について解説するのだ」「今回は〇〇の理由を紹介するのだ」を禁止パターンとして明記
  - 「ヤバい」「衝撃」などの雑な煽りだけに頼ることを禁止。構造として疑問→答えの入口を先に作る方針
  - ファミチキ袋・ドーナツの穴・バームクーヘン年輪・おにぎり包装の4例を追加
  - local/ はGit管理外のためコミットに含まれない

---

## 2026-05-20（続き3）

### `000_uploaded` を削除してもよい構造に変更

- アップロード記録の中央台帳 `output/upload_records.json` を追加。
- アップロード成功時に、各動画フォルダの `_meta/upload_record.json` と中央台帳の両方へ記録するように変更。
- アプリ起動時に既存の `output/000_uploaded/**/upload_record.json` を中央台帳へ移行。
- 固定コメント、公開予定変更、スロット詰め直し、Analytics補完は中央台帳を優先して参照するように変更。
- 中央台帳で公開予定動画を探すとき、同名タイトルより公開予定日時の一致を優先するよう修正。
- `output/000_uploaded/` はアップロード済み生成物の保管場所として扱い、削除しても `video_id`、公開予定、固定コメント状態、再生リスト登録結果、生成区分情報が残るようにした。
- README / SPEC を更新。

---

## 2026-05-20（続き2）

### タイトル案プロンプト大幅改善・台本プロンプトに生成区分追加

**タイトル案プロンプト（`core/script_prompts.py` `build_title_prompt()`）:**
- 分類にH「名前・発祥の勘違い」を追加（天津飯・ナポリタン・シュークリーム系を正しく分類）
- data_wait 動画の優先度を原則A止まりに制限（views 3000以上・likes 30以上・comments 3以上のみ暫定S可）
- 改善再挑戦枠を追加：既存食材でも条件A（views 1000以上+視聴率30〜49%）または条件B（views 500以上+like_rate 1.5%以上）を満たす場合は最大2案まで出力可
- 20案表を16列→12列に軽量化。選定理由・想定フック・冒頭1秒・注意点・事実確認ポイントはTOP5表に集約
- 型の内訳を20案表の直後に集計出力するルールを追加
- 自分ごと化タイトルの定義を明文化（勘違い破壊型・損回避型・日常の理由型・名前の罠型等）
- 新規開拓枠に品質チェックを追加（採点7点未満は出力しない）
- 30文字超タイトルの削除候補ワードを明示（「意外な」「知られざる」「本当の」等）
- 良いタイトル例を既存外の食材（天津飯・ちくわ・ナス等）に差し替え。例は構造参考のみと明記
- Long候補例にも既存食材流用禁止の注記を追加

**台本生成プロンプト（`core/script_generation_prompt.txt` および `core/prompt_parts/local/script_generation_prompt.txt`）:**
- フォーマット例に `生成区分` / `元動画` / `目的` フィールドを追加（説明付き）
- これにより Claude/ChatGPT 生成台本でも横展開・品質改善の記録が `upload_record.json` に保存されるようになった

**その他:**
- `core/ai_generator.py` と `main.py` に `generate_script()` がデッドコードである旨のコメントを追加

**注意:** `core/prompt_parts/local/` は Git 管理外のため、`local/script_generation_prompt.txt` の変更はコミットに含まれない。手元の環境で同ファイルを直接編集済み。

## 2026-05-20（続き）

### タイトル案プロンプトに自分ごと化・暫定横展開ルールを追加

- タイトル案生成プロンプトに、勘違い破壊型・損回避型・日常の理由型・名前の罠型など、視聴者が自分ごと化しやすい攻略帳型のタイトルルールを追加。
- 「食べ物の歴史」だけでなく「食べ物の勘違いを壊す」方向へ寄せる方針を追加。ただし20案中5〜7案程度に抑え、チャンネル本来の価値逆転型と混ぜる。
- `analysis_status=data_wait` の動画でも views / likes / like_rate / comments が強い場合は「暫定横展開候補」として扱うルールを追加。
- 既存・予約済みタイトルの近似重複禁止を強化し、同じ食材・同じ主張の言い換えを禁止。
- 20案の出力表に `優先度` / `型` / `想定フック` を追加。
- SPEC と食べ物用サンプルプロンプト部品を更新。

---

## 2026-05-20

### 横展開・品質改善版の追跡情報をAnalyticsに追加

- 台本メタ情報に `生成区分` / `元動画` / `目的` を追加。`新規` / `横展開` / `品質改善版` / `再挑戦` の判別に使う。
- 生成時の `metadata.txt` とアップロード時の `upload_record.json` に生成区分情報を保存。
- Analytics取得時に `output/000_uploaded/**/upload_record.json` を参照し、動画IDに紐づく生成区分情報をマージ。
- Analytics一覧とTSVに `生成区分` / `元動画` / `目的` を追加。
- README / SPEC に台本メタ情報とAnalytics表示仕様を追記。

---

## 2026-05-19（続き⑫）

### Analytics取得件数の見え方を改善

- Analytics一覧の各列ヘッダークリックで昇順/降順ソートできるように変更。
- Analytics画面のサマリーに、全件数だけでなく `公開 / 予約 / 分析 / 待ち` の内訳を表示。
- Analytics APIにまだ出ていない公開動画でも、YouTube Data APIの `statistics` から再生数・いいね数・コメント数を補完。
- 平均視聴率などが未取得の動画は、数値を補完してもスコア判定せず `data_wait` のまま扱う。
- SPEC に Analytics API と Data API のマージ仕様を追記。

---

## 2026-05-19（続き⑪）

### Codex/Claudeクレジット節約の作業ルールを明記

- `CLAUDE.md` に、常に Codex / Claude の利用クレジット消費を抑えて作業するルールを追加。
- 不要な長文出力、重複調査、過剰なファイル読み込み、不要な並列探索、同じ確認のやり直しを避ける方針を明記。
- アプリ側の動画生成・画像生成・LLMレビューは必要時だけ実行する方針を補足。YouTube APIは運用上必要なら使ってよいが、同じ取得や更新の無意味な繰り返しは避ける。

---

## 2026-05-19（続き⑩）

### Codex/Claude作業時のPowerShell文字化け対策を明記

- `CLAUDE.md` に、PowerShellで日本語ファイルを確認するときは `Get-Content` 直読みを避け、UTF-8指定のPython読み取り・`rg`・`git diff` を優先するルールを追加。
- PowerShell表示が文字化けした場合も、すぐにソース破損と判断せずUTF-8で読み直すよう明記。

---

## 2026-05-19（続き⑨）

### アップロード成功後に同一テーマのバックアップを自動削除

- 再生成時のバックアップ退避後、同一テーマのバックアップは最新1世代だけ残して古いものを自動削除。
- 生成時に `output/000_backups/` へ退避した同一テーマのバックアップを、アップロード成功後に自動削除するように変更。
- 削除対象は `output/000_backups/` 配下で、アップロード済みフォルダ名と一致または同じ接頭辞を持つディレクトリに限定。
- 実行ログに削除件数を表示。
- README / SPEC にバックアップ削除の挙動を追記。

---

## 2026-05-19（続き⑧）

### Longアップロード後の再生リスト自動追加に対応

- `.env` / `config.py` の `LONG_UPLOAD_PLAYLIST_NAME` に再生リスト名を設定すると、Long動画アップロード成功後に自チャンネルの再生リストへ自動追加するように変更。
- 未設定時の既定再生リスト名は `ロング動画`。
- 再生リストは名前完全一致で検索し、既に同じ動画が入っている場合は重複追加しない。
- 追加結果を `_meta/upload_record.json` の `playlist_*` フィールドに保存。
- 実行ログに `再生リスト登録完了` / `再生リスト登録済み` / `再生リスト登録失敗` を明示。
- README / SPEC に設定方法と挙動を追記。

---

## 2026-05-19（続き⑦）

### ドキュメント更新ルールを明文化

- `CLAUDE.md` に、仕様・画面・プロンプト・設定・YouTube連携・Analytics判定・生成フローを変更した場合はドキュメント更新を必須にする運用ルールを追加。
- 最新仕様は `SPEC.md`、大きめの変更履歴は `CHANGELOG.md`、セットアップやAPIキー・設定に関わる変更は `README.md` も更新する方針を明記。

---

## 2026-05-19（続き⑥）

### アナリティクス横展開候補の選定ルールを厳格化

`core/analytics_score.py` の採点ロジックを更新。

- **最低視聴率ライン**: Shorts 45% / ShortLong 50% 未満では `横展開` に昇格しない。
- **判定保留フラグ** (`is_provisional`): views < 500 かつ公開後24時間未満の動画は横展開アクションに `(判定保留)` を付与。
- **登録者純増 >= 1**: 弱いスコアに `・登録導線あり` を補足表示（>= 2 は引き続き強い横展開候補）。
- **コメント >= 1**: `弱い` / `要見直し` スコアに `・反応あり` を補足表示。
- **高エンゲージメント・低視聴率**: like率 >= 1.5% かつ最低ライン未達 → `テーマ有望・構成改善`。
- **views 上位20% 昇格ロジック**: 最低視聴率ラインと `is_provisional` チェックを追加（viewsだけで横展開しない）。
- TSV 出力に `is_provisional` カラムを追加。
- Longは登録者増だけで `横展開` にせず、CTR 8%以上かつ平均視聴率40%以上を横展開条件にする。
- Analytics画面に `分析状態` / `判定保留` 列を追加。
- タイトル案プロンプトの実績データTSVヘッダーに `publish_status` / `analysis_status` / `is_provisional` を追加。
- SPEC の動画スコア判定ルールを最新実装に合わせて更新。

---

## 2026-05-19（続き⑤）

### Long画像節約モードを追加

- `config.py` に `MAX_BACKGROUNDS_LONG_BUDGET = 16` を追加。
- GUI オプション行に **「Long節約」チェックボックス**（デフォルト OFF）を追加。ON にすると Long の背景生成上限を 16 枚に制限。Shorts には影響なし。
- `main.py`: `run_pipeline()` に `long_budget_mode` パラメータを追加。上限超過シーンは自動的に前の背景を継続使用。
- **明示的再利用記法**: 台本の背景行に `背景: 前と同じ` と書くとカウントを消費せず前の背景を継続する（新規生成なし）。
- 台本生成プロンプトに節約モードの記法説明を追記。
- SPEC / README を更新。

---

## 2026-05-19（続き④）

### Long台本生成ルールを厳格化・Long向き題材ルールを追加

- `core/prompt_parts/local/script_generation_prompt.txt` に **Long 生成の最低尺ルール（絶対厳守）** セクションを追加。
  - Long指定時は必ず150〜200セリフ。150未満はLongとして不合格。
  - シーン数 35〜45、1シーン3〜5セリフ、チャプター5〜6章を明示。
  - 5分未満になりそうな題材はShortLong扱い（Longにしない）。
- **Long向き題材ルール** セクションを追加。「章を増やせる題材」だけをLongにするルールと、Shorts向きとの判別基準を明記。
- 自己チェックに Long専用チェック項目を追加（セリフ数・シーン数・チャプター構成・引き伸ばし禁止）。

---

## 2026-05-19（続き③）

### 固定コメント「未投稿だけ」フィルタのバグ修正

- `fixed_comment_thread_id` が未記録でも `fixed_comment_pinned_at` が設定済みなら完了扱いにする。
- YouTube Studio 等で外部ピン留めしアプリで記録した場合も、「未投稿だけ」チェック時に正しく非表示になる。

---

## 2026-05-19（続き②）

### スケジュールダイアログを開くたびにYouTubeと自動同期

- `📅 スケジュール` を開くと自動的に YouTube API でステータスを確認し、ローカルとの差異があれば確認ダイアログを表示するように変更。
- `public` になっていた動画は手動公開済みとして処理（予約スロット削除・`uploaded_titles.txt` 追記）。
- ローカルと YouTube の `publishAt` が 1 分以上ズレている場合はローカルスケジュールと `upload_record.json` を YouTube 側に合わせて更新。
- 差異がない場合はログに「差異なし」とだけ表示して静かに完了。
- `core/youtube_uploader.py` に `get_video_statuses()` 関数を追加（50件バッチ、privacyStatus + publishAt を返す）。

---

## 2026-05-19（続き）

### Long サムネイル A/B テストを無効化オプションに変更

- `config.py` に `LONG_THUMBNAIL_AB_TEST`（デフォルト `False`）を追加。
- `False` のときは Variant A のみ生成し、`thumbnail_ab_test.json` を書かないように変更。
- `True` にすると従来どおり A/B/C 3バリアント生成・マニフェスト保存。
- GUI のオプション行に「LongサムネAB」チェックボックスを追加（デフォルト OFF）。チェックすると A/B/C 3枚生成に切り替わる。
- 背景再利用フローでのサムネイル再生成時も AB テスト設定が正しく引き継がれるよう修正。

---

## 2026-05-19

### アナリティクスの取得件数を全動画対象に変更

- Analytics API の取得期間内に再生実績がない動画も含め、チャンネル全動画を対象にスコアリングするように変更。
- Data API の uploads プレイリストから全動画 ID をページネーション付きで取得し、Analytics データと結合するように変更。
- 動画の `publish_status`（published / scheduled / private / unlisted）を判定し、Analytics 画面に表示するように変更。予約公開中（private ＋ publishAt が未来）は `scheduled` として扱う。
- `analysis_status`（analyzable / data_wait / scheduled / excluded）でスコアリングの対象外を分類し、予約中・非公開はスコア「未計測」・「対象外」として表示するように変更。
- 61〜120 秒の動画を `ShortLong` タイプとして Shorts / Long と別に判定し、専用スコアリング閾値を適用するように変更。
- `views == 0` はスコア「未計測・データ待ち」として処理するように変更。
- 登録者純増 ≥ 2 でスコアを最低 B に引き上げ、さらに平均視聴率 ≥ 60% なら action を「横展開」に変更。
- 高評価率 ≥ 1.5% かつスコアが C/D の場合は action を「テーマ有望・冒頭/構成改善」に変更。
- 再生数上位 20%（80 パーセンタイル）かつ平均視聴率 ≥ 65% の場合は action を「横展開・微改善」に変更。

### スケジュール画面にスロット詰め直し機能を追加

- `📅 スケジュール` に「スロット詰め直し」ボタンを追加。未来の予約スロット全件を現在から最速の空きスロットに前詰めするように変更。
- `upload_record.json` の `publish_at` から video_id を特定し、YouTube 側の公開予定時刻・`upload_schedule_*.json`・`upload_record.json` を一括更新。video_id が見つからない場合はスケジュール JSON のみ更新して警告ログを出す。

### スケジュール画面に絞り込みフィルターを追加

- デフォルト表示を「予定のみ」に変更（済みは非表示）。
- ラジオボタン（すべて / Shorts / Long）で種別ごとに絞り込めるように変更。
- 「済みも表示」チェックボックスで済みエントリーを表示・非表示できるように変更。
- フィルター変更に連動して下部のカウント（合計 / 予定 / 済）も更新されるように変更。

### Ollamaレビュー失敗時に処理中止するよう変更

- Ollama冒頭レビューが接続エラーなどで失敗した場合、ローカル判定へフォールバックして続行せず、レビュー結果を保存して生成処理を中止するように変更。
- Ollama APIが応答していない場合は、レビュー前に `ollama serve` の自動起動を試みるように変更。
- 自動起動してもAPIが応答しない場合は、レビュー結果を保存して生成処理を中止する。
- 冒頭スコア表示に使用モデル名を追加。
- GUIログやAnalytics画面の尺評価表示を日本語化。
- 複数台本の一括生成では、生成開始前に全台本の冒頭スコア・推定尺チェックを先に実行し、要確認がある場合は生成へ進まないように変更。

### 主要ボタンにホバー説明を追加

- メイン画面の生成、停止、LLM/尺チェック、AI台本作成、AIタイトル案、画像確認、YouTubeアップ、スケジュール、アナリティクスなどにツールチップを追加。
- Analytics画面の取得、評価一覧コピー、AI分析用コピーにもツールチップを追加。
- 複数台本処理中に、実行ログラベル横へ「何本中何本完了」形式の進捗表示を追加。
- アップロード済み履歴の `script.txt` にある固定コメントを既存動画へ投稿するボタンを追加。投稿成功後は `upload_record.json` にコメントIDを記録し、二重投稿を避ける。
- 固定コメント投稿前に動画状態を確認し、非公開・存在しない動画・子ども向け設定の動画は投稿せずスキップするように変更。
- 固定コメント投稿成功時に、確認用の一覧画面を表示し、通常動画URLを開けるように変更。
- 固定コメント対象一覧に「未投稿だけ」「公開済みだけ」フィルタを追加し、ピン留め済みの手動記録を残せるように変更。
- 固定コメント投稿後の一覧画面からYouTube Studioコメントボタンを削除し、通常動画URLを開くボタンだけに変更。
- Analytics画面とTSVに高評価率を追加し、AI分析用コピーとタイトル案プロンプトへ実績サマリーを自動で付けるように変更。
- `Longタイトル案` ボタンを追加し、Long候補だけを出すタイトル案プロンプトをコピーできるように変更。
- 既存の `AIタイトル案` ボタン表示を `Shortsタイトル案` に変更。
- LLM/尺チェック後のAI修正依頼文を、問題がない台本も含めて全台本を返す指示に変更し、元台本本文を添付するように変更。
- 冒頭スコアがローカルルール判定だけで通過した場合も `model review:local-rule` を表示し、ChatGPT生成前スコアにも使用モデルを表示するように変更。
- スケジュール画面から予約投稿済み動画の公開予定日時を変更できるようにし、YouTube側の `publishAt`、アプリ内スケジュール、`upload_record.json` を同時に更新するように変更。
- 公開予定変更の変更先時刻を、既存のアップロード時刻ルール（Shorts 7/12/19時、Long 平日21時・土日12/21時）に限定。
- 公開予定変更の日時指定を手入力から日付・時間のプルダウン選択に変更。
- 公開予定変更で同じ種別の既存予定枠に移動する場合、エラーではなく2本の公開予定を入れ替えられるように変更。
- 固定コメント投稿前の動画状態確認に失敗した場合は、誤投稿防止のため投稿処理を中止するように変更。
- README / SPEC にAPIキー・YouTube OAuthの取得手順と、`config.py` / `.env` で変更できる主な設定一覧を追記。
- タイトル案プロンプトを、固定ルールと既存タイトル・実績データなどの差し込み情報が分かる構造に整理。
- タイトル案プロンプトのネタ固有部分を `core/prompt_parts/` に分離し、実績データ欄・重複チェック・既存食材リストを差し替えやすく変更。
- 個人用プロンプト差し替え欄 `core/prompt_parts/local/` をGit管理外にし、同名ファイルがあればローカル側を優先して読み込むように変更。
- `core/prompt_parts/local/script_generation_prompt.txt` がある場合は、台本生成プロンプト本体もローカル側を優先するように変更。
- 共有用のサンプル台本 `samples/scripts/food_shorts_sample.txt` を追加。
- 食べ物用プロンプト設定の復元サンプルを `samples/prompt_parts/food/` に追加。
- 初回クローンでも食べ物用設定でそのまま動くように、Git管理側の既存食材リストを食べ物用に戻した。
- README / SPEC の初回セットアップ手順に、別ジャンル用 `local/` 差し替えと食べ物用設定の復元手順を追加。
- 初回セットアップのプロンプト設定確認を必須手順として明記。
- SPEC にAI編集者向けルールを追加し、ネタ固有プロンプト変更は `core/prompt_parts/local/` を編集するよう明記。
- SPEC のシステム構成に `core/prompt_parts/`、`core/prompt_parts/local/`、`samples/` を追記。
- SPEC 全体を実装に合わせて見直し、パイプライン順、Shorts尺判定、冒頭レビュー停止条件、Ollama設定、VOICEVOX末尾処理、GUI主要機能の記述を更新。

### AIタイトル案プロンプトを実績データ横展開型に変更

- `AIタイトル案` ボタンで、直近の `output/analytics_score_*.tsv` を自動でタイトル生成プロンプトへ差し込むように変更。
- タイトル案の評価に YouTube Analytics の `views`、`average_view_duration`、`average_percentage_viewed`、`subscribers_net`、`likes`、`comments` を反映。
- `ctr` / `impressions` が 0 または空欄の場合は評価に使わず、視聴率・視聴時間・登録者増を優先するルールを追加。
- 20案の出力表に `横展開元` と `実績根拠` を追加。TOP5選定にも必須化。
- 実績根拠には数値を最低1つ以上入れるルールを追加。
- 実績横展開は12〜15案、新規開拓枠は5〜8案を目安に変更。同じ横展開元から最大4案・TOP5は最大2案に制限。
- タイトル案に `既知度` と `既知ネタ回避` の判定を追加。既知度高の案は出力・TOP5採用しないルールを追加。
- Long候補にも実績データ横展開を強制し、3幕構成・5〜10分へ伸ばせる背景を評価する専用ルールを追加。

### 台本プロンプトに既知ネタ深掘りルールを追加

- 台本の中心が「誰でも知っている話」や単なる商品特徴説明にならないよう、既知ネタ深掘りルールを追加。
- 既知度が高いテーマは、開発背景、改良の歴史、味や香りの仕組み、誤解されているポイントへ中心をズラすように変更。

### タイトル・サムネ・冒頭ルールを強化

- 抽象表現だけのタイトル・サムネを禁止。タイトルは理由・経緯、サムネは一番強い事実という役割分担を明確化。
- サムネに書いた衝撃ワードを冒頭5秒以内に回収するルールを追加。
- Longサムネは8〜16文字、最大20文字、食材名 + 逆転ワードを基本に変更。

---

## 2026-05-18

### Longアップスロットを毎日21時・土日は追加で12時に変更

- Long のアップロードスロットを「毎日 21:00 + 土日のみ 12:00」に変更。
- `upload_scheduler.py` の定数を `LONG_SLOTS_WEEKDAY = [21]` / `LONG_SLOTS_WEEKEND = [12, 21]` に変更。

### 出力フォルダ構造をサブフォルダに整理

- 生成物を `_meta/`（レビュー結果・メタデータ）と `thumbnails/`（サムネイル画像）に分離。
- `opening_review.json`、`duration_review.json`、`final_review.json`、`upload_record.json` などすべて `_meta/` へ移動。

### 台本生成プロンプトに既存タイトル重複禁止リストを追加

- `Shortsタイトル案` / `Longタイトル案` のプロンプトに、`output/` 配下のタイトルと `uploaded_titles.txt` をまとめた重複禁止リストを自動で差し込むように変更。

### ScriptParser を共有定数化・parse_string の tempfile 廃止

- `ScriptParser.META_TYPES` を `gui.py` / `main.py` 共通の判定定数として使うように変更。
- `parse_string()` をメモリ内処理に変更（tempfile を使わない）。

### Shorts尺ステータスを細分化・LLMチェック閾値を整備

- Shorts尺ステータスを `ideal`（38〜50秒）/ `ok_but_short`（35〜37秒）/ `ok_but_long`（51〜55秒）/ `warning`（32〜34秒・56〜58秒）/ `needs_review`（範囲外）の5段階に細分化。GUI事前推定と最終尺ログの両方に反映。
- 冒頭スコア判定: 80以上=通過、70〜79=クリティカルエラーなしで警告通過、70未満=停止。クリティカルエラー定義: 1行目食べ物名欠如・不完全・驚きなし、同話者4行連続、Shorts21行以上。
- Ollama書き直し候補はローカル再採点し、書き直し後スコアが80以上の場合のみ採用。主モデルで70以上が出なければフォールバックモデル（`gemma4:e4b`）を1回試みる。
- 冒頭のクリティカルエラーまたは70未満でパイプラインが停止した場合、GUIは`要修正`と表示。

### ChatGPT最終レビューを生成前に移動・事前停止条件を整備

- ChatGPT最終レビューを画像・音声・native MP4生成の前に実行するよう変更。must_fix・スコア70未満・レビュー失敗・スキップでアセット生成前に停止。
- `publish_ok=false`（must_fixなし）は警告ログのみで停止しない。推定Shorts尺35秒未満または55秒超はアセット生成前に停止。
- VOICEVOX実尺計測は音声生成後に引き続き実施し人間判断用にログ記録。

### GUI機能追加: LLM/尺チェックボタン・スコアタグ色分け・画像レビュープロンプト編集

- `gui.py` に `LLM/尺チェック` ボタンを追加。アセット生成なしで全台本のOllama冒頭レビュー・推定尺レビューを実行しサマリーをログ表示。完了後AI修正依頼レポートをクリップボードにコピー。
- スコアタグに色付き背景を追加（強い→緑、警告→黄、低→赤）。スコア行に `■■■ ... ■■■` マーカーを追加。
- 画像レビューダイアログのサムネカードにプロンプト編集ボタンを追加。編集保存でそのサムネが再生成対象にマークされプロンプトファイルが保存される。

### アナリティクス機能を追加

- `core/youtube_analytics.py`: 動画別YouTube Analyticsを7/28/90日ウィンドウで取得。
- `core/analytics_score.py`: ルールベースのS/A/B/C/D評価とactionラベルを付与。
- GUIに独立した `📊 アナリティクス` ウィンドウを追加（色付きスコア行、TSVコピー、AI分析コピー、`output/analytics_score_YYYYMMDD.{json,tsv}` 保存）。

---

## 2026-05-17

### YouTube アナリティクス GUI を追加

- `📊 アナリティクス` ボタンを追加。YouTube Analytics API から動画・チャンネル指標を取得し、S/A/B/C/D スコアで評価する画面を追加。
- スコア行に色付き表示（強い＝緑・注意＝黄・低い＝赤）。TSV コピー・AI 分析用コピー・`output/analytics_score_YYYYMMDD.{json,tsv}` エクスポートに対応。

### Ollama 冒頭レビューを厳格化・項目別スコア対応

- 冒頭レビューを項目別スコア形式に変更。
- 冒頭スコアが 80 未満の場合はパイプラインを中止するように変更（しきい値を 60 → 80 へ引き上げ）。

### 生成前危険チェック・Shorts 尺予測・完了後総合判定を追加

- 生成開始前に危険チェック（NGワード・尺外れ）を実行し、問題があれば中止するように変更。
- Shorts の推定尺を冒頭 2.0 倍速 / 本編 1.65 倍速で計算してログ出力するように変更。
- 全動画の生成完了後に冒頭スコア・尺・最終レビューを並べた総合判定をログ表示するように変更。
- アップロード確認ダイアログにスコア列（冒頭 / 尺 / 最終）を追加。

### 説明文の VOICEVOX クレジット手書き行を自動除去

- 説明文に手書きで入っている VOICEVOX クレジット行を自動で除去し、警告なしに `_VOICEVOX_CREDIT` / `_CHANNEL_FOOTER` を末尾に付与するように変更。

### アップロード完了後に MP4 を自動削除

- アップロード成功後、`output/` 内の MP4 ファイルを自動で削除するように変更（容量節約）。

### FPS を 60 → 30 に変更・音声末尾処理を改善

- `config.py` の `VIDEO_FPS` を 60 → 30 に変更。
- `VOICE_TAIL_SAFETY` / `INTER_DIALOGUE_GAP` をフレーム数定数から秒数定数（FPS 非依存）に変更。
- `VOICE_TAIL_SAFETY_SEC = 0.5s` / `INTER_DIALOGUE_GAP_SEC = 0.2s` に設定。

### サムネイル生成を nanobanana2 に固定

- 背景と統一するため、サムネイル生成モデルを常に `nanobanana2` に固定。

---

## 2026-05-16

### 投稿済みタイトルを uploaded_titles.txt に永続保存

- アップロード完了後、タイトルを `output/uploaded_titles.txt` に追記するように変更。
- `Shortsタイトル案` / `Longタイトル案` の重複禁止リストに `uploaded_titles.txt` も含めるように変更。

### タイトル一覧のクリップボードコピーボタンを追加

- `output/` 配下の全テーマタイトルをクリップボードへ一括コピーするボタンを追加。

### タイトル体言止め禁止ルールを強化

- 台本・タイトル案プロンプトの体言止め禁止ルールを強化。動詞・形容詞止めを必須とするよう変更。

---

## 2026-05-15

### YouTube 予約投稿・スケジュール管理を追加

- `YouTubeアップ` から複数動画を一括予約投稿できるように変更。Shorts は毎日 7:00 / 12:00 / 19:00、Long は毎日 21:00 に自動割り当て。
- `📅 スケジュール` ボタンを追加。予約済み一覧確認・削除・手動公開済み処理に対応。
- スケジュールを `output/upload_schedule_shorts.json` / `upload_schedule_long.json` に永続化。

### 音声末尾無音を自動付加

- VOICEVOX 生成 WAV の末尾に 0.5 秒の無音を Python で直接付加するように変更（`postPhonemeLength` API が効かないため）。

### Shorts 品質改善・パーサー強化

- Shorts の台本パラメータ（行数目標・尺目標）を実測値ベースに更新。
- `ScriptParser` を強化し、区切り記号（`━━ 動画1 ━━`）による複数台本分割に対応。

---

## 2026-05-14

### BGM を固定曲に変更・ワークフロー制御ボタンを追加

- BGM を BGMer「のほほん」に固定し、生成時に自動追加するように変更。
- 作業中止ボタンを追加し、生成処理を即時キャンセルできるように変更。

### Nano Banana クォータ枯渇時の対応を追加

- 画像生成で Nano Banana のクォータが枯渇した場合にエラーを適切に処理してリトライを止めるように変更。
