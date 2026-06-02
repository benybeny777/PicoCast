# 変更履歴

このファイルには、現行アーキテクチャ以降の運用や品質に影響する大きめの変更だけを残します。

---

## 2026-06-02

### 都市伝説チャンネルの説明文・タグをチャンネル別（ジャンル駆動）に

- `zundamon_kowai` の `channel_theme` / `default_hashtags` を都市伝説向けに設定（DB）。
- YouTube 説明文の SEO 文・タグ・ハッシュタグが**全チャンネルで食べ物固定**だった問題を修正。`core/youtube_metadata.py` を active profile の genre 設定（`config/prompt_profiles/genres/{genre}/profile.yaml` の `seo_sentence_*` / `default_tags`）駆動にした。設定があるチャンネル（都市伝説）はそれを使い、未設定のチャンネル（食べ物）は従来の挙動のまま（**食べ物チャンネルは無変更**）。
- これにより都市伝説チャンネルの説明文に食べ物 SEO 文・`#食べ物雑学`・食べ物タグが混入しなくなった。`normalize_tags` の食べ物向け除外リスト（`都市伝説`/`怖い話` を含む）はジャンル設定チャンネルには適用しない。
- 再生リストは従来どおり genre 駆動（`playlist_categories.md`）で、`zundamon_kowai` は都市伝説カテゴリ。

### 背景プロンプトの欠落・デバッグログ氾濫を修正

- 背景プロンプト `prompt_bg_XXXX.txt` を「生成/再利用」に関わらず**常に保存**するようにした。従来は実生成パスでしか書いておらず、背景再利用時に prompt ファイルが欠落 → 画像ページのプロンプトが空表示・個別再生成が失敗していた。
- `initialize_db()` を**プロセス内で DB パス毎に1回だけ**実行・ログするようにした。移行で多数のホット関数（runner ポーリング・ジョブ操作）が毎回 `initialize_db()` を呼び、`[SQLite] DB 起動` ログが毎操作ごとに氾濫していたのを解消（DDL/マイグレーション再実行も回避）。
- app_shutdown のユニットテストが実 DB のジョブ状態に依存していたため、`_get_running_jobs` をモックして隔離した（移行で `list_jobs` が DB 参照になったことへの追随）。

### runner のffmpeg孤児・キャンセル不能を修正／ジョブログ肥大を抑制

- job-runner 終了・再起動時に、子の ffmpeg がツリーから外れて**孤児プロセスとして残る**問題を修正。Web から runner を停止する際に、Windows は `taskkill /T`、POSIX は専用プロセスグループへの `killpg` でツリーごと終了する（runner は `start_new_session` で起動）。
- レンダー（`render_native_test`）が `cancel_event` を受け取り、**セグメント境界でキャンセルを検出**して `RenderCancelled` で中断するようにした。実行中の長い ffmpeg エンコード後（秒単位）で確実に停止する。runner はこれを cancelled として記録する。
- `append_job_logs` がフラッシュ毎に `logs_json` 全体を再シリアライズして肥大化（O(n²)）していたため、1ジョブのログ行を `JOB_LOG_MAX_ENTRIES`（既定3000）で上限化し、古い行から破棄するようにした。

### profile_context のスレッドローカル残留（要再起動バグ）を恒久修正

- `profile_context.__enter__` が active profile の上書きをスレッドローカルへ設定した直後に `get_profile()` で例外が出ると、`with` 本体に入らず `__exit__` も呼ばれないため上書きが**残留**していた。スレッドプール上のスレッドが誤プロファイルを参照し続け、履歴フォルダ未検出（「フォルダが見つかりません」）・音声件数0件などが**アプリ再起動まで直らない**原因になり得た。`__enter__` 失敗時に必ず復元するよう修正し、リーク不可をテストで保証。

### BGM パスを相対化・履歴からBGM編集を撤去・food_trivia 残骸を掃除

