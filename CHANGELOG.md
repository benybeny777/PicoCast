# 変更履歴

このファイルには、現行アーキテクチャ以降の運用や品質に影響する大きめの変更だけを残します。

---

## 2026-06-01

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
