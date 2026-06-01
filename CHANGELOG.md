# 変更履歴

このファイルには、現行アーキテクチャ以降の運用や品質に影響する大きめの変更だけを残します。

---

## 2026-06-01

### 複数同時実行でWebが無応答になる問題をジョブ並列数の自動制御（キュー）で解消

- 複数ジョブ同時実行時に Web プロセスが応答不能になり UI のログ更新が止まる事象を修正。`worker_runner.py` に Apache MPM 風の `_ConcurrencyGate` を追加し、ワーカー subprocess の同時起動数を下限 `JOB_MIN_CONCURRENT_WORKERS` ↔ 上限 `JOB_MAX_CONCURRENT_WORKERS`（ともに既定1）の範囲で**負荷（待ち行列）に応じて自動増減**するようにした。超過分は順番待ち（キュー）。
- 既定 `min=max=1`（直列）で最も安全。`max` を上げると並行実行で速くなるが Web 無応答リスクが上がる。
- 追加インフラ不要・純Python実装（配布・販売を想定し外部ミドルウェアに依存しない）。Kafka/Redis 等は配布に不向きなため将来の選択肢として SPEC に記載。

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