- `bgm_assets.file_path` をプロファイルルート相対（例 `000_assets/bgm/<id>.mp3`）で保存し、読み出し時に現プロファイルの絶対パスへ解決する方式へ変更。`output/` ディレクトリごと移動・プロファイル名変更しても壊れないようにした。既存の絶対パス行は初回に相対へ自動マイグレーションする。
- これにより、旧プロファイル名(food_trivia)の絶対パスが残っていた zunkami の既定BGMが正しく解決されるようになり、再レンダー時の「BGMファイルが見つかりません」を解消。
- `resolve_bgm_selection` に、実体が無い場合へ現プロファイルの `000_assets/bgm/` をファイル名で探す自己修復フォールバックを追加。
- 履歴詳細画面から BGM の表示行と編集UI（モード/ファイル/音量）を撤去。BGMはチャンネル設定で管理し、履歴からの再作成は常にチャンネル既定を使用する。
- 存在しないプロファイル（food_trivia / urban_legend）を参照する `channel_schedule_settings` / `prompt_templates` の孤立行を削除。

### 設定画面の起動時プリロードを追加

- Web UI 起動時に設定画面用の補助データ（Ollamaモデル一覧、`assets/bgm/` の音源ファイル一覧）をバックグラウンドで先読みするようにした。
- `/settings` のHTML生成時にフルサービス診断を待たず、APIキー登録状態はDBの bool だけで表示するようにした。
- プリロード未完了でも `/api/settings/ollama-models` / `/api/settings/bgm-files` は暫定値を即返し、設定項目本体が外部サービス待ちで出ない状態を避けるようにした。

### 履歴一覧の行ボタンを修正

- 履歴一覧の行ごとの「削除」「フォルダを開く」ボタンが、HTML属性内の引用符衝突で動かない場合があったため、行の `data-name` を読むイベントリスナー方式に変更した。

### ジョブログ表示を共通化

- 履歴詳細の処理ログとログ画面のジョブカード描画を `job_poll.js` の共通ロジックへ寄せた。
- job-runner 実行中の queued ジョブで、Webプロセス側の古いメモリ状態ではなく DB の最新ログを返すようにした。
- デバッグログタブも `WEB_LOG_POLL_INTERVAL_MS` と同じ間隔で自動更新するようにし、手動更新ボタンを削除した。

### 履歴一覧の途中データ除外

- 台本だけDB保存された途中停止データが履歴一覧へ出ないよう、render_info / MP4 / サムネ / 実生成ファイルがある履歴だけ表示するようにした。
- 履歴詳細のファイル状態に音声データ数を追加し、「フォルダを開く」が `videos/` / `000_uploaded/` 配下の実フォルダを開くよう修正した。

### Web薄化とjob-runnerを導入

- 生成・レンダージョブを Web プロセス内 subprocess IPC から、`metadata.db:jobs` を共有状態にした常駐 `workers.runner` 実行へ移行した。
- jobs に `profile_id` / `params_json` / `cancel_requested` / `heartbeat_at` / `runner_pid` を追加し、runner が `queued` を原子的に claim して実行するようにした。
- runner はジョブの `profile_id` をスレッドローカルで固定して実行し、Web UI でチャンネルを切り替えても生成先 profile が混線しないようにした。
- ジョブ詳細取得・キャンセル・ログ追記も `job.profile_id` 基準にし、ジョブ投入後にWeb UIのactive profileを切り替えても対象ジョブを取りこぼさないようにした。
- 既存DBの jobs テーブルに新列が無い状態でも、ジョブ参照・キャンセル・runner claim 前に migration を保証するようにした。
- 旧 `web_app/worker_runner.py` / `workers/worker_pipeline.py` / `workers/worker_render.py` と `input.json` / `result.json` ベースのファイルIPCを廃止した。
- デバッグログを `app_debug_web.log` / `app_debug_runner.log` に分離し、QueueListener 経由の書き込みで Windows のローテーション衝突を避けるようにした。

---

## 2026-06-01

### 依存漏れの追加・固定コメント候補の N+1 解消

