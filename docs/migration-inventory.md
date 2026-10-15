# Python旧版からRust版への移行棚卸し

WP-R1-1。2026-10-16のソースを対象とする。合計642件（仕様節143、routes関数180、画面テンプレート19、設定定数275、旧DBテーブル25）。
判断は移行方針であり実装完了を示さない。「移す」は意味とデータを維持、「作り直す」は操作や責務をRust/Tauriへ再設計、「やめる」は新規に提供しない。切り替え前の旧コード削除を許可する表ではない。

仕様はコードブロック外の全見出しを掲載し、順序を識別子にする。routesはHTTPハンドラーと内部補助関数の全トップレベル関数を掲載する。同じ関数の複数HTTPメソッドは同じ行に併記する。画面は19テンプレート（共通baseを含む）。設定は非公開の大文字定数も含み、値・実設定・秘密値を収録しない。DBはcore内のCREATE TABLE宣言を対象とし、実DBは開かない。

新テーブルはDESIGN_implementation_plan.md §4.2が正本。専用列のない旧状態はproject_revisionsの取り込みスナップショットへ保持し、WP-R1-2で型付き表現を確定する。固定コメントや再生リストの記録を捨てて再投稿しない。取り込み元DB・素材・認証情報は保護し、照合をWP-R1-6、不要コードの削除をWP-R5-4で行う。AquesTalkの既存設定はvoiceプロバイダ境界へ保持し、VOICEVOXへ無言で変更しない。

cargo xtask inventory は全識別子とソースを双方向で照合する。cargo xtask verify に同じ検査を組み込む。更新漏れ・削除済み項目・重複・判断やWPの欠損で失敗する。新画面の実操作・データ一致・外部APIの実確認はこの静的検査に含めない。

## 仕様の全節

| 識別子 | 対象 | 判断 | 担当WP | 移行先・理由 |
|---|---|---|---|---|
| `spec:001` | Native Video Factory 仕様書 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:002` | Rust版の基盤（R0） | 移す | WP-R0-3 / WP-R0-4 / WP-R0-5 | R0共通基盤 / app_settings / secrets |
| `spec:003` | 概要 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:004` | 📑 目次 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:005` | バージョン表示 | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:006` | システム構成 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:007` | キャラクター設定の分離（character_profiles） | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `spec:008` | 動画フォーマット | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:009` | Shorts | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:010` | Long | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:011` | 四国めたん 役割固定ルール（キャラクター設定で管理） | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:012` | 説明密度・掛け合い品質ルール | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:013` | ネタ会議 (Idea Meeting / ShortLong) | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:014` | 動画生成パイプライン (`workers/main.py: run_pipeline`) | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:015` | 全体フロー | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:016` | 尺推定（native基準） | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:017` | 背景・音声の再利用ロジック | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:018` | IMAGE_BACKEND（画像生成バックエンド統合設定） | 作り直す | WP-R2-8 | assets / asset_refs / scenes / job_steps |
| `spec:019` | Stable Diffusion WebUI 背景生成 | 作り直す | WP-R2-8 | assets / asset_refs / scenes / job_steps |
| `spec:020` | Stable Diffusion WebUI モデル管理 | 作り直す | WP-R2-8 | assets / asset_refs / scenes / job_steps |
| `spec:021` | 品質レビュー (`core/opening_quality.py`) | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:022` | 冒頭レビュー 3段階 | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:023` | `should_auto_rewrite_opening` の条件（いずれか） | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:024` | 処理中止条件 | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:025` | ChatGPT生成前レビュー | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:026` | DB保存 | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:027` | LLMレビューの有効化 | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:028` | Ollamaレビュースキーマ | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:029` | スコア採点基準（Ollamaに渡す指示） | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:030` | アップロードスケジューラー (`core/upload_scheduler.py`) | 移す | WP-R1-3 / WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `spec:031` | 出力データディレクトリ | 作り直す | WP-R0-4 / WP-R1-4 | 共通保存先 / assets / asset_refs / projects |
| `spec:032` | ローカル Web UI (`web_app/`) | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:033` | 起動 | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:034` | FastAPI 構成 | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:035` | ジョブ管理 (`job_manager.py`) | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:036` | チャンネル別フルオート運用 | 作り直す | WP-R2-15 / WP-R4-6 | autopilot_policies / cost_ledger / jobs |
| `spec:037` | Web UI のジョブ監視 | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:038` | ジョブの同時実行制御（キュー） | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:039` | 製品版MVP機能 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:040` | 初回セットアップ | 作り直す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings / channels / prompt_templates |
| `spec:041` | ライセンス管理 | やめる | WP-R5-4 | 対象なし（販売しない） |
| `spec:042` | 診断パッケージ | 作り直す | WP-R0-3 / WP-R4-3 / WP-R4-9 | デバッグログ / crash_reports / notifications |
| `spec:043` | バックアップ / 復元 | 作り直す | WP-R1-8 | audit_log（バックアップ実体は管理保存先） |
| `spec:044` | 起動・多重起動の自己回復 | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:045` | 製品版SEED | 作り直す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings / channels / prompt_templates |
| `spec:046` | 設定画面の表示モード | 作り直す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings / channels / prompt_templates |
| `spec:047` | 主要画面 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:048` | API概要 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:049` | セキュリティ方針 | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:050` | Web一本化方針 | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:051` | 主要機能 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:052` | アプリ終了フロー (`core/app_shutdown.py`) | 作り直す | WP-R4-1 / WP-R4-2 | Tauri IPC・単一起動・終了処理 / app_settings |
| `spec:053` | SQLite 接続管理方針 (`core/metadata_db.py`) | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |
| `spec:054` | ログカラー | 作り直す | WP-R0-3 / WP-R4-3 / WP-R4-9 | デバッグログ / crash_reports / notifications |
| `spec:055` | Shorts尺アラート（6段階） | 作り直す | WP-R2-12 / WP-R2-13 | qa_results / project_revisions |
| `spec:056` | 事前チェック (`_pre_generate_check`) | 作り直す | WP-R2-11 / WP-R4-9 | app_settings / channel_settings / notifications |
| `spec:057` | アップロード確認ダイアログ | 作り直す | WP-R3-2 / WP-R4-6 | uploads / youtube_videos / projects |
| `spec:058` | よみがな正規化 (`core/reading_normalizer.py`) | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `spec:059` | 音声生成バックエンド (`core/audio_backends.py` / `core/voicevox.py`) | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `spec:060` | VOICEVOX音声生成 | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `spec:061` | AquesTalk音声生成 | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `spec:062` | 音声タイミング | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `spec:063` | 台本フォーマット | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:064` | Shortsフォーマット例 | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:065` | Longフォーマット（追加要素） | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:066` | 記法一覧 | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:067` | 設定 (`config/config.py`) | 作り直す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings / channels / prompt_templates |
| `spec:068` | ffmpeg ネイティブレンダラー (`core/native_renderer.py`) — 本番レンダラー | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:069` | 安定条件 | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:070` | 実尺チェック（VOICEVOX 音声生成直後） | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:071` | 詳細ログ（`render_native_test` 完了時） | 作り直す | WP-R0-3 / WP-R4-3 / WP-R4-9 | デバッグログ / crash_reports / notifications |
| `spec:072` | native字幕の可読性 | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:073` | Long動画専用機能 | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:074` | 📢 CTA/Long動画の運用ポリシー | 移す | WP-R3-3 | projects / project_revisions（CTA・チャプター・クレジット） |
| `spec:075` | サムネイルA/Bテスト | 作り直す | WP-R2-9 / WP-R6-2 | experiments / experiment_assignments / assets / projects |
| `spec:076` | タイトルA/Bテスト | 作り直す | WP-R2-9 / WP-R6-2 | experiments / experiment_assignments / assets / projects |
| `spec:077` | 画像生成解像度 | 作り直す | WP-R2-8 | assets / asset_refs / scenes / job_steps |
| `spec:078` | 画像生成APIエラーの扱い（503混雑など） | 作り直す | WP-R2-8 | assets / asset_refs / scenes / job_steps |
| `spec:079` | エラーコード | 作り直す | WP-R0-5 | エラーカタログ（DB保存対象外） |
| `spec:080` | デバッグログの内容 | 作り直す | WP-R0-3 / WP-R4-3 / WP-R4-9 | デバッグログ / crash_reports / notifications |
| `spec:081` | Long画像節約モード | 作り直す | WP-R2-8 | assets / asset_refs / scenes / job_steps |
| `spec:082` | チャプターマーカー自動生成 | 移す | WP-R3-3 | projects / project_revisions（CTA・チャプター・クレジット） |
| `spec:083` | 出力ファイル構成 | 作り直す | WP-R0-4 / WP-R1-4 | 共通保存先 / assets / asset_refs / projects |
| `spec:084` | レイヤー構成 | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `spec:085` | 立ち絵テンプレート | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `spec:086` | 操作手順 | 作り直す | WP-R1-1 / WP-R4-10 | 横断仕様（個別機能は各行で追跡） |
| `spec:087` | 初回セットアップ時のプロンプト設定 | 移す | WP-R1-3 / WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / channel_settings（固有seedを製品seedに混ぜない） |
| `spec:088` | 生成 | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:089` | Shortsタイトル案 / Longタイトル案 | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:090` | 複数台本の一括生成 | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:091` | 履歴から複数生成 | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `spec:092` | 画像確認 | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `spec:093` | 動画出力 | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines / channel_settings |
| `spec:094` | YouTubeアップロード | 作り直す | WP-R3-2 / WP-R4-6 | uploads / youtube_videos / projects |
| `spec:095` | 動画スコア判定ルール (`core/analytics_score.py`) | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `spec:096` | 台本作成ルール | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:097` | 最優先ルール | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:098` | キャラ設定 | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `spec:099` | 掛け合い品質ルール | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:100` | Shortsループ構成 | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:101` | vidIQ反映ルール | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:102` | CTA優先順位 | 移す | WP-R3-3 | projects / project_revisions（CTA・チャプター・クレジット） |
| `spec:103` | 背景・テロップ | 作り直す | WP-R2-4 / WP-R2-8 | scenes / lines / assets |
| `spec:104` | NGワード | 作り直す | WP-R2-2 / WP-R2-13 | prompt_templates / prompt_template_versions / projects / lines / qa_results |
| `spec:105` | 外部サービス依存 | 作り直す | WP-R2-11 / WP-R4-9 | app_settings / channel_settings / notifications |
| `spec:106` | APIキー・OAuth取得 | 作り直す | WP-R1-3 / WP-R3-1 | secrets（暗号化と更新後の保存） |
| `spec:107` | 設定の扱い | 作り直す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings / channels / prompt_templates |
| `spec:108` | CTA / 導線制御 | 移す | WP-R3-3 | projects / project_revisions（CTA・チャプター・クレジット） |
| `spec:109` | チャンネルプロファイル管理（複数チャンネル対応） | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `spec:110` | `channel_profiles` テーブル | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `spec:111` | `channel_schedule_settings` テーブル（`data/settings.db`） | 移す | WP-R1-3 / WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `spec:112` | 出力ディレクトリ構造（profile 別） | 作り直す | WP-R0-4 / WP-R1-4 | 共通保存先 / assets / asset_refs / projects |
| `spec:113` | API | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `spec:114` | `prompt_templates` テーブル（`data/settings.db`） | 移す | WP-R1-3 / WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / channel_settings（固有seedを製品seedに混ぜない） |
| `spec:115` | API | 移す | WP-R1-3 / WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / channel_settings（固有seedを製品seedに混ぜない） |
| `spec:116` | プロンプトプロファイル構成 | 移す | WP-R1-3 / WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / channel_settings（固有seedを製品seedに混ぜない） |
| `spec:117` | `zundamon_kowai` の怪談寄り移行 | 移す | WP-R1-3 / WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / channel_settings（固有seedを製品seedに混ぜない） |
| `spec:118` | チャンネル登録・設定 | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `spec:119` | DB アーキテクチャ | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |
| `spec:120` | 概要 | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |
| `spec:121` | 認証情報管理 (`data/settings.db` — `encrypted_secrets` テーブル) | 作り直す | WP-R1-3 / WP-R3-1 | secrets（暗号化と更新後の保存） |
| `spec:122` | マスターキー管理 | 作り直す | WP-R1-3 / WP-R3-1 | secrets（暗号化と更新後の保存） |
| `spec:123` | `encrypted_secrets` テーブル | 作り直す | WP-R1-3 / WP-R3-1 | secrets（暗号化と更新後の保存） |
| `spec:124` | DB 正本仕様 | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |
| `spec:125` | `output/{profile_id}/000_data/metadata.db` テーブル定義 | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |
| `spec:126` | `videos` — 動画基本情報 | 移す | WP-R1-4 | projects / project_revisions / scenes / lines / assets / asset_refs |
| `spec:127` | `render_info` — レンダリング設定・メタデータ | 移す | WP-R1-4 | project_revisions / job_steps |
| `spec:128` | `image_replacements` — 画像手動差し替え履歴 | 移す | WP-R1-4 | project_revisions / assets / asset_refs |
| `spec:129` | `bgm_assets` — チャンネル別BGM（`data/settings.db`） | 移す | WP-R1-3 | assets / asset_refs / asset_licenses / music_tags |
| `spec:130` | `video_metadata` — 台本由来のメタ情報・CTA ポリシー | 移す | WP-R1-4 | projects / project_revisions |
| `spec:131` | `youtube_status` — YouTube 投稿・公開状態 | 移す | WP-R1-4 | uploads / youtube_videos / project_revisions（固定コメント状態） |
| `spec:132` | `analytics_snapshots` — YouTube Analytics スナップショット | 移す | WP-R1-4 | analytics_daily（同日の最新値）/ project_revisions（原記録） |
| `spec:133` | `playlists` — 再生リスト登録状態 | 移す | WP-R1-4 | project_revisions（再生リスト登録状態） |
| `spec:134` | `topic_history` — トピック重複チェック | 移す | WP-R1-4 | topics |
| `spec:135` | `script_quality` — 台本品質スコア・レビュー結果 | 移す | WP-R1-4 | qa_results / project_revisions |
| `spec:136` | `jobs` — バックグラウンドジョブ履歴 | 移す | WP-R1-4 | jobs / job_steps（放置中は履歴扱い。再実行しない） |
| `spec:137` | `image_generation_failures` — 背景画像生成の失敗記録（v6） | 移す | WP-R1-4 | job_steps / notifications |
| `spec:138` | `data/settings.db` テーブル定義 | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |
| `spec:139` | `settings` — アプリ設定 | 移す | WP-R1-3 | app_settings / channel_settings |
| `spec:140` | `reading_dictionary_entries` — よみがな辞書 | 移す | WP-R1-3 | reading_entries |
| `spec:141` | `reading_candidates` — 読み補正候補 | 移す | WP-R1-3 | reading_candidates |
| `spec:142` | スキーマバージョン履歴 | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |
| `spec:143` | 主要 API 関数（`core/metadata_db.py`） | 作り直す | WP-R1-2 / WP-R1-4 | schema_migrations / 新スキーマ全表（DB写像表を参照） |