- `requirements.txt` に不足していた依存を追加: `keyring`（macOS/Linux のシークレットマスターキー保管。Windows は DPAPI のため `platform_system != "Windows"` 限定）、`psd-tools`（キャラ立ち絵PSDの表情レイヤー読み込み）。これまで Mac/Linux で認証情報の保存・復号が動かない可能性があった。
- 固定コメント候補一覧 `list_fixed_comment_candidates` が候補フォルダ1件ごとにレコードを個別クエリしていた N+1 を、`_fixed_comment_records_bulk()` の1クエリにまとめて解消（履歴一覧と同方針）。

### 履歴一覧の N+1 クエリを解消

- 履歴一覧の生成でフォルダ1件ごとにメタ情報を個別クエリ（4テーブルJOIN）していた N+1 を、`_history_db_info_bulk()` で `WHERE local_id IN (...)` の1クエリにまとめて解消。動画本数が増えても `/history` 表示が重くならないようにした。回帰テストを追加。

### 画像の手動差し替えをコピペ対応

- 画像確認画面の手動差し替えに **「📋 貼り付け」ボタン**を追加し、クリップボードの画像で差し替えできるようにした（ファイル選択不要）。Clipboard API でワンクリック貼り付け、未対応/権限拒否時は対象を選んで Ctrl+V するフォールバックも用意。バックエンド（`/api/images/{name}/replace`）は変更なし。

### サムネ欠番の再生成・再生成経路のテスト追加

- 背景再利用時にサムネイル(`thumbnail.png`)が欠けている（503失敗など）と、再生成せず「サムネイル画像を生成できませんでした」で**中止**していたのを修正。再利用指定でもサムネが無ければ再生成するようにした（背景のファイル名基準修正と同系統）。
- `reuse_audio` / `reuse_backgrounds` が worker へ正しく渡るサービス層テスト、`/api/history/regenerate`（reuse_audio受理）・`/api/images/{name}/regenerate`（job_id返却）の経路テストを追加。

### 背景再利用のバグ修正（インデックス基準→ファイル名基準）

- `reuse_backgrounds` の再利用判定が並び順インデックス基準だったため、欠番（503失敗などで未生成の背景）があると背景番号がズレて誤った画像を割り当て、かつ**欠番自体を再生成しない**バグを修正。期待ファイル名 `bg_NNN_001.png` の存在で判定し、**有れば再利用・無ければ再生成**するようにした（生成と再利用で `_background_filename()` を共用）。
- これにより「履歴から再生成（背景再利用）で未生成分だけ作り直す」が全工程再生成パスでも正しく機能する。回帰テストを追加。

### コード整理（バッチ削除・音声孤児掃除・SDエラー分類・例外コメント）

- 到達不能な死にコードのバッチ背景生成経路（`use_batch_api` / `generate_backgrounds_batch`）を削除。完了タイムアウト無しのポーリングによるハングリスクも併せて解消。
- `reuse_audio` 時、台本変更で不要になった旧WAV（孤児）を `_cleanup_orphan_audio()` で掃除し、字幕数とWAV数の不一致を防止。
- Stable Diffusion WebUI 経路の背景生成失敗も `classify_image_api_error` で分類し `ImageGenerationError`（エラーコード付き）として扱うよう統一。
- サイレントに握りつぶしていた `except Exception: pass` 13箇所に `# フォールバック許可:` 理由コメントを付与（no-silent-fallback ルール準拠の明確化）。
- `_cleanup_orphan_audio` と SD WebUI エラーコードの単体テストを追加。

### 失敗背景の再生成導線・音声再利用・エラーコード全面適用

- 履歴詳細に「⚠ 背景生成の失敗」カード（背景番号 / エラーコード / HTTP / モデル）と **「失敗した背景だけ再生成」** ボタンを追加。`image_generation_failures`（DB）を参照し、保存済みプロンプトで該当背景のみ再生成、成功でその失敗記録を消す。
- 再生成時に既存音声を使い回す **「音声を再利用する」**（`reuse_audio`、既定OFF）を追加。バックアップの WAV を復元し、同じ台本でファイル名が一致する音声は VOICEVOX 合成をスキップする。
- エラーコードを画像生成以外にも適用: `E-SECRET-MISSING`（APIキー未登録）/ `E-SCRIPT-MISSING`（台本なし）/ `E-VOICE-FAIL`（音声失敗）/ `E-RENDER-FAIL`（レンダー失敗）を該当例外・メッセージに付与。

### エラーコードの中央管理とデバッグログ拡充

- エラーコードと文言を `core/error_codes.py` の `ERROR_CATALOG` で一元管理するようにした（`E-IMG-BUSY` / `E-IMG-AUTH` / `E-IMG-QUOTA` / `E-IMG-FAIL` / `E-SECRET-MISSING` / `E-SCRIPT-MISSING` / `E-VOICE-FAIL` / `E-RENDER-FAIL` / `E-UNKNOWN`）。`format_error()` / `AppError` / `image_error_code()` を追加。背景生成失敗ログ・`image_generation_failures.error_code`（スキーマ v7）にコードを付与する。
- `app_debug.log` を拡充: 全ジョブのログ（ワーカー subprocess の stdout/stderr 転送分を含む）を `job_manager._log()` から `yj.job` ロガー経由でミラーし、生成・レンダーの進捗とエラーが永続デバッグログにも残るようにした。ジョブ開始/終了/所要時間、ワーカー起動/終了 exit code、結果ファイル無しクラッシュも記録。ログ書式に関数名:行番号を追加。

### 画像生成API 503混雑のエラー表示・再実行導線を改善

- 背景画像生成（Gemini / Nano Banana）の失敗を HTTP ステータスで分類するようにした（`401/403`=認証・権限、`429`=レート制限・クォータ、`503`=API混雑、その他=通常）。`core/image_generator.py` に `ImageGenerationError` / `classify_image_api_error()` を追加。
- **503 は「🚧 画像生成API混雑 / 後で再実行推奨」**と通常エラーと分けて目立つ形で表示し、失敗ログに 動画タイトル / 背景番号(例 4/8) / モデル / HTTPステータス / エラーメッセージ / 既存背景の再利用可否 を出すようにした。1本でも 503 があれば「台本やプロンプトの問題ではない」旨を明示する。
- **自動フォールバック禁止**を維持（別モデル・別バックエンド・ローカル生成へ切り替えない）。生成済み背景は破棄せず、再生成時は『背景再利用』で未生成分だけ作り直せる。
- 失敗記録を `metadata.db` の `image_generation_failures` テーブル（スキーマ v6）に保存するようにした（`_meta/*.json` は作らない）。背景生成開始時に旧記録をクリアする。

### ログ画面のコピペ改善（更新間隔を長く・選択中は再描画停止）

- `/logs` の自動更新間隔を固定2秒から `WEB_LOG_POLL_INTERVAL_MS`（既定8秒）に変更し、設定画面からも調整可能にした。
- ログをテキスト選択している間は、その回のポーリング再描画をスキップしてコピー操作が途切れないようにした。

### Ollama冒頭レビューの可視化を改善

- Ollama冒頭レビュー完了時に、`overall_score` と hook / title_match / tempo / clarity / loop / cta の詳細スコア、`must_fix`、`warnings`、`fix_target` をGUIログへ出すようにした。
- 70〜79点で `must_fix` が空の場合は「生成継続可 / 軽微改善推奨」「中止不要。冒頭改善余地あり」と表示し、停止対象ではないことを分かるようにした。
- 78点付近への採点癖を検証できるよう、Ollama の `model` / `prompt_version` / `raw_response` / パース後スコア / サブスコア / 警告文 / `fix_target` / `created_at` を `metadata.db` の `script_quality.opening_review_debug`（JSON、スキーマ v5）へ保存するようにした（`get_opening_review_debug` で取得）。ローカルJSONファイルは作成しない。
- Ollamaレビューのプロンプトに、80〜89点と70〜79点の使い分け、78点時の具体的修正例必須、抽象的な「引きが弱い」だけの禁止を明記した。

### 生成ログの解像度表記を整理