## APIとルート内補助関数

| 識別子 | 対象 | 判断 | 担当WP | 移行先・理由 |
|---|---|---|---|---|
| `route:web_app/routes/api_analytics.py#api_analytics` | GET /api/analytics | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_analytics.py#api_analytics_tsv` | GET /api/analytics/tsv | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_analytics.py#api_analytics_ai_copy` | GET /api/analytics/ai-copy | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_analytics.py#api_analytics_shorts_title_prompt` | GET /api/analytics/shorts-title-prompt | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_analytics.py#api_analytics_long_title_prompt` | GET /api/analytics/long-title-prompt | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_analytics.py#api_analytics_refresh` | POST /api/analytics/refresh | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_analytics.py#api_analytics_retention` | GET /api/analytics/retention | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_autopilot.py#_check_profile` | 内部補助 _check_profile | 作り直す | WP-R2-15 / WP-R4-6 | autopilot_policies / jobs / cost_ledger |
| `route:web_app/routes/api_autopilot.py#get_status` | GET /api/autopilot | 作り直す | WP-R2-15 / WP-R4-6 | autopilot_policies / jobs / cost_ledger |
| `route:web_app/routes/api_autopilot.py#save_settings` | POST /api/autopilot/settings | 作り直す | WP-R2-15 / WP-R4-6 | autopilot_policies / jobs / cost_ledger |
| `route:web_app/routes/api_autopilot.py#dismiss` | POST /api/autopilot/{run_id}/dismiss | 作り直す | WP-R2-15 / WP-R4-6 | autopilot_policies / jobs / cost_ledger |
| `route:web_app/routes/api_bgm.py#api_list_bgm` | GET /api/bgm | 作り直す | WP-R2-5 / WP-R4-7 | assets / asset_licenses / music_tags |
| `route:web_app/routes/api_bgm.py#api_create_bgm` | POST /api/bgm | 作り直す | WP-R2-5 / WP-R4-7 | assets / asset_licenses / music_tags |
| `route:web_app/routes/api_bgm.py#api_update_bgm` | PUT /api/bgm/{bgm_id} | 作り直す | WP-R2-5 / WP-R4-7 | assets / asset_licenses / music_tags |
| `route:web_app/routes/api_bgm.py#api_set_default_bgm` | POST /api/bgm/{bgm_id}/default | 作り直す | WP-R2-5 / WP-R4-7 | assets / asset_licenses / music_tags |
| `route:web_app/routes/api_bgm.py#api_delete_bgm` | DELETE /api/bgm/{bgm_id} | 作り直す | WP-R2-5 / WP-R4-7 | assets / asset_licenses / music_tags |
| `route:web_app/routes/api_channel.py#api_channel_info` | GET /api/channel-info | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#_profile_to_dict` | 内部補助 _profile_to_dict | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#_save_channel_schedule` | 内部補助 _save_channel_schedule | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/api_channels.py#api_list_channels` | GET /api/channels | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#api_current_channel` | GET /api/channels/current | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#api_create_channel` | POST /api/channels | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#api_update_channel` | PUT /api/channels/{profile_id} | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#api_activate_channel` | POST /api/channels/{profile_id}/activate | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#api_validate_channel` | POST /api/channels/{profile_id}/validate | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#api_delete_channel` | DELETE /api/channels/{profile_id} | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_channels.py#api_prompt_profiles_redirect` | GET /api/channels/prompt-profiles | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_channels.py#api_product_seed_profiles` | GET /api/channels/product-seed-profiles | 移す | WP-R1-3 / WP-R4-9 | channels / channel_settings |
| `route:web_app/routes/api_character_profiles.py#_active_profile_id` | 内部補助 _active_profile_id | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `route:web_app/routes/api_character_profiles.py#_to_dict` | 内部補助 _to_dict | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `route:web_app/routes/api_character_profiles.py#list_character_profiles` | GET /api/character-profiles | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `route:web_app/routes/api_character_profiles.py#_assert_owned` | 内部補助 _assert_owned | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `route:web_app/routes/api_character_profiles.py#update_character_profile` | PATCH /api/character-profiles/{character_id} | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `route:web_app/routes/api_character_profiles.py#create_character_profile` | POST /api/character-profiles | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `route:web_app/routes/api_character_profiles.py#delete_character_profile` | DELETE /api/character-profiles/{character_id} | 作り直す | WP-R1-5 / WP-R2-6 | characters / assets |
| `route:web_app/routes/api_check.py#api_check` | POST /api/check | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_db.py#_ensure_init` | 内部補助 _ensure_init | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_db.py#api_db_videos` | GET /api/db/videos | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_db.py#api_db_stats` | GET /api/db/stats | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_db.py#api_db_duplicates` | GET /api/db/duplicates | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_db.py#api_db_sync` | POST /api/db/sync/{history_name} | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_db.py#api_db_analytics` | GET /api/db/analytics/{local_id:path} | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/api_db.py#api_db_delete_video` | DELETE /api/db/videos/{local_id:path} | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_db.py#api_db_import_all` | POST /api/db/import-all | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_fixed_comment.py#api_fixed_comment_candidates` | GET /api/fixed-comment/candidates | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_fixed_comment.py#api_fixed_comment` | POST /api/fixed-comment | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_fixed_comment.py#api_fixed_comment_mark_posted` | POST /api/fixed-comment/mark-posted | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_fixed_comment.py#api_fixed_comment_mark_all_posted` | POST /api/fixed-comment/mark-all-posted | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_generate.py#api_generate` | POST /api/generate | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_generate.py#api_batch_generate` | POST /api/generate/batch | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_history.py#api_list_history` | GET /api/history | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_history.py#api_get_history` | GET /api/history/{history_name} | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_history.py#api_delete_history` | DELETE /api/history/{history_name} | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_history.py#api_render` | POST /api/history/{history_name}/render | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines |
| `route:web_app/routes/api_history.py#api_open_folder` | POST /api/history/{history_name}/open-folder | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_history.py#api_fixed_comment_copy` | GET /api/history/{history_name}/fixed-comment-copy | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_history.py#api_poll_copy` | GET /api/history/{history_name}/poll-copy | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_history.py#api_regenerate_histories` | POST /api/history/regenerate | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/api_images.py#api_list_images` | GET /api/images/{history_name} | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_images.py#api_regenerate` | POST /api/images/{history_name}/regenerate | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_images.py#api_save_prompts` | POST /api/images/{history_name}/save-prompts | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_images.py#api_replace_image` | POST /api/images/{history_name}/replace | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_images.py#api_replacements` | GET /api/images/{history_name}/replacements | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_images.py#api_restore_image` | POST /api/images/{history_name}/restore | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_images.py#serve_file` | GET /api/images/{history_name}/file/{file_path:path} | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_jobs.py#list_jobs` | GET /api/jobs | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `route:web_app/routes/api_jobs.py#get_job` | GET /api/jobs/{job_id} | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `route:web_app/routes/api_jobs.py#cancel_job` | POST /api/jobs/{job_id}/cancel | 作り直す | WP-R2-10 | jobs / job_steps / step_cache |
| `route:web_app/routes/api_playlist_classifier.py#api_playlist_classifier_candidates` | GET /api/playlist-classifier/candidates | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_playlist_classifier.py#api_playlist_classifier` | POST /api/playlist-classifier | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_prompt.py#api_script_prompt` | GET /api/prompt/script | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt.py#api_title_prompt` | GET /api/prompt/title | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt.py#api_meeting_prompt` | GET /api/prompt/meeting | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#_active_profile_id` | 内部補助 _active_profile_id | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#_check_ownership` | 内部補助 _check_ownership | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_list_templates` | GET /api/prompt-templates | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_create_template` | POST /api/prompt-templates | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_seed` | POST /api/prompt-templates/seed | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_export_templates` | GET /api/prompt-templates/export | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_import_templates` | POST /api/prompt-templates/import | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_get_template` | GET /api/prompt-templates/{template_id} | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_update_template` | PUT /api/prompt-templates/{template_id} | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_set_default` | POST /api/prompt-templates/{template_id}/set-default | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_clone_template` | POST /api/prompt-templates/{template_id}/clone | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#api_delete_template` | DELETE /api/prompt-templates/{template_id} | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_prompt_templates.py#_tmpl_to_dict` | 内部補助 _tmpl_to_dict | 作り直す | WP-R2-2 / WP-R4-9 | prompt_templates / prompt_template_versions / projects / lines |
| `route:web_app/routes/api_schedule.py#api_schedule` | GET /api/schedule | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/api_schedule.py#api_schedule_sync` | POST /api/schedule/sync | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/api_schedule.py#api_schedule_rebalance` | POST /api/schedule/rebalance | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/api_schedule.py#api_schedule_rebalance_apply` | POST /api/schedule/rebalance/apply | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/api_schedule.py#api_schedule_update` | POST /api/schedule/update | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/api_schedule.py#api_schedule_delete` | POST /api/schedule/delete | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/api_sd_models.py#_make_progress` | 内部補助 _make_progress | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#_run_download` | 内部補助 _run_download | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#_run_delete_redownload` | 内部補助 _run_delete_redownload | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#list_models` | GET /api/sd-models | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#list_webui_models` | GET /api/sd-models/webui | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#get_current_model` | GET /api/sd-models/current | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#get_progress` | GET /api/sd-models/progress | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#download_model` | POST /api/sd-models/download | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#delete_model` | POST /api/sd-models/delete | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#delete_and_redownload` | POST /api/sd-models/delete-redownload | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#use_model` | POST /api/sd-models/use | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_sd_models.py#rescan` | POST /api/sd-models/rescan | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/api_settings.py#api_settings_status` | GET /api/settings/status | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_refresh_status` | POST /api/settings/status/refresh | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_aquestalk_test` | POST /api/settings/aquestalk/test | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `route:web_app/routes/api_settings.py#api_get_config` | GET /api/settings/config | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_get_log_poll_interval` | GET /api/settings/runtime/log-poll-interval | 作り直す | WP-R0-3 / WP-R0-5 / WP-R4-3 | notifications / crash_reports |
| `route:web_app/routes/api_settings.py#api_save_config` | POST /api/settings/config | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_get_output_base` | GET /api/settings/output-base | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_change_output_base` | POST /api/settings/output-base | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_fixed_comment_task_status` | GET /api/settings/fixed-comment-task | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_settings.py#api_fixed_comment_task_repair` | POST /api/settings/fixed-comment-task/repair | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_settings.py#api_fixed_comment_task` | POST /api/settings/fixed-comment-task | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_settings.py#api_save_secrets` | POST /api/settings/secrets | 作り直す | WP-R1-3 / WP-R3-1 | secrets |
| `route:web_app/routes/api_settings.py#api_secret_status` | GET /api/settings/secrets/status | 作り直す | WP-R1-3 / WP-R3-1 | secrets |
| `route:web_app/routes/api_settings.py#api_save_api_key` | POST /api/settings/secrets/api-key | 作り直す | WP-R1-3 / WP-R3-1 | secrets |
| `route:web_app/routes/api_settings.py#api_save_client_secrets` | POST /api/settings/secrets/client-secrets | 作り直す | WP-R1-3 / WP-R3-1 | secrets |
| `route:web_app/routes/api_settings.py#api_delete_api_key` | DELETE /api/settings/secrets/api-key | 作り直す | WP-R1-3 / WP-R3-1 | secrets |
| `route:web_app/routes/api_settings.py#api_delete_youtube_secret` | DELETE /api/settings/secrets/youtube | 作り直す | WP-R3-2 / WP-R3-3 | uploads / youtube_videos / projects |
| `route:web_app/routes/api_settings.py#api_delete_legacy_file` | DELETE /api/settings/secrets/legacy-file | 作り直す | WP-R1-3 / WP-R3-1 | secrets |
| `route:web_app/routes/api_settings.py#api_bgm_files` | GET /api/settings/bgm-files | 作り直す | WP-R2-5 / WP-R4-7 | assets / asset_licenses / music_tags |
| `route:web_app/routes/api_settings.py#api_get_reading_dict` | GET /api/settings/reading-dict | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `route:web_app/routes/api_settings.py#api_add_reading_dict_base` | POST /api/settings/reading-dict/base | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `route:web_app/routes/api_settings.py#api_delete_reading_dict_base` | DELETE /api/settings/reading-dict/base/{word:path} | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `route:web_app/routes/api_settings.py#api_delete_reading_dict_user` | DELETE /api/settings/reading-dict/user/{word:path} | 作り直す | WP-R2-3 | reading_entries / reading_candidates / characters |
| `route:web_app/routes/api_settings.py#api_debug_log` | GET /api/settings/debug-log | 作り直す | WP-R0-3 / WP-R0-5 / WP-R4-3 | notifications / crash_reports |
| `route:web_app/routes/api_settings.py#api_ollama_models` | GET /api/settings/ollama-models | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_legal_consent_status` | GET /api/settings/legal-consent | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_accept_legal_consent` | POST /api/settings/legal-consent | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_setup_status` | GET /api/settings/setup | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_setup_readiness` | GET /api/settings/setup-readiness | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_setup_complete` | POST /api/settings/setup | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_product_info` | GET /api/settings/product-info | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_check_update` | POST /api/settings/check-update | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_license_status` | GET /api/settings/license | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_license_machine_code` | GET /api/settings/license/machine-code | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_save_license` | POST /api/settings/license | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#_license_operation` | 内部補助 _license_operation | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_save_activation` | POST /api/settings/license/activation | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_renew_activation` | POST /api/settings/license/renew | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_deactivate_activation` | POST /api/settings/license/deactivate | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/api_settings.py#api_create_diagnostics` | POST /api/settings/diagnostics | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_create_backup` | POST /api/settings/backup | 作り直す | WP-R1-8 | audit_log（実体は管理保存先） |
| `route:web_app/routes/api_settings.py#api_restore_backup` | POST /api/settings/restore | 作り直す | WP-R1-8 | audit_log（実体は管理保存先） |
| `route:web_app/routes/api_settings.py#api_detect_services` | POST /api/settings/detect-services | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_settings.py#api_apply_detected_services` | POST /api/settings/detect-services/apply | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_shutdown.py#api_shutdown` | POST /api/shutdown | 作り直す | WP-R4-1 / WP-R4-2 | app_settings（Tauri IPC・単一起動） |
| `route:web_app/routes/api_shutdown.py#api_shutdown_status` | GET /api/shutdown/status | 作り直す | WP-R4-1 / WP-R4-2 | app_settings（Tauri IPC・単一起動） |
| `route:web_app/routes/api_status.py#health` | GET /api/health | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_status.py#api_status` | GET /api/status | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_status.py#api_dashboard` | GET /api/dashboard | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/api_upload.py#_require_channel` | 内部補助 _require_channel | 作り直す | WP-R3-2 / WP-R3-3 | uploads / youtube_videos / projects |
| `route:web_app/routes/api_upload.py#_require_playlist_mode` | 内部補助 _require_playlist_mode | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/api_upload.py#api_upload_candidates` | GET /api/upload/candidates | 作り直す | WP-R3-2 / WP-R3-3 | uploads / youtube_videos / projects |
| `route:web_app/routes/api_upload.py#api_upload` | POST /api/upload | 作り直す | WP-R3-2 / WP-R3-3 | uploads / youtube_videos / projects |
| `route:web_app/routes/api_upload.py#api_batch_upload` | POST /api/upload/batch | 作り直す | WP-R3-2 / WP-R3-3 | uploads / youtube_videos / projects |
| `route:web_app/routes/errors.py#raise_api_error` | 内部補助 raise_api_error | 作り直す | WP-R0-3 / WP-R0-5 / WP-R4-3 | notifications / crash_reports |
| `route:web_app/routes/errors.py#error_payload` | 内部補助 error_payload | 作り直す | WP-R0-3 / WP-R0-5 / WP-R4-3 | notifications / crash_reports |
| `route:web_app/routes/pages.py#_render` | 内部補助 _render | 作り直す | WP-R2-4 / WP-R2-7 | projects / scenes / lines |
| `route:web_app/routes/pages.py#_static_asset_version` | 内部補助 _static_asset_version | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/pages.py#page_dashboard` | GET / | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/pages.py#page_autopilot` | GET /autopilot | 作り直す | WP-R2-15 / WP-R4-6 | autopilot_policies / jobs / cost_ledger |
| `route:web_app/routes/pages.py#page_generate` | GET /generate | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/pages.py#page_check` | GET /check | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/pages.py#page_history` | GET /history | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/pages.py#page_history_detail` | GET /history/{history_name} | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |
| `route:web_app/routes/pages.py#page_images` | GET /images | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/pages.py#page_analytics` | GET /analytics | 移す | WP-R3-6 / WP-R4-8 | analytics_daily / retention_curves |
| `route:web_app/routes/pages.py#page_schedule` | GET /schedule | 作り直す | WP-R5-2 / WP-R4-6 | schedule_slots / jobs |
| `route:web_app/routes/pages.py#page_upload` | GET /upload | 作り直す | WP-R3-2 / WP-R3-3 | uploads / youtube_videos / projects |
| `route:web_app/routes/pages.py#page_playlist_classifier` | GET /playlist-classifier | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/pages.py#page_fixed_comment` | GET /fixed-comment | 移す | WP-R3-4 | youtube_videos / project_revisions（投稿済み印・登録状態） |
| `route:web_app/routes/pages.py#page_settings` | GET /settings | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/pages.py#page_setup` | GET /setup | 作り直す | WP-R4-9 | app_settings / channel_settings |
| `route:web_app/routes/pages.py#page_legal` | GET /legal/{doc} | やめる | WP-R5-4 | 対象なし（販売しない） |
| `route:web_app/routes/pages.py#page_logs` | GET /logs | 作り直す | WP-R0-3 / WP-R0-5 / WP-R4-3 | notifications / crash_reports |
| `route:web_app/routes/pages.py#page_sd_models` | GET /sd-models | 作り直す | WP-R2-8 / WP-R4-5 | assets / asset_refs / scenes |
| `route:web_app/routes/pages.py#page_db` | GET /db | 作り直す | WP-R1-2 / WP-R1-4 | projects / project_revisions / schema_migrations |