- 解像度ログを「縮小生成解像度(SD) → 最終保存解像度(FHD)」の矢印表記に変更した。SD（縮小生成）は `540x960 (SD) → 1080x1920 (FHD)`、FHD（高画質生成）は `1920x1080 (FHD)` のように表示し、フルHD解像度に `(SD)` が付いて紛らわしかった旧表記を解消した。
- Nano Banana の送信設定ログも同じ矢印表記に統一し、`1K` / `2K` のAPI指定ラベルは前面に出さない。

### LLM/尺チェック表示と個別履歴削除を修正

- `/check` は推定尺を基本表示とし、Ollama / ChatGPT が有効な場合だけ各スコアを追加表示するようにした。無効な LLM は呼び出さず、ローカルレビュー詳細や修正依頼文は表示しない。
- 履歴一覧・履歴詳細の個別削除で、APIエラー時に画面上へ必ず原因を表示するようにした。
- `SPEC.md` に残っていた作業者向け運用ルールを `AGENTS.md` へ移し、仕様書の先頭表現を複数チャンネル共通へ整理した。
- 説明欄フッターのチャンネル登録URLとハッシュタグを active profile から組み立てるようにし、特定チャンネル固定の文言が別チャンネルへ混ざらないようにした。

### 投稿予約スロットをチャンネル別設定化

- Shorts の既定予約スロットを 07:00 / 12:00 / 21:00、Long の既定予約スロットを 22:00 に変更。タイムゾーンは Asia/Tokyo。
- Long の土日 12:00 追加枠と旧 21:00 枠を廃止し、曜日問わず 22:00 のみに統一した。
- `data/settings.db` に `channel_schedule_settings` を追加し、食べ物雑学チャンネル・都市伝説チャンネル・今後追加されるチャンネルの投稿予約スロットを profile_id ごとに管理するようにした。
- 設定画面のチャンネル詳細フォームから、Shorts / Long の投稿予約スロットとタイムゾーンを編集できるようにした。
- 新規予約・公開予定変更候補・スロット詰め直しは active profile のチャンネル別スケジュール設定を使う。既存の予約済み `publish_at` は通常の設定変更では変更せず、詰め直し適用時のみ新スロットに従って更新される。

### 履歴削除・prefix正規化・台本先行保存を追加

- 履歴画面と履歴詳細から、確認付きで履歴フォルダと `metadata.db` の関連レコードを削除できるようにした。
- 旧 `short_` / `shorts_` / `long_` / `meeting_` 系のフォルダ名を読み取り時に後方互換として扱い、新規生成では設定済みの `Shorts_` / `Long_` / `ネタ会議_` 系へ正規化するようにした。
- 生成パイプライン開始直後に台本本文を `videos.script_content` へ保存するようにし、途中失敗時も台本が DB に残るようにした。
- 背景画像の「前と同じ」「再利用」指定を生成枚数から除外し、Nano Banana の不要な追加生成を防ぐようにした。Stable Diffusion WebUI 背景生成は直列化し、WebUI 側の詰まりを避けるようにした。
- 既存の profile 別 `metadata.db` で旧 `output_root` や移動前フォルダを指していた `videos.output_dir` を、実在する `output/{profile_id}/...` 配下へ補正した。

### 複数同時実行でWebが無応答になる問題をジョブ直列化（キュー）で解消

- 複数ジョブ同時実行時に Web プロセスが応答不能になり UI のログ更新が止まる事象を修正。`worker_runner.py` で `threading.BoundedSemaphore` によりワーカー subprocess を **直列実行（同時1本、`JOB_MAX_CONCURRENT_WORKERS` 既定1）** にし、超過分は順番待ち（キュー）にした。
- 設定値は `.env` ではなく `config/config.py` に置く。追加インフラ不要・純Python実装（配布・販売を想定し外部ミドルウェア＝Kafka/Redis 等に依存しない）。

### 履歴詳細の「メタデータ」欄を DB から再構築して復活

- `_meta/metadata.txt` 廃止（metadata.db 正本化）の際に履歴詳細の「メタデータ」欄が空（`metadata_txt=""`）になっていた回帰を修正。`video_metadata`（動画タイトル・サムネ文字・説明文・タグ・生成区分・元動画・目的・固定コメント）から旧 `metadata.txt` と同じ体裁で再構築するようにした。

### 台本ファイル(script.txt)を完全廃止し metadata.db を唯一の正本に

- 生成パイプラインが `script.txt` を**出力しない**ようにし、台本本文を `sync_folder_to_db(theme_dir, script_content=...)` で `metadata.db` の `videos.script_content` へ直接保存するようにした。
- 台本を読む全経路を DB 参照へ統一した: native レンダー（`native_renderer`）・アップロードのタグ抽出（`youtube_uploader`）・履歴詳細表示・画像の Shorts 判定・ネタ募集CTA候補カウント（`cta_policy`）・サムネイル再生成。`native_renderer` の字幕/演出/サイズ判定ヘルパーはファイルパスではなく台本テキストを受け取るように変更した。
- 既存フォルダの取り込み（`import_output_dir` / `sync_folder_to_db` の引数省略時）に限り、後方互換として既存の `script.txt` を読む。
- 不要になった `history_service._read_text` / `cta_policy._script_meta_from_path` を削除した。

### 履歴フォルダ参照先ズレ・再生成エラーを修正

- 履歴からの再生成が `metadata.db` の `videos.script_content`（正本）を読むようにした。従来はディスクの `script.txt` を読んでおり、DB の `output_dir` が旧パスのままだと参照先が外れて「再生成可能なscript.txtが見つかりません」になっていた。
- 履歴フォルダ名から実体パスを引く処理を `security.find_history_dir()`（`videos/` → `000_uploaded/` の順で解決）に統一した。画像配信（サムネイル・背景の表示）・画像再生成・手動差し替え・再レンダーが `videos/` 配下のフォルダを解決できず壊れていた不具合を修正。
- `upsert_video()` が `ON CONFLICT` 時に `videos.output_dir` を同期フォルダの実体パスへ更新するようにし、旧パスが残り続けないようにした。既存DBの古い `output_dir` は再同期で修正済み。
- `import_output_dir` の進捗 `print()` が絵文字で Windows(cp932) コンソールでは `UnicodeEncodeError` で落ちていたのを ASCII 表記に修正した。
- 履歴詳細の再生成フォームの文言・確認ダイアログ・エラーメッセージから `script.txt` 表記を外し、「保存済みの台本（DB正本）」を元に再生成する旨へ統一した。

### チャンネル識別子をハンドル基準に統一

- `profile_id` / `genre_profile` / `output_root` をチャンネルハンドル（`@` なし）へ統一するようにした。
- 既存 DB の異なる値はハンドル名へ移行し、関連テーブル・output フォルダ・genre_profile フォルダも合わせて移行するようにした。
- 旧 `default` に保存されていた APIキー・YouTube Client Secrets は、未登録の各チャンネルへ暗号化済みのままコピーするようにした。
- チャンネル詳細フォームから、そのチャンネル専用の APIキー・YouTube Client Secrets を登録できるようにした。

### APIキーのチャンネル別管理を復旧