## 画面

| 識別子 | 対象 | 判断 | 担当WP | 移行先・理由 |
|---|---|---|---|---|
| `screen:web_app/templates/analytics.html` | analytics.html | 作り直す | WP-R4-8 | 分析 |
| `screen:web_app/templates/autopilot.html` | autopilot.html | 作り直す | WP-R4-6 | 自動運用 |
| `screen:web_app/templates/base.html` | base.html | 作り直す | WP-R4-2 | 共通ナビゲーション・通知・チャンネル選択 |
| `screen:web_app/templates/check.html` | check.html | 作り直す | WP-R2-11 / WP-R4-9 | 健康診断 |
| `screen:web_app/templates/dashboard.html` | dashboard.html | 作り直す | WP-R4-3 | ホーム |
| `screen:web_app/templates/db.html` | db.html | 作り直す | WP-R4-9 | データ管理（任意SQL実行は提供しない） |
| `screen:web_app/templates/fixed_comment.html` | fixed_comment.html | 作り直す | WP-R3-4 / WP-R4-6 | 投稿後操作 |
| `screen:web_app/templates/generate.html` | generate.html | 作り直す | WP-R4-4 | つくる |
| `screen:web_app/templates/history.html` | history.html | 作り直す | WP-R4-7 | ライブラリ |
| `screen:web_app/templates/history_detail.html` | history_detail.html | 作り直す | WP-R4-5 | スタジオ |
| `screen:web_app/templates/images.html` | images.html | 作り直す | WP-R4-5 | 背景編集 |
| `screen:web_app/templates/legal.html` | legal.html | やめる | WP-R5-4 | 対象なし（販売しない） |
| `screen:web_app/templates/logs.html` | logs.html | 作り直す | WP-R4-3 / WP-R4-9 | 通知・診断 |
| `screen:web_app/templates/playlist_classifier.html` | playlist_classifier.html | 作り直す | WP-R3-4 / WP-R4-6 | 再生リスト設定 |
| `screen:web_app/templates/schedule.html` | schedule.html | 作り直す | WP-R4-6 | カレンダー |
| `screen:web_app/templates/sd_models.html` | sd_models.html | 作り直す | WP-R4-9 | 画像プロバイダ設定 |
| `screen:web_app/templates/settings.html` | settings.html | 作り直す | WP-R4-9 | 設定 |
| `screen:web_app/templates/setup.html` | setup.html | 作り直す | WP-R4-9 | 初回設定 |
| `screen:web_app/templates/upload.html` | upload.html | 作り直す | WP-R4-6 | 投稿承認 |

## 設定定数

| 識別子 | 対象 | 判断 | 担当WP | 移行先・理由 |
|---|---|---|---|---|
| `config:_SETTINGS_VALUES` | 旧版共通定数 | やめる | WP-R1-3 | 対象なし（旧版の内部キャッシュ・環境移行補助） |
| `config:PRODUCT_ID` | 端末コードの製品識別子。T5の改名時にPicoCastへ変更する | やめる | WP-R4-1 | 対象なし（HTTP常駐・販売識別を廃止） |
| `config:AUTOPILOT_DAILY_SHORTS` | 1日あたりのShorts生成本数の初期値 | 移す | WP-R2-15 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTOPILOT_DAILY_LONGS` | 1日あたりのLong生成本数の初期値 | 移す | WP-R2-15 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTOPILOT_START_HOUR` | 生成開始時刻の初期値（チャンネルのタイムゾーン） | 移す | WP-R2-15 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTOPILOT_MIN_SCORE` | 自動投稿を許可する品質スコアの初期値 | 移す | WP-R2-15 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTOPILOT_DAILY_PAID_LIMIT` | 有料APIの1日上限。0では有効化を禁止 | 移す | WP-R2-15 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTOPILOT_MAX_DAILY_VIDEOS` | 設定できる1日の合計本数の上限 | 移す | WP-R2-15 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:_ENV_VALUE_QUOTES` | 旧版共通定数 | やめる | WP-R1-3 | 対象なし（旧版の内部キャッシュ・環境移行補助） |
| `config:CHANNEL_NAME` | チャンネル表示名（アップロード必須） | 移す | WP-R3-2 / WP-R3-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHANNEL_HANDLE` | @ハンドル（アップロード必須） | 移す | WP-R3-2 / WP-R3-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHANNEL_THEME` | テーマ説明（任意） | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHANNEL_ACCENT_COLOR` | UIアクセント色（#RRGGBB / 未設定可） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:DEFAULT_HASHTAGS` | デフォルトハッシュタグ（任意） | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_FOOD_TOXIC_GENRE_PROFILES` | 辛口相方めたんを既定有効にする genre_profile | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_URL` | VOICEVOX エンジン API エンドポイント | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_PATH` | VOICEVOX 自動起動用パス（空=手動起動） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_ENABLED` | AquesTalk系ゆっくり音声バックエンドを有効化 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_ENGINE_PATH` | AquesTalk系エンジン実行ファイルまたはラッパーCLIのパス | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_LICENSE_CONFIRMED` | A-Quest公式ライセンス確認済みフラグ | 移す | WP-R2-3 / WP-R4-9 | channel_settings / characters.usage_rules_json（外部音声の規約確認は必要） |
| `config:AQUESTALK_COMMAND_TEMPLATE` | AquesTalk系エンジン呼び出しコマンドテンプレート | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_DEFAULT_SPEED` | AquesTalk既定速度 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_DEFAULT_PITCH` | AquesTalk既定高さ | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_DEFAULT_VOLUME` | AquesTalk既定音量 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_TIMEOUT_SEC` | AquesTalk音声生成タイムアウト秒数 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_TEST_TEXT` | AquesTalk疎通テスト用テキスト | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_QUERY_WORKERS` | audio_query 並列数（上限4） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_SYNTH_WORKERS` | synthesis 並列数（安定性優先で1） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_QUERY_WORKERS_MAX` | audio_query の安全上限 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_SYNTH_WORKERS_MAX` | synthesis の安全上限 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NANOBANANA_BG_WORKERS` | Nano Banana 背景生成並列数 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_BODY_VOICE_SPEED` | Shorts 本編 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_INTRO_VOICE_SPEED` | Shorts 冒頭 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_LONG_BODY_VOICE_SPEED` | Long 本編 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_LONG_INTRO_VOICE_SPEED` | Long 冒頭 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICE_SPEED_SCALE` | VOICEVOX API のデフォルト値。生成時は用途別速度を明示指定する | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICE_POST_PHONEME_LENGTH` | 各音声 WAV 末尾に追加する無音（秒）。0 = 無効 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICE_INTRO_FAST_LINES` | line_count モード: 冒頭 N 行をイントロ速度にする | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_INTRO_VOICE_SPEED_MIN` | 旧版共通定数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_INTRO_VOICE_SPEED_MAX` | 旧版共通定数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_BODY_VOICE_SPEED_MIN` | 旧版共通定数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_BODY_VOICE_SPEED_MAX` | 旧版共通定数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_AUDIO_LOUDNORM_ENABLED` | loudnorm 有効/無効 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_AUDIO_LOUDNORM_I` | Integrated loudness 目標 (LUFS) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_AUDIO_LOUDNORM_TP` | True Peak 上限 (dBTP) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_AUDIO_LOUDNORM_LRA` | Loudness Range 目標 (LU) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_MIN_SILENCE_BETWEEN_LINES` | 許容最小値 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_DEFAULT_SILENCE_BETWEEN_LINES` | 通常セリフ間 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SCENE_CHANGE_SILENCE` | 背景切り替え時 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_MAX_NORMAL_SILENCE` | この値超は警告 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_WARNING_SILENCE` | この値超は要確認 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_BGM_VOLUME_DB` | native 出力の BGM 音量 (dB) | 移す | WP-R2-5 / WP-R4-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_UPPER_BODY_MODE` | 有効で腰から上表示 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_UPPER_BODY_SCALE` | Long: キャラ拡大倍率 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_UPPER_BODY_SHORTS_SCALE` | Shorts: キャラ拡大倍率（縦画面は幅が狭いため Long より小さく） | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET` | Shorts: 下方向シフト量 (px) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_UPPER_BODY_LONG_Y_OFFSET` | Long: 下方向シフト量 (px) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_CHARACTER_SCALE` | 旧版共通定数 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_ESTIMATE_BASE_CPS` | 推定尺計算の基準文字数/秒 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_CHARS_MUST_FIX_MIN` | これ未満の総文字数は must_fix | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_TARGET_CHARS_MIN` | 目標文字数の下限 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_TARGET_CHARS_MAX` | 目標文字数の上限 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_AVG_CHARS_MIN` | 1行あたり平均文字数の下限 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_SHORT_LINE_MAX` | 短すぎる行（≤4文字）の最大許容数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_LINES_IDEAL_MIN` | 理想セリフ数: 下限 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_LINES_IDEAL_MAX` | 理想セリフ数: 上限 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_LINES_TARGET_MIN` | 目標セリフ数: 下限 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_LINES_TARGET_MAX` | 目標セリフ数: 上限 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_LINES_WARNING` | 29〜30行: warning | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHORTS_LINES_MUST_FIX` | 31行以上: must_fix | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_REVIEW_USE_LLM` | Ollama レビュー有効/無効 | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_REVIEW_PROVIDER` | 現状 "ollama" 固定 | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_REVIEW_MODEL` | レビューモデル | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_REVIEW_AUTO_REWRITE` | スコア不足時に自動リライトするか | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_SCORE_ABORT_THRESHOLD` | これ未満: warning 扱い | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_SCORE_HARD_ABORT_THRESHOLD` | これ未満: 処理中止 | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_REVIEW_MAX_LLM_RETRIES` | LLM リトライ上限 | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_BASE_URL` | Ollama API エンドポイント | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_REVIEW_MODEL` | 冒頭レビューモデル | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_REWRITE_MODEL` | 冒頭リライトモデル | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_TRANSLATE_MODEL` | Stable Diffusion WebUI プロンプト日→英翻訳モデル | 移す | WP-R2-2 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_PLAYLIST_MODEL` | 再生リストジャンル判定モデル | 移す | WP-R3-4 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_PLAYLIST_TIMEOUT_SEC` | 再生リストジャンル判定タイムアウト秒数 | 移す | WP-R3-4 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_PLAYLIST_NUM_PREDICT` | 再生リストジャンル判定の最大生成トークン数 | 移す | WP-R3-4 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:IMAGE_BACKEND` | 画像生成バックエンド（gemini / sd_webui） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_BASE_URL` | Stable Diffusion WebUI / A1111 API URL | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_TIMEOUT_SEC` | Stable Diffusion WebUI API タイムアウト(秒) | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_MODEL` | Stable Diffusion WebUI で使用するモデル名（空=起動中モデルをそのまま使用） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_SAMPLER` | Stable Diffusion WebUI サンプラー名 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_STEPS` | Stable Diffusion WebUI 生成ステップ数 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_CFG_SCALE` | Stable Diffusion WebUI CFGスケール | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_WIDTH` | Stable Diffusion WebUI 出力幅(px) — 背景デフォルト | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_HEIGHT` | Stable Diffusion WebUI 出力高さ(px) — 背景デフォルト | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_NEGATIVE_PROMPT` | Stable Diffusion WebUI ネガティブプロンプト（人物・低品質抑制） | 移す | WP-R2-2 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_ROOT` | Stable Diffusion WebUI 本体ルートディレクトリ（例: C:\sd.webui\webui） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_MODEL_MANIFEST_PATH` | Stable Diffusion WebUI モデルマニフェストパス（空=同梱既定値を使用） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTO_DOWNLOAD_SD_MODELS` | 未導入モデルの自動ダウンロード許可（0=停止/手動のみ, 1=自動可） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_REWRITE_FALLBACK_MODEL` | リライト失敗時のフォールバックモデル | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENING_REWRITE_MAX_FALLBACKS` | フォールバック試行上限 | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENAI_FINAL_REVIEW_ENABLED` | レビュー有効/無効 | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OPENAI_FINAL_REVIEW_MODEL` | レビューモデル | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SHORT_FULL_SCRIPT_REVIEW` | Shorts 全文レビュー | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:LONG_FULL_SCRIPT_REVIEW` | Long 全文レビュー（重いため OFF） | 移す | WP-R2-12 / WP-R2-13 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTO_FULL_REWRITE_ENABLED` | must_fix 時に自動全文リライトするか | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICE_READING_MODE` | 読み補正モード | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:GEMINI_MODEL` | 台本生成モデル | 移す | WP-R2-2 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NANOBANANA_PRO_MODEL` | 背景・サムネ生成（高品質） | 移す | WP-R2-9 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NANOBANANA_FLASH_MODEL` | 背景・サムネ生成（高速） | 移す | WP-R2-9 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_REIMU_SPEAKER_KEY` | ゆっくり霊夢風の内部speaker_key | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_MARISA_SPEAKER_KEY` | ゆっくり魔理沙風の内部speaker_key | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_REIMU_VOICE_TYPE` | AquesTalk側の霊夢風voice_type/phont指定 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AQUESTALK_MARISA_VOICE_TYPE` | AquesTalk側の魔理沙風voice_type/phont指定 | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTERS` | 旧版共通定数 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VIDEO_FPS` | 出力フレームレート | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:FFMPEG_BIN` | ffmpeg バイナリパス | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_FFMPEG_TIMEOUT_SEC` | nativeレンダーのffmpeg 1コマンド最大実行秒数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_FFPROBE_TIMEOUT_SEC` | nativeレンダーのffprobe 最大実行秒数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:THUMBNAIL_HOLD_FRAMES_SHORTS` | Shorts先頭サムネ保持フレーム数 | 移す | WP-R2-9 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ASSETS_DIR` | 同梱リソースの assets ディレクトリ | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_PNG_DIR` | キャラ PNG 格納ディレクトリ | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_PSD_DIR` | キャラ PSD 格納ディレクトリ | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ZUNDAMON_PSD_PATH` | ずんだもんPSD立ち絵 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:METAN_PSD_PATH` | 四国めたんPSD立ち絵 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:REIMU_CHARACTER_PNG_PATH` | 霊夢の立ち絵PNG | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:MARISA_CHARACTER_PNG_PATH` | 魔理沙の立ち絵PNG | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_PNGS` | 旧版共通定数 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:CHARACTER_EXPRESSION_PNGS` | 旧版共通定数 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:THUMBNAIL_CHARACTER_PNGS` | サムネイル生成時に使うキャラ画像 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_FFMPEG_ENCODER` | エンコーダ（NVENC / libx264 等） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_FFMPEG_PRESET` | エンコードプリセット | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_FFMPEG_CRF` | CRF 値（libx264 用） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_FFMPEG_CQ` | CQ 値（NVENC 用） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:DEVELOPER_TOOLS_ENABLED` | 開発者向けUI/APIの有効化（販売版は 0） | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:TRIAL_WATERMARK_TEXT` | Trial版MP4の右下に焼き込む透かし文字 | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:TRIAL_WATERMARK_FONT_SCALE` | 透かし文字サイズ（短辺に対する倍率） | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:TRIAL_WATERMARK_FONT_MIN_PX` | 透かし文字サイズの下限px | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_DOWNLOAD_URL` | VOICEVOX 公式ダウンロード | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:FFMPEG_DOWNLOAD_URL` | ffmpeg Windows ビルド配布 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OLLAMA_DOWNLOAD_URL` | Ollama 公式ダウンロード | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SD_WEBUI_DOWNLOAD_URL` | Stable Diffusion WebUI 配布 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:LICENSE_API_URL` | アクティベーションAPIのHTTPS URL（旧失効確認URLは自動転用しない） | やめる | WP-R5-4 | 対象なし（販売しない） |
| `config:LICENSE_LEASE_RENEW_BEFORE_DAYS` | 証明書期限の何日前から起動時に更新するか | やめる | WP-R5-4 | 対象なし（販売しない） |
| `config:LICENSE_API_TIMEOUT_SEC` | ライセンスAPIの通信タイムアウト秒数 | やめる | WP-R5-4 | 対象なし（販売しない） |
| `config:PRODUCT_PURCHASE_URL` | 購入ページURL（空=未設定。設定すると購入導線リンクを表示） | やめる | WP-R5-4 | 対象なし（販売しない） |
| `config:PRODUCT_SUPPORT_URL` | サポート/問い合わせページURL（空=非表示） | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:PRODUCT_SUPPORT_EMAIL` | サポート問い合わせメール（空=非表示） | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:PRODUCT_UPDATE_CHECK_URL` | 更新確認用JSONのURL（空=無効） | やめる | WP-R5-4 | 対象なし（販売しない） |
| `config:DISK_MIN_FREE_GB` | 生成/レンダー登録時に必要な最低空き容量(GB) | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_RENDER_CHARACTERS` | キャラ描画 有効/無効 | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_LIPSYNC` | リップシンク有効/無効 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_BLINK` | まばたき有効/無効 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_CHARACTER_HEIGHT_SHORTS` | Shorts: キャラ基本高さ (px) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_CHARACTER_HEIGHT_LONG` | Long: キャラ基本高さ (px) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS` | Shorts: 下マージン (px, 負=画面外下) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_CHARACTER_SIDE_MARGIN_SHORTS` | Shorts: 左右マージン (px, 負=画面外) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_CHARACTER_BOTTOM_MARGIN_LONG` | Long: 下マージン (px) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_CHARACTER_SIDE_MARGIN_LONG` | Long: 左右マージン (px, 負=画面外) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_BACKGROUND_TRANSITION` | トランジション種別（"fade" / "none"） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_BACKGROUND_TRANSITION_SEC` | フェード時間 (秒) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_MOTION_EFFECTS` | native Shorts の軽量演出全体 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_BG_KEN_BURNS` | 背景のゆっくりズーム/パン | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_CHARACTER_BOUNCE` | 話者開始時の軽いバウンス | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_TALK_WIGGLE` | 発話中の話者キャラ小刻み揺れ | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS` | 発話中小刻み揺れを何セリフに1回出すか（1=毎回） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_POP_TELOP` | テロップ行のポップ表示 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_ENABLE_SHAKE` | ツッコミ/驚き時の軽い画面揺れ | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_MAX_SHAKE_COUNT_SHORTS` | Shorts 1本あたりのシェイク最大回数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_MAX_ICON_COUNT_SHORTS` | Shorts 1本あたりの疑問/驚きアイコン最大回数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_REACTION_EFFECT_MIN_GAP_SEGMENTS` | シェイク/アイコンを再表示するまでの最低セリフ間隔 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_BG_ZOOM_MAX` | 背景Ken Burnsの最大拡大倍率 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_OFFSET_SEC` | 字幕の開始タイミング補正 (秒) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_FONT` | 字幕フォント名 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_FONT_SIZE_SHORTS` | Shorts: 基本フォントサイズ (px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_FONT_SIZE_LONG` | Long: 基本フォントサイズ (px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_FONT_SCALE` | フォントサイズ倍率（FONT_SIZE × FONT_SCALE が実際のサイズ） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_ALIGNMENT_SHORTS` | Shorts: ASS alignment（5=中央中段） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_ALIGNMENT_LONG` | Long: ASS alignment（2=中央下段） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_MARGIN_V_SHORTS` | Shorts: 縦マージン (px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_MARGIN_V_LONG` | Long: 縦マージン (px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_Y_OFFSET_SHORTS` | Shorts: 字幕 Y 追加オフセット (px)。height/2 + offset がテキスト中心 Y 座標 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_Y_OFFSET_LONG` | Long: 字幕 Y 追加オフセット (px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_STROKE_WIDTH` | 内フチ幅 (px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_OUTER_STROKE_WIDTH` | 外フチ幅 (px)。デフォルトは内フチ+4 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_PADDING_Y` | 字幕帯の上下パディング (px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_BOX_LINE_HEIGHT` | 字幕帯高さ = font_size × この値 + PADDING_Y×2 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_BOX_SHORTS` | Shorts: 半透明帯を表示するか | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_BOX_ALPHA` | 帯の不透明度 (0=透明 1=不透明) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_BOX_OPACITY_SHORTS` | 旧名エイリアス | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_WRAP_CHARS_SHORTS` | Shorts: 字幕の1行最大文字数（超えると折り返し） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SUBTITLE_WRAP_CHARS_LONG` | Long:   字幕の1行最大文字数 | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_CHANNEL_REMAKE_DATE` | チャンネルリメイク実稼働開始日（この日以前は旧チャンネル時代） | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_CHANNEL_LEGACY_NOTE` | 旧チャンネル時代の登録者に関する注記（AI分析・GUI表示用） | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_DISLIKE_RATE_MIN_REACTIONS` | dislike_rate を参考値と見なす likes+dislikes の下限 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_MIN_VIEWS_FOR_SCORE` | これ未満のviewsは配布不足・判定保留扱い（スコア非対象） | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_REACTION_MIN_LIKES` | 配布不足動画の「反応あり」判定：最低いいね数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_REACTION_STRONG_LIKE_RATE` | 配布不足動画の「反応強い」判定：最低高評価率(%) | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_REACTION_STRONG_MIN_LIKES` | 配布不足動画の「反応強い」判定：最低いいね数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_EXPANSION_MIN_VIEWS_SHORTS` | Shorts横展開候補の最低再生数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_EXPANSION_VIEWS_MULTIPLIER` | 同期間平均比で横展開候補にできる最低倍率 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_EXPANSION_MIN_AVG_PCT_SHORTS` | Shorts横展開候補の最低平均視聴率 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_EXPANSION_MIN_AVG_DURATION_SHORTS` | Shorts横展開候補の最低平均視聴時間秒数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_EXPANSION_MIN_LIKE_RATE` | 横展開候補で明確に高いと扱う最低高評価率 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_EXPANSION_MIN_PATTERN_COUNT` | 同じ構造で横展開候補に必要な適格動画数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_BL_MIN_VIEWS_SHORTS` | Shorts/ShortLong ブラックリスト判定の最低視聴数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_BL_MAX_AVG_PCT_SHORTS` | Shorts ブラックリスト判定の最大平均視聴率 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_BL_MIN_VIEWS_LONG` | Long ブラックリスト判定の最低視聴数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_BL_MAX_AVG_PCT_LONG` | Long ブラックリスト判定の最大平均視聴率 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_BL_MAX_CTR_LONG` | Long ブラックリスト判定の最大CTR（None の場合は無視） | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:ANALYTICS_BL_MAX_LIKE_RATE` | ブラックリスト判定の最大高評価率 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:TRANSITION_SEC` | 背景クロスフェード時間（秒） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICE_TAIL_SAFETY_SEC` | 音声WAV末尾の安全余裕（秒） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_INTER_DIALOGUE_GAP_SEC` | nativeレンダラーのセリフ間追加ギャップ（秒） | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:BGM_FILE` | 旧版共通定数 | 移す | WP-R2-5 / WP-R4-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:BGM_PATH` | 旧版共通定数 | 移す | WP-R2-5 / WP-R4-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:_OUTPUT_ANCHOR` | 出力の基準。exe(onefile)では exe と同じフォルダ・開発時はリポジトリルート | やめる | WP-R1-3 | 対象なし（旧版の内部キャッシュ・環境移行補助） |
| `config:OUTPUT_BASE_DIR` | 全プロファイル共通の出力ベース(各profile_idフォルダの親)。空=既定 output/ | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OUTPUT_DIR` | 旧版共通定数 | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OUTPUT_DATA_DIR` | 旧版共通定数 | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OUTPUT_ANALYTICS_DIR` | 旧版共通定数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:OUTPUT_LEGACY_DIR` | 旧版共通定数 | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:FOLDER_PREFIX_SHORTS` | 短動画フォルダプレフィックス | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:FOLDER_PREFIX_LONG` | 長動画フォルダプレフィックス | 移す | WP-R1-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:FOLDER_PREFIX_MEETING` | ネタ会議フォルダプレフィックス | 移す | WP-R2-2 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:_LEGACY_FOLDER_PREFIXES` | 旧版共通定数 | やめる | WP-R1-3 | 対象なし（旧版の内部キャッシュ・環境移行補助） |
| `config:LONG_THUMBNAIL_AB_TEST` | Long サムネ A/B テスト（OFF: A のみ生成） | 移す | WP-R2-9 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:LONG_UPLOAD_PLAYLIST_NAME` | Long アップロード後に自動追加する再生リスト名（空で無効） | 移す | WP-R3-4 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:PLAYLIST_CLASSIFIER_SCRIPT_CHARS` | 単体再生リスト判定でOllamaへ渡す台本本文の最大文字数 | 移す | WP-R3-4 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:TOPIC_REQUEST_CTA_EVERY_N` | Shorts新規/横展開のネタ募集CTAを許可する間隔（N本に1本、0で自動付与なし） | 移す | WP-R3-2 / WP-R3-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:UPLOAD_TIMEZONE` | 投稿予約スロットのタイムゾーン | 移す | WP-R5-2 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:SHORTS_UPLOAD_SLOT_HOURS` | Shorts投稿予約スロット時刻（時） | 移す | WP-R5-2 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:LONG_UPLOAD_SLOT_HOURS` | Long投稿予約スロット時刻（時、曜日共通） | 移す | WP-R5-2 / WP-R4-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:MAX_BACKGROUNDS_SHORTS` | Shorts: 最大背景枚数 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:MAX_BACKGROUNDS_LONG` | Long: 最大背景枚数（通常モード） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:MAX_BACKGROUNDS_LONG_BUDGET` | Long: 最大背景枚数（節約モード） | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_APP_NAME` | Web UI の表示アプリ名 | 移す | WP-R4-1 / WP-R4-2 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_UI_HOST` | バインドホスト（外部公開禁止） | やめる | WP-R4-1 | 対象なし（HTTP常駐・販売識別を廃止） |
| `config:WEB_UI_PORT` | ポート番号（他アプリと競合しにくい高番号） | やめる | WP-R4-1 | 対象なし（HTTP常駐・販売識別を廃止） |
| `config:WEB_AUTO_OPEN_BROWSER` | 起動時にブラウザを自動で開くか（既定ON。CLIの--open-browser/--no-open-browserで上書き可） | やめる | WP-R4-1 | 対象なし（HTTP常駐・販売識別を廃止） |
| `config:WEB_DEFAULT_IMAGE_STYLE` | Web UI の既定画像スタイル | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_IMAGE_STYLE_CHOICES` | Web UI 画像スタイル選択肢 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_DEFAULT_REUSE_BACKGROUNDS` | Web UI 生成時の背景再利用既定値 | 移す | WP-R2-8 / WP-R4-5 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST` | Web UI 生成時のLongサムネAB既定値 | 移す | WP-R2-9 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_DEFAULT_LONG_BUDGET_MODE` | Web UI 生成時のLong節約既定値 | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_JOB_POLL_INTERVAL_MS` | Web UI のジョブポーリング間隔(ms) | やめる | WP-R4-1 | 対象なし（HTTP常駐・販売識別を廃止） |
| `config:WEB_LOG_POLL_INTERVAL_MS` | ログ画面(/logs)のポーリング間隔(ms)。既定30秒。テキスト選択中は更新を止め、デバッグログを上へスクロール中は表示位置を維持する | やめる | WP-R4-1 | 対象なし（HTTP常駐・販売識別を廃止） |
| `config:WEB_SUCCESS_RELOAD_DELAY_MS` | Web UI ジョブ成功後の再読み込み待ち時間(ms) | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_TOAST_VISIBLE_MS` | Web UI トースト表示時間(ms) | 移す | WP-R4-1 / WP-R4-2 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_TOAST_HIDE_DELAY_MS` | Web UI トースト非表示待ち時間(ms) | 移す | WP-R4-1 / WP-R4-2 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_VOICEVOX_CHECK_TIMEOUT_SEC` | Web UI のVOICEVOX疎通確認タイムアウト(秒) | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:WEB_FFMPEG_CHECK_TIMEOUT_SEC` | Web UI のffmpeg疎通確認タイムアウト(秒) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:DEBUG_LOG_ENABLED` | デバッグログ出力の有効/無効 | 移す | WP-R0-3 / WP-R0-5 / WP-R4-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:DEBUG_LOG_DIR` | デバッグログ保存ディレクトリ | 移す | WP-R0-3 / WP-R0-5 / WP-R4-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:DEBUG_LOG_RETENTION_DAYS` | デバッグログ保持日数 | 移す | WP-R3-6 / WP-R4-8 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:DEBUG_LOG_LEVEL` | デバッグログ出力レベル | 移す | WP-R0-3 / WP-R0-5 / WP-R4-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:DEBUG_LOG_VIEW_LINES` | Web UIログ画面に表示する最大行数 | 移す | WP-R0-3 / WP-R0-5 / WP-R4-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_CONNECTION_TIMEOUT_SEC` | VOICEVOX接続確認タイムアウト（秒） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_QUERY_TIMEOUT_SEC` | VOICEVOXクエリ生成タイムアウト（秒） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:VOICEVOX_SYNTHESIS_TIMEOUT_SEC` | VOICEVOX音声合成タイムアウト（秒） | 移す | WP-R2-3 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHAKE_AMP_X` | 画面シェイクの水平方向振幅(px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_SHAKE_AMP_Y` | 画面シェイクの垂直方向振幅(px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_CHARACTER_BOUNCE_SEC` | キャラクターバウンス演出時間(秒) | 移す | WP-R1-5 / WP-R2-6 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_TALK_WIGGLE_X_PX` | 発話中キャラ揺れの左右振幅(px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_TALK_WIGGLE_Y_PX` | 発話中キャラ揺れの上下振幅(px) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_TALK_WIGGLE_HZ` | 発話中キャラ揺れの周波数(Hz) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_TELOP_POP_START_SEC` | ポップテロップの表示開始ディレイ(秒) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:NATIVE_TELOP_POP_MAX_SEC` | ポップテロップの最大表示持続時間(秒) | 移す | WP-R2-4 / WP-R2-7 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:AUTO_FIXED_COMMENT_PROFILE_SCOPE` | OSタスク自動投稿の対象（active / all） | 移す | WP-R3-4 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_LOG_MAX_JOBS` | 保持する最大ジョブ件数 | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_MAX_CONCURRENT_WORKERS` | job-runner の同時実行数。既定1=直列実行。2以上で生成・レンダーを並列処理する | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_RUNNER_EXECUTOR_CAPACITY` | job-runner が内部で確保する最大スレッド数。JOB_MAX_CONCURRENT_WORKERS の上限 | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_RUNNER_POLL_INTERVAL_SEC` | job-runner が queued/cancel を確認する間隔(秒) | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_RUNNER_HEARTBEAT_INTERVAL_SEC` | job-runner が実行中ジョブの生存時刻を更新する間隔(秒) | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC` | heartbeat が途絶えた running ジョブを failed 化するまでの秒数 | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_LOG_FLUSH_INTERVAL_SEC` | runner がジョブログを DB へまとめ書きする間隔(秒) | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |
| `config:JOB_LOG_MAX_ENTRIES` | 1ジョブが保持するログ行の上限。超過分は古い行から破棄し logs_json 肥大と再書込コストを抑える | 移す | WP-R2-10 / WP-R4-9 | app_settings / channel_settings（型付き設定。秘密値はsecrets） |

## 旧DBから新DBへの写像

| 識別子 | 対象 | 判断 | 担当WP | 移行先・理由 |
|---|---|---|---|---|
| `db:core/autopilot_store.py#autopilot_runs` | autopilot_runs | 移す | WP-R1-4 | jobs / job_steps / notifications（履歴。再実行しない） |
| `db:core/autopilot_store.py#autopilot_usage` | autopilot_usage | 移す | WP-R1-3 | cost_ledger（旧件数はunits_json。金額を捏造しない） |
| `db:core/bgm_store.py#bgm_assets` | bgm_assets | 移す | WP-R1-3 | assets / asset_refs / asset_licenses / music_tags |
| `db:core/channel_profile.py#channel_profiles` | channel_profiles | 移す | WP-R1-3 | channels / channel_settings |
| `db:core/channel_schedule.py#channel_schedule_settings` | channel_schedule_settings | 移す | WP-R1-3 | schedule_slots |
| `db:core/channel_schedule.py#channel_schedule_migrations` | channel_schedule_migrations | やめる | WP-R1-3 | 対象なし（旧移行履歴。取り込み結果はaudit_log） |
| `db:core/character_profile_store.py#character_profiles` | character_profiles | 移す | WP-R1-3 / WP-R1-5 | characters / assets |
| `db:core/metadata_db.py#schema_version` | schema_version | 作り直す | WP-R1-2 | schema_migrations（旧版番号は引き継がない） |
| `db:core/metadata_db.py#videos` | videos | 移す | WP-R1-4 | projects / project_revisions / scenes / lines / assets / asset_refs |
| `db:core/metadata_db.py#video_metadata` | video_metadata | 移す | WP-R1-4 | projects / project_revisions |
| `db:core/metadata_db.py#youtube_status` | youtube_status | 移す | WP-R1-4 | uploads / youtube_videos / project_revisions（固定コメント状態） |
| `db:core/metadata_db.py#analytics_snapshots` | analytics_snapshots | 移す | WP-R1-4 | analytics_daily（同日の最新値）/ project_revisions（原記録） |
| `db:core/metadata_db.py#playlists` | playlists | 移す | WP-R1-4 | project_revisions（再生リスト登録状態） |
| `db:core/metadata_db.py#topic_history` | topic_history | 移す | WP-R1-4 | topics |
| `db:core/metadata_db.py#script_quality` | script_quality | 移す | WP-R1-4 | qa_results / project_revisions |
| `db:core/metadata_db.py#render_info` | render_info | 移す | WP-R1-4 | project_revisions / job_steps |
| `db:core/metadata_db.py#image_replacements` | image_replacements | 移す | WP-R1-4 | project_revisions / assets / asset_refs |
| `db:core/metadata_db.py#jobs` | jobs | 移す | WP-R1-4 | jobs / job_steps（放置中は履歴扱い。再実行しない） |
| `db:core/metadata_db.py#image_generation_failures` | image_generation_failures | 移す | WP-R1-4 | job_steps / notifications |
| `db:core/prompt_template_store.py#prompt_templates` | prompt_templates | 移す | WP-R1-3 | prompt_templates / prompt_template_versions（初版） |
| `db:core/reading_dictionary_store.py#reading_dictionary_entries` | reading_dictionary_entries | 移す | WP-R1-3 | reading_entries |
| `db:core/reading_dictionary_store.py#reading_candidates` | reading_candidates | 移す | WP-R1-3 | reading_candidates |
| `db:core/reading_dictionary_store.py#reading_dictionary_seed_state` | reading_dictionary_seed_state | 作り直す | WP-R1-3 | app_settings（seed適用版） |
| `db:core/secret_store.py#encrypted_secrets` | encrypted_secrets | 移す | WP-R1-3 | secrets（復号後、新AADで再暗号化） |
| `db:core/settings_store.py#settings` | settings | 移す | WP-R1-3 | app_settings / channel_settings |