- `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `HF_TOKEN` の保存・状態表示・利用を active profile 基準に統一した。
- チャンネル切替時に設定ステータスキャッシュを破棄し、切替先 profile の認証状態を表示するようにした。
- profile 別の APIキー登録状態が混ざらないことをテストで確認するようにした。

### 画像手動差し替えとBGM選択を追加

- `/images` から背景画像・サムネイルを手動アップロードで差し替え可能にした。元画像は `000_backups/image_replacements/` に保存し、差し替え履歴は `metadata.db` の `image_replacements` テーブルに記録する。
- 設定画面にBGM管理タブを追加し、チャンネル別に `bgm_assets` を DB 管理できるようにした。生成・履歴詳細のレンダーでは「チャンネル既定 / 個別指定 / BGMなし」を選択できる。
- nativeレンダー時に選択したBGM情報を `render_info` に保存し、再レンダーやアップロード前確認で参照できるようにした。

### 固定コメント自動投稿の全チャンネル対応

- `AUTO_FIXED_COMMENT_PROFILE_SCOPE` を追加し、固定コメント自動投稿の対象を `all`（全チャンネル）/ `active`（アクティブのみ）で切り替え可能にした。
- `all` では登録済み channel profile すべての `metadata.db` と profile_id 別 YouTube OAuth token を使って未投稿候補を巡回する。
- 手動画面は従来通り active profile のみを対象にする。

### 現行ドキュメントの整理

- 現行アーキテクチャに関係する変更だけを記録する方針へ変更。
- `AGENTS.md` / `SPEC.md` / `README.md` / `MANUAL.md` / `CHANGELOG.md` の最新内容を正本として扱う運用に整理。
- 認証状態表示を DB の `encrypted_secrets` 基準に統一。

### YouTube側を正とする動画DB同期を追加

- `core/metadata_db.py` に `sync_youtube_statuses()` / `sync_youtube_statuses_from_api()` を追加。
- YouTube Data API の `title` / `privacyStatus` / `publishAt` / `publishedAt` / 動画種別を正として、`videos` / `render_info` / `youtube_status` を更新するようにした。
- YouTube側で削除済みの既知動画IDは、`delete_missing=True` 指定時に関連DBレコードも削除する。
- 同期後に孤立行を削除し、過去削除や移行で残った空欄メタデータが画面・集計に混ざらないようにした。
- スケジュール同期でも `metadata.db` へ YouTube 側の状態を書き戻すよう変更。
- 固定コメント、履歴表示、Analytics補助情報、CTAポリシー、YouTubeメタ、生成メタの参照・保存を `metadata.db` 正本へ寄せた。

### prompt_templates DB化

- `data/settings.db` に `prompt_templates` テーブルを新設。テンプレートを `profile_id` 単位で管理。
- `config/prompt_profiles/genres/{genre_profile}/` の既存ファイルから初期 seed を自動実行するようにした。
- `build_script_generation_prompt()` / `build_title_prompt()` / `build_meeting_script_prompt()` / `build_gemini_system_prompt()` が DB テンプレートから読み込むよう変更。
- テンプレート未登録時は `RuntimeError` で停止する。
- 設定画面に「テンプレート」タブを追加。active チャンネルのテンプレートのみ表示・編集可能。
- REST API として `GET/POST/PUT/DELETE /api/prompt-templates`、クローン、デフォルト設定、seed 実行を追加。

### 複数チャンネルプロファイル運用

- `channel_profiles` テーブルを `data/settings.db` に追加し、active profile によって出力パス・DB・プロンプトが切り替わる設計を導入。
- `core/channel_profile.py` を追加し、profile CRUD と `require_active_profile()` を提供。
- `config/prompt_profiles/genres/food_trivia/` と `genres/urban_legend/` を追加。
- `core/prompt_profile_loader.py` を追加し、seed 用プロンプトファイルを読み込む処理を集約。
- `core/script_prompts.py` からジャンル固有文言を除去し、`genre_profile` パラメータで切り替え可能にした。
- `core/output_paths.py` を profile 別パス解決の関数群に整理。
- `core/metadata_db.py` の DB パスを active profile の `000_data/metadata.db` に変更。
- Web UI ヘッダーに active channel profile を表示し、Web UI上で登録済み profile を切り替えられるようにした。

### ドキュメント整合

- `AGENTS.md` の出力フォルダ構造を `output/{profile_id}/videos/{テーマ名}/` 配下の現行仕様に更新。
- `AGENTS.md` に「Web UI チャンネル切替」セクションを追加。
- `AGENTS.md`・`SPEC.md` のプロジェクト概要を複数チャンネル対応の汎用ツールとして再記述。
- `SPEC.md` の Shorts アップロードスロットを 7:00 / 12:00 / 19:00 に修正。

---

## 変更履歴に書く目安

- プロンプト方針を大きく変えた。
- YouTube Analytics、アップロード、スケジュールなど運用フローを変えた。
- 生成物の品質レビュー、尺チェック、NGワードなど判定基準を変えた。
- Web UI の主要ボタンや出力形式を変えた。
