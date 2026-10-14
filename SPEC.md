# Native Video Factory 仕様書

対象: 複数YouTubeチャンネル共通
最終更新: 2026-06-03

---

## 概要

複数のYouTubeチャンネル向けに、台本生成・VOICEVOX音声・画像生成・native MP4・YouTubeアップロード・Analytics確認までを行うローカルWebツール。チャンネルごとの設定は channel profile で管理し、Web UI上でいつでも切り替えられる。

- **台本生成** → Gemini AI
- **音声生成** → VOICEVOX (ずんだもん / 四国めたん)（よみがな正規化を SudachiPy + 自前辞書で前処理）
- **背景画像生成** → Nano Banana (Gemini画像生成) / Stable Diffusion WebUI（`IMAGE_BACKEND` で切替）
- **サムネイル生成** → Nano Banana (Gemini画像生成) / Stable Diffusion WebUI（`IMAGE_BACKEND` で切替）
- **動画組立** → ffmpeg/native MP4
- **品質レビュー** → ローカルルール + Ollama LLM + ChatGPT
- **アップロード** → YouTube Data API v3

---

## 📑 目次

> [!NOTE]
> 操作手順は **[MANUAL.md](MANUAL.md)**、セットアップ・起動は **[README.md](README.md)** を参照。本書は仕様の正本。

**全体像**
- [概要](#概要) ／ [バージョン表示](#バージョン表示) ／ [システム構成](#システム構成)

**生成パイプライン**
- [動画フォーマット](#動画フォーマット)（Shorts / Long / ネタ会議）
- [動画生成パイプライン](#動画生成パイプライン-workersmainpy-runpipeline)（`run_pipeline` 全体フロー・尺推定・背景再利用・IMAGE_BACKEND）
- [品質レビュー](#品質レビュー-coreopeningqualitypy)（冒頭3段階・中止条件・ChatGPT）／ [Ollamaレビュースキーマ](#ollamaレビュースキーマ)
- [よみがな正規化](#よみがな正規化-corereadingnormalizerpy)／ [VOICEVOX音声生成](#voicevox音声生成-corevoicevoxpy)
- [ffmpeg ネイティブレンダラー](#ffmpeg-ネイティブレンダラー-corenativerendererpy-本番レンダラー)（本番レンダラー）
- [Long動画専用機能](#long動画専用機能)／ [CTA/Long動画の運用ポリシー](#-ctalong動画の運用ポリシー)

**台本**
- [台本フォーマット](#台本フォーマット)（記法一覧・例）／ [台本作成ルール](#台本作成ルール)

**Web UI・運用**
- [ローカル Web UI](#ローカル-web-ui-webapp)（FastAPI構成・ジョブ管理・キュー・画面・**API概要**・セキュリティ）
- [製品版MVP機能](#製品版mvp機能)
- [アップロードスケジューラー](#アップロードスケジューラー-coreuploadschedulerpy)／ [CTA / 導線制御](#cta-導線制御)
- [操作手順](#操作手順)

**設定・データ・基盤**
- [設定 (`config/config.py`)](#設定-configconfigpy)（全環境変数一覧）
- [出力ファイル構成](#出力ファイル構成)／ [レイヤー構成](#レイヤー構成)／ [立ち絵テンプレート](#立ち絵テンプレート)
- [外部サービス依存](#外部サービス依存)／ [チャンネルプロファイル管理](#チャンネルプロファイル管理複数チャンネル対応)
- [DB アーキテクチャ](#db-アーキテクチャ)（全テーブル定義・スキーマ版・主要関数）

---

## バージョン表示

- アプリのタイトルバーにはGitのコミット数・短縮ハッシュを自動表示する。未コミット変更がある場合は `dirty` を付ける。

---

## システム構成

```
yukkurijidou/
├── web_app/                # ローカル Web UI (FastAPI)
│   ├── app.py              # FastAPI エントリポイント (通常起動はOS別起動スクリプト推奨)
│   ├── job_manager.py      # DB queue ジョブ登録・参照
│   ├── schemas.py          # Pydantic リクエスト/レスポンススキーマ
│   ├── security.py         # パストラバーサル対策・output/配下制限
│   ├── services/           # ビジネスロジック層
│   │   ├── status_service.py       # 設定診断・ダッシュボード状態
│   │   ├── config_service.py       # Web UIから編集できる非秘密設定
│   │   ├── secrets_service.py      # 認証情報の DB 暗号化保存・削除
│   │   ├── history_service.py      # 生成履歴一覧・詳細
│   │   ├── generation_service.py   # 動画生成ジョブ
│   │   ├── script_check_service.py # LLM/尺チェックジョブ
│   │   ├── image_service.py        # 画像確認・再生成
│   │   ├── prompt_service.py       # 台本/タイトルプロンプト生成
│   │   ├── render_service.py       # 履歴MP4再レンダー
│   │   ├── analytics_service.py    # Analytics取得・表示
│   │   ├── schedule_service.py     # スケジュール管理
│   │   ├── upload_service.py       # YouTubeアップロード
│   │   ├── fixed_comment_service.py # 固定コメント投稿
│   │   ├── auto_fixed_comment_service.py # OSタスクから実行する固定コメント一括投稿（前回結果を記録）
│   │   └── sd_model_service.py    # Stable Diffusion WebUI モデル管理 Web UIサービス
│   ├── routes/             # APIルート層
│   │   ├── pages.py        # Jinja2ページルート
│   │   ├── api_status.py   # GET /api/health, /api/status, /api/dashboard
│   │   ├── api_jobs.py     # GET/POST /api/jobs
│   │   ├── api_history.py  # GET /api/history
│   │   ├── api_generate.py # POST /api/generate
│   │   ├── api_check.py    # POST /api/check
│   │   ├── api_images.py   # GET/POST /api/images
│   │   ├── api_analytics.py # GET/POST /api/analytics
│   │   ├── api_schedule.py  # GET/POST /api/schedule
│   │   ├── api_upload.py    # GET/POST /api/upload
│   │   ├── api_fixed_comment.py # GET/POST /api/fixed-comment
│   │   ├── api_prompt.py   # GET /api/prompt
│   │   ├── api_settings.py # GET/POST /api/settings
│   │   └── api_sd_models.py # GET/POST /api/sd-models
│   ├── templates/          # Jinja2 HTMLテンプレート
│   └── static/             # CSS/JS (app.css, app.js)
├── workers/
│   ├── main.py             # 動画生成パイプライン
│   ├── pipeline_helpers.py # 台本形式判定・素材ファイル整理などの共通補助処理
│   ├── pipeline_metadata.py # 説明文・タグ・音声クレジット整形
│   ├── pipeline_models.py  # 生成結果モデル・Long用バリアント定義
│   └── runner.py           # DB queue から生成・レンダージョブを実行する常駐 runner
├── core/
│   ├── ai_generator.py     # 台本・タイトルA/B/C案生成（text_llm 経由）
│   ├── text_llm.py         # 文章生成AIの窓口（Gemini / Claude Code CLI / Codex CLI / Ollama）
│   ├── comfyui_generator.py # ComfyUI（ローカル・Krea 2 Turbo）画像生成
│   ├── codex_image.py      # Codex CLI の画像生成（ChatGPT の使用枠）
│   ├── local_image_compose.py # ローカル画像の文字入れ・サムネの立ち絵合成
│   ├── voicevox.py         # VOICEVOX音声生成
│   ├── reading_normalizer.py # よみがな正規化（Ollama）
│   ├── image_generator.py  # 背景・サムネ画像生成（IMAGE_BACKEND に基づきバックエンドを選択）
│   ├── sd_webui_generator.py  # Stable Diffusion WebUI / A1111互換APIクライアント
│   ├── sd_model_manager.py    # Stable Diffusion WebUI モデルのインストール確認・ダウンロード
│   ├── parser.py           # 台本パーサー (ScriptParser)
│   ├── native_renderer.py  # ffmpeg/native MP4レンダラー
│   ├── opening_quality.py  # 冒頭品質レビュー
│   ├── script_prompts.py   # 台本生成プロンプト組み立て（DB テンプレートから読む）
│   ├── prompt_template_store.py  # prompt_templates テーブル CRUD
│   ├── prompt_template_seeder.py # genres/ ファイルから DB へ初期投入
│   ├── analytics_score.py  # YouTube Analytics評価・TSV保存
│   ├── youtube_analytics.py # YouTube Analytics API取得（維持率取得含む）
│   ├── retention_analysis.py # 視聴者維持率の離脱・ループ点分析
│   ├── comment_templates.py # 固定コメント自動生成テンプレート（めたん調）
│   ├── fixed_comment_task.py # 固定コメント投稿のOSタスク登録（Win=タスクスケジューラ/Mac=launchd・アプリ非起動でも投稿）
│   ├── upload_scheduler.py # YouTube Data API とチャンネル別設定を正とするアップロードスケジュール管理
│   ├── upload_records.py   # metadata.db の youtube_status + render_info からアップロード記録を構築
│   ├── output_paths.py     # 出力パスの集約・マイグレーション
│   ├── youtube_uploader.py # YouTube APIアップロード
│   ├── playlist_resolver.py # 台本カテゴリ名＋動画形式 → YouTube再生リスト名の解決。`resolve_video_type(video_format, screen_format)` でネタ会議を含む全動画形式を "shorts"/"long" に統一判定する関数も提供
│   ├── app_shutdown.py     # アプリ終了管理（shutdown hookの登録・実行・uvicorn.Server参照管理）
│   ├── metadata_db.py      # SQLite メタデータDB（スキーマ定義・upsert/query 関数群）
│   ├── settings_store.py   # SQLite 設定DB（data/settings.db の読み書き・.env 移行）
│   ├── secret_store.py     # 認証情報の暗号化保存（AES-GCM + DPAPI/keyring マスターキー）
│   └── ng_words.py         # NGワード置換
├── config/
│   ├── config.py            # 定数・設定
│   ├── requirements.txt
│   └── prompt_profiles/
│       └── genres/          # ジャンル別プロンプトファイル（seed 用）
│           ├── food_trivia/
│           ├── urban_legend/
│           ├── zundamon_kowai/
│           └── zunkami/
└── output/                 # 生成物出力先
```

プロンプトテンプレートは `data/settings.db` の `prompt_templates` テーブルで管理する（DB が正本）。実行時は DB から読む。`config/prompt_profiles/genres/{genre_profile}/` は起動時 seed 専用。

### キャラクター設定の分離（character_profiles）

キャラクター設定（役割・口調・禁止台詞・掛け合い構造）は台本テンプレートから分離し、`data/settings.db` の `character_profiles` テーブルで channel 別に管理する（`core/character_profile_store.py`）。

- **責務分離**: 台本テンプレート（`prompt_templates.script_rules`）には動画構成・尺・シーン構造・分量・出力形式だけを書く。キャラの役割・口調・禁止表現・掛け合いは `character_profiles` に書く。テンプレートにキャラ設定を直書きしない／キャラ設定に尺・行数・シーン構造を書かない。
- **テーブル列**: `character_id` / `profile_id`（channel）/ `character_key` / `display_name` / `character_name` / `role` / `tone_style` / `speaking_rules` / `forbidden_phrases` / `dialogue_rules` / `voice_backend` / `voice_speaker` / `voice_speaker_id` / `voice_styles_json` / `voice_type` / `voice_speed` / `voice_pitch` / `voice_volume` / `portrait_png_path` / `credit_required` / `credit_text` / `enabled` / `sort_order` / `created_at` / `updated_at`。
- **合成順**: 生成時に `compose_character_section(profile_id)` が enabled のキャラを `sort_order` 順に合成し、台本プロンプトへ「キャラクター設定（最優先・厳守）」セクションとして注入する（`build_gemini_system_prompt` / `build_script_generation_prompt`）。合成は **script のみ**。ネタ会議（meeting）には注入しない。
- **チャンネル別の既定**: 食べ物雑学堂（genre `zunkami` / `food_trivia`）は四国めたんを「辛口相方ツッコミ（ずんだハウス風）」（`metan_food_toxic`）にする。都市伝説（`zundamon_kowai`）は従来の「お嬢様毒舌めたん」（`metan_standard_toxic`）。別チャンネルのキャラ設定を流用しない（`profile_id` で厳密分離）。
- **同名キャラの排他有効化**: `enabled=true` にする時は、同一 `profile_id` かつ同一 `character_name` の他キャラ設定を自動で `enabled=false` にする。四国めたんの辛口相方版とお嬢様毒舌版が同時にプロンプトへ混ざる事故を防ぐ。
- **管理画面**: 設定画面「キャラクター設定」タブで active channel のキャラ設定を一覧・追加・編集・削除できる。役割・口調に加えて、音声バックエンド、話者ID/キー、表情別話者ID（JSON）、AquesTalk用 `voice_type/phont`、速度・高さ・音量、立ち絵PNG参照、クレジット要否、クレジット表記も編集できる。削除は確認ダイアログと `confirmed=true` 必須。画面上の有効トグルは保存後に一覧を再読み込みし、同名キャラの排他状態を即時反映する。
- **追加キャラ**: seed は `ずんだもん` / `四国めたん` に加え、無効状態の `ゆっくり霊夢風` / `ゆっくり魔理沙風` を追補する。新規キャラは `character_name` を台本の話者名と一致させ、`voice_backend` と `portrait_png_path` を登録すれば台本生成プロンプトと native 立ち絵解決の対象になる。同梱立ち絵は `asset:assets/characters/reimu.png` のような `asset:` 参照で保存し、実行時に `resource_base_dir()` 基準で解決する。アプリ配下の絶対パスは保存時に相対参照へ正規化し、外部ドライブ等の任意素材だけ絶対パスを許可する。台本話者名 `霊夢` / `ゆっくり霊夢` / `reimu` は `霊夢`、`魔理沙` / `ゆっくり魔理沙` / `marisa` は `魔理沙` として音声設定を解決する。
- **音声バックエンド**: `voice_backend=voicevox` の場合は `voice_speaker` または `voice_speaker_id` を VOICEVOX speaker ID として使い、`voice_styles_json` に `{"怒り": 9}` のような表情/スタイル別IDを持てる。`voice_backend=aquestalk` の場合は `voice_speaker` を内部speaker_key、`voice_type` をAquesTalk側の voice_type/phont 指定として扱い、`voice_speed` / `voice_pitch` / `voice_volume` を生成コマンドへ渡す。未対応バックエンド名は明示エラーで停止する。
- **AquesTalk設定**: `AQUESTALK_ENABLED` / `AQUESTALK_ENGINE_PATH` / `AQUESTALK_LICENSE_CONFIRMED` / `AQUESTALK_COMMAND_TEMPLATE` / `AQUESTALK_DEFAULT_SPEED` / `AQUESTALK_DEFAULT_PITCH` / `AQUESTALK_DEFAULT_VOLUME` / `AQUESTALK_TIMEOUT_SEC` を設定DBで管理する。`AQUESTALK_ENGINE_PATH` は相対パスなら `app_base_dir()` 基準で解決し、アプリ配下の絶対パスは保存時に相対化する。ライセンスキーは `encrypted_secrets:aquestalk_license_key` に暗号化保存し、レスポンス・ログには値を出さない。`AQUESTALK_COMMAND_TEMPLATE` は `{engine}` / `{text}` / `{output}` / `{voice}` / `{speaker}` / `{speed}` / `{pitch}` / `{volume}` / `{license_key}` を展開して実行する。
- **必要クレジット**: 説明文末尾の「使用音声合成」は、台本で実際に発話したキャラの `credit_required` / `credit_text` から組み立てる。`credit_required=false` のキャラは表示しない。`credit_text` が空なら `voice_backend` と `character_name` から既定表記を作る。
- **自動フォールバック禁止**: 有効なキャラ設定が無いチャンネルは `compose_character_section()` が例外を送出する（標準めたんへ勝手に戻さない）。
- **移行**: 起動時 `ensure_character_profiles_all()` が既存チャンネルにキャラ設定を保証し、`migrate_strip_character_rules_from_templates()` が旧テンプレートに直書きされたキャラ設定の長文（旧 `METAN_TSUNDERE_RULES`）を除去する（マーカー検出・冪等）。
- 共通定数 `METAN_TSUNDERE_RULES`（`core/script_prompts.py`）は **ネタ会議プロンプトのみ**で使用する（script 側はキャラ設定へ移行済み）。

---

## 動画フォーマット

### Shorts
- 尺: **38〜50秒（理想）/ 35〜55秒（許容）**
- セリフ数: **24〜27行を基本**（22〜28行は許容、31行以上禁止）
- セリフ本文の文字数: **280〜330文字を目標 / 260文字未満は禁止**（背景・テロップ・メタ情報は含めない。21行・190文字前後はnative実尺で短くなりやすい）
- 1セリフ: **原則11〜15文字 / 平均11.5文字以上**（10文字以下は最大4行、7文字以下は原則禁止）
- 尺計算式（native）: `各セリフ本文の文字数 ÷ (5.4 × 音声速度) + 0.1 × 音声速度 = 推定尺`
- 背景枚数: 6〜9枚（Shorts背景は下半分をキャラ立ち絵・字幕用に余白として空ける。食べ物・図解・重要テキストは画面上半分〜中央上寄せに配置。各背景プロンプトに「画面下半分はキャラ立ち絵用に余白を広く空ける。」を必ず含める）
- 再生速度（native）: イントロ1.40x / 本編1.25x
- アップロードスロット: 毎日 21:00 (Asia/Tokyo)

### Long
- 尺: **5〜10分（理想5〜8分）**
- セリフ数: 150〜250行
- 背景枚数: 5〜7秒に1枚（同一背景10秒以上禁止）
- 再生速度（native）: イントロ1.40x / 本編1.20x
- アップロードスロット: 毎日 22:00 (Asia/Tokyo)

### 四国めたん 役割固定ルール（キャラクター設定で管理）

四国めたんは **解説役でも相槌役でも共同解説者でもない**。情報・理由・答え・背景・結論は基本ずんだもんが出し、めたんは視聴者目線の疑問・違和感・浅さ・既知ネタ臭・構成の弱さを突っ込んでずんだもんから次の情報を引き出す。役割・口調・禁止表現は `character_profiles`（上記「キャラクター設定の分離」）で channel 別に管理する。

**役割分担（共通）**:
- ずんだもん: 事実を出す / 理由を説明する / 今との違い・具体例・結論を出す
- めたん: 説明の浅さに突っ込む / 既知ネタ臭を指摘 / 視聴者の疑問を投げる / 構成の弱さを刺す / 次の情報を要求 / 短く雑に流す（情報は説明しない）

**チャンネル別の口調**:
- 食べ物雑学堂（`zunkami`）= `metan_food_toxic`: 「辛口相方ツッコミ（ずんだハウス風）」。「ですわ」連発禁止・お嬢様口調に寄せない。「あんた」「〜じゃん」「〜だろ」「〜でしょ」「〜なのよ」「〜わね」「〜しなさい」可。1文〜短い2文で切る。呆れ・雑な流し・冷たい一言も混ぜる。
  - 禁止: 「そうですわね」「なるほどですわ」「補足すると〇〇ですわ」「理由は〇〇ですわ」「実は〇〇なのよ」「知らなかったですわ」「えっ、そうなの？」などの復唱・同意・説明・驚きだけの単独使用。
- 怪談・都市伝説（`zundamon_kowai`）= `metan_kaidan_viewer`: 視聴者目線の疑問・怖がり・違和感・現実的ツッコミ役。怪談の情報や答えは説明せず、ずんだもんの説明を復唱しない。

**共通の必須条件**: めたんの各セリフは「疑問・反論・毒舌・皮肉・違和感・次の情報要求」のいずれかを含める。ただの相槌・情報補足・解説肩代わりは禁止。情報密度を保ち、掛け合いは必ず情報を前に進める（Shorts1本に「意外性」「理由」「今とのつながり」を入れる）。

### 説明密度・掛け合い品質ルール

通常Shorts / Longは「掛け合い」ではなく「説明コンテンツ」として生成する。会話は情報量・理解・疑問解消・展開整理のためだけに使う。

- ずんだもんが事実・理由・背景・経緯・具体例・結論を担当し、2〜5行連続で説明してよい。
- めたんは説明・補足・相槌を担当せず、視聴者目線の疑問、違和感、既知ネタ臭、説明の浅さ、タイトルや構成の弱さを必要な時だけ突く。
- 機械的な交互会話、意味のない相槌・復唱・同意、驚きだけの行、3往復以上情報が増えない押し問答は禁止。
- Shortsは24〜27セリフ、本文280〜330文字、平均11.5文字以上、10文字以下4行以内を維持し、中盤に最低3つの具体情報を入れる。
- Longは章ごとに説明ブロックを作り、各章に背景・経緯・具体例・現代とのつながりのいずれかを入れる。
- タイトルや導入を毎回「〇〇の理由」へ寄せず、結論や強い違和感から自然に始めてよい。
- 毒舌の対象は弱い構成、薄い説明、既知ネタ臭、甘い導入、チャンネル自虐に限定し、視聴者・実在人物・地域・文化を攻撃しない。

**食べ物雑学**: 名前、昔の扱い、価値の逆転、勘違い、製法、容器、包装、商品開発、海外との違いから複数を説明し、「実は〇〇だった」で止めず、なぜそうなったかまで扱う。

**怪談・都市伝説**: 「怖い」「ゾッとする」で止めず、時代、場所、怪異の設定、目撃談の型、噂の広まり方、学校・地域・ネット文化の背景から複数を説明する。実話・危険・呪いを断定せず、「実話として語られている」「真偽は不明」「怪談として広まった」など記録と噂を区別する。
**毒舌NG対象（絶対禁止）**: 視聴者への侮辱・食べ物そのものへの罵倒・国/地域/文化批判・特定企業/人物攻撃・人格否定・差別的発言。

### ネタ会議 (Idea Meeting / ShortLong)
- 尺: **2〜4分程度**（ShortLong / ミニ番組枠）
- 次回の制作に向けた候補ネタ（4〜5個）をずんだもんと四国めたんが会議する「制作会議コント」
- めたんは辛口査定役として強めに動く。「その入り、弱いわ」「はいスワイプ。次」のように企画・タイトル・出し方を辛口で査定する。本気の人格否定にはしない
- `動画形式: ネタ会議` などの記述でミニ番組として解釈される（Shortsの判定からは外れる）
- バリアント: `ネタ会議Long` → 横画面 (1920×1080)、`ネタ会議Shorts` または `ネタ会議`（デフォルト）→ 縦画面 (1080×1920)。`画面形式: 横` でも横判定
- `render_native_test` が呼ばれる際、フォルダ名 `ネタ会議_...` は `_video_size` で上記バリアントを台本から再判定して解像度を決定する
- プレミア公開や視聴者への投票（コメントやアンケート）を前提とする
- 候補ネタなどの管理データは `metadata.db` に保存し、ローカルメタファイルを正本にしない
- ネタ会議モードでは、第1部の候補一覧に実績根拠として具体数値を保存するが、第2部の本編台本では再生数・平均視聴率・高評価数・コメント数などの具体数値を読み上げない。本編では「前に反応がよかった」「手応えがあった」「関心を持たれやすい」など、視聴者向けの自然な表現へ変換する。
- 候補選定において、既存タイトルと同一主語・切り口の重複を避け、再挑戦候補は最大1個とし、未使用食材を3つ以上含めるようプロンプトで厳格に制御している。
- **ネタ会議にも適用する標準ルール**: めたんは辛口編集者・毒舌ツッコミ役として固定（相槌禁止セリフ: 「なるほどですわ」「そうなんですの」「驚きですわ」等の単独使用禁止）。動画タイトルを0〜100点で内部採点し78点未満は出力禁止。TOP5汎用ワード（実は/意外な/驚き/知らなかった/衝撃）のタイトル単独使用禁止。本編セリフへの感情タグ必須。

---

## 動画生成パイプライン (`workers/main.py: run_pipeline`)

### 全体フロー

```
1. 出力ディレクトリ準備
2. 台本本文を `metadata.db:videos.script_content` へ先行保存
3. 台本パース (ScriptParser)
4. メタデータ抽出 (タイトル / サムネ文字 / 説明文 / タグ / 固定コメント)
5. 冒頭品質レビュー
   ├── ローカルルールベース
   ├── Ollamaレビュー（スコア<70または重大エラーありの場合）
   └── 必要に応じてOllamaリライト → 再パース
6. 冒頭スコアが重大エラー基準未満、または `must_fix` ありなら処理中止 (デフォルト70点)
7. 生成前の尺推定 + 尺レビュー
8. ChatGPT生成前レビュー（評価のみ、修正なし）
   └── `must_fix` あり、または重大エラー基準未満なら処理中止
9. よみがな正規化（SudachiPy + 自前辞書で補正）
   └── 変換後テキストをVOICEVOXに渡す。字幕・ファイル名は元テキストのまま
10. VOICEVOX音声生成（セリフ1行ずつ）
11. サムネイル生成（Nano Banana または Stable Diffusion WebUI）
12. 背景画像生成（Nano Banana または Stable Diffusion WebUI）
   └── 再利用チェック: 台本変更で枚数が変わる場合は全再生成
13. 素材タイミングを組立
14. BGM追加
15. native MP4出力
16. 実尺レビュー + 完了レポート
```

### 尺推定（native基準）

```python
CHARS_PER_SEC_AT_1X = NATIVE_SHORTS_ESTIMATE_BASE_CPS  # 既定 5.4
INTRO_SPEED = NATIVE_SHORTS_INTRO_VOICE_SPEED          # 既定 1.40
BODY_SPEED = NATIVE_SHORTS_BODY_VOICE_SPEED            # 既定 1.25
INTRO_LINES = VOICE_INTRO_FAST_LINES                   # 既定 3行

elapsed = 0.0
for idx, item in enumerate(dialogue_items):
    chars = len(item["text"])
    speed = INTRO_SPEED if idx < INTRO_LINES else BODY_SPEED
    line_time = chars / (CHARS_PER_SEC_AT_1X * speed) + 0.1 * speed
    elapsed += line_time
```

### 背景・音声の再利用ロジック

- **背景再利用**（履歴詳細「背景を再利用する」/ `reuse_backgrounds`）: 再生成時、退避済みバックアップの `bg_*.png` と `thumbnails/*.png` を復元して使い回し、背景は未生成分だけ生成する。`thumbnail.png` が復元できた場合はサムネイル生成もスキップする。
- **音声再利用**（履歴詳細「音声を再利用する」/ `reuse_audio`、既定OFF）: 再生成時、退避済みバックアップの `audio/*.wav` を復元し、**同じ台本でファイル名が一致する音声は VOICEVOX 合成をスキップ**して使い回す（変わった行だけ再合成）。音声の再生成コスト・時間を節約できる。台本変更で不要になった旧WAV（孤児）は `_cleanup_orphan_audio()` で削除し、字幕数とWAV数の不一致を防ぐ。
- **台本変更により必要な背景枚数が変わった場合**: 既存の背景（サムネ除く）を全削除して再生成。音声もファイル名が変わるため一致しない分は再合成される。
- 503混雑などで一部背景が未生成のまま終わった場合は、履歴詳細の「⚠ 背景生成の失敗」カードの **「失敗した背景だけ再生成」** ボタンから、保存済みプロンプトで該当背景のみ作り直せる（`image_generation_failures` を参照、成功でその記録を消す）。

### IMAGE_BACKEND（画像生成バックエンド統合設定）

`IMAGE_BACKEND` 環境変数が画像生成バックエンドの主スイッチとなる。

| `IMAGE_BACKEND` | 内部エンジン | 背景生成 | サムネイル生成 | Gemini APIが必要か |
|:---|:---|:---|:---|:---:|
| `gemini`（デフォルト） | `nanobanana` | Nano Banana / Gemini | Nano Banana / Gemini | ✅ |
| `sd_webui` | `sd_webui` | Stable Diffusion WebUI | Stable Diffusion WebUI | ❌ |
| `comfyui` | `comfyui` | ComfyUI（Krea 2 Turbo・ローカル） | ComfyUI＋立ち絵合成＋文字入れ（ローカル） | ❌ |
| `codex_cli` | `codex_cli` | Codex CLI の画像生成（gpt-image・ChatGPT の使用枠） | Codex CLI（立ち絵を参照画像として添付） | ❌ |

- `THUMBNAIL_IMAGE_BACKEND`（空=背景と同じ）でサムネイルだけ別のバックエンドにできる（例: 枚数の多い背景はローカルの ComfyUI、1本に1〜3枚のサムネは Codex）。決定順は「画像画面・履歴詳細で明示したエンジン → `THUMBNAIL_IMAGE_BACKEND` → 背景と同じ」（`workers/main.py: generate_thumbnail(engine=...)`、`core/image_generator.py: thumbnail_engine()`）。

- `IMAGE_BACKEND=gemini` のとき、背景エンジンは常に `nanobanana` に固定される。
- `background_engine` を明示的に渡したときは `IMAGE_BACKEND` より優先される（再生成画面からの個別指定用）。
- `Auto` や自動切替設定は持たない（フォールバック禁止）。

### 文章生成AI（TEXT_LLM_BACKEND）

- `core/text_llm.py: generate()` が台本生成（`AIGenerator.generate_script`）・タイトルA/B/C案（`generate_title_variants`）・生成画面の「AIで台本を作る」「AIでShorts/Longタイトル案」「AIでネタ会議台本を作る」の共通窓口。失敗時に別の AI へ切り替えない（`E-LLM-BACKEND` / `E-LLM-CLI-MISSING` / `E-LLM-FAILED` / `E-LLM-TIMEOUT`）。
- `claude_cli` / `codex_cli` は手元の CLI をログイン済みのサブスクリプションで動かす。起動オプションは PicoAgent（`src-tauri/src/providers/agent_cli.rs`）で検証済みの安全指定に揃える。
  - Claude: `claude -p --safe-mode --tools <空 または WebSearch> --permission-mode plan --no-session-persistence [--model M]`。ファイル編集・コマンド実行ツールは渡さない。
  - Codex: `codex exec --ignore-user-config --sandbox read-only --ephemeral --skip-git-repo-check [--model M] -`。モデル未指定時は `~/.codex/config.toml`（`CODEX_HOME`、profile 指定を含む）の model を引き継ぐ。Codex では Web 検索を使わない。
  - **プロンプトは標準入力で渡す。** Windows の `claude.cmd` / `codex.cmd` は cmd.exe 経由で起動されるため、引数に台本の記号・改行を入れると誤解釈され、コマンドライン長の上限にも当たる。モデル名は記号を制限して検証する。
  - 時間切れは子孫プロセスごと停止する（psutil）。stderr はデバッグログだけに残し、画面には出さない。
- 生成画面のボタンは `POST /api/prompt/run`（`kind` = script / title / title-long / meeting、`theme` = 台本のテーマ）でジョブ（`prompt_run`）を登録し、`GET /api/jobs/{id}` の `result.text` を台本欄（タイトル案はプロンプト欄）へ入れる。テーマは「「テーマ」で台本を作ってください。」として手作業と同じ形でプロンプトの前に付ける。`GET /api/prompt/backends` は選択中の AI と各 CLI の有無を返す。
- 生成パイプラインは台本取得後も同じ設定でタイトルA/B/C案を作る（以前は Gemini クライアントを閉じた後に呼んでいたため常に既定案になっていた）。

### ComfyUI 背景・サムネイル生成（ローカル）

- `core/comfyui_generator.py: ComfyUIGenerator` が、利用者が起動した ComfyUI（`COMFYUI_BASE_URL`、既定 `http://127.0.0.1:8188`）へ `POST /prompt` → `GET /history/{id}` → `GET /view` で1枚生成する。時間切れ（`COMFYUI_TIMEOUT_SEC`）は `POST /interrupt` で止めてから失敗にする。
- 内蔵ワークフローは Krea 2 Turbo NVFP4（`COMFYUI_KREA_UNET` / `COMFYUI_KREA_TEXT_ENCODER` / `COMFYUI_KREA_VAE`、8ステップ・CFG 1・`VAEDecodeTiled`）。PicoAgent（`character-maker/sidecar/media/generate.py`）で RTX 5060 Laptop 8GB・RAM 34GB の実機生成を確認した構成と同じ。モデルの取得条件・ライセンス（Krea 2 Community License）は PicoAgent の `docs/models.md` を参照。NVFP4 は NVIDIA Blackwell（RTX 50系）以降が必要。
- テキストエンコーダーが Qwen3-VL のため日本語プロンプトをそのまま渡す（Stable Diffusion WebUI のような Ollama 英訳は行わない）。
- `COMFYUI_WORKFLOW_PATH` に ComfyUI の「API形式で保存」した JSON を指定すると、入力値がちょうど `{{PROMPT}}` / `{{WIDTH}}` / `{{HEIGHT}}` / `{{SEED}}` / `{{STEPS}}` の箇所へ値を入れて使う。`{{PROMPT}}` が無いワークフローは拒否する。
- 生成解像度は最終解像度と同じ向きで `COMFYUI_GEN_LONG_EDGE` × `COMFYUI_GEN_SHORT_EDGE`（16の倍数）。保存時に最終解像度へ合わせる（Nano Banana と同じ扱い）。シードは毎回ランダムで、デバッグ時は `image_prompts.txt` に記録する。
- **文字は画像AIに描かせない。** 背景プロンプトの「」（キャッチコピー）と `merge_telops_into_backgrounds()` が足す【テロップ演出】を `core/local_image_compose.py: split_overlay_text()` で取り除いて文字なしで生成し、生成後に Pillow で上部中央へ重ねる（テロップがあればテロップ、無ければ最初の「」）。見た目は Nano Banana への指示と同じ白文字・極太黒縁・影。フォントは `IMAGE_TEXT_FONT_PATH`（Windows 既定 `C:\Windows\Fonts\YuGothB.ttc`、macOS 既定 ヒラギノ角ゴシック W8）。見つからなければ `E-IMG-FONT` で停止する。位置と大きさは `IMAGE_TEXT_*` 設定。
- サムネイルは台本全文ではなく題材（サムネタイトル）だけの短い指示で文字なしの絵を作り、`THUMBNAIL_CHARACTER_PNGS` の先頭2体を左下・右下へ合成（高さ `THUMBNAIL_CHARACTER_HEIGHT_RATIO`）し、台本の `サムネ文字` またはタイトルを重ねる。Long の A/B/C では各案の構図指示（英語）をそのまま使う。
- 接続失敗・ComfyUI の実行エラー・出力なしは `ImageGenerationError(backend="comfyui")` で止める。他エンジンへの自動フォールバックは行わない。

### Codex CLI 画像生成

- `core/codex_image.py: generate_png()` が、ChatGPT のサブスクリプションでログイン済みの `codex exec` に内蔵の画像生成（`image_generation` 機能、codex-cli 0.162.1 で既定有効を確認）で1枚作らせ、作業フォルダの `output.png` を受け取る。API キーは使わない。生成は OpenAI のサーバーで行われ、ローカル生成ではない。
- 起動: `codex exec --ignore-user-config --sandbox workspace-write --ephemeral --skip-git-repo-check --cd <専用一時フォルダ> [--model M] [--image=<参照画像>...] -`。保存のため書き込みを許可するが、書ける場所は専用一時フォルダ（と Codex 既定の /tmp）だけ。参照画像は一時フォルダへ複製してから `--image=` で1枚ずつ渡す（`--image a b` の形は後ろの `-` まで画像として読まれうるため）。プロンプトは標準入力。
- **`OPENAI_API_KEY` を外して起動する。** 残っていると API の従量課金に切り替わるため。
- プロンプトは Nano Banana と同じ `_build_full_prompt()`（日本語の文字も画像AIに描かせる）。参照画像があれば `_reference_instruction()` を前に置く（Nano Banana と共通）。保存時に最終解像度へ合わせる。
- `output.png` が無ければ `E-CODEX-IMAGE-MISSING`、CLI の失敗は `E-LLM-FAILED`、時間切れ（`CODEX_IMAGE_TIMEOUT_SEC`）は `E-LLM-TIMEOUT`。別の場所を探して代わりに使わない。一時フォルダは成功・失敗とも削除する。
- 使用枠: 画像1枚で文章の数倍の使用枠を使うという報告があり、5時間・週ごとの上限がある。背景を何十枚も作る用途には向かない。

### Stable Diffusion WebUI 背景生成

- `core/sd_webui_generator.py: StableDiffusionWebUIGenerator` が担当する。
- `GET /sdapi/v1/options` で疎通確認・モデル取得、`POST /sdapi/v1/txt2img` で画像生成。
- Stable Diffusion WebUI (AUTOMATIC1111互換API)を前提とする。
- 日本語の説明文は `core/image_generator.py: _translate_to_english_for_sd()` でまず Ollama（`OLLAMA_TRANSLATE_MODEL`）を使って英語プロンプトに翻訳し、その結果に英語品質補助サフィックスを自動付加してから送信する。
  - 背景用サフィックス: `anime style background, colorful manga illustration, ...` 等
  - サムネイル用サフィックス: `bold Japanese YouTube thumbnail style, ...` 等
- Ollama が未起動の場合は `ensure_ollama_server()` で自動起動を試みる。**Stable Diffusion WebUI バックエンドでは Ollama を必須とし**、起動不可・接続不可・タイムアウト時は `E-OLLAMA-DOWN`（対処手順つき `AppError`）で停止する（サイレントスキップ・サイレントフォールバックなし）。Gemini（nanobanana）バックエンドでは Ollama は不要。
- API未起動・HTTPエラー・画像なし・タイムアウトはすべて `RuntimeError` として上位に伝播する。他エンジンへの自動フォールバックは行わない。
- 設定: `SD_WEBUI_BASE_URL`, `SD_WEBUI_TIMEOUT_SEC`, `SD_WEBUI_MODEL`, `SD_WEBUI_SAMPLER`, `SD_WEBUI_STEPS`, `SD_WEBUI_CFG_SCALE`, `SD_WEBUI_WIDTH`, `SD_WEBUI_HEIGHT`, `SD_WEBUI_NEGATIVE_PROMPT`

### Stable Diffusion WebUI モデル管理

- `core/sd_model_manager.py: SDWebUIModelManager` がモデルのインストール確認・ダウンロード・削除を担当する。
- モデルマニフェストは `assets/sd_webui/model_manifest.json`（`SD_MODEL_MANIFEST_PATH` で変更可）。
- マニフェスト形式: `{"version": 1, "models": [{id, display_name, type, filename, target_subdir, source_url, sha256, description, recommended, requires_auth, license_note, source_page_url, api_match_hint}]}`
- ダウンロードは `.part` 一時ファイルを使用し、完了後に `os.replace` でリネームする。
- SHA256 が非空文字のときは検証を実施し、不一致の場合は RuntimeError を送出して `.part` を削除する。SHA256 が空文字のときは検証をスキップする。
- **既存ファイルの扱い**: ダウンロード前に既存ファイルを確認し、SHA256 一致なら再ダウンロードをスキップして返す。SHA256 不一致なら自動上書きせず RuntimeError を送出する（「削除して再ダウンロード」案内を含む）。SHA256 未設定の場合は既存ファイルをそのまま返す。
- **認証付きダウンロード**: `requires_auth=true` のモデルは `HF_TOKEN` が設定されていない場合に RuntimeError を送出する。`HF_TOKEN` が設定されている場合は `Authorization: Bearer {HF_TOKEN}` ヘッダーを付与してダウンロードする。401/403 応答の場合はライセンス同意が必要な旨のエラーを送出する。
- **モデル削除** (`delete_model(model_id, *, confirmed=False)`): `confirmed=True` 必須。`SD_WEBUI_ROOT` 配下のファイルのみ削除可（`os.path.realpath` でパストラバーサルを検査）。ファイルが存在しない場合も RuntimeError。
- フォールバック禁止: 指定モデルが未インストール・SHA256不一致のいずれでも処理を中止する。

**`SD_WEBUI_MODEL` 設定時の事前モデル準備フロー（画像生成前に実行）:**
1. `SD_WEBUI_MODEL` が空 → スキップ（現在 Stable Diffusion WebUI にロードされているモデルを使用）
2. `SD_WEBUI_MODEL` が設定されている場合:
   - マニフェスト内で一致するモデルを検索（ファイル名・api_match_hint 部分一致）
   - 見つかりかつ未インストール:
     - `AUTO_DOWNLOAD_SD_MODELS=1` → `download_model()` → `rescan_models()`
     - `AUTO_DOWNLOAD_SD_MODELS=0` → RuntimeError（"Stable Diffusion WebUI モデル管理画面からダウンロードしてください"）
   - `StableDiffusionWebUIGenerator.set_active_model(SD_WEBUI_MODEL)` でモデル切り替え

**Stable Diffusion WebUI モデル管理 Web UI (`/sd-models`):**
- マニフェスト内モデルのインストール状況確認・アプリ内ワンクリックダウンロード・使用モデル切り替えを行う
- 「🎨 次の生成で使われるモデル」バナーを最上部に表示し、`SD_WEBUI_MODEL` 設定値または Stable Diffusion WebUI 現在ロード中モデルを示す
- `HF_TOKEN` 未設定時は `requires_auth=true` モデルのダウンロードボタンを非表示にし、設定へ誘導する
- 「このモデルを使う」は Stable Diffusion WebUI への即時切り替え + `SD_WEBUI_MODEL` を設定DBへ保存（次回起動以降も維持）
- 「削除して再DL」は `confirmed=true` 必須のバックグラウンド操作（破損ファイル・SHA256不一致時に使用）

**API エンドポイント:**
- `/api/sd-models` (GET): マニフェスト内全モデルのステータス
- `/api/sd-models/webui` (GET): Stable Diffusion WebUI API からインストール済みモデル一覧
- `/api/sd-models/current` (GET): Stable Diffusion WebUI の現在ロード済みモデル名
- `/api/sd-models/download` (POST): バックグラウンドダウンロード開始
- `/api/sd-models/progress` (GET): ダウンロード進捗確認（ポーリング用）
- `/api/sd-models/delete` (POST): モデルファイル削除（`confirmed=true` 必須）
- `/api/sd-models/delete-redownload` (POST): 削除して再ダウンロード（`confirmed=true` 必須、バックグラウンド）
- `/api/sd-models/use` (POST): Stable Diffusion WebUI アクティブモデル切り替え + `SD_WEBUI_MODEL` を設定DBに保存
- `/api/sd-models/rescan` (POST): Stable Diffusion WebUI への再スキャン依頼

**追加設定項目:**
| 設定 | 説明 | デフォルト |
|---|---|---|
| `SD_WEBUI_ROOT` | Stable Diffusion WebUI インストールディレクトリ（モデルパス解決・削除安全確認用） | `""` |
| `SD_MODEL_MANIFEST_PATH` | Stable Diffusion WebUI モデルマニフェスト JSON パス | `assets/sd_webui/model_manifest.json` |
| `AUTO_DOWNLOAD_SD_MODELS` | `1` のとき未インストールモデルを自動ダウンロード | `0` |
| `HF_TOKEN` | Hugging Face アクセストークン（`requires_auth=true` モデルのダウンロードに使用。値はレスポンス・ログに含めない） | `""` |

---

## 品質レビュー (`core/opening_quality.py`)

### 冒頭レビュー 3段階

| ステップ | 内容 | 条件 |
|---|---|---|
| ローカルルールベース | 意外性ワード・食べ物名・掛け合い・セリフ長チェック | 常時実行 |
| Ollamaレビュー | `qwen3:8b` でLLMスコアリング | ローカルスコア < 70 または重大エラーあり |
| Ollamaリライト | 冒頭セリフを自動修正 | `should_auto_rewrite_opening` = True |

### `should_auto_rewrite_opening` の条件（いずれか）

- `must_fix` に項目がある
- `hook < 75` / `loop < 70` / `cta < 70`
- 総合スコア < `OPENING_SCORE_HARD_ABORT_THRESHOLD`（デフォルト70）

### 処理中止条件

冒頭スコアが `OPENING_SCORE_HARD_ABORT_THRESHOLD`（デフォルト70）未満、または `must_fix` / 重大エラーあり → パイプライン中止。

`OPENING_SCORE_ABORT_THRESHOLD`（デフォルト80）は、ログ表示上の「pass / warning」判定の目安として使う。70〜79点は警告扱いだが、重大エラーがなければ処理を続行する。

### ChatGPT生成前レビュー

- モデル: `OPENAI_FINAL_REVIEW_MODEL`（デフォルト `gpt-5.2`）
- 入力: タイトル / サムネ文字 / 固定コメント / 台本 / 各レビュー結果 / 推定尺
- 出力: `final_score` / `publish_ok` / `risk` / `must_fix` / `nice_to_fix`
- **自動修正なし** — ログ表示と `metadata.db` 保存のみ
- `must_fix` がある場合、または `final_score` が `OPENING_SCORE_HARD_ABORT_THRESHOLD` 未満の場合は、音声・画像生成へ進まず中止する
- `render_engine` を入力に含め、native Shorts では「31行以上のみ must_fix」の基準で判定させる（22〜28行は可、24〜27行は理想）
- ChatGPT 応答に現行基準外の行数指摘が返ってきた場合、native かつ dialogue_count <= 28 なら自動で除去する
- 冒頭1行目の食べ物名チェック: タイトル由来キーワードだけでなく `FOOD_HINT_WORDS`（コーヒー・コーラ・牛乳・紅茶等の飲み物を含む）が初行に直接あればOKとする。N選型は初行に代表食材1つがあればOK（全食材の列挙は不要）

### DB保存

動画メタ・レビュー結果は `metadata.db` に保存する。ローカルJSON/TXTを正本・補完元として使わない。

- `videos.script_content` が台本本文の**唯一の正本**。`script.txt` ファイルは生成・参照しない。生成パイプラインは出力ディレクトリ準備直後に `save_script_content()` で台本本文を DB へ先行保存し、この保存は独立したDB接続で即時 `commit()` する。後段の音声・画像・レンダーで失敗しても保存済み台本はロールバックしない。終盤の `sync_folder_to_db(theme_dir, script_content=...)` でメタデータと合わせて再同期する。再生成・レンダー（`native_renderer`）・アップロードのタグ抽出・履歴詳細表示・is_shorts 判定・CTA候補カウントはすべて `metadata_db.get_script_content(local_id)` で DB から読む。既存フォルダの取り込み（`import_output_dir` / `sync_folder_to_db` の引数省略時）に限り、後方互換として既存の `script.txt` を読む。
- `videos.output_dir` は `sync_folder_to_db()` のたびに同期フォルダの実体パスへ更新（`ON CONFLICT` で上書き）する。フォルダ移動（`videos/` → `000_uploaded/`）や旧パスからの移行に追随し、古いパスが残り続けないようにする。

| 保存先 | 内容 |
|---|---|
| `script_quality` | ローカル・Ollamaレビュー結果、final_score、final_status、尺レビュー、ChatGPT生成前レビュー要約 |
| `video_metadata` | 固定コメント・CTA方針・説明文・タグ等 |
| `render_info` | レンダリング情報・実尺・画面形式・再生リストカテゴリ等 |
| 辞書ファイル | よみがな正規化辞書（ローカルファイル管理禁止の対象外） |

### LLMレビューの有効化

デフォルトはLLMレビュー有効（`OPENING_REVIEW_USE_LLM=1`）。冒頭LLMレビューと冒頭リライトはローカルの Ollama を使う。無効化する場合は設定画面、または環境変数 `OPENING_REVIEW_USE_LLM=0` で設定する。

```text
OPENING_REVIEW_USE_LLM=1
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_REVIEW_MODEL=qwen3:8b
OLLAMA_REWRITE_MODEL=qwen3:8b
OLLAMA_REWRITE_FALLBACK_MODEL=gemma4:e4b
```

Ollamaに接続できない場合、誤通過防止のため冒頭レビュー段階で処理を中止する。ChatGPT生成前レビューは別系統で、`OPENAI_FINAL_REVIEW_ENABLED` / `OPENAI_FINAL_REVIEW_MODEL` を使う。

---

## Ollamaレビュースキーマ

```json
{
  "overall_score": 78,
  "publish_ok": true,
  "rewrite_recommended": true,
  "must_fix": [],
  "warnings": ["冒頭の意外性はあるが3秒以内の引きがやや弱い"],
  "scores": {
    "hook": 82,
    "title_match": 90,
    "tempo": 76,
    "clarity": 85,
    "loop": 72,
    "cta": 70
  },
  "fix_target": "hook"
}
```

### スコア採点基準（Ollamaに渡す指示）

| 範囲 | 評価 |
|---|---|
| 90〜100 | そのまま出せる強い台本 |
| 80〜89 | 出せるが軽微な改善あり |
| 70〜79 | 明確な弱点あり。ただし `must_fix` が空なら生成継続可 / 軽微改善推奨として扱い、「中止不要。冒頭改善余地あり」とログ表示する |
| 60〜69 | 伸びにくい、修正必須 |
| 59以下 | 作り直し候補 |

Ollama 冒頭レビューでは、GUIログに `overall_score` と `scores.hook` / `title_match` / `tempo` / `clarity` / `loop` / `cta`、`must_fix`、`warnings`、`fix_target` を表示する。70〜79点の warning は単なる warning ではなく、人間が「台本修正が必要か、レビューAIの採点癖か」を判断できるように補足文を出す。

冒頭・生成前レビューでは、相槌・復唱・同意、めたんの説明役化、具体情報の不足、機械的な交互会話、「〇〇の理由」構文への偏り、Shortsの説明密度、Longの説明ブロックを確認する。次は `must_fix` とする。

- めたんの台詞の半分以上が相槌・復唱・同意
- 3往復以上、具体情報が増えない押し問答
- ずんだもんの説明が抽象語だけで、具体例・背景・理由が不足
- Shortsが驚きだけで具体説明が2〜3行
- Longに章ごとの説明ブロックがなく会話だけで進む
- 都市伝説が「怖い」「ゾッとする」だけを繰り返す
- 食べ物雑学が「実は違った」だけで、なぜそうなったかを説明しない

ずんだもんの2〜5行連続説明は減点しない。同一話者4連続を一律NGにする判定は使用しない。

78点付近への偏りを検証するため、Ollamaレビュー実行時は `metadata.db` の `script_quality.opening_review_debug`（JSON）に `review_debug` として `model` / `prompt_version` / `raw_response` / `parsed_score` / `parsed_subscores` / `warning_text` / `fix_target` / `created_at` を保存する（`upsert_opening_review` 経由、取得は `get_opening_review_debug`）。ローカルJSONファイルでのデータ管理は行わない。

---

## アップロードスケジューラー (`core/upload_scheduler.py`)

| 種別 | スロット | 日程 |
|---|---|---|
| Shorts | 21:00 | 毎日 |
| Long | 22:00 | 毎日 |

- スロット設定は `data/settings.db` の `channel_schedule_settings` テーブルで profile_id ごとに管理する。既定値は全チャンネル共通。タイムゾーンは `Asia/Tokyo`。
- チャンネル詳細フォームで Shorts / Long の投稿予約スロットとタイムゾーンを編集できる。既存チャンネルに設定がない場合は自動作成する。2026-06-06 の既定値変更では既存の個別設定も Shorts 12:00 / 21:00、Long 22:00 へ更新する。2026-06-23 に Shorts の既定スロットを 21:00 の1枠へ変更し、マイグレーション `upload_slots_20260623_shorts_21` で既存チャンネルの Shorts スロットも全件 21:00 へ更新する（config 既定の変更は既存チャンネルのDB値に自動反映されないため）。
- スロット割当範囲: 最大90日先まで探索
- アップロード実行後:
  1. `assign_slots_from_youtube()` で YouTube 予約済み一覧を正として次の空きスロットを取得。YouTube から取得できないときはローカル記録で推定せず `E-YOUTUBE-SCHEDULE` で止める（記録に無い予約と同じ枠へ重ねないため）。アップロード処理はこの失敗を受けて非公開のまま続ける
  2. `update_video_publish_time()` で YouTube API に公開予定を設定（`_slot_lock` で複数本同時アップロード時の競合を防止）
  3. `metadata.db` の `youtube_status` テーブルに書き込む（`video_id` / `title` / `video_type` / `uploaded_at` / `publish_status=scheduled` / `publish_at=JST isoformat`）。スロット取得失敗時は `publish_status=private`。
  4. フォルダを `output/{profile_id}/000_uploaded/<フォルダ名>/` へ移動する。履歴画面は `videos/` と `000_uploaded/` の両方を走査するため、移動後も履歴に表示される
  5. `output/{profile_id}/000_backups/` 内の同テーマバックアップ（`<フォルダ名>` または `<フォルダ名>_*` にマッチするもの）をすべて削除する
- スケジュールの正は YouTube Data API の `privacyStatus` / `publishAt`。`rebalance_slots()` はYouTube側の予約状態を参照する。アップロード状態は `metadata.db` の `youtube_status` テーブルが正本
- `list_schedule()` はページ表示のたびに `get_channel_upload_video_statuses()` を直接呼び出し、YouTube から最新状態を返す。`publish_at` はJST isoformat で返す。取得できないときは空の一覧を返さず `E-YOUTUBE-SCHEDULE` で止め、スケジュール画面にエラーを表示する（空だと「予約なし」と区別できないため）
- `sync_schedule_from_youtube()`: YouTube API を正として `youtube_status` テーブルへ書き戻す。チャンネル全件取得に失敗した場合は `E-YOUTUBE-SCHEDULE` で止める（既知 video_id だけで同期すると、記録に無い予約を見落としたまま同期済みになるため）。
- 割当・一覧・詰め直し・同期の予約取得と検証は共通化する。取得失敗や予約日時の破損・タイムゾーン欠損を「予約なし」として続けず、`E-YOUTUBE-SCHEDULE` で止める。同期は全予約の検証完了後にDBへ書き戻す。
- 投稿予約スロットと `publish_at` はチャンネル設定のタイムゾーンで扱う。既定は `Asia/Tokyo`。
- `infer_video_type()`: タイトルプレフィックス優先。タイトルなしの場合は duration ≤ 60s を shorts と推定

### 出力データディレクトリ

すべてのデータは `output/{profile_id}/000_data/metadata.db`（SQLite）に格納する。

| パス | 用途 |
|---|---|
| `output/{profile_id}/000_data/metadata.db` | 動画メタ・youtube_status・Analytics・ジョブ履歴（正本） |
| `output/{profile_id}/000_uploaded/` | アップロード済み動画フォルダのアーカイブ |
| `output/{profile_id}/000_backups/` | 生成時のフォルダバックアップ |

`core/output_paths.py` が active profile の `output_root` を基準にパスを解決して各モジュールへ提供する。

---

## ローカル Web UI (`web_app/`)

### 起動

```text
Windows: start.ps1
macOS: ./start.command
# 手動起動する場合:
python -m web_app.app [--open-browser] [--port 58080] [--auto-port]
```

| オプション | 説明 |
|---|---|
| `--port N` | 指定ポートで起動（省略時は `WEB_UI_PORT` を使用） |
| `--auto-port` | 指定ポートが使用中の場合、自動で空きポートを探して起動 |
| `--open-browser` | 起動後にブラウザを自動で開く |
| `--reload` | ファイル変更時に自動リロード（開発用） |

ポート競合時は `--auto-port` を使うか、`--port` で別ポートを明示指定する。

アクセス: `http://127.0.0.1:58080`

生成・レンダーを処理する `workers.runner` は Web UI 起動時に別プロセスとして自動起動・監視される。検証などで自動起動を止める場合のみ、環境変数 `NVF_DISABLE_JOB_RUNNER=1` を指定する。

### FastAPI 構成

- フレームワーク: FastAPI + Uvicorn + Jinja2
- バインド: `127.0.0.1` のみ（外部公開しない）
- 層分離: API層 (`routes/`) / サービス層 (`services/`) / テンプレート層 (`templates/`)
- ジョブ管理: `job_manager.py` でバックグラウンド実行・ステータス追跡

### ジョブ管理 (`job_manager.py`)

画面のジョブ取得はHTTP成功・要求したjob_id・既知状態を共通検証する。通信失敗では直前ログを維持し、理由を表示する。監視停止後は通信中の応答から再始動しない。キャンセル要求の受付は処理終了とみなさず、終了状態まで監視を続ける。アップロードの監視が通信失敗で中断した場合は、完了と表示せず履歴確認を案内する。初回起動時にチャンネル未登録であればprofile別DBの初期化を行わず、セットアップ画面へ進める。

長時間処理（生成・チェック・アップロード・Analytics等）はすべてジョブ化する。

| フィールド | 説明 |
|---|---|
| job_id | UUID |
| type | generate / check / render / upload / analytics_refresh / schedule_sync / schedule_rebalance / schedule_update / fixed_comment / image_regenerate |
| profile_id | ジョブ投入時の channel profile ID |
| status | queued / running / success / failed / cancelled |
| progress_text | 直近の進行メッセージ |
| started_at / finished_at | ISO8601 タイムスタンプ |
| logs | [{time, tag, message}] のリスト |
| params_json | 実行パラメータ |
| cancel_requested / heartbeat_at / runner_pid | キャンセル・runner生存監視用 |
| result / error | 成功時の結果 / 失敗時のエラーメッセージ |

ジョブ情報は active profile の `metadata.db` の `jobs` テーブルへ永続化され（`upsert_job` / `load_jobs_from_db`）、アプリ再起動後も指定件数分を参照できる。生成・レンダーのジョブは Web プロセスでは実行せず、`workers.runner` が `queued` を取得して `running` へ原子的に更新してから実行する。ジョブには `profile_id` と `params_json` を保存し、runner はジョブ実行中にその profile をスレッドローカルで固定するため、Web UI のチャンネル切替と生成先が混線しない。

runner は `generate` / `render` ジョブの `heartbeat_at` を定期更新し、`runner_pid` を持つ runner 管轄ジョブだけを stale 回収対象にする。heartbeat が `JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC` を超えて途絶えた runner 管轄の `running` ジョブは `failed`（`runner停止により中断`）へ戻す。`check` など Web プロセス内で動く軽量ジョブは Web 側が heartbeat を更新し、runner の stale 回収対象にはしない。キャンセルは `cancel_requested=1` を DB に書き、runner または Web 側ジョブがポーリングして `cancel_event` へ反映する。ジョブログは `append_job_logs` で追記し、runner はバッファ書き込みで頻繁な DB writer 競合を避ける。

Ctrl+C / SIGTERM / `/api/shutdown` の終了時は `core.app_shutdown` の終了フックを通し、job-runner を停止してから metadata DB 接続を閉じる。Ctrl+C が uvicorn の lifespan shutdown へ到達しない場合も、`web_app.app` の `KeyboardInterrupt` 捕捉で `request_shutdown(force=True, async_shutdown=False)` を呼び、runner プロセスを残さない。終了フックは二重実行しない。

### ジョブの同時実行制御（キュー）

Web UI は生成・レンダーを直接実行しない。`app.py` が起動時に `workers.runner` を別プロセスとして起動・監視し、runner が DB queue から `generate` / `render` を取得して処理する。

- 同時実行数は `JOB_MAX_CONCURRENT_WORKERS`（既定 `1` = 直列）。設定画面の「管理者設定」タブから変更でき、runner は設定DBを定期的に読み直して次のジョブ取得から反映する。2以上にすると runner 内で生成・レンダーを並列実行する。
- 複数台本生成は、全件を一度に `generate` キューへ投入しない。Web側の軽量な親ジョブ `generate_batch` が `JOB_MAX_CONCURRENT_WORKERS` の枠数ぶんだけ子 `generate` ジョブを投入し、子ジョブが終了して枠が空いたら次を投入する。大量生成時でもDBキューを先に膨らませず、同時実行数に合わせて順次進める。
- Web は queued 登録と DB 参照だけを行うため、重い生成中でもジョブ一覧・履歴・設定画面の応答を維持する。
- runner は起動時に、前回セッションで残っていた `queued` の `generate` / `render` を `cancelled`（`起動時に破棄（前回の未実行ジョブ）`）へ破棄する（`discard_pending_jobs`）。また `running` なのに `runner_pid` / `heartbeat_at` が無い `generate` / `render` は前回の実行中ジョブ残骸として `failed` へ破棄する（`discard_orphan_running_jobs`）。前回の未実行・不整合ジョブを再起動だけで自動実行したり、新規バッチ投入の同時実行数判定を塞いだりしない。起動後に新規登録されたジョブは通常どおり実行する。

設定画面 (`/settings`) で使う補助データ（Ollamaモデル一覧、`assets/bgm/` の音源ファイル一覧）は、Web UI 起動時に `settings_preload_service` がバックグラウンドでプリロードする。プリロードが未完了の状態で設定画面を開いた場合でも、`GET /api/settings/ollama-models` と `GET /api/settings/bgm-files` は待機せず暫定値を返し、設定項目本体を先に表示する。APIキー登録状態は `encrypted_secrets` の bool だけを使い、`/settings` のHTML生成時に VOICEVOX / ffmpeg / Ollama / Stable Diffusion のフル診断を実行しない。ジョブ実行・ログ保持・各種タイムアウト・Web UI 表示名など運用負荷やアプリ全体に影響する項目は「管理者設定」タブに分離する。
- `JOB_RUNNER_POLL_INTERVAL_SEC` ごとに queued/cancel を確認し、`JOB_LOG_FLUSH_INTERVAL_SEC` ごとにログをまとめ書きする。
- 追加インフラ不要・純 Python + SQLite のため配布物にそのまま同梱できる（Kafka/Redis/Docker 等には依存しない）。

## 製品版MVP機能

### 初回セットアップ

- `/setup` の最初に**法務同意**（利用規約・使用許諾EULA・プライバシーポリシー・特商法表記）を求める。文書は `GET /legal/{doc}`（`core/legal_consent.py:LEGAL_DOCUMENTS` のホワイトリスト限定）で閲覧、同意は `data/settings.db:settings`（`LEGAL_CONSENT_ACCEPTED` / `LEGAL_CONSENT_AT`）に記録する。**未同意ではセットアップ完了 API（`POST /api/settings/setup`）を 422 でブロック**する（=生成・アップロードも解禁されない）。`/legal` は setup リダイレクトミドルウェアの除外に含める。
- active channel profile が存在しない初回起動時のみ、通常画面への GET を `/setup` へ誘導する（`web_app/app.py:setup_redirect_middleware`）。
- active channel が登録済みであれば、`PRODUCT_SETUP_COMPLETED` が未完了でも通常画面・設定画面には入れる。未完了状態では生成・アップロード API を分かりやすい 403 でブロックする（`core/setup_state.py` の gate と `core/license_manager.py`）。完了状態は `data/settings.db:settings.PRODUCT_SETUP_COMPLETED` に保存する。
- `/setup` ではチャンネル名・ハンドル・製品版 seed profile、APIキー登録導線（各キーの必要条件を明記）、ソフトウェアのインストール案内、VOICEVOX / ffmpeg / Ollama / Stable Diffusion WebUI 診断、BGM登録導線、サンプル台本のテスト生成、完了保存を扱う。
- インストール案内は `core/service_detector.py:get_installation_guides()` が返すカタログ（`label` / `required` / `purpose` / `download_url` / `steps` / `note`）を `/setup` のカードで常時表示する。VOICEVOX・ffmpeg を必須、Ollama・Stable Diffusion WebUI を任意として表示する。外部ソフトは同梱せず各自で入手させる方針。
- APIキーの必要条件: Google API キー＝AI台本生成（Gemini）と Gemini 画像生成に必要（手書き台本＋Stable Diffusion WebUI 画像なら不要）、YouTube 認証＝アップロード時のみ必要、OpenAI / HF Token＝任意。
- サンプル生成だけは `setup_test=true` により未完了状態でも登録できる。
- 「プロセスを走査して自動設定」で外部依存サービスを検出できる（`core/service_detector.py`）。起動中プロセスと既定ポート（VOICEVOX 50021 / Ollama 11434 / Stable Diffusion WebUI 7860）、PATH 上の ffmpeg を走査し、`VOICEVOX_PATH` / `VOICEVOX_URL` / `OLLAMA_BASE_URL` / `SD_WEBUI_BASE_URL` / `FFMPEG_BIN` を `POST /api/settings/detect-services` で検出、`POST /api/settings/detect-services/apply` で EDITABLE_CONFIG 経由保存・即時反映する。秘密情報は扱わない。
- 設定画面から保存するパス系設定（`VOICEVOX_PATH` / `AQUESTALK_ENGINE_PATH` / `SD_MODEL_MANIFEST_PATH` / `SD_WEBUI_ROOT` / `FFMPEG_BIN`）は `config_service.sanitize_path_value()` で保存前に正規化する。引用符を除去し、環境変数・`~` を展開し、Windowsパスが `\b` などの制御文字に化けた場合はバックスラッシュ表記へ修復する。修復できない制御文字は保存エラーにする。
- 未検出のサービスには `core/service_detector.py:_INSTALL_GUIDE` のダウンロードURL（`config.py` の `VOICEVOX_DOWNLOAD_URL` / `FFMPEG_DOWNLOAD_URL` / `OLLAMA_DOWNLOAD_URL` / `SD_WEBUI_DOWNLOAD_URL`）とインストール手順、必須/任意（VOICEVOX・ffmpeg が必須、Ollama・Stable Diffusion WebUI が任意）を `detect_services()` の各 service に付与し、`/setup` でダウンロードリンクとして表示する。外部依存は同梱せず個別に入手させる方針。

### ライセンス管理

- ライセンス情報は `data/settings.db:settings` を正本とする。`LICENSE_EDITION` 未設定時は `trial`。
- edition は `trial` / `personal` / `pro` / `studio`。秘密情報や購入者情報をログ・レスポンスへ出さない。
- 制限項目: Trial 透かし、1日生成本数、最大 channel profile 数、YouTubeアップロード可否、Analytics可否、テンプレート数上限。
- Trial は native MP4 の最終出力へ `Native Video Factory Trial` の小さな透かしを焼き込む。
- 試用→購入の動線（UX先行）: `get_license_info()` は `purchase_url`（`config.PRODUCT_PURCHASE_URL`）と `upgrade_available`（edition が studio 以外）を返す。上限到達エラー（生成本数・profile 数・アップロード・Analytics・テンプレート）の文言には購入導線を付ける。設定画面「製品管理」のライセンスカードに購入リンクとライセンスキー入力欄を表示し、`POST /api/settings/license` で即時反映する。実ライセンスキーの署名検証は未実装（後付け予定）。

### 診断パッケージ

- 設定画面「製品管理」から `output/_diagnostics/diagnostics_*.zip` を作成する。
- ZIPに含める: app version、OS / Python / GPU（nvidia-smi で検出）/ ffmpeg / VOICEVOX / Ollama / Stable Diffusion WebUI 診断、マスク済み設定値、最新ジョブログ、直近失敗ジョブ、エラーコード一覧、DB schema version。
- ZIPに含めない: APIキー、OAuth token、client_secrets、台本本文、生成動画、背景画像、サムネ画像。
- ジョブログ内の `key` / `token` / `secret` / `oauth` / `password` 形式の値はマスクする。

### バックアップ / 復元

- 設定画面「製品管理」からバックアップZIPを作成する。出力先は `output/_backups/`。
- バックアップ対象は `data/settings.db` と各 `output/{profile_id}/000_data/metadata.db`。`prompt_templates` / `channel_profiles` / `bgm_assets` は `settings.db` 内のテーブルとして含まれる。
- 復元前には現在の `settings.db` と profile 別 `metadata.db` を `pre_restore_*` に自動退避する。
- バックアップの `metadata_schema_version` が現行より新しい場合は fail closed で中止する。
- `encrypted_secrets` は同一PCのマスターキーでのみ復号可能。**パスフレーズを指定したバックアップでは認証情報を PBKDF2(SHA-256, 20万回) + AES-GCM でパスフレーズ由来鍵により再暗号化し、`secrets_export.enc` として同梱する**（`core/secret_store.py:export_secrets_with_passphrase`）。復元時は DB 復元後に同じパスフレーズで復号し、復元先 PC のマスターキーで `save_secret()` し直す（`import_secrets_with_passphrase`）。これにより別PCへ認証情報を移行できる。
- パスフレーズを含むバックアップを復元するにはパスフレーズが必須（未入力なら中止）。パスフレーズ空欄のバックアップは従来どおり同一PC専用で、別PC復元時はAPIキー・OAuthを再登録する。
- API: `POST /api/settings/backup`（`passphrase` 任意）、`POST /api/settings/restore`（`backup_path` / `confirmed=true` / `passphrase` 任意）。

### 起動・多重起動の自己回復

- `/health` は `{status, service: "native-video-factory", app}` を返す。`service` マーカーで「ポートを使っているのが本アプリ自身か」を起動時に判別する。
- 多重起動はポート確認より先に OS のファイルロックで防ぐ（`core/instance_lock.py`）。Web UI は `{app_base_dir}/data/web_ui.lock` を排他ロックしてプロセス終了まで保持し、待ち受けURLを `data/web_ui_instance.json` に記録する。ロックを取れない2つ目の起動は、記録URLの `/health` が本アプリなら既存ウィンドウを開いて終了し、応答が無ければ「起動処理中または終了処理中」としてエラー終了する。ロックは異常終了時も OS が解放する。
  - 理由: 既定ポートを別アプリが使っていて既存インスタンスが空きポートへ退避していると、ポート確認では検出できない。2つ目の job-runner は起動時の残骸破棄（`discard_pending_jobs`）で既存インスタンスの待機ジョブをキャンセルしてしまう。
  - `--run-runner` と `--post-fixed-comments` はロックを取らない（Web UI 起動中に実行される前提のため）。
- `web_app/app.py:main()` の起動時ポート処理:
  - 既定ポートが使用中で、本アプリが既に起動している（`/health` の `service` 一致）場合は**二重起動せず**、`--open-browser` 指定時は既存ウィンドウを開いて終了する。
  - 別アプリが使用中の場合、既定ポート（または `--auto-port`）なら自動で空きポートへ退避する。`--port` を明示指定したポートが別アプリ使用中のときはユーザー意図を尊重してエラー停止する。
  - 起動直前のレースでポートを奪われた場合（`OSError`）は、空きポートで1度だけ再試行する。
- job-runner はWeb起動時に常駐起動し、異常終了を監視して自動再起動する（`_start_job_runner` の watch スレッド）。

### 製品版SEED

- 初期データ類は `config/SEED/` 配下に集約する。
- 製品版テンプレートパックは `config/SEED/prompt_packs/product/{seed_profile}/` に置く。現行の汎用製品seedは `general`。
- `/setup` のジャンル選択は product seed profile だけを表示するため、`@zunkami` 食べ物雑学専用テンプレートは製品版seedに混入しない。
- 既存 `config/prompt_profiles/genres/` は互換用・既存チャンネル用として残す。チャンネル作成時、product seed を選ぶと handle 名の genre_profile へコピーしてから DB seed する。
- テンプレートには `template_pack` / `visibility` / `product_bundle` を保存できる。テンプレートパック export には APIキー・Analytics実績・ユーザー固有データを含めない。
- テンプレートパックのインポート/エクスポートは設定画面「テンプレート」タブから行う。エクスポートは `GET /api/prompt-templates/export`（JSONダウンロード）、インポートは `POST /api/prompt-templates/import`（`confirmed=true` 必須・active profile へ追加）。

### 設定画面の表示モード

- 設定画面（`/settings`）上部の「表示モード」で **通常 / 詳細 / 開発者** を切り替え、危険設定・開発者向け機能を通常利用時は隠す。選択はブラウザの `localStorage`（`nvf_settings_mode`）に保持する純UI設定で、設定DBの正本ではない。
- 通常: 設定変更 / チャンネル / APIキー / BGM / テンプレート / キャラクター設定 / 製品管理。
- 詳細: ＋ よみがな辞書 / Stable Diffusion WebUI 詳細（モデル選択）。
- 開発者: ＋ 管理者設定（ジョブ並列数・ログ保持・DB診断・危険操作）。
- 隠れたタブへの URL ハッシュ遷移時は必要なモードまで自動で引き上げる。破壊的操作は従来どおり `confirmed=true` と確認ダイアログを必須にする。
- 販売版では `DEVELOPER_TOOLS_ENABLED=0`（`config/config.py`）にすることで、管理者設定タブ・「開発者」モード・edition切替などの開発者向けUIをサーバー側で描画しない。あわせて `admin` 指定の設定項目は `get_editable_config()` から除外し、`save_config()` も拒否する（HTML非表示だけでなくAPIでも保護する）。表示モードは localStorage 依存のため、秘匿はこのフラグで行う。

### 主要画面

| URL | 画面 |
|---|---|
| `/` | ダッシュボード |
| `/generate` | 台本貼り付け / 動画生成 |
| `/check` | LLM/尺チェック |
| `/history` | 生成履歴一覧 |
| `/history/{name}` | 生成履歴詳細 |
| `/analytics` | Analytics |
| `/schedule` | スケジュール管理 |
| `/upload` | YouTubeアップロード |
| `/fixed-comment` | 固定コメント |
| `/settings` | 設定 |
| `/logs` | ジョブログ |
| `/sd-models` | Stable Diffusion WebUI モデル管理 |

### API概要

```
GET  /health                            # ヘルスチェック（プレーン応答）
GET  /api/health                        # ヘルスチェック（JSON）
GET  /api/status                        # 外部サービス稼働状況・設定診断
GET  /api/dashboard                     # ダッシュボード集計（予約数・状態など）
GET  /api/jobs                          # ジョブ一覧
GET  /api/jobs/{job_id}                 # ジョブ詳細・ログ
POST /api/jobs/{job_id}/cancel          # ジョブの中止要求

GET  /api/history                       # 生成履歴一覧（videos/ と 000_uploaded/ を走査）
GET  /api/history/{history_name}        # 履歴詳細（台本・メタデータ・画像・アップロード状態）
DELETE /api/history/{history_name}      # confirmed=true 必須。履歴フォルダとDB関連行を削除
POST /api/history/regenerate            # 履歴から全工程を再生成（台本はDBから取得、confirmed=true）

POST /api/generate                      # 台本から動画を生成（1本）
POST /api/generate/batch                # 複数台本を一括生成
POST /api/check                         # 台本のLLM/尺チェック（生成・保存はしない）

GET  /api/images/{history_name}                   # 背景・サムネイル画像の一覧
GET  /api/images/{history_name}/file/{file_path}  # 履歴フォルダ配下のファイル配信（画像/動画）
POST /api/images/{history_name}/save-prompts      # 背景プロンプトの保存
POST /api/images/{history_name}/regenerate        # 選択した画像（背景/サムネ）の再生成

GET  /api/analytics                     # Analytics 一覧・評価スコア
GET  /api/analytics/tsv                 # Analytics の TSV エクスポート
POST /api/analytics/refresh             # YouTube から最新の視聴データを取得
GET  /api/analytics/retention?video_id=...&duration=...  # 視聴維持率（動画ID・尺指定）

GET  /api/schedule                   # 予約スケジュール一覧（YouTube 側の状態が正）
POST /api/schedule/sync              # YouTube の予約・公開状態を metadata.db へ同期
POST /api/schedule/rebalance         # dry-run（YouTube APIへの書き込みなし）
POST /api/schedule/rebalance/apply   # 計算して YouTube へ適用（confirmed=true 必須）
POST /api/schedule/update            # 個別の公開予定を変更（confirmed=true 必須）
POST /api/schedule/delete            # Web UIでは無効化、YouTube Studioで手動操作

GET  /api/upload/candidates             # アップロード候補（videos/ 配下で MP4 のある履歴）
POST /api/upload                        # 選択動画を YouTube へ予約投稿（confirmed=true 必須）
POST /api/upload/batch                  # 複数動画を一括アップロード（confirmed=true 必須）

GET  /api/fixed-comment/candidates       # 固定コメント未投稿の公開済み動画候補
POST /api/fixed-comment                  # 公開済み動画へ固定コメントを投稿（confirmed=true 必須）
POST /api/fixed-comment/mark-posted      # 指定動画をローカル記録上で投稿済みにする（confirmed=true 必須）
POST /api/fixed-comment/mark-all-posted  # 未投稿候補をすべてローカル記録上で投稿済みにする（confirmed=true 必須）

GET  /api/prompt/script                  # 台本生成プロンプトを取得（実績ベース）
GET  /api/prompt/title                   # タイトル生成プロンプトを取得
GET  /api/settings/status                # 設定診断（秘密値は返さない）
POST /api/settings/status/refresh        # 外部サービスチェックを再実行
GET  /api/settings/config                # 編集可能な設定項目と現在値を取得
POST /api/settings/config                # 設定を DB 保存し現在プロセスへ即時反映
POST /api/settings/secrets               # APIキー一括保存（後方互換エンドポイント）
POST /api/settings/secrets/api-key       # APIキーを個別に暗号化保存（profile別）
POST /api/settings/secrets/client-secrets # YouTube client_secrets(JSON) を暗号化保存
GET  /api/settings/ollama-models         # Ollama で利用可能なモデル一覧（起動時プリロード、未完了時は暫定値を即返す）
GET  /api/settings/bgm-files             # assets/bgm/ 内の音源ファイル一覧（起動時プリロード、未完了時は暫定値を即返す）
GET  /api/settings/reading-dict          # よみがな辞書（同梱・ユーザー）を取得
POST /api/settings/reading-dict/{dict_type}        # よみがな辞書にエントリ追加/上書き
DELETE /api/settings/reading-dict/{dict_type}/{word}  # よみがな辞書からエントリ削除

GET  /api/channels                       # チャンネルプロファイル一覧
GET  /api/channels/current               # アクティブなプロファイル
POST /api/channels                       # プロファイル新規作成
PUT  /api/channels/{profile_id}          # プロファイル更新（APIキー・client_secrets含む）
POST /api/channels/{profile_id}/activate # アクティブプロファイルを切替
POST /api/channels/{profile_id}/validate # プロファイル設定の検証
DELETE /api/channels/{profile_id}        # プロファイル削除
GET  /api/channels/prompt-profiles       # 利用可能な genre_profile 一覧

GET  /api/bgm                            # 登録BGM一覧（active profile）
POST /api/bgm                            # BGMを登録
POST /api/bgm/{bgm_id}/default           # 既定BGMに設定
DELETE /api/bgm/{bgm_id}                 # BGMを削除

GET  /api/prompt-templates               # プロンプトテンプレート一覧（active profile）
POST /api/prompt-templates               # テンプレート新規作成
GET  /api/prompt-templates/{template_id}             # テンプレート取得
PUT  /api/prompt-templates/{template_id}             # テンプレート更新
POST /api/prompt-templates/{template_id}/set-default # 種別ごとの既定テンプレートに設定
POST /api/prompt-templates/{template_id}/clone       # テンプレート複製
DELETE /api/prompt-templates/{template_id}           # テンプレート削除
POST /api/prompt-templates/seed          # seed ファイルから初期テンプレートを投入

GET  /api/sd-models                     # モデルマニフェスト一覧
GET  /api/sd-models/webui               # Stable Diffusion WebUI 導入済みモデル一覧
GET  /api/sd-models/current             # 現在選択中のモデル
GET  /api/sd-models/progress            # ダウンロード進捗
POST /api/sd-models/download            # モデルのダウンロード開始
POST /api/sd-models/delete              # モデル削除（confirmed=true 必須）
POST /api/sd-models/delete-redownload   # 削除して再ダウンロード（confirmed=true 必須、バックグラウンド）
POST /api/sd-models/use                 # 指定モデルに切替
POST /api/sd-models/rescan              # モデル一覧を再スキャン

POST /api/shutdown                  # confirmed=true 必須。force=true でworker実行中も強制終了
GET  /api/shutdown/status           # 終了処理中フラグを返す
```

### セキュリティ方針

- `127.0.0.1` のみバインド
- output/ 配下のみファイルアクセス可（`security.py` で検証）
- `.env` / `client_secrets.json` / `token.json` / `token_analytics.json` の内容は返さない
- APIキー設定（`GOOGLE_API_KEY` / `OPENAI_API_KEY` / `HF_TOKEN`）は active profile ごとの有無（bool）のみ返す。値をレスポンス・ログに含めない
- 設定DB書き込みAPIは許可キーだけを受け付け、値に改行を含む場合は拒否する
- パストラバーサル拒否（`output/` 配下 / `SD_WEBUI_ROOT` 配下の実パス検査を実施）
- 履歴フォルダ名（`history_name`）から実体パスを引くときは `security.find_history_dir()` に統一する。`videos/` → `000_uploaded/` の順で探し、active profile の `output_root` 配下に限定する。テーマフォルダは `output_root` 直下ではなく `videos/`・`000_uploaded/` 配下にあるため、`safe_output_path(history_name)`（base=`output_root`）で直接引いてはならない（画像配信・画像再生成・差し替え・再レンダーの参照先ズレの原因になる）
- 破壊的操作（アップロード・固定コメント投稿・モデル削除）は `confirmed=true` が必須
- 例外時に秘密値をログへ出さない（HF_TOKEN 付き URL はログに含めない）

### Web一本化方針

- 操作入口はローカル Web UI のみ。
- `workers/main.py` は `run_pipeline()` を提供する生成パイプラインとして残し、Web UI のジョブから呼び出す。
- `run_pipeline` / `ScriptParser` / `core/*` はWeb UIの共通基盤として維持する。

### 主要機能

| 機能 | Web UI 画面 |
|---|---|
| 生成 / 中止 | `/generate` |
| LLM/尺チェック | `/check` |
| AI台本作成プロンプト | `/generate` |
| Shortsタイトル案 / Longタイトル案 | `/generate` |
| 履歴から複数生成 | `/history` |
| 画像確認 / プロンプト編集 / 再生成 | `/images`（`/history/{name}` からリンク） |
| YouTubeアップロード / 一括アップロード | `/upload` |
| 固定コメント投稿 | `/fixed-comment` |
| スケジュール確認 / 同期 / 公開予定変更 | `/schedule` |
| アナリティクス取得・表示 | `/analytics` |
| 設定（即時反映 / APIキー変更） | `/settings` |
| Stable Diffusion WebUI モデル管理 | `/sd-models` |

`/check` の LLM/尺チェックは、台本本文を保存・生成せずに確認だけ行う。基本表示は推定尺のみで、`OPENING_REVIEW_USE_LLM=1` の場合だけ Ollama 点数、`OPENAI_FINAL_REVIEW_ENABLED=1` の場合だけ ChatGPT 点数を追加表示する。ローカル冒頭レビューの詳細、警告一覧、修正依頼文、台本本文は結果表示に出さない。

`/generate` と `/history/{name}` の再生成フォームには **画像エンジン**（Google AI / Stable Diffusion WebUI）の選択が含まれる。`/images` 再生成にも同様のエンジン選択がある。

`/generate` の通常・ネタ会議タブは、画像・BGM設定と生成ボタンを先に表示し、その下に台本入力欄を配置する。

`/settings` のAPIキー設定タブ（「APIキー設定」）は画面最下部に置く。通常の設定変更欄には秘密値を含めない。APIキー設定欄には `GOOGLE_API_KEY`・`OPENAI_API_KEY`・`HF_TOKEN`（Hugging Face アクセストークン）が含まれ、いずれも active profile ごとの有無（bool）のみ画面に表示する。保存した値は active profile の `encrypted_secrets` に紐づき、チャンネル切替後は切替先 profile の登録状態を表示・使用する。設定保存後の値はアプリ再起動なしで即時反映される（`WEB_UI_PORT` など起動時固定パラメータを除く）。保存時はトースト通知で確認できる。

`/settings` のチャンネル管理タブには、各 channel profile の `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `HF_TOKEN` / YouTube client_secrets / Upload OAuth / Analytics OAuth の登録状態を bool バッジで表示する。値そのものは表示しない。

チャンネル詳細フォームには、そのチャンネル専用の `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `HF_TOKEN` / YouTube client_secrets 登録欄を置く。保存時は編集中のチャンネルの `profile_id` に紐づけて `encrypted_secrets` へ保存し、空欄は変更なしとして扱う。共通設定画面のAPIキー欄も active profile に対する編集として扱い、認証情報はチャンネルごとに分離する。

ナビゲーションバーの「設定」リンクは常にナビゲーション最右端に固定する（CSS `margin-left: auto`）。

ナビゲーションバーには「設定」リンクのさらに右端に「⏻ 終了」ボタンを配置する（`.nav-shutdown-btn` スタイル）。

### アプリ終了フロー (`core/app_shutdown.py`)

ナビゲーションバーの「⏻ 終了」ボタンから `POST /api/shutdown` を呼び、uvicorn を安全に停止する。

**通常終了（worker なし）:**
1. 「⏻ 終了」ボタンをクリック → `POST /api/shutdown {confirmed:true}`
2. worker が 0 件 → `shutdown_requested=true`
3. バックグラウンドで registered hook を実行 → `server.should_exit=True`
4. uvicorn が lifespan の shutdown フェーズを実行 → `run_lifespan_shutdown()` でフック再実行（冪等）

**強制終了（worker 実行中）:**
1. 「⏻ 終了」ボタンをクリック → `POST /api/shutdown {confirmed:true}`
2. worker 実行中 → 拒否・理由返却（UI に確認ダイアログ再表示）
3. ユーザーが強制終了を選択 → `POST /api/shutdown {confirmed:true, force:true}`
4. shutdown hook で job-runner を terminate → kill の順に停止
5. 以降は通常終了と同じ

**Ctrl+C / SIGTERM:**
- uvicorn が受信し lifespan の shutdown フェーズを実行 → `run_lifespan_shutdown()` でフック実行
- `--reload` モードでは `uvicorn.Server` 参照なし（開発専用のため許容）
- pytest 実行中に `uvicorn.Server` 参照が無い場合は、テストプロセスを落とさないためシグナル停止フォールバックを抑止する。`request_shutdown(..., async_shutdown=False)` で終了処理を同期実行できる。

**shutdown hook 登録:**

```python
from core.app_shutdown import register_shutdown_hook
register_shutdown_hook("my_module", my_close_function)
```

起動時にモジュールが自分で登録する。現在の登録済み hook:
- `metadata_db`: `close_all_connections()` — 全 SQLite 接続を close

### SQLite 接続管理方針 (`core/metadata_db.py`)

- DB ファイル: `output/{profile_id}/000_data/metadata.db`
- DB 更新は `with ManagedConnection() as conn:` または明示的 `commit()` / `close()` で短時間に完了させる
- アプリ起動中に DB 接続を長期保持しない。処理単位で取得・コミット・closeする
- shutdown hook `close_all_connections()` が登録済みのため、アプリ終了時に未closeの接続があっても安全に解放される

画像確認・再生成（`/images`）は `/history/{name}` 詳細画面の「画像確認・再生成」リンクからも遷移できる。ナビゲーションには独立リンクを設けない。

### ログカラー

| タグ | 色 | 用途 |
|---|---|---|
| info | #00d8d6 | 通常情報 |
| success | #05c46b | 成功 |
| warning | #ffa502 bold | 警告 |
| error | #ff5e57 | エラー |
| stderr | #ffaa66 | stderr（トレースバック等） |
| batch | #ef57ff bold | バッチ処理 |
| score | #ffd32a bold 11pt | スコア表示 |
| duration | #34ace0 bold 11pt | 尺情報 |

### Shorts尺アラート（6段階）

| 推定尺 | 色 |
|---|---|
| < 35秒 | 赤 (error) |
| 35〜38秒未満 | 緑 (success) ← やや短いがOK |
| 38〜50秒 | 緑 (success) ← 理想 |
| 50〜55秒 | 黄 (warning) |
| 55〜58秒 | 橙 (warning) |
| > 58秒 | 赤 (error) |

### 事前チェック (`_pre_generate_check`)

エラー（中止）:
- タイトル未設定

警告（ログのみ）:
- サムネ文字が15文字超
- 背景枚数が少ない
- 最初のセリフが8文字未満

### アップロード確認ダイアログ

- 列: 番号 / タイトル / スケジュール / スコア（冒頭 / 尺 / 最終）
- 幅: 860px

---

## よみがな正規化 (`core/reading_normalizer.py`)

VOICEVOX が固有名詞・専門用語・難読漢字を誤読するのを防ぐため、音声合成前に SudachiPy と自前辞書で読み補正する。

- `VOICE_READING_MODE` は `off` / `dictionary` / `safe_auto` から選択する
- `dictionary`: `data/settings.db` の `reading_dictionary_entries`（`dict_type=base/user`）の単純置換だけを使う
- `safe_auto`: SudachiPy / `sudachidict_core` で形態素解析し、安全な名詞類だけを自動でひらがな化する
- 補正後テキスト → VOICEVOX へ渡す（読み上げ用）
- 元テキスト → ファイル名・字幕に使う（字幕マッチング維持）
- 必要ライブラリ不足、辞書DB読み書き失敗、候補保存失敗などは `RuntimeError` または元例外で生成を中止する（サイレントスキップ禁止）

**よみがな辞書は全チャンネル共通（プロファイル非依存）。** `data/settings.db` の `reading_dictionary_entries` / `reading_candidates` テーブルを正本とし、`output/{profile_id}/` 配下には保存しない。アクティブチャンネルを切り替えても同じ辞書（手動 / 自動学習 / candidates）を使う。`metadata.db` や認証情報がチャンネル別なのとは異なる扱い。設定画面から登録した読みは全チャンネルへ即時反映される。よみがな辞書・自動学習辞書・候補の JSON ファイルは廃止済み。

```
VOICE_READING_MODE = "safe_auto"
```

---

## 音声生成バックエンド (`core/audio_backends.py` / `core/voicevox.py`)

- `core.audio_backends.resolve_audio_speaker()` が `character_profiles.voice_backend` を解決し、各セリフごとに `voicevox` または `aquestalk` へ振り分ける。
- 自動フォールバックは禁止。AquesTalkが無効、エンジン未配置、ライセンス未確認、生成失敗、WAV不正の場合はVOICEVOXへ代替せず明示エラーで停止する。VOICEVOX失敗時もAquesTalkへ代替しない。
- AquesTalkはVOICEVOXとは別ライセンス。YouTube収益化や商用利用では、利用者自身がA-Quest公式ライセンスを確認する必要がある。
- 霊夢・魔理沙など東方Project由来のキャラ名や立ち絵を使う場合は、東方Project二次創作ガイドラインと動画配信サービス向けガイドラインを確認する。

### VOICEVOX音声生成

- API: `/audio_query` → `/synthesis` を1行ずつ個別呼び出し
- `postPhonemeLength`: `VOICE_POST_PHONEME_LENGTH`（デフォルト0.0）を VOICEVOX API に渡す
- 末尾無音: 生成後のWAVへ `max(0.1, 0.1 × speed_scale)` 秒の無音を直接追加
- キャラクター・スピーカーIDは active profile の `character_profiles.voice_backend` / `voice_speaker` / `voice_speaker_id` / `voice_styles_json` を優先して解決する。DBに未設定の既定キャラは `config.CHARACTERS` を使う。
- 既定の VOICEVOX スピーカーID:

| キャラ | スタイル | ID |
|---|---|---|
| ずんだもん | ノーマル | 3 |
| ずんだもん | あまあま | 1 |
| ずんだもん | ツンツン | 7 |
| ずんだもん | セクシー | 5 |
| ずんだもん | ささやき | 22 |
| 四国めたん | ノーマル | 2 |
| 四国めたん | あまあま | 0 |
| 四国めたん | ツンツン | 6 |
| 四国めたん | セクシー | 4 |
| 四国めたん | ささやき | 36 |

### AquesTalk音声生成

- AquesTalkは実行ファイルまたはラッパーCLIを `AQUESTALK_ENGINE_PATH` に指定し、`AQUESTALK_COMMAND_TEMPLATE` で呼び出す。`AQUESTALK_ENGINE_PATH` が相対パスの場合は exe / リポジトリルート（`app_base_dir()`）基準で解決する。
- `ゆっくり霊夢風` は `AQUESTALK_REIMU_SPEAKER_KEY`（既定 `yukkuri_reimu`）、`ゆっくり魔理沙風` は `AQUESTALK_MARISA_SPEAKER_KEY`（既定 `yukkuri_marisa`）を内部speaker_keyとして使う。
- 生成後は出力WAVを `wave.open()` で検証し、フレーム数0やWAV不正ならエラー停止する。

### 音声タイミング

Shorts / Long ともに、VOICEVOX の WAV 実長へテンプレートの `AdditionalTime` 0.3 秒を加え、さらに `VOICE_TAIL_SAFETY_SEC = 0.5` 秒を音声アイテム長に足します。次のセリフ開始までは `INTER_DIALOGUE_GAP_SEC = 0.2` 秒空けます。

WAV 末尾には `max(0.1, 0.1 × speed_scale)` 秒の無音を直接書き込みます（Shorts 冒頭 2.0x なら 0.2秒）。高速音声で末尾フォネームが切れるのを防ぎます。

---

## 台本フォーマット

### Shortsフォーマット例

```
動画形式: Shorts
動画タイトル: チョコは500年間ずっと飲み物だった
サムネ文字: 飲み物
説明文: チョコレートの驚きの歴史を解説！
タグ: ずんだもん,ゆっくり解説,VOICEVOX,...
固定コメント: チョコレートが飲み物だった時代、飲んでみたかった？
再生リスト: 実は薬・毒扱いだった！食べ物の黒歴史

# Scene 1: Opening hook
背景: 漫画風イラスト調。人物禁止。「飲み物」を白文字・極太黒縁で配置。
テロップ: 飲み物
ずんだもん(ノーマル): チョコは薬だったのだ！
四国めたん(ツンツン): えっ、薬ですの？
```

`再生リスト:` はカンマ区切りで複数のカテゴリ名を指定できる（`Playlist:` も同義）。動画形式（Shorts/Long/ネタ会議）に応じてアップロード時に実際の再生リスト名を解決する（`core/playlist_resolver.py`）。

| カテゴリ | 動画形式 | 解決後の再生リスト名 |
|---|---|---|
| `{カテゴリ}` | Shorts / 縦 | `{カテゴリ} Shorts` |
| `{カテゴリ}` | Long / 横 | `{カテゴリ}【じっくり解説】` |
| — | ネタ会議（縦） | `ずんだもんとめたんのネタ会議 Shorts` |
| — | ネタ会議Long / 横 | `ずんだもんとめたんのネタ会議【じっくり版】` |

指定した再生リストが YouTube 上に存在しない場合は自動作成してから登録する。判定不能な動画形式の場合は `None` を返し、フォールバックなしで警告ログを出す。

### Longフォーマット（追加要素）

```
動画形式: Long
チャプター: 1.イントロ / 2.起源 / 3.広まった理由 / 4.まとめ
再生リスト: 実は薬・毒扱いだった！食べ物の黒歴史
```

---


### 記法一覧

| 記法 | 説明 |
|:---|:---|
| (スタイル名) | VOICEVOX のスタイル（例: (ノーマル) (あまあま) (ツンツン)） |
| [表情名] | native立ち絵の表情 PNG 指定（例: [笑い]） |
| テロップ: | セグメント冒頭にポップアップ表示するテキスト |
| サムネイル: | サムネイルに使う背景の指定 |
| サムネ文字: | サムネイルに表示する大きなテキスト |
| 再生リスト: | アップロード先の再生リストカテゴリ名（カンマ区切りで複数可） |
| ━━ タイトル ━━ | 複数動画を1つのテキストで一括処理する区切り |

## 設定 (`config/config.py`)

| 設定 | デフォルト | 説明 |
|---|---|---|
| `VOICEVOX_URL` | `http://localhost:50021` | VOICEVOX API URL |
| `VOICEVOX_PATH` | 空 | VOICEVOX自動起動用パス（空の場合は手動起動） |
| `VOICEVOX_QUERY_WORKERS` | 4 | audio_query 並列リクエスト数（安全上限4。既存DBの超過値はジョブ開始時に4へ補正） |
| `VOICEVOX_SYNTH_WORKERS` | 1 | synthesis リクエスト数（VOICEVOX 0.25系のプロセス停止を避けるため1固定。既存DBの超過値も1へ補正） |
| `NANOBANANA_BG_WORKERS` | 3 | Nano Banana 背景生成の並列数 |
| `NATIVE_SHORTS_BODY_VOICE_SPEED` | 1.25 | Shorts本編再生速度（native） |
| `NATIVE_SHORTS_INTRO_VOICE_SPEED` | 1.40 | Shortsイントロ再生速度（native） |
| `NATIVE_LONG_BODY_VOICE_SPEED` | 1.20 | Long本編再生速度（native） |
| `NATIVE_LONG_INTRO_VOICE_SPEED` | 1.40 | Longイントロ再生速度（native） |
| `NATIVE_SHORTS_ESTIMATE_BASE_CPS` | 5.4 | Shorts native推定の基準文字/秒 |
| `NATIVE_SUBTITLE_WRAP_CHARS_SHORTS` | 13 | Shorts（縦画面）字幕の1行最大文字数。超えると自動折り返し（句読点優先） |
| `NATIVE_SUBTITLE_WRAP_CHARS_LONG` | 24 | Long（横画面）字幕の1行最大文字数。超えると自動折り返し（句読点優先） |
| `NATIVE_SHORTS_CHARS_MUST_FIX_MIN` | 260 | Shorts native文字数 must_fix 下限 |
| `NATIVE_SHORTS_TARGET_CHARS_MIN` | 280 | Shorts native文字数 目標下限 |
| `NATIVE_SHORTS_TARGET_CHARS_MAX` | 330 | Shorts native文字数 目標上限 |
| `NATIVE_SHORTS_AVG_CHARS_MIN` | 11.5 | Shorts native平均文字数 必須下限 |
| `NATIVE_SHORTS_SHORT_LINE_MAX` | 4 | 10文字以下の短文セリフ 許容上限 |
| `NATIVE_SHORTS_LINES_IDEAL_MIN` | 22 | Shorts nativeセリフ数 理想下限 |
| `NATIVE_SHORTS_LINES_IDEAL_MAX` | 28 | Shorts nativeセリフ数 理想上限 |
| `NATIVE_SHORTS_LINES_TARGET_MIN` | 24 | Shorts nativeセリフ数 目標下限 |
| `NATIVE_SHORTS_LINES_TARGET_MAX` | 27 | Shorts nativeセリフ数 目標上限 |
| `NATIVE_SHORTS_LINES_WARNING` | 29 | Shorts nativeセリフ数 warning閾値 |
| `NATIVE_SHORTS_LINES_MUST_FIX` | 31 | Shorts nativeセリフ数 must_fix閾値 |
| `VOICE_INTRO_FAST_LINES` | 3 | native: 冒頭N行がintro速度 |
| `NATIVE_AUDIO_LOUDNORM_ENABLED` | `true` | native MP4最終音声へ loudnorm を適用するか |
| `NATIVE_AUDIO_LOUDNORM_I` | -15 | native loudnorm Integrated loudness目標 |
| `NATIVE_AUDIO_LOUDNORM_TP` | -1.5 | native loudnorm True Peak上限 |
| `NATIVE_AUDIO_LOUDNORM_LRA` | 6 | native loudnorm Loudness Range目標 |
| `NATIVE_BGM_VOLUME_DB` | -20 | native出力のBGM音量(dB) |
| `NATIVE_SHORTS_CHARACTER_SCALE` | 1.05 | native Shortsのキャラ表示倍率。`CHARACTER_UPPER_BODY_MODE=1` のとき無効 |
| `CHARACTER_UPPER_BODY_MODE` | 1 | `1` でnative腰から上表示モードを有効化 |
| `NATIVE_ENABLE_MOTION_EFFECTS` | `true` | native Shorts軽量エフェクト全体を有効化 |
| `NATIVE_ENABLE_BG_KEN_BURNS` | `true` | 背景画像を各セグメント内でゆっくりズーム/パン |
| `NATIVE_ENABLE_CHARACTER_BOUNCE` | `true` | セリフ開始時に話者キャラだけ軽く拡大縮小 |
| `NATIVE_ENABLE_TALK_WIGGLE` | `false` | 発話中の話者キャラを小刻みに上下左右へ揺らす。既定OFF。設定DB / 設定画面で変更 |
| `NATIVE_ENABLE_POP_TELOP` | `true` | 台本の `テロップ:` 行を短時間ポップ表示 |
| `NATIVE_ENABLE_SHAKE` | `true` | ツッコミ/驚き系の短い反応で軽いシェイク |
| `NATIVE_MAX_SHAKE_COUNT_SHORTS` | 2 | Shorts 1本あたりのシェイク最大回数 |
| `NATIVE_MAX_ICON_COUNT_SHORTS` | 2 | Shorts 1本あたりの疑問/驚きアイコン最大回数 |
| `NATIVE_REACTION_EFFECT_MIN_GAP_SEGMENTS` | 4 | シェイク/アイコンを再表示するまでの最低セリフ間隔 |
| `NATIVE_BG_ZOOM_MAX` | 1.06 | 背景Ken Burnsの最大拡大倍率 |
| `NATIVE_TALK_WIGGLE_X_PX` | 2 | 発話中キャラ揺れの左右振幅(px)。設定DB / 設定画面で変更 |
| `NATIVE_TALK_WIGGLE_Y_PX` | 6 | 発話中キャラ揺れの上下振幅(px)。設定DB / 設定画面で変更 |
| `NATIVE_TALK_WIGGLE_HZ` | 5.5 | 発話中キャラ揺れの周波数(Hz)。設定DB / 設定画面で変更 |
| `NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS` | 3 | 発話中キャラ揺れを何セリフに1回出すか。1=毎回。設定DB / 設定画面で変更 |
| `CHARACTER_UPPER_BODY_SCALE` | 1.55 | 腰から上モード時のキャラ拡大倍率（Long用） |
| `CHARACTER_UPPER_BODY_SHORTS_SCALE` | 1.15 | 腰から上モード時のキャラ拡大倍率（Shorts用。縦画面は幅が狭いため Long より小さく） |
| `CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET` | 310 | 腰から上モード: Shorts の下方向シフト量(px)。設定DB / 設定画面で変更 |
| `CHARACTER_UPPER_BODY_LONG_Y_OFFSET` | 460 | 腰から上モード: Long の下方向シフト量(px)。設定DB / 設定画面で変更 |
| `NATIVE_CHARACTER_SIDE_MARGIN_SHORTS` | -120 | Shorts の左右マージン(px)。負値で画面外へ出す。設定DB / 設定画面で変更 |
| `NATIVE_CHARACTER_SIDE_MARGIN_LONG` | -90 | Long の左右マージン(px)。負値で画面外へ出す。設定DB / 設定画面で変更 |
| `VOICE_READING_MODE` | `safe_auto` | よみがな補正モード（`off` / `dictionary` / `safe_auto`）。`safe_auto` は SudachiPy + 自前辞書。Ollama は使わない |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | 台本生成モデル（`TEXT_LLM_BACKEND=gemini` のとき） |
| `TEXT_LLM_BACKEND` | `gemini` | 文章生成AI（`gemini` / `claude_cli` / `codex_cli` / `ollama`）。台本・タイトルA/B/C案・生成画面の「AIで〜」ボタンが使う |
| `TEXT_LLM_WEB_SEARCH` | `1` | 台本作成時に Web 検索で事実確認させる（Gemini は google_search、Claude CLI は WebSearch ツールだけを許可） |
| `TEXT_LLM_TIMEOUT_SEC` | `900` | 文章生成1回の上限秒数（CLI・Ollama） |
| `CLAUDE_CLI_PATH` / `CLAUDE_CLI_MODEL` | `claude` / 空 | Claude Code CLI の実行ファイルとモデル（空=CLI の既定） |
| `CODEX_CLI_PATH` / `CODEX_CLI_MODEL` | `codex` / 空 | Codex CLI の実行ファイルとモデル（空=`~/.codex/config.toml` の model） |
| `OLLAMA_TEXT_MODEL` | `qwen3:8b` | 文章生成AIを `ollama` にしたときのモデル |
| `COMFYUI_*` | — | ComfyUI（ローカル画像生成）。「ComfyUI 背景・サムネイル生成」節を参照 |
| `THUMBNAIL_IMAGE_BACKEND` | 空 | サムネイルの画像生成バックエンド（空=背景と同じ / `gemini` / `sd_webui` / `comfyui` / `codex_cli`） |
| `CODEX_IMAGE_TIMEOUT_SEC` | `600` | Codex CLI の画像1枚の生成待ち上限(秒) |
| `IMAGE_TEXT_FONT_PATH` / `IMAGE_TEXT_*` | OS 別の太字ゴシック | ローカル画像の文字入れ |
| `OLLAMA_REVIEW_MODEL` | `qwen3:8b` | 冒頭レビューモデル |
| `OLLAMA_REWRITE_MODEL` | `qwen3:8b` | 冒頭リライトモデル |
| `OLLAMA_TRANSLATE_MODEL` | `qwen3:8b` | Stable Diffusion WebUI プロンプト日→英翻訳モデル |
| `OLLAMA_PLAYLIST_MODEL` | `qwen3:8b` | 単体再生リスト振り分けの判定モデル |
| `OLLAMA_PLAYLIST_TIMEOUT_SEC` | 60 | 単体再生リスト振り分けのタイムアウト秒数 |
| `OLLAMA_PLAYLIST_NUM_PREDICT` | 128 | 単体再生リスト振り分けの最大生成トークン数 |
| `OPENAI_FINAL_REVIEW_MODEL` | `gpt-5.2` | ChatGPT生成前レビューモデル |
| `OPENING_SCORE_ABORT_THRESHOLD` | 80 | pass / warning 表示の目安 |
| `OPENING_SCORE_HARD_ABORT_THRESHOLD` | 70 | 処理中止スコア閾値 |
| `MAX_BACKGROUNDS_SHORTS` | 9 | Shorts最大背景枚数 |
| `MAX_BACKGROUNDS_LONG` | 90 | Long最大背景枚数（通常モード） |
| `MAX_BACKGROUNDS_LONG_BUDGET` | 16 | Long節約モードの最大背景生成枚数 |
| `WEB_APP_NAME` | `Native Video Factory` | Web UI表示アプリ名 |
| `WEB_UI_PORT` | 58080 | Web UIポート番号 |
| `WEB_DEFAULT_IMAGE_STYLE` | `通常` | Web UI生成画面の既定画像スタイル |
| `WEB_IMAGE_STYLE_CHOICES` | `通常,アニメ,水彩` | Web UI生成画面の画像スタイル選択肢。正本はカンマ区切り。互換のため引用符付き値・Python/JSON配列風の値も読み込み時に正規化する |
| `WEB_DEFAULT_REUSE_BACKGROUNDS` | `false` | Web UI生成画面の背景再利用既定値 |
| `WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST` | `false` | Web UI生成画面のLongサムネAB既定値 |
| `WEB_DEFAULT_LONG_BUDGET_MODE` | `false` | Web UI生成画面のLong節約既定値 |
| `AUTO_FIXED_COMMENT_PROFILE_SCOPE` | `"all"` | 固定コメント自動投稿の対象。`all`=全チャンネル、`active`=アクティブのみ |
| `WEB_JOB_POLL_INTERVAL_MS` | 2000 | Web UIジョブ状態更新間隔(ms) |
| `WEB_LOG_POLL_INTERVAL_MS` | 30000 | ログ画面(/logs)のポーリング間隔(ms)。設定保存後は開いているログ画面も値を再取得してタイマーを組み直すため、アプリ再起動・ページ再読み込みは不要。テキスト選択中は再描画をスキップし、デバッグログを上へスクロール中は表示位置を維持する |
| `WEB_SUCCESS_RELOAD_DELAY_MS` | 1500 | Web UIジョブ成功後再読み込み待ち時間(ms) |
| `WEB_TOAST_VISIBLE_MS` | 2000 | Web UIトースト表示時間(ms) |
| `WEB_TOAST_HIDE_DELAY_MS` | 420 | Web UIトースト非表示待ち時間(ms) |
| `WEB_VOICEVOX_CHECK_TIMEOUT_SEC` | 2.0 | Web UIのVOICEVOX疎通確認タイムアウト(秒) |
| `WEB_FFMPEG_CHECK_TIMEOUT_SEC` | 5.0 | Web UIのffmpeg疎通確認タイムアウト(秒) |
| `NATIVE_FFMPEG_TIMEOUT_SEC` | 900 | nativeレンダーのffmpeg 1コマンド最大実行秒数 |
| `NATIVE_FFPROBE_TIMEOUT_SEC` | 30 | nativeレンダーのffprobe 最大実行秒数 |
| `LONG_UPLOAD_PLAYLIST_NAME` | `ロング動画` | Longアップロード後に自動追加する再生リスト名。空なら無効 |
| `PLAYLIST_CLASSIFIER_SCRIPT_CHARS` | 1600 | 単体再生リスト振り分けでOllamaへ渡す台本本文の最大文字数 |
| `TOPIC_REQUEST_CTA_EVERY_N` | 5 | Shorts新規/横展開のネタ募集CTAを通算何本に1本許可するか。0なら自動付与しない |
| `HF_TOKEN` | `""` | Hugging Face アクセストークン（`requires_auth=true` モデルのダウンロードに使用。`.env` に記載。値はレスポンス・ログに含めない） |
| `JOB_LOG_MAX_JOBS` | 300 | 保持する最大ジョブ件数。`metadata.db` の `jobs` テーブルに保存し、超過分は `delete_old_jobs` で古い順に削除する |
| `JOB_MAX_CONCURRENT_WORKERS` | 1 | job-runner の同時実行数。2以上で生成・レンダーを並列処理する |
| `JOB_RUNNER_EXECUTOR_CAPACITY` | 8 | job-runner が内部で確保する最大スレッド数。`JOB_MAX_CONCURRENT_WORKERS` の上限 |
| `JOB_RUNNER_POLL_INTERVAL_SEC` | 0.5 | job-runner が queued/cancel を確認する間隔 |
| `JOB_RUNNER_HEARTBEAT_INTERVAL_SEC` | 2.0 | job-runner が実行中ジョブの heartbeat を更新する間隔 |
| `JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC` | 30.0 | heartbeat が途絶えた running ジョブを failed 化するまでの秒数 |
| `JOB_LOG_FLUSH_INTERVAL_SEC` | 0.5 | runner がジョブログを DB へまとめ書きする間隔 |

---

## ffmpeg ネイティブレンダラー (`core/native_renderer.py`) — 本番レンダラー

Shorts / Long の本番レンダラー。通常の「生成」ボタンで native MP4 を出力する。

- **デフォルト動作**: `run_pipeline()` は常にnative用素材を生成する。
- 素材生成後、Web UIジョブが `render_native_test()` を呼び出してnative MP4を作る。
- `render_native_test(output_dir, voice_speed_intro, voice_speed_body, estimated_duration_sec)` が音声・背景を結合して `{履歴フォルダ名}_native.mp4` を出力する。固定ファイル名のため再生成時は上書き。
- ffmpeg は常に `-nostdin` と `stdin=DEVNULL` で非対話実行し、履歴からの再作成で既存ファイルや入力待ちによりWebジョブがハングしないようにする。1コマンドの上限は `NATIVE_FFMPEG_TIMEOUT_SEC`、ffprobe は `NATIVE_FFPROBE_TIMEOUT_SEC` で制御する。
- 最終MP4生成時は、VOICE+BGMミックス後の音声へ `loudnorm=I=-15:TP=-1.5:LRA=6` を適用する。`NATIVE_AUDIO_LOUDNORM_*` で `.env` 上書き可能。
- BGMは `data/settings.db` の `bgm_assets` テーブルで channel profile 単位に管理する。生成・再レンダー時に `profile_default`（チャンネル既定）/ `selected`（個別指定）/ `none`（BGMなし）を選ぶ。旧 `BGM_FILE` はBGM未登録チャンネルの初回移行用としてのみ使い、以後はDB登録されたBGMを正本にする。
- 出力後に ffmpeg `ebur128=peak=true` で最終MP4の音量解析を行い、Integrated loudness / LRA / True peak の要約をログに出す。
- MP4生成後、ffprobe で実尺を取得し `📏 native実尺評価: Xs [理想/やや短い/OKだけど長め/警告/要確認]` をログ表示する。評価基準はShortsと同じ（38〜50s=理想 / 35〜37s=やや短い / 51〜55s=OKだけど長め / 32〜34s or 56〜58s=警告）。
- `estimated_duration_sec` を渡すと `📏 native実尺: Xs / 推定尺: Ys / 差分: ±Zs` も出力する。
- **キャラ拡大**: `CHARACTER_UPPER_BODY_MODE=1`(デフォルト) のとき native Shorts/Long は腰から上表示モードになる。Long は `CHARACTER_UPPER_BODY_SCALE=1.55`、Shorts（縦画面1080px幅）は `CHARACTER_UPPER_BODY_SHORTS_SCALE=1.15` で拡大し、それぞれ `CHARACTER_UPPER_BODY_LONG_Y_OFFSET=460` / `CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET=310` px 下方向にシフトする。左右マージンは Long `NATIVE_CHARACTER_SIDE_MARGIN_LONG=-90` / Shorts `NATIVE_CHARACTER_SIDE_MARGIN_SHORTS=-120` を既定とし、画面端から少し外へ出す。設定画面の「native立ち絵配置」には Shorts / Long の簡易プレビュー、配置プリセット、発話揺れプリセット、ライブ揺れプレビューを表示し、数値変更中に位置と動きを確認できる。runner は生成・レンダー開始前に設定DBを再読込するため、保存後の再レンダーだけで反映される。`CHARACTER_UPPER_BODY_MODE=0` のときは Shorts のみ `NATIVE_SHORTS_CHARACTER_SCALE`(1.05)を使う。
- 字幕フチ幅は `NATIVE_SUBTITLE_STROKE_WIDTH`(内フチ, デフォルト 9) / `NATIVE_SUBTITLE_OUTER_STROKE_WIDTH`(外フチ, デフォルト 13) で調整可能。字幕帯のパディングは `NATIVE_SUBTITLE_PADDING_Y` で調整。
- **字幕自動折り返し**: セリフが `NATIVE_SUBTITLE_WRAP_CHARS_SHORTS`（Shorts 縦画面: 13文字）または `NATIVE_SUBTITLE_WRAP_CHARS_LONG`（Long 横画面: 24文字）を超えると `_wrap_subtitle()` が自動折り返しを行う。句読点（、。！？…）が直前にある場合は句読点位置を優先し、折り返し後2行目が `max(2, max_chars // 3)` 文字未満になる場合は句読点折り返しを適用しない。折り返し行数に応じて SubtitleBox の高さを自動拡張する。
- **Shorts軽量エフェクト**: `NATIVE_ENABLE_MOTION_EFFECTS=1` のとき、背景に最大 `NATIVE_BG_ZOOM_MAX` までのKen Burns風ズーム/パン、話者キャラの0.2秒前後の軽いバウンス、`テロップ:` 行の0.8〜1.5秒ポップ表示、短いツッコミ/疑問場面の軽いシェイクと疑問/驚きアイコンを追加する。シェイクとアイコンは各 `NATIVE_MAX_SHAKE_COUNT_SHORTS` / `NATIVE_MAX_ICON_COUNT_SHORTS` 回まで、かつ `NATIVE_REACTION_EFFECT_MIN_GAP_SEGMENTS` セリフ以上の間隔に制限する。発話中の小刻みな上下左右揺れは `NATIVE_ENABLE_TALK_WIGGLE=1` の場合だけ有効で、既定はOFF。発話中揺れは `NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS` / `NATIVE_TALK_WIGGLE_X_PX` / `NATIVE_TALK_WIGGLE_Y_PX` / `NATIVE_TALK_WIGGLE_HZ` で調整できる。感情タグ (`expression`) が付与されている場合、タグ優先でシェイク判定とアイコン選択を行う（驚き/ドン引き → "!?" or "！"、困惑/疑問 → "？"、焦り/怒り → "!" or "！"、呆れ → 揺れのみ・アイコンなし）。
- レンダー開始時のジョブログに `native立ち絵配置` と `発話中揺れ` の実設定値を出力し、保存した設定が runner に反映されているか確認できる。
- エフェクトはセグメント単位で付与し、BGM・音声タイミングは変更しない。ffmpegフィルタが失敗したセグメントはエフェクトなしで再レンダーして生成を継続する。
- YouTubeアップロード時は履歴フォルダ内の最新MP4を優先して選択する。
- **Shorts のみ**: `thumbnails/thumbnail.png` がある場合、native MP4 の先頭に `THUMBNAIL_HOLD_FRAMES_SHORTS`（デフォルト3フレーム≒0.1秒）だけサムネイル画像を挿入する（Long は挿入しない）。保持フレーム数は `.env` の `THUMBNAIL_HOLD_FRAMES_SHORTS` で変更可。1秒以上の静止サムネは設定値に関係なく生じない（上限5フレーム≒0.17秒）。
- レンダー開始時に使用エンコーダ名（`NATIVE_FFMPEG_ENCODER` の値）をジョブログへ出力する。GPU エンコーダ（h264_nvenc 等）が利用不可の場合は `tag="warning"` 付きの警告メッセージとして送出し、UI 上でオレンジ色表示で視覚的に識別できる。ソフトウェアエンコーダ（libx264）へのフォールバックは最大3箇所で検知・警告する。
- `metadata.db` の `render_info` に以下を保存する: render_engine / estimated_duration_sec / actual_duration_sec / actual_duration_status / loudnorm_enabled / loudnorm_i / loudnorm_tp / loudnorm_lra / screen_format / playlist_categories / bgm_mode / bgm_id / bgm_display_name / bgm_file_path / bgm_volume_db / bgm_loop_enabled。

### 安定条件

| 項目 | native |
|---|---|
| Shorts セリフ数（理想） | 24〜27行（22〜28行は許容） |
| Shorts セリフ数（warning） | 29〜30行 |
| Shorts セリフ数（must_fix） | 31行以上 |
| Shorts 推定尺チェック | 参考値のみ表示（停止しない） |
| Shorts **実尺チェック（音声合計）** | `needs_review` 時は MP4 化を中止 |
| Shorts 音声速度 | イントロ 1.40x / 本編 1.25x |
| Long 音声速度 | イントロ 1.40x / 本編 1.20x |

native では尺ではなく**語り速度（chars/sec）と台本量**で調整するため、推定尺による停止は行わない。

### 実尺チェック（VOICEVOX 音声生成直後）

VOICEVOX 音声生成ループ完了後、よみがな正規化済みの全 WAV ファイルの長さを合算して `duration_review()` で評価する。WAV 合計 ≈ MP4 実尺 − 約 1s（サムネ保持 + 背景遷移分）のため、同じ閾値で判定して問題ない。

- 結果はログ表示し、最終的な実尺情報は `metadata.db` に保存する
- Shorts で `needs_review`（< 35s または > 58s）のときは MP4 化を中止し、台本修正を促す
- `warning` / `ok_but_short` / `ok_but_long` はログ警告のみで続行する
- Long は `warning`（< 4分 または > 11分）のみログ警告、中止しない
- 判定基準は native 実尺基準（ideal: 38〜50s / ok_but_short: 35〜37s / ok_but_long: 51〜55s / warning: 56〜58s / needs_review: それ以外）

### 詳細ログ（`render_native_test` 完了時）

```
📊 render_engine: native
   voice_speed_intro: 1.40 / voice_speed_body: 1.25
   dialogue_lines: 25 / script_chars: 420
   audio_duration_total: 52.3秒 / silence_total: 4.80秒 / median_silence: 0.20秒
   speech_chars_per_sec: 8.02 / final_video_duration: 57.1秒
   速度判定: Shorts向きで良い / 台本量判定: OK
```

### native字幕の可読性

Shortsの通常字幕は、背景に左右されない可読性を最優先する。本文は白文字で統一し、話者差は文字色ではなくフチ色で表現する。

- ずんだもん: 白文字 + 濃緑の内フチ + 黒外フチ
- 四国めたん: 白文字 + 濃ピンク紫の内フチ + 黒外フチ
- 背景が複雑な場合でも読めるよう、Shortsでは半透明黒帯を背面に出せる
- 黒帯を使う場合もキャラ色フチは残し、V13相当のキャラ色の印象と可読性のバランスを取る
- 黄緑・赤・黄色などの色付き字幕は全文ではなく重要語の強調に限定する

---

## Long動画専用機能

## 📢 CTA/Long動画の運用ポリシー

- **Shorts本編のループ視聴優先:** 直接的な誘導セリフは警告対象。「ネタ募集CTA」は既定で5本に1本のみ許可。
- **Long動画の目次:** 概要欄用の 【目次】(0:00形式) チャプターマーカーを自動追加。
- **Longサムネイル A/B テスト:** 3パターンのサムネイル画像を自動出力し YouTube Studio でのテストをサポート。


### サムネイルA/Bテスト

Web UI の **「LongサムネAB」チェックボックス**（デフォルト OFF）または `config/config.py` の `LONG_THUMBNAIL_AB_TEST` / `WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST` で制御する。

- **OFF（デフォルト）**: Variant A のみ生成。
- **ON**: 3バリアントを `thumbnails/{テーマ名}_thumbnail_A/B/C.png` として生成する。
  - **Variant A**: 食べ物クローズアップ（クリック重視）
  - **Variant B**: 古い歴史・驚き演出
  - **Variant C**: 昔と今の比較・ギャップ

YouTube Data APIでは公式A/Bテストを開始できないため、A/B/C案はPC版YouTube Studioで手動登録します。通常アップロードではA案だけを `thumbnail.png` としてAPI設定します。

> 旧仕様の `_meta/thumbnail_ab_test.json` 等のローカルマニフェスト管理および `<video_id>_thumbnail_*.png` コピー保存は廃止済み（生成物は variant PNG のみ。`_meta/` ディレクトリは使用しない）。

### タイトルA/Bテスト

Long ではタイトル候補（A/B/C案）を生成し、`metadata.db:render_info.title_variants` にJSONで保存して履歴詳細へ表示する。アップロード時は A 案を既定タイトルとして使い、B/C 案は YouTube Studio で手動テストする。旧仕様の `_meta/title_ab_test.json` によるローカルマニフェスト管理は廃止済み。

### 画像生成解像度

背景・サムネイルは常に最終解像度（Shorts 1080x1920 / Long 1920x1080）で扱う。Nano Banana へは `image_size` を送らず（API 既定サイズで生成）、保存時に `_save_image_part` が最終解像度へリサイズする。Stable Diffusion WebUI も最終解像度で生成する。解像度ログ・Nano Banana 送信設定ログは `1080x1920` のように最終解像度を単体表示する。

> 旧「縮小生成モード（SDサイズモード / `sd_size_mode`）」は廃止した。`NANOBANANA_SD_IMAGE_SIZE` / `NANOBANANA_FHD_IMAGE_SIZE` / `SD_SIZE_IMAGE_SCALE` / `WEB_DEFAULT_SD_SIZE_MODE` および UI の「高画質（FHD）生成」チェックボックスは削除済み。

### 画像生成APIエラーの扱い（503混雑など）

背景画像生成（Gemini / Nano Banana・Stable Diffusion WebUI の両バックエンド）の失敗は HTTP ステータスで分類し、表示と記録を分ける。**自動フォールバックは禁止**（別モデル・別バックエンド・ローカル生成へ切り替えない）。

- `core/image_generator.py` の `classify_image_api_error()` が例外から `(category, status)` を判定し、`ImageGenerationError(category, status_code, model, backend)` を送出する（nanobanana / sd_webui 両経路でラップ）。
  - `401/403` → `auth`（認証・権限）
  - `429` → `quota`（レート制限・クォータ）
  - `503` → `api_busy`（API混雑。台本・プロンプトの問題ではない。後で再実行推奨）
  - その他 → `generic`
- ログ表示はカテゴリ別。**503 は「🚧 画像生成API混雑 / 後で再実行推奨」**とし、失敗ログに 動画タイトル / 背景番号(例 4/8) / モデル / HTTPステータス / エラーメッセージ / 既存背景の再利用可否 を出す。1本でも 503 があれば「背景生成APIが混雑しています。台本やプロンプトの問題ではありません。…」を目立つ形で出す。
- **生成済み背景は破棄しない。** 失敗背景は記録のみで、再生成時に台本・背景数・プロンプトが変わっていなければ『背景再利用』で既存を再利用し未生成分だけ生成する。
- 失敗は `metadata.db` の `image_generation_failures` テーブルに記録する（`failed_index` / `total_backgrounds` / `model` / `backend` / `status_code` / `category` / `error_code` / `error_message` / `prompt` / `retry_recommended` / `failed_at`）。**`_meta/*.json` などローカルJSONは作らない。** 背景生成開始時に対象動画の旧失敗記録を `clear_image_generation_failures()` でクリアする（`record_image_generation_failure` / `get_image_generation_failures` で保存・取得）。
- エラーコードは下記「エラーコード」の中央カタログ（`E-IMG-BUSY` / `E-IMG-AUTH` / `E-IMG-QUOTA` / `E-IMG-FAIL`）を使い、ログ表示にも `[E-IMG-BUSY]` のように付与する。

### エラーコード

エラーコードと文言は `core/error_codes.py` の `ERROR_CATALOG` で一元管理する（コードは安定IDとして維持し、文言変更はここだけで行う）。

- `ErrorDef(code, message, category, retry_recommended, remediation)` を保持し、`format_error(code, detail, with_fix=False)` が `[CODE] 文言（detail）`（`with_fix=True` で末尾に ` 対処: <remediation>`）を返す。`AppError(code, detail)` はコード付き例外で、`AppError.user_message()` が「何が起きたか＋対処」をまとめて返す。
- **すべての `ERROR_CATALOG` エントリに `remediation`（具体的な対処手順）を必須化する**（製品方針: 対処不明のエラーをユーザーに出さない）。`tests/test_error_codes.py` で全エントリの remediation を検証する。
- Web の未処理 `AppError` はグローバル例外ハンドラ（`web_app/app.py`）が 422 で `{error: user_message, code, remediation, retry_recommended}` を返す。
- 未登録コードは `E-UNKNOWN` にフォールバックする（参照で落とさない）。
- 主なコード: `E-IMG-BUSY`（503混雑・再実行推奨）/ `E-IMG-AUTH`（401/403）/ `E-IMG-QUOTA`（429・レート制限/クォータ/残高）/ `E-IMG-FAIL`（画像生成その他）/ `E-SECRET-MISSING` / `E-SCRIPT-MISSING` / `E-VOICE-FAIL` / `E-RENDER-FAIL` / `E-VOICEVOX-DOWN` / `E-FFMPEG-MISSING` / `E-OLLAMA-DOWN` / `E-NET` / `E-UPLOAD-AUTH` / `E-UPLOAD-FAIL` / `E-SETUP-INCOMPLETE` / `E-LICENSE-LIMIT` / `E-DISK` / `E-UNKNOWN`。
- 画像APIの `category` → コードは `image_error_code()` で変換する。新種別を増やすときは `ERROR_CATALOG` に追記する。
- 画像生成失敗の表示は `format_image_error(code, backend=…, model=…, status_code=…, detail=…)` を使い、`[CODE] バックエンド名：文言（HTTP=… / model=… / detail）` の形にする。`backend_label()` が `nanobanana`→`Gemini` / `sd_webui`→`Stable Diffusion WebUI` に変換し、**どのバックエンドで・どの種別（混雑 / クォータ・残高 / 認証 / その他）の失敗か**を一目で判別できるようにする。残高切れと一時混雑を取り違える誤誘導文言（「接続・残高を確認」等）は使わない。
- **サムネイル生成失敗は握りつぶさず `ImageGenerationError` を上位伝播する。** `generate_thumbnail()` は失敗時に分類済み例外を投げ、`run_pipeline` 側の `_report_thumbnail_failure()` が job ログ・デバッグログ（`_logger.error` にスタックと code/backend/category/HTTP）・`image_generation_failures`（`prompt="thumbnail"`）へ判別情報つきで記録し、トレースバックを生で出さずに `finish_result` で正常終了する（背景生成失敗と同じ扱い）。

### デバッグログの内容

デバッグログは `QueueHandler` / `QueueListener` 構成で、アプリ処理スレッドはキュー投入だけを行う。ファイルは role 別に `app_debug_web.log` / `app_debug_runner.log` へ分け、1ファイル1書き手にして Windows のローテーション rename 衝突を防ぐ。`TimedRotatingFileHandler` で日次ローテートし、フォーマットは `%(asctime)s %(levelname)s [pid] %(name)s %(funcName)s:%(lineno)d: %(message)s`。秘密値は `_SecretRedactingFilter` でマスクする。

- **ジョブ失敗は必ずデバッグログに残す。** 全ジョブ（generate / render / 未知種別）が通る `runner._run_job` の funnel で、例外経路は `_logger.error(..., exc_info=…)`（スタックつき）、結果メッセージ異常経路（`_result_error_message` が ❌ / 空を検出）は `_logger.error` に記録する。完了行も `status="failed"` のときは error レベルで出す。job ログだけに出して debug ログに残さない経路を作らない。
- レンダージョブ成功時の結果には必ず `message`（`✅ MP4 生成完了: …`）を含める。これが無いと `_result_error_message` が空メッセージを失敗と誤判定する。

### Long画像節約モード

Web UI の **「Long節約」チェックボックス**（デフォルト OFF）または `WEB_DEFAULT_LONG_BUDGET_MODE` で制御する。Shorts には影響しない。

| モード | 最大新規生成数 | 用途 |
|--------|-----------|------|
| 通常（OFF） | 90枚 | 全シーン個別生成 |
| 節約（ON） | 16枚 | コスト削減 |

**上限超過時の動作**: 設定枚数を超えたシーンは前の背景をそのまま継続使用する。

**明示的再利用記法**: 台本で `背景: 前と同じ` と書いたシーンはカウントを消費せずに前の背景を継続する。重要シーン（冒頭・章タイトル・対比・オチ）に新規生成を集中させ、説明シーンは再利用するのが推奨パターン。

```
# 節約版 Long の背景割り当て例
背景: 白パンと黒パンの対比（新規生成）
...
背景: 前と同じ   ← 同じ画像を継続、生成なし
...
背景: 製粉小麦の古い工程（新規生成）
```

native 側のズーム・パン・トリミング効果と組み合わせることで、視覚的な変化を維持しながら API 呼び出しを削減できる。

### チャプターマーカー自動生成

Gemini AIがロング台本からYouTube概要欄用チャプターマーカーを生成。

---

## 出力ファイル構成

動画フォルダは `output/{profile_id}/videos/{テーマ名}/` に生成される。アップロード後は `output/{profile_id}/000_uploaded/{テーマ名}/` へ移動する。

台本本文（旧 `script.txt`）はファイルとして出力しない。`metadata.db` の `videos.script_content` が正本。

```
output/{profile_id}/videos/{テーマ名}/
├── {テーマ名}_native.mp4   # native MP4
├── thumbnails/
│   ├── thumbnail.png                       # サムネイル（Upload はこの A 案を使用）
│   ├── {テーマ名}_thumbnail_A.png          # Long: A案
│   ├── {テーマ名}_thumbnail_B.png          # Long: B案
│   └── {テーマ名}_thumbnail_C.png          # Long: C案
├── audio/
│   └── *.wav
└── backgrounds/
    └── bg_*.png
```

タイトル・説明文・タグ・レビュー・アップロード状態などの管理データは `output/{profile_id}/000_data/metadata.db` に保存する。

**アップロード記録は `metadata.db` の `youtube_status` テーブルが正本。**
予約・公開状態の正は YouTube Data API 側（`publishAt` / `privacyStatus`）。生成時に退避した `000_backups/` の同一テーマバックアップは最新1世代のみ保持し、アップロード成功後に削除する。

---

## レイヤー構成

| レイヤー | 用途 |
|---:|---|
| 0 | 背景画像 |
| 1 | トランジション |
| 2 | 固定 BGM |
| 3-4 | 立ち絵 |
| 6 | セリフ字幕 / 音声 |

---

## 立ち絵テンプレート

台本の音声スタイル指定は丸括弧、画面上の表情指定は角括弧で分離します。nativeレンダラーは生成済み表情PNGをセリフ単位で切り替えます。

```text
ずんだもん(あまあま): うれしいのだ！
ずんだもん(ツンツン): それは違うのだ！
ずんだもん(ささやき): ここだけの話なのだ。
四国めたん(あまあま): いい感じね。
四国めたん(ツンツン): ちょっと待ちなさい。
四国めたん(ささやき): ここだけの話よ。
```

表情PNGの生成・PSDレイヤー診断は `core/character_expressions.py` で行います。表情PNGの参照先は `config/config.py` の `CHARACTER_EXPRESSION_PNGS` で調整できます。

---

## 操作手順

### 初回セットアップ時のプロンプト設定

初回セットアップでは、必ずプロンプト設定を確認します。

プロンプトテンプレートは `data/settings.db` の `prompt_templates` テーブルが正本です。`config/prompt_profiles/genres/{genre_profile}/` は初期 seed 用のジャンル固有テンプレート置き場として使います。実行時のプロンプト組み立ては DB テンプレートから行います。

### 生成

1. VOICEVOXを起動し、通常はOS別の起動スクリプトでWeb UIを起動（手動起動時のみ `python -m web_app.app --open-browser` を使用）
2. 必要に応じて `📊 アナリティクス` で実績データを取得
3. `Shortsタイトル案` でタイトル案作成プロンプトをコピーし、候補を作成
4. `AI台本作成` で active profile のジャンル設定に基づく台本作成プロンプトをコピー
5. 作成した台本を Web UI の台本欄に貼り付け
6. 必要に応じて画風を選ぶ
7. `生成開始` を押す

生成中に止めたい場合は `中止` を押します。押した時点でジョブは中止扱いになり、後続処理へ進みません。外部API呼び出し（画像生成・VOICEVOX通信など）は裏で待つことがありますが、戻ってきた結果は成功扱いにしません。

主要な処理は `/logs` でジョブ状態とログを確認できます。

### Shortsタイトル案 / Longタイトル案

`Shortsタイトル案` は、既存タイトルと直近の YouTube Analytics 実績データを使って、active profile のジャンル設定に基づくタイトル案プロンプトをコピーします。`Longタイトル案` は、Long候補だけを出す条件を付けたプロンプトをコピーします。

- `metadata.db` の `analytics_snapshots` テーブルから直近データがある場合、最大80件をプロンプトへ自動差し込み
- 実績データがない場合は、実績根拠のない案を `新規開拓枠` として扱う指示を追加
- 20案の表は軽量化（13列）。詳細（選定理由・台本化理由・想定フック・冒頭1秒・注意点・事実確認ポイント）はTOP5表に集約
- タイトル分類は A〜H。H は「名前・発祥の勘違い」（天津飯・ナポリタン・シュークリーム等）
- 自分ごと化タイトル（勘違い破壊型・損回避型・日常の理由型・名前の罠型など）を20案中5〜7案混ぜる
- TOP5は、タイトル単体ではなく実績データを加味して選定。事実確認ポイント欄を必ず記入
- **採点は0〜100点満点**。点数の目安: 90〜100=逆転/勘違い破壊強・80〜89=興味はあるが弱め・70〜79=「理由」「歴史」止まり・69以下=汎用/既知ネタ
- **78点止まり判定**: 「〇〇の理由」「〇〇の歴史」「〇〇の秘密」だけで成立するタイトルは原則78点以下。TOP5に入れない。改稿必須
- **90点条件**: 名前の勘違い破壊・価値逆転・本物/偽物のズレ・海外ギャップ・身近な商品の構造・視聴者自身の勘違い・冒頭断言 のうち2つ以上を満たす場合のみ90点以上
- **汎用性チェック**: 食べ物名を別食材に置き換えても成立するタイトルは汎用タイトルとして−10点・78点判定 yes
- 20案表: `78点判定` 列 (yes/no) を追加。TOP5表: `78点判定` / `逆転要素` / `自分ごと化要素` 列を追加
- **バズ型分類**（vidIQ分析由来）: 警告型 / 感情触発型 / 行動誘発型 / 海外ギャップ型 / 通常雑学型 / キャラ主役型
  - 20案表に `バズ型` 列を追加。TOP5表に `バズ型` / `スワイプ停止理由` 列を追加
  - Long候補表にも `バズ型` / `78点判定` 列を追加。Long TOP5表に `バズ型` / `78点判定` / `事実確認ポイント` 列を追加
  - 優先順: 警告型 > 感情触発型 > 海外ギャップ型 > 行動誘発型 > 通常雑学型
  - TOP5・Long TOP5に警告型または感情触発型を2本以上含める。通常雑学型は実績根拠が強い場合のみ最大1本
  - バズ型内訳集計: 警告型＋感情触発型＋海外ギャップ型＋行動誘発型の合計12案以上（通常雑学型は最大8案）
  - 警告型は医療・健康効果の断定を禁止。食品雑学の範囲内に限定
- **採点ゲート（通常・Long共通）**: 全案に0〜100点採点・78点判定・バズ型を必須（空欄禁止）。78点未満は出力禁止
- **TOP5汎用ワード単独使用禁止**: 「実は」「意外な」「驚き」「知らなかった」「衝撃」5語の単独タイトル使用は78点未満として差し替え
- **共通 最終ゲート**: 通常20案・Long候補双方への出力直前13項目確認
- **Long候補 最終ゲート**: ロング候補指定時の13項目確認（Shorts実績深掘り方針・3幕構成必須・事実確認ポイント必須を含む）
- 実績根拠には、可能な限り `views`、`average_percentage_viewed`、`average_view_duration`、`subscribers_net`、`likes`、`comments` の数値を入れる
- 横展開では「毒だと思われていた」「危険だった」「薬だった」系、袋・容器・穴・形・名前の理由、寿司/魚の価値逆転・名前の罠を優先
- viewsだけで判断せず、平均視聴率・平均視聴時間・高評価率・登録者増を重視。高再生だけの発祥説明型は優先度を下げる
- タイトル本文へ `雑学 ショート` / `食べ物 雑学` / `ゆっくり解説 食べ物` を不自然に入れない。SEO語はタグ・説明欄で補完する
- AIO/SEO補完はタイトルではなく、説明文・タグ・ハッシュタグ・固定コメントで行う
- **説明文フォーマット**: 1行目 = `#ずんだもん #ゆっくり解説 #食べ物雑学 #食べ物の歴史 #VOICEVOX`、2行目以降 = 動画内容の自然文要約（食べ物名・意外な結論・解説内容を短く）、最後 = 固定コメントと連動するCTA。後処理で `#雑学ショート` 等の固定ハッシュタグが自動付与されるため、台本側で重複させない
- 固定コメントは要約1文 + 答えやすい質問1文にする
- **CTA二択形式**: Shortsの通常コメントCTAは原則として二択質問形式（「〇〇派か〇〇派か」）。一択の呼びかけ型（「感想をコメントして」だけ）は禁止。ループ締めが優先されるときはCTAよりループ構成を先にする。「ネタ募集CTA: 許可」時のみネタ募集CTAを使ってよい
- **タイトルと1行目の連動**: セリフ1行目はタイトルで予告した食べ物名・逆転要素・時代感と必ず一致させる。タイトル「ドリアは外国料理じゃなかった理由」なら1行目は「ドリアは日本生まれなのだ」。ズレる台本は禁止
- **TOP5汎用ワード単独使用禁止**: 「実は」「意外な」「驚き」「知らなかった」「衝撃」をタイトルの主役として単独使用することを禁止。これらだけで引っ張るタイトルは78点以下・作り直し。食べ物名＋具体的な逆転事実とセットのみ可
- vidIQ方針として当面はShorts集中。Longは主力にせず、Shortsで実績が出たネタの深掘り候補を優先する
- Shorts案は冒頭1〜3行または5秒以内にタイトルの核心を回収できるものを優先する
- Shorts案は15〜30秒地点に2つ目の驚き、逆転、具体例を入れられる構造を加点する
- コメントしやすい質問（どっち派 / 他にも知ってる / これ知ってた）へ自然につながる案を加点する
- 3選・クイズ形式は実験枠として許可するが、通常の1ネタ深掘りを主力にする
- `analysis_status=data_wait` の動画は優先度A止まり（views 3000以上・likes 30以上・comments 3以上のみ暫定S可）。実績根拠には `暫定` と明記する
- 改善再挑戦枠: views 1000以上かつ平均視聴率30〜49%（条件A）、またはviews 500以上かつlike_rate 1.5%以上（条件B）の既存食材は最大2案まで再挑戦可
- 新規開拓枠は採点7点未満を出力しない
- タイトルは30文字超の場合「意外な」「知られざる」「本当の」「ヤバすぎた」等を優先削除
- 既存食材は原則出さず、例外でも最大2案まで。TOP5には原則入れない
- 同じ横展開元からの案は20案中最大4案、TOP5中最大2案まで
- 型の内訳を20案表の直後に集計出力（自分ごと化/価値逆転/新規開拓/既存食材/改善再挑戦）

`ctr` / `impressions` が 0 または空欄の場合は評価に使わず、views・平均視聴時間・平均視聴率・登録者増減を優先します。

台本生成プロンプトには「スワイプ率対策：ネタ入口パワー判定」を入れています。台本化前に、タイトル・サムネ・冒頭1秒だけで見たくなるかを判定し、弱い場合は名前の罠、昔と今の真逆、食べ物の正体ズレ、袋・容器・包装などの具体物へ切り口を変更します。
vidIQ/Analytics分析の反映として、食べ物雑学Shortsでは1行目を「食べ物名 + 数字/期間/場所 + 意外な結論」に寄せます。疑問投げっぱなし、理由先行、衝撃事実後の説明間延び、きれいに閉じすぎる締めは低AVP型として避けます。

プロンプト文章は、固定部分と差し込み部分を分けて扱います。

- 固定部分: チャンネル方針、タイトル・サムネルール、既知ネタ除外、採点（100点満点）、Shorts / Long判定、出力形式、最終チェック
- 差し込み部分: 既存タイトル一覧、既存食材リスト、YouTube Analytics実績データ、実績サマリー、今回の生成条件

コード上では `core/script_prompts.py` の `build_title_prompt()` / `build_script_generation_prompt()` / `build_meeting_script_prompt()` が、active profile のデフォルト DB テンプレートから組み立てます。実績データ未取得時の TSV 見出しは `TITLE_ANALYTICS_TSV_HEADER` で管理します。

テンプレートの編集は設定画面「テンプレート」タブまたは `POST/PUT /api/prompt-templates` で行います。

AI編集者向けルール:

- プロンプトを変更する場合は設定画面「テンプレート」タブで直接 DB テンプレートを編集する。
- ジャンル全体の共通変更は `config/prompt_profiles/genres/{genre_profile}/` のファイルを更新し、`POST /api/prompt-templates/seed` で再 seed する（既存テンプレートはスキップされるため手動削除 → 再 seed が必要）。

タイトル・サムネの基本方針:

- タイトルは理由・経緯を伝える
- サムネは一番強い事実を短く刺す
- サムネの衝撃ワードは冒頭5秒以内に回収する
- 抽象表現だけのタイトル・サムネは禁止

### 複数台本の一括生成

次のどちらかで複数動画として扱われます。

- `---` で区切る
- `━━ 動画1：ショート版 ━━` のような見出しを付ける
- `動画形式:` が複数回出てくる

### 履歴から複数生成

`履歴から複数生成` を押すと、`output/` 配下の履歴を複数選択できます。再生成に使う台本本文は `metadata.db` の `videos.script_content`（正本）から取得します。DB に台本本文が保存済みの途中停止履歴は、MP4・サムネイル・音声・背景がまだ無くても一覧に表示し、再生成対象にできます。DB に台本本文が無い履歴は再生成対象になりません。

### 画像確認

`画像確認` を押すと、履歴を選んで以下の画像を確認・再生成できます。

- `thumbnails/thumbnail.png`
- Long動画の `thumbnail A` / `thumbnail B` / `thumbnail C`
- `backgrounds/bg_*.png`

確認画面で再生成したい画像だけ選ぶと、同じファイル名で上書きします。A案を個別再生成した場合は `thumbnail.png` もA案に同期します。

手動差し替えは、ファイル選択のほか「📋 貼り付け」ボタンでクリップボードの画像からも行える（Clipboard API、未対応時は対象を選んで Ctrl+V のフォールバック。送信は同じ multipart の `image_file` でバックエンド変更なし）。対象画像と同じサイズへ中央トリミングして上書きします。差し替え前の画像は `output/{profile_id}/000_backups/image_replacements/{local_id}/` に保存し、`metadata.db` の `image_replacements` テーブルに対象パス・バックアップパス・適用サイズ・日時を記録します。復元操作も同じ履歴テーブルへ `restore` として追記します。MP4へ反映するには差し替え後にレンダーのみ再作成が必要です。

### 動画出力

動画出力は ffmpeg/native MP4 のみを対象にします。

### YouTubeアップロード

`YouTubeアップ` は履歴選択式です。複数の履歴を選択できます。アップロード選択画面には `output/{profile_id}/videos/` 配下にある `.mp4` がある履歴フォルダだけを表示します（`000_uploaded/` 配下は表示しない）。各履歴フォルダから最新の `.mp4` を探し、`metadata.db` の `render_info` テーブルのタイトル・説明文・タグを使ってアップロードします。アップロードの可否判断はローカルステータスでブロックしない（YouTube Data API が正）。アップロード成功後は履歴フォルダを `output/{profile_id}/000_uploaded/` に移動し、`metadata.db` の `youtube_status` テーブルへ結果を記録します。予約枠の空き判断はYouTube側の予約状態を参照します。再アップロードが必要な場合はフォルダを `videos/` に手動で戻せば候補に現れます。

YouTubeタグは `core/youtube_metadata.py` で一元管理します。共通タグの先頭は常に `ずんだもん,ゆっくり解説,VOICEVOX` とし、続いて `雑学`/`雑学 ショート`/`食べ物 雑学`/`食べ物 雑学 ショート`/`食べ物雑学`/`食べ物の歴史`/`ゆっくり解説 食べ物`/`ずんだもん解説`/`四国めたん`/`VOICEVOX解説`/`トリビア`/`ショート`/`Shorts` を固定タグとして入れます。題材別タグとして、寿司系・アイス系・飲み物系・お菓子系・調味料系などをタイトルや台本本文（`metadata.db` の `videos.script_content`）から自動追加します。`食べ物 豆知識` / `食べ物豆知識` やアニメ・ゲーム・都市伝説系タグは除外します。タグ欄は500文字以内に調整します。タイトルにはSEOキーワードを無理に詰め込まず、タグ欄と説明文で補完します。

アップロード成功後の再生リスト自動登録フローは2系統あります。アップロード画面では同名の既存再生リストを「既存を活かす」または「既存を削除して作り直す」から選べます。削除して作り直す場合は YouTube 上の再生リスト自体を削除して新規作成するため、既存動画の並びは失われます（動画本体は削除しない）。

**① 台本に `再生リスト:` が指定されている場合（新方式）**

`metadata.db` の `render_info` に保存された `playlist_categories`（カテゴリ名リスト）と `screen_format`（画面形式）を参照し、`core/playlist_resolver.py` がアップロード時に実際の YouTube 再生リスト名を解決して登録します。

- Shorts / 縦: `{カテゴリ名} Shorts`
- Long / 横: `{カテゴリ名}【じっくり解説】`
- ネタ会議（縦）: `ずんだもんとめたんのネタ会議 Shorts`
- ネタ会議Long / 横: `ずんだもんとめたんのネタ会議【じっくり版】`

対象の再生リストが YouTube 上に存在しない場合は自動作成してから登録します。カンマ区切りで複数カテゴリを指定した場合はすべてに登録します。結果は `metadata.db` の `playlists` テーブルに保存します。

**② 台本に `再生リスト:` がない場合**

アップロード処理はOllama判定を実行しません。Long動画のみ、後方互換として `LONG_UPLOAD_PLAYLIST_NAME` と完全一致する再生リストへ追加します。未設定時の既定値は `ロング動画` です。空にすると無効です。Shortsには適用しません。

Ollamaによるカテゴリ判定は独立した「再生リスト振り分け」画面からユーザーが明示実行した場合だけ動作します。対象動画を選択し、「再生リスト未登録のみ実行」を有効にすると、既に `playlist_categories` が保存されている動画をスキップします。判定結果は `render_info.playlist_categories` と `video_metadata.playlist_categories` に保存します。この機能は生成・レンダー・アップロード・YouTube再生リスト登録を開始しません。

ユーザー向けの処理ログ・jobログにはスタックトレースを保存しません。処理ログにはエラーコード、失敗した処理、対象、対処手順を表示し、スタックトレースは `logging` の `exc_info=True` により role 別の `app_debug_*.log` だけへ記録します。Webプロセス、常駐runner、DB保存直前の各ログ入口でスタックトレースを除去します。

いずれの場合も、既に同じ動画が登録済みなら重複追加しません。Ollama判定はアップロード前に実行し、再生リスト作成・動画追加はアップロード成功後に実行します。再生リスト作成・追加に失敗した場合、アップロード自体は成功扱いのまま警告ログを出します。

`💬 固定コメント` は、`output/{profile_id}/000_uploaded/` 配下のアップロード済み履歴から、`youtube_status` テーブルに `video_id` がある公開済み動画を選んでコメント投稿します。候補の最終判定は YouTube Data API の現在状態を正とし、ローカルDBの `publish_status` が `scheduled` / `reserved` のまま残っていても YouTube 側が `public` なら候補に表示します。YouTube Data API で状態取得できる場合は、存在しない動画・公開済み以外の動画を一覧から除外し、公開日を表示します。投稿成功後は `youtube_status` テーブルの `fixed_comment_id` に保存します。対象一覧は「未投稿だけ」「公開済みだけ」をデフォルトにし、非公開・存在しない動画・子ども向け設定の動画は投稿前にスキップします。投稿成功時は確認用の一覧画面を表示し、通常動画URLを開けます。手動投稿後は「投稿済みにする」で `fixed_comment_posted` を記録できます。画面の「未投稿をすべて投稿済みにする」は、候補一覧の未投稿分をYouTube APIで実投稿せずローカル記録だけ一括更新します。ピン留め後は手動で「ピン留め済み」として記録できます。APIで投稿はできますが、ピン留めはYouTube Studio側で確認してください。

固定コメントは **Web UI 内では手動投稿のみ**（アプリ内に自動投稿ウォッチャーは持たない）。手動画面は active profile のみを対象にします。

**自動投稿はOSタスクのみ（アプリ非起動でも投稿）**: 自動投稿はアプリと切り離し、OS スケジューラから単発投稿を定期実行します。
- 投稿の中核は `fixed_comment_service.post_fixed_comment_now()`（job_manager / runner を介さず YouTube へ直接投稿）。手動投稿（job 経由）もこの関数を共有する。
- 二重投稿防止: YouTube API を呼ぶ**前**に `youtube_status.fixed_comment_posted` を `0→1` へ条件付き原子 UPDATE して投稿権を確保（claim）する。SQLite は書き込みを直列化するため、手動投稿とOSタスク・複数タスクが完全同時に走っても UPDATE が成立する1プロセスだけが投稿する。投稿失敗時は claim を戻して再試行可能にする。
- CLI エントリ `<exe> --post-fixed-comments`（開発時 `python -m web_app.app --post-fixed-comments`）が `auto_fixed_comment_service.post_all_pending()` を1回実行し、対象プロファイルの未投稿固定コメントを直接投稿して終了する。対象は `AUTO_FIXED_COMMENT_PROFILE_SCOPE`（`all`=全 channel profile の metadata.db と profile_id 別 YouTube OAuth token を巡回 / `active`=アクティブのみ）。
- `core/fixed_comment_task.py` が OS スケジューラへ登録/解除/検査/修復する。Windows=タスクスケジューラ（`Register-ScheduledTask`、ユーザータスク・管理者権限不要）で、非表示PowerShellからアプリを `WindowStyle Hidden` で起動し、定期実行時にコンソールを表示しない。macOS=launchd LaunchAgent（`~/Library/LaunchAgents`）。実行時刻は予約スロット時刻＋5分。
- **タスク名/ラベルにはインストールディレクトリの識別子（リーフ名＋パスのSHA1先頭8桁）を含める**ため、同一PCで複数のインストール/テストディレクトリを使い分けても区別できる。
- exe を移動すると登録済みタスクが旧パスを指したまま（迷子）になるため、`inspect()` でズレ(stale)・迷子(orphans)を検出し、アプリ起動時に `repair()` で自動修正（現在のパスで再登録＋実行ファイルが消えた迷子タスクの削除）する。設定画面の「見つけて修正」でも手動修正できる。
- **失敗は画面へ出す**: 裏で実行されるため、失敗をデバッグログだけに残すと利用者は「未実行」と「毎回失敗」を区別できない。`post_all_pending()` は実行ごとに前回結果（投稿件数・失敗件数・失敗ごとの対象と利用者向け文言）を `settings.db:background_task_runs`（`core/background_task_status.py`、task=`fixed_comment_auto_post`）へ上書き保存する。失敗が1件以上あれば全画面のヘッダーに警告を出し、固定コメント画面に一覧を表示する。次に失敗0件で実行されると表示は消える。文言は `AppError.user_message()`、投稿前チェックの `ValueError`/`FileNotFoundError` は理由付きの `E-FIXED-COMMENT-AUTO`、それ以外は例外の種類だけを付けた `E-FIXED-COMMENT-AUTO` とし、外部APIの生の応答・スタックトレースは出さない（詳細は `app_debug_fixed_comment.log`）。取得 API は `GET /api/fixed-comment/auto-status`。
- 設定画面（設定 → 製品管理タブ「固定コメント自動投稿」）でON/OFF。API は `GET /api/settings/fixed-comment-task`（状態＋stale/orphans）/ `POST /api/settings/fixed-comment-task`（`{enabled}` で登録/解除）/ `POST /api/settings/fixed-comment-task/repair`（修復）。認証は `secret_store`（DB）から読むのでアプリ非起動でも投稿できる。Windows / macOS 以外は未対応。

台本メタ情報には任意で `生成区分` / `元動画` / `目的` を書けます。`生成区分` は `新規` / `横展開` / `品質改善版` / `再挑戦` を想定します。`metadata.db` の `render_info` テーブルへ保存し、Analytics 一覧で横展開・品質改善版・再挑戦の成果を追えるようにします。

Analytics取得・画面表示・TSV出力には `dislikes`（低評価数）/ `like_dislike_total`（いいね+低評価合計）/ `dislike_rate`（低評価率 = dislikes / max(likes+dislikes, 1) × 100）を含める。`likes + dislikes < ANALYTICS_DISLIKE_RATE_MIN_REACTIONS`（デフォルト10）の場合は `dislike_rate_provisional=True` とし、画面では `*` を付けて参考値であることを示す。低評価はS/A/B/C/Dスコア判定には使わない。Analytics画面には `高評価率` に加えて `低評価(参考)` / `低評価率(参考)` / `生成区分` / `元動画` / `目的` を表示します。低評価はAPIから取得不能な場合は空欄扱いとなります。`AI分析用にコピー` と `Shortsタイトル案` / `Longタイトル案` には、対象期間・取得日時、再生数上位・平均視聴率上位・高評価率上位・data_wait注目動画をまとめた実績サマリーを付けます。`AI分析用にコピー` では `analysis_status=data_wait` の動画にも暫定評価コメントを入れるよう指示します。`Longタイトル案` はLong候補だけを出すプロンプトをコピーします。

動画別列には `登録者増`（`subscribers_gained`）と `登録者減`（`subscribers_lost`）を個別表示し、`登録者増減`（純増 = gained - lost）も並べます。サマリーバーにはチャンネル全体の登録者増減（dimension なし API 取得）を `+gained -lost 純増net` 形式で表示します。AI分析コピーの実績サマリーにもチャンネル全体の登録者増減とチャンネル注記（`ANALYTICS_CHANNEL_LEGACY_NOTE`）を含めます。Analytics画面下部には固定の注記ラベルとしてチャンネル文脈（インド広告・リメイク開始日 `ANALYTICS_CHANNEL_REMAKE_DATE`）を常時表示します。

Analytics一覧は各列のヘッダークリックで昇順/降順ソートできます。数値列は数値として、公開日時は日時として、評価列は `A > B > C > D > E > 未計測 > 対象外` の順で並び替えます。

Analytics APIは期間内に再生のある動画しか返さないため、YouTube Data API でチャンネルのアップロード済み全動画を取得してマージします。Analytics APIにまだ出ていない動画は、Data APIの `statistics` から現在の再生数・いいね数・コメント数を補完しつつ、平均視聴率などがないため `data_wait` としてスコア判定は保留します。200件を超える場合は `startIndex` によるページネーションで全件取得します。

#### 動画スコア判定ルール (`core/analytics_score.py`)

動画種別は秒数で分類します（APIの `video_type` フィールドより優先）。

| 種別 | 秒数 |
|---|---|
| Shorts | 〜60秒 |
| ShortLong | 61〜120秒 |
| Long | 121秒以上 |

各動画には `publish_status` と `analysis_status` が付与されます。

| publish_status | 意味 |
|---|---|
| published | 公開済み |
| scheduled | 公開予約中 |
| private | 非公開 |
| unlisted | 限定公開 |

| analysis_status | score | action | 重複除外対象 |
|---|---|---|---|
| analyzable | A〜E | 通常判定 | ✅ |
| underdistributed | 未計測 | 配布不足・判定保留[・反応あり] | ❌ |
| data_wait | 未計測 | データ待ち | ✅ |
| scheduled | 未計測 | 予約中 | ✅ |
| excluded | 対象外 | 対象外 | ❌ |

- 公開予約中・データ待ちは **分析（横展開判定）には使わない** が、タイトル案生成の重複除外には使う
- `build_performance_summary` は `analysis_status == "analyzable"` の動画のみ対象
- `published_at` が 2026-05-16 以前の動画は `audio_cutoff_risk = true` として、音声末尾切れの可能性がある動画として扱う
- **views < `ANALYTICS_MIN_VIEWS_FOR_SCORE`（デフォルト1000）の動画は配布不足とし、スコア判定対象外**（`analysis_status = "underdistributed"`）。ネタ失敗と誤判定しないこと。likes>=`ANALYTICS_REACTION_MIN_LIKES` または comments>=1 または subscribers_net>=1 の場合は action に `・反応あり` を補足する。

スコアは `A / B / C / D / E / 未計測 / 対象外` の7段階です。Shorts改善の主KPIは**平均視聴率（維持率）**。スワイプ率は入口の診断補助指標であり、主KPIではない。

- **Shorts**: 平均視聴率・平均視聴時間でA〜E判定
- **ShortLong**: Shortsより緩いしきい値でA〜E判定（Long扱いを避ける）
- **Long**: CTR + 平均視聴率でA〜E判定

補正ルール（ベーススコア算出後に適用）：

| 条件 | 効果 |
|---|---|
| Shorts `avg_percent < 45` / ShortLong `avg_percent < 50` | `横展開` に昇格させず `テーマ有望・構成改善` にする |
| Long `ctr < 8` または `avg_percent < 40` | 登録者増だけでは `横展開` にしない |
| `subscribers_net >= 2` かつスコアが C 未満 | スコアを C に引き上げ・action `登録者増・改善候補` |
| `subscribers_net >= 2` かつ最低視聴率ライン以上 | Shorts / ShortLong は action `横展開` |
| `subscribers_net >= 2` かつ Long の横展開条件未達 | action `登録者増・構成改善` |
| `subscribers_net >= 1` かつ弱いスコア | action に `登録導線あり` を補足 |
| `like_rate >= 1.5%` かつ最低視聴率ライン未達 | action `テーマ有望・構成改善` |
| `like_rate >= 1.5%` かつ `score in (D, E)` | action `テーマ有望・冒頭/構成改善` |
| `comments >= 1` かつ弱いスコア | action に `反応あり` を補足 |
| `views < 500` かつ公開後24時間未満 | `is_provisional = true`。横展開系actionには `(判定保留)` を付ける |
| `audio_cutoff_risk = true` かつ公開済み・分析可能な Shorts / ShortLong で `views >= 1000`、`average_percentage_viewed >= 55`、`like_rate >= 1.0`、`comments >= 1`、`subscribers_net >= 1` のいずれか | score は変えず、既存 action に `音切れ改善候補` を補足 |

ブラックリスト候補判定（`_mark_blacklist_candidate`）：

| 種別 | 条件 |
|---|---|
| Shorts/ShortLong | views >= `ANALYTICS_BL_MIN_VIEWS_SHORTS`(3000) かつ avg_pct < `ANALYTICS_BL_MAX_AVG_PCT_SHORTS`(45) かつ subscribers_net<=0 かつ like_rate < `ANALYTICS_BL_MAX_LIKE_RATE`(1.0) かつ comments==0 |
| Long | views >= `ANALYTICS_BL_MIN_VIEWS_LONG`(1000) かつ avg_pct < `ANALYTICS_BL_MAX_AVG_PCT_LONG`(30) かつ (ctr取得不可 or ctr < `ANALYTICS_BL_MAX_CTR_LONG`(5)) かつ subscribers_net<=0 かつ like_rate < 1.0 |

- ブラックリスト判定は視聴維持率・反応指標で行う。スワイプ率だけでは判定しない。
- `avoid_pattern` フィールドにタイトルから推定したネタ型パターン（歴史・由来説明型、有名ネタ消耗型、抽象理由型、驚き不足型）を付与する。
- スワイプ率データ（Viewed vs Swiped Away）は現状取得不能のため、入口診断はスキップする。

`AI分析用にコピー` / `Shortsタイトル案` / `Longタイトル案` ボタンでそれぞれのテキストをクリップボードにコピーできます。AI分析用コピーには弱い動画ランキング・ブラックリスト候補・避けるべきネタ型が含まれます。タイトル案プロンプトにはブラックリスト候補と横展開強い動画の実績が含まれ、同じネタ型・切り口を繰り返しにくくします。

views 上位20% ルール（`score_items` でまとめて適用）：

- analyzable 動画の views 80パーセンタイル以上 かつ `avg_percent >= 65` → action `横展開・微改善`
- ただし `is_provisional = true` の動画は昇格しない
- Shorts / ShortLong は最低視聴率ライン未満なら昇格しない
- ただし action が `横展開` の場合は維持

TSVには `publish_status` / `analysis_status` / `is_provisional` / `render_engine` 列を含むため、AIへのプロンプト差し込み時に予約中テーマの重複や判定保留を考慮できます。`render_engine` は `metadata.db` から取得されます。
TSVには `audio_cutoff_risk` 列も含み、2026-05-16以前の動画を品質改善版候補として再評価できるようにします。

YouTube Studio 側で予約動画を手動公開した場合:

`📅 スケジュール` を開くと自動的に YouTube API でステータスを確認し、差異があれば確認ダイアログを表示します。

- **手動公開済み検出**: `privacyStatus == "public"` になっていた動画を一覧表示し、確認後に予約スロットから削除・`youtube_status` テーブルを更新。
- **時刻ズレ修正**: ローカルと YouTube の `publishAt` が 1 分以上ズレている場合、`youtube_status` テーブルを YouTube 側の時刻に更新。
- 差異がない場合はログに「差異なし」とだけ表示してダイアログを維持。

手動で特定の動画だけを処理したい場合は、行を選択して `手動公開済みにする` ボタンを使います。

予約投稿済み動画の公開予定を変更する場合:

1. `📅 スケジュール` を開く
2. 予定状態の動画を1件選択
3. `公開予定を変更` を押す
4. 日付と時間をプルダウンから選択

この操作は YouTube の `publishAt` を更新する。対象動画には YouTube の `video_id` が必要。指定可能時刻はチャンネル別スケジュール設定から取得し、既定では Shorts が 7:00 / 12:00 / 21:00、Long が 22:00。移動先スロットに同じ動画タイプの別動画がある場合は、YouTube 側で2本の公開予定時刻を入れ替える。

予約スロットを前詰めしたい場合:

1. `📅 スケジュール` を開く
2. `スロット詰め直し計算` で変更案を確認（YouTube への書き込みなし）
3. 内容を確認して `スロット詰め直し適用` で YouTube へ反映

未来の予約枠は、最も早い空きスロットから前詰めできる。`rebalance_slots_detailed()` は YouTube の `publishAt` / `video_id` を正として読み、`update_video_publish_time()` で YouTube 側の公開予定時刻を更新する。詰め直しを実行した動画の `publish_at` は、実行時点のチャンネル別スケジュール設定に従って変更される。Shorts と Long は同じ `publishAt` を共有してよいが、同じ動画タイプ内で `publishAt` が重複している場合は詰め直し対象にする。

native Shorts の立ち絵は、腰より上が見える程度に下寄せし、左右は画面端から少し外へ出す。Shorts通常字幕は中央寄せ、既定1.4倍のフォント倍率、白文字、話者色の内フチ（ずんだもん=濃緑 / めたん=濃い紫ピンク）、黒外フチ、任意の半透明黒帯（`NATIVE_SUBTITLE_BOX_SHORTS`, `NATIVE_SUBTITLE_BOX_OPACITY_SHORTS`）で可読性を優先する。字幕は `NATIVE_SUBTITLE_Y_OFFSET_SHORTS` で少し下げる。調整は `NATIVE_CHARACTER_HEIGHT_SHORTS`、`NATIVE_CHARACTER_SIDE_MARGIN_SHORTS`、`NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS`、`CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET`、`NATIVE_SUBTITLE_FONT_SCALE`、`NATIVE_SUBTITLE_ALIGNMENT_SHORTS`、`NATIVE_SUBTITLE_Y_OFFSET_SHORTS` で行う。

---

## 台本作成ルール

### 最優先ルール
1. 冒頭1秒で衝撃事実を断言
2. 前置き・挨拶禁止
3. Shortsは1セリフ原則11〜15文字。24〜27行、本文280〜330文字を目標にし、260文字未満は禁止。平均11.5文字以上を維持する。10文字以下の短文は最大4行まで、7文字以下は原則禁止。
4. AI説明口調禁止
5. 掛け合い会話

### キャラ設定
- **ずんだもん**: ボクっ娘。語尾「〜なのだ」。情報を短く投げる役。2chまとめのレス読み上げ風に事実を小出しにする。「なお、原因は〇〇」「結果、〇〇扱い」のような型でテンポを作る。
- **四国めたん**: お嬢様口調。「〜ですわ」「〜よ」。単なる驚き役ではなく、視聴者の違和感・疑問・反論を強めに代弁するツッコミ役。「犯人そっちですの？」「昔の判断、雑すぎますわ」「完全に巻き添えですわ」のような型を使う。
- 声のスタイルは丸括弧 `()`、画面上の表情は角括弧 `[]` で分離する。例: `ずんだもん(ノーマル)[驚き]: ...` / `四国めたん(ツンツン)[ジト目]: ...`。
- 使える表情は、ずんだもん: 驚き / 焦り / 得意げ / 困惑 / にやけ、四国めたん: 驚き / 呆れ / ジト目 / ドン引き / ニヤリ。未知表情や未配置素材は生成停止せず既定表情へフォールバックする。
- 表情PNG使用中（`expression` 指定セリフの話者）は口パク・まばたきオーバーレイを両方無効化する。表情PNGはPSDから合成した専用口・目レイヤーを持つため、base.pngとの差分オーバーレイと重ねると二重口・二重目になるため。
- Shortsの強い表情変化は3〜5回までを目安にし、冒頭、原因判明、オチを優先する。全セリフへの表情指定や意味のない表情変更は禁止。

### 掛け合い品質ルール

意味のない相槌は禁止。めたんの「えっ？」「すごいですわ」「知らなかったですわ」「なるほどですわ」は単独使用禁止（必ず具体的な疑問・反論・ツッコミを付ける）。

- めたんの役割: 視聴者の疑問を先回りして言う / 雑な説明に強くツッコむ / 一般的な誤解をあえて口にする / 原因が出た瞬間に強く反応する
- めたんの推奨型: 犯人そっちですの？ / 急に雑ですわ / 昔の判断、雑すぎますわ / 急に工業製品ですわ / 見た目でだましてますわ / 完全に巻き添えですわ
- ずんだもんの役割: 1セリフ1事実で短く投げる / 「昔の人「〇〇やん」」「現代人「なんで？」」「なお、原因は〇〇」「結果、〇〇扱い」型で展開する
- レス読み上げ風の濃さ: Shorts=3〜5割（冒頭・原因・オチで積極的に使う）/ Long=1〜2割（自然な会話に寄せる）。全セリフに適用しない
- 禁止: 草・ワロタ・ンゴ・wwwの多用 / 差別語・罵倒語 / 情報が進まない掛け合い

### Shortsループ構成

最後の1〜2セリフが冒頭の衝撃事実に自然につながる。視聴者が無意識にもう一周見たくなる構成。

### vidIQ反映ルール

- 当面はShorts集中。Longは主力にせず、Shortsで実績が出たネタの深掘りを優先する
- Longを増やすより、Shortsの維持率とコメント率を優先する
- Shorts冒頭1〜3行でタイトルの核心を必ず出し、「今日は〜」「今回は〜」などの導入は禁止する
- タイトルで期待させた内容は5秒以内に回収する
- 冒頭の驚きだけで最後まで引っ張らず、15〜30秒地点に2つ目の驚き、逆転、具体例を入れる
- Shorts本編CTAは最後1行を基本とし、登録お願いよりコメントしやすい質問を優先する
- 3選・クイズ形式は実験枠として許可するが、主力は通常の1ネタ深掘りにする
- SEO語（食べ物雑学 / ゆっくり解説 / ずんだもん）はタイトルへ無理に入れず、タグ・説明欄・ハッシュタグで補完する
- 説明文冒頭1〜2行には答えが分かる自然文の要約を入れる
- Shorts冒頭1〜5秒以内に、題材と結論が分かる一文を掛け合いの中で自然に入れる
- 固定コメントは動画内容の要約1文 + コメントしやすい質問1文で構成する
- 高AVP型として、1行目は「食べ物名 + 数字/期間/場所 + 意外な結論」を優先する
- Shortsではサムネ文字・1行目・中盤の第2驚きを連動させる。1行目は原則ずんだもんが担当し、`metan_first` / `metan_otaku` の場合のみめたん冒頭を許可する
- サムネ文字が逆転ワードまたは具体ワードの場合、1行目で「食べ物名 + サムネ文字の方向性」を断言し、5秒以内に答えの入口を出す
- 15〜25秒地点に第2驚きとして、原因・真犯人・逆転事実・具体例のいずれかを置く。中盤が補足説明だけで止まる構成は禁止する
- 低AVP型として、疑問投げっぱなし・理由先行・説明間延び・きれいに終わりすぎる締めを禁止する
- 再挑戦/品質改善版は、目的欄に「何を改善したか」を書く

### CTA優先順位

コメント誘導 > 登録誘導 > 他動画誘導  
お願い口調・事務的定型文禁止。オチの流れで自然に誘導。

### 背景・テロップ

- 背景は展開が変わる時に入れる。Shortsは理想3〜5秒ごと、ロングは基本5〜7秒ごとに見た目を変える。同じ背景を10秒以上続けない
- 台本本編はシーンごとに作る。`# Scene 1: Opening hook` のような見出しを入れ、その下に `背景:`、必要なら `テロップ:`、会話をまとめる
- `# Scene ...` 行は管理用で、アプリ側では無視される
- 通常字幕は常時表示されるため、追加テロップはセリフの丸写しにしない
- 追加テロップは冒頭フック、重要ワード、章・場面転換、オチ・ツッコミだけに絞る
- Shortsの追加テロップは6〜12個、多くても15個以内。0.8〜1.5秒で短く出す
- Longの追加テロップは少なめにし、章タイトル・数字・年代・固有名詞・重要語を中心にする
- 追加テロップは下に置かない。画面中央、画面上部、右上・左上を使う
- Shortsの1枚目背景はVSA特化。食材の極端クローズアップ、強い明暗差または色差、画面上部の短い強テロップで0〜3秒のスワイプ停止を狙う
- native立ち絵と役割分離するため、背景画像内にずんだもん/めたんや人物を描かせない

### NGワード

NGワードは自動でマイルド表現へ変換されるが、タイトルや説明文は必要に応じて人間が確認する。

---

## 外部サービス依存

アプリ起動時に `core/external_service_check.py` が各サービスの起動状態と使用デバイス（GPU/CPU）を確認し、コンソールおよびデバッグログに出力する。ダッシュボードの「連携アプリ」欄の「更新」ボタンでも再確認できる。

| サービス | 用途 | 認証 |
|---|---|---|
| VOICEVOX | 音声合成 | ローカル起動 |
| Google Gemini API | 台本生成・台本チェック | `GOOGLE_API_KEY` |
| Nano Banana (Gemini) | 背景・サムネ画像生成（`IMAGE_BACKEND=gemini` のとき） | `GOOGLE_API_KEY` |
| **Stable Diffusion WebUI** | **背景・サムネ画像生成（`IMAGE_BACKEND=sd_webui` のとき）** | **ローカル起動（`--api` 必須）** |
| Ollama (qwen3:8b) | 冒頭品質レビュー・リライト | ローカル起動 |
| SudachiPy / sudachidict_core | よみがな正規化（VOICEVOX誤読対策。`VOICE_READING_MODE=safe_auto`） | ローカル（pip） |
| OpenAI API | ChatGPT生成前レビュー | `OPENAI_API_KEY` |
| YouTube Data API v3 | 動画アップロード | OAuth2（`encrypted_secrets` DB） |

### APIキー・OAuth取得

認証情報は設定画面（`/settings`）の「APIキー」タブから登録します。APIキー・OAuthトークン・YouTube client_secrets は active profile ごとに `data/settings.db` の `encrypted_secrets` テーブルへ AES-GCM で暗号化保存します。
`.env` / `client_secrets.json` / `token.json` / `token_analytics.json` は正本として使用しません。

`GOOGLE_API_KEY`:
- 取得先: https://aistudio.google.com/apikey
- 用途: Gemini台本生成、Nano Banana系の背景・サムネ画像生成
- 登録先: 設定画面「APIキー」タブの `GOOGLE_API_KEY`

`OPENAI_API_KEY`:
- 取得先: https://platform.openai.com/api-keys
- 用途: ChatGPT生成前レビュー
- 登録先: 設定画面「APIキー」タブの `OPENAI_API_KEY`
- `OPENAI_FINAL_REVIEW_ENABLED=0` にするとChatGPT生成前レビューを無効化できます。

YouTube OAuth:
- Google Cloud Console でプロジェクトを作成または選択します。
- APIライブラリで `YouTube Data API v3` と `YouTube Analytics API` を有効化します。
- 認証情報で OAuthクライアントIDを作成します。
- アプリケーションの種類は「デスクトップアプリ」を選びます。
- OAuthクライアントJSONの内容を設定画面「APIキー」タブの YouTube Client Secrets 登録欄に貼り付けて保存します。
- `YouTubeアップ` / `アナリティクス` の認証フローで取得したトークンは、それぞれ `youtube_upload_token` / `youtube_analytics_token` として DB に保存します。
- OAuth refresh 後のトークンも `save_secret()` で DB へ再保存します。`token.json` / `token_analytics.json` を恒久ファイルとして新規作成しません。
- スコープ変更や認証エラーが出た場合は、設定画面から該当する YouTube 認証情報を削除して再認証します。

取得先:
- Google Cloud APIライブラリ: https://console.cloud.google.com/apis/library
- Google Cloud 認証情報: https://console.cloud.google.com/apis/credentials

秘密情報:
- `data/settings.db` / `data/settings.db-wal` / `data/settings.db-shm` の `encrypted_secrets` 登録値
- `data/secret_master.key`
- `.env` / `client_secrets.json` / `token.json` / `token_analytics.json`
### 設定の扱い

主な設定は設定画面（`/settings`）から `data/settings.db:settings` へ保存する。定数定義と初期値は [config/config.py](config/config.py) にあり、環境変数は初期値・起動時補助として扱う。Web UIで保存できる項目は設定DBが優先され、保存後は `config_service._apply_runtime_updates()` によりアプリ再起動なしで反映する（`WEB_UI_PORT` など起動時固定パラメータを除く）。

| 設定 | 場所 | 内容 |
|---|---|---|
| 備考 | 設定DB / `config/config.py` / 環境変数 | 表中の `config.py` は `config/config.py` を指す。認証情報はこの表では扱わず `encrypted_secrets` が正本 |
| `VOICEVOX_URL` | `config.py` | VOICEVOX API のURL |
| `VOICEVOX_PATH` | `config.py` | VOICEVOX実行ファイルの場所 |
| `NATIVE_SHORTS_BODY_VOICE_SPEED` | `.env` / `config.py` | native Shorts本編の音声速度 |
| `NATIVE_SHORTS_INTRO_VOICE_SPEED` | `.env` / `config.py` | native Shorts冒頭の音声速度 |
| `NATIVE_LONG_BODY_VOICE_SPEED` | `.env` / `config.py` | native Long本編の音声速度 |
| `NATIVE_LONG_INTRO_VOICE_SPEED` | `.env` / `config.py` | native Long冒頭の音声速度 |
| `VOICE_INTRO_FAST_LINES` | `.env` / `config.py` | 冒頭高速化するセリフ行数 |
| `VOICE_POST_PHONEME_LENGTH` | `config.py` | VOICEVOX API に渡す `postPhonemeLength` |
| `OPENING_REVIEW_USE_LLM` | `.env` | Ollama冒頭レビューを使うか |
| `OLLAMA_REVIEW_MODEL` | `.env` | 冒頭レビュー用Ollamaモデル |
| `OPENING_REVIEW_AUTO_REWRITE` | `.env` | 冒頭リライトを自動実行するか |
| `OLLAMA_REWRITE_MODEL` | `.env` | 冒頭リライト用Ollamaモデル |
| `OLLAMA_REWRITE_FALLBACK_MODEL` | `.env` | 冒頭リライトのフォールバックモデル |
| `OPENING_SCORE_ABORT_THRESHOLD` | `.env` | 冒頭スコアのpass / warning表示目安 |
| `OPENING_SCORE_HARD_ABORT_THRESHOLD` | `.env` | 重大エラー扱いにするスコア |
| `OPENAI_FINAL_REVIEW_ENABLED` | `.env` | ChatGPT生成前レビューを使うか |
| `OPENAI_FINAL_REVIEW_MODEL` | `.env` | ChatGPT生成前レビューのモデル |
| `SHORT_FULL_SCRIPT_REVIEW` | `.env` | Shortsの全文レビューを行うか |
| `LONG_FULL_SCRIPT_REVIEW` | `.env` | Longの全文レビューを行うか |
| `AUTO_FULL_REWRITE_ENABLED` | `.env` | 全文自動リライトを有効化するか |
| `GEMINI_MODEL` | `.env` / `config.py` | 台本生成で使うGeminiモデル |
| `NANOBANANA_PRO_MODEL` | `.env` / `config.py` | 高品質画像生成モデル |
| `NANOBANANA_FLASH_MODEL` | `.env` / `config.py` | 速い画像生成モデル |
| `IMAGE_BACKEND` | `.env` / `config.py` | 画像生成バックエンド主スイッチ。`gemini`（デフォルト）または `sd_webui` |
| `SD_WEBUI_BASE_URL` | `.env` / `config.py` | Stable Diffusion WebUI API URL |
| `SD_WEBUI_TIMEOUT_SEC` | `.env` / `config.py` | Stable Diffusion WebUI API タイムアウト(秒) |
| `SD_WEBUI_MODEL` | `.env` / `config.py` | Stable Diffusion WebUI で使うモデル名（空=起動中モデルをそのまま使用） |
| `SD_WEBUI_SAMPLER` | `.env` / `config.py` | Stable Diffusion WebUI サンプラー名 |
| `SD_WEBUI_STEPS` | `.env` / `config.py` | Stable Diffusion WebUI 生成ステップ数 |
| `SD_WEBUI_CFG_SCALE` | `.env` / `config.py` | Stable Diffusion WebUI CFGスケール |
| `SD_WEBUI_WIDTH` | `.env` / `config.py` | Stable Diffusion WebUI 出力幅(px)（横動画基準） |
| `SD_WEBUI_HEIGHT` | `.env` / `config.py` | Stable Diffusion WebUI 出力高さ(px)（横動画基準） |
| `SD_WEBUI_NEGATIVE_PROMPT` | `.env` / `config.py` | Stable Diffusion WebUI ネガティブプロンプト（人物・低品質抑制） |
| `CHARACTERS` | `config.py` | VOICEVOX話者ID・スタイルID |
| `CHARACTER_FOOD_TOXIC_GENRE_PROFILES` | `.env` / `config.py` | キャラクターseed時に「辛口相方めたん」を既定有効にする genre_profile のカンマ区切り |
| `CHARACTER_PNGS` | `config.py` | native合成用キャラ立ち絵 |
| `CHARACTER_EXPRESSION_PNGS` | `config.py` | native表情指定用PNG。素材未配置時は既定立ち絵へフォールバック |
| `THUMBNAIL_CHARACTER_PNGS` | `config.py` | サムネ生成用参照画像 |
| `THUMBNAIL_HOLD_FRAMES_SHORTS` | `config.py` / `.env` | Shorts先頭サムネ保持フレーム数。1〜5（30fps換算: 1=0.033s / 3=0.100s / 5=0.167s）。デフォルト3。不正値は3、範囲外は1〜5にクランプ。Long非対応 |
| `BGM_FILE` | `config.py` | 旧BGMファイル名。BGM未登録チャンネルの初回移行用としてのみ使用 |
| `NATIVE_BGM_VOLUME_DB` | `.env` / `config.py` | native出力のBGM音量(dB) |
| `NATIVE_ENABLE_MOTION_EFFECTS` | `.env` / `config.py` | native Shorts軽量エフェクト全体の有効/無効 |
| `NATIVE_ENABLE_BG_KEN_BURNS` | `.env` / `config.py` | 背景画像のゆっくりズーム/パン |
| `NATIVE_ENABLE_CHARACTER_BOUNCE` | `.env` / `config.py` | セリフ開始時の話者キャラバウンス |
| `NATIVE_ENABLE_TALK_WIGGLE` | 設定DB / 設定画面 | 発話中の話者キャラ小刻み揺れ |
| `NATIVE_ENABLE_POP_TELOP` | `.env` / `config.py` | `テロップ:` 行のポップ表示 |
| `NATIVE_ENABLE_SHAKE` | `.env` / `config.py` | 短いツッコミ/驚き場面のシェイク |
| `NATIVE_MAX_SHAKE_COUNT_SHORTS` | 設定DB / 設定画面 | Shorts 1本あたりのシェイク最大回数 |
| `NATIVE_MAX_ICON_COUNT_SHORTS` | 設定DB / 設定画面 | Shorts 1本あたりの疑問/驚きアイコン最大回数 |
| `NATIVE_REACTION_EFFECT_MIN_GAP_SEGMENTS` | 設定DB / 設定画面 | シェイク/アイコンを再表示するまでの最低セリフ間隔 |
| `NATIVE_BG_ZOOM_MAX` | `.env` / `config.py` | 背景Ken Burnsの最大拡大倍率 |
| `NATIVE_TALK_WIGGLE_X_PX` | 設定DB / 設定画面 | 発話中キャラ揺れの左右振幅(px) |
| `NATIVE_TALK_WIGGLE_Y_PX` | 設定DB / 設定画面 | 発話中キャラ揺れの上下振幅(px) |
| `NATIVE_TALK_WIGGLE_HZ` | 設定DB / 設定画面 | 発話中キャラ揺れの周波数(Hz) |
| `NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS` | 設定DB / 設定画面 | 発話中キャラ揺れを何セリフに1回出すか |
| `CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET` | 設定DB / 設定画面 | Shorts 腰上表示の下方向シフト量(px) |
| `CHARACTER_UPPER_BODY_LONG_Y_OFFSET` | 設定DB / 設定画面 | Long 腰上表示の下方向シフト量(px) |
| `NATIVE_CHARACTER_SIDE_MARGIN_SHORTS` | 設定DB / 設定画面 | Shorts キャラ左右マージン(px、負値で画面外) |
| `NATIVE_CHARACTER_SIDE_MARGIN_LONG` | 設定DB / 設定画面 | Long キャラ左右マージン(px、負値で画面外) |
| `WEB_APP_NAME` | `.env` / `config.py` | Web UIの表示アプリ名 |
| `WEB_UI_HOST` | `.env` / `config.py` | Web UIのバインドホスト。既定は `127.0.0.1` |
| `WEB_UI_PORT` | `.env` / `config.py` | Web UIのポート番号 |
| `WEB_DEFAULT_IMAGE_STYLE` | `.env` / `config.py` | Web UI生成画面の既定画像スタイル |
| `WEB_IMAGE_STYLE_CHOICES` | `.env` / `config.py` | Web UI生成画面の画像スタイル選択肢（正本はカンマ区切り）。互換のため引用符付き値・Python/JSON配列風の値も読み込み時に正規化する |
| `WEB_DEFAULT_REUSE_BACKGROUNDS` | `.env` / `config.py` | Web UI生成画面の背景再利用既定値 |
| `WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST` | `.env` / `config.py` | Web UI生成画面のLongサムネAB既定値 |
| `WEB_DEFAULT_LONG_BUDGET_MODE` | `.env` / `config.py` | Web UI生成画面のLong節約既定値 |
| `AUTO_FIXED_COMMENT_PROFILE_SCOPE` | `.env` / `config.py` | 固定コメント自動投稿の対象。`all`=全チャンネル、`active`=アクティブのみ |
| `WEB_JOB_POLL_INTERVAL_MS` | `.env` / `config.py` | Web UIのジョブ状態更新間隔(ms) |
| `WEB_SUCCESS_RELOAD_DELAY_MS` | `.env` / `config.py` | Web UIのジョブ成功後再読み込み待ち時間(ms) |
| `WEB_TOAST_VISIBLE_MS` | `.env` / `config.py` | Web UIのトースト表示時間(ms) |
| `WEB_TOAST_HIDE_DELAY_MS` | `.env` / `config.py` | Web UIのトースト非表示待ち時間(ms) |
| `WEB_VOICEVOX_CHECK_TIMEOUT_SEC` | `.env` / `config.py` | Web UIのVOICEVOX疎通確認タイムアウト(秒) |
| `WEB_FFMPEG_CHECK_TIMEOUT_SEC` | `.env` / `config.py` | Web UIのffmpeg疎通確認タイムアウト(秒) |
| `NATIVE_FFMPEG_TIMEOUT_SEC` | `.env` / `config.py` | nativeレンダーのffmpeg 1コマンド最大実行秒数 |
| `NATIVE_FFPROBE_TIMEOUT_SEC` | `.env` / `config.py` | nativeレンダーのffprobe 最大実行秒数 |
| `MAX_BACKGROUNDS_SHORTS` | `config.py` | Shortsの最大背景生成枚数 |
| `MAX_BACKGROUNDS_LONG` | `config.py` | Longの最大背景生成枚数 |
| `LONG_UPLOAD_PLAYLIST_NAME` | `.env` / `config.py` | Longアップロード後に自動追加する再生リスト名。未設定時は `ロング動画`。完全一致で検索 |
| `TOPIC_REQUEST_CTA_EVERY_N` | `.env` / `config.py` | Shorts新規/横展開のネタ募集CTAを通算何本に1本許可するか。未設定時は5。0なら自動付与しない |

## CTA / 導線制御

- Shortsは本編内の他動画誘導より、完走率・平均視聴率・ループ視聴を優先する。
- Shortsの `次回は` / `次の動画` / `他の動画も見て` / `チャンネル登録お願いします` / `高評価お願いします` は生成前チェックで警告する。
- `core/cta_policy.py` が生成登録時に `ネタ募集CTA: 許可 / 禁止` を判定する。Shortsかつ生成区分が `新規` / `横展開` の対象を既存出力から通算し、`TOPIC_REQUEST_CTA_EVERY_N`（既定5）本に1本だけ許可する。`TOPIC_REQUEST_CTA_EVERY_N=0` の場合は自動付与しない。
- ネタ募集CTAを許可した台本で固定コメントが未指定なら、ネタ募集用固定コメントを自動差し込みする。
- Longでは関連動画誘導・vidIQタイトル調整・説明欄YouTubeチャプター追加を許可する。アップロード時に `チャプター:` 行または既定章立てから `【目次】` を説明欄末尾へ追加する。
- CTA方針とアップロード時のYouTubeメタ方針は `metadata.db` に保存する。YouTube Analytics取得時は `ネタ募集CTA` / `ネタ募集CTA理由` を取り込み、Analytics画面とTSVで確認できるようにする。

## チャンネルプロファイル管理（複数チャンネル対応）

チャンネル単位の設定を `channel_profiles` テーブル（`data/settings.db`）で管理する。
active profile によってすべての出力パス・DB・プロンプト・Analytics・再生リストが切り替わる。

### `channel_profiles` テーブル

| カラム | 型 | 説明 |
|---|---|---|
| `profile_id` | TEXT PK | チャンネルハンドルから `@` を除いた値（例: `zundamon_kowai`） |
| `channel_name` | TEXT | チャンネル表示名（必須） |
| `channel_handle` | TEXT | `@` で始まるハンドル |
| `genre_profile` | TEXT | `profile_id` と同じ値。保存時に既存ジャンルから `config/prompt_profiles/genres/{profile_id}/` を作成する |
| `output_root` | TEXT | `profile_id` と同じ値。実パスは `output/{profile_id}` に解決する |
| `default_hashtags` | TEXT | デフォルトハッシュタグ |
| `channel_theme` | TEXT | テーマ説明（UI バナー表示用） |
| `channel_accent_color` | TEXT | UI アクセント色（#RRGGBB） |
| `is_active` | INTEGER | 1 のプロファイルが active（必ず1件のみ） |
| `created_at` / `updated_at` | TEXT | ISO8601 UTC |

### `channel_schedule_settings` テーブル（`data/settings.db`）

チャンネル別の投稿予約スロットを管理する。新規予約・公開予定変更候補・スロット詰め直しは active profile のこの設定を使う。既定値は全チャンネル共通で Shorts が 12:00 / 21:00、Long が 22:00、タイムゾーンは Asia/Tokyo。

| カラム | 型 | 説明 |
|---|---|---|
| `profile_id` | TEXT PK | channel_profiles.profile_id |
| `timezone_name` | TEXT | IANA タイムゾーン名（既定 `Asia/Tokyo`） |
| `shorts_slot_hours` | TEXT | Shorts の時刻リスト（例 `12:00,21:00`） |
| `long_slot_hours` | TEXT | Long の時刻リスト（例 `22:00`） |
| `created_at` / `updated_at` | TEXT | ISO8601 UTC |

### 出力ディレクトリ構造（profile 別）

```
{出力ベース}/{profile_id}/
  videos/        ← 動画テーマフォルダ（Shorts_xxx / Long_xxx）。生成中・未アップロード
  000_uploaded/  ← YouTube アップロード済みアーカイブ（履歴画面でも表示）
  000_backups/   ← バックアップ
  000_data/      ← metadata.db（動画メタ・Analytics・youtube_status 等すべて格納）
```

**出力ベースディレクトリ**は全プロファイル共通の親フォルダで、既定はリポジトリ直下の `output/` 。設定 `OUTPUT_BASE_DIR`（設定 DB に保存）で別ドライブ等へ変更できる。`core/output_paths.py` の `output_base_dir()` が解決し、各 profile の `output_root` はこの直下に置かれる。変更は次の入口で行う:

- 初回セットアップ画面「7. 出力先フォルダ」（既定値として現状パスを表示）
- 設定画面 → 製品管理タブ「出力先フォルダ」
- API `GET /api/settings/output-base`（現在値・既定値・カスタムか）/ `POST /api/settings/output-base`（`confirmed=true` 必須）

変更時は `output_paths.relocate_output_base()` が既存の出力一式（各 profile フォルダ・metadata.db）を新ベースへ移動し、`OUTPUT_BASE_DIR` を設定 DB に保存して即時反映する。**実行中/待機中ジョブがある場合は移動せず 409 で拒否**する（runner が metadata.db を掴んでいる間の移動による破損を防ぐため）。移動先に同名フォルダが既存なら拒否、現ベースとの入れ子指定も拒否する。

生成時のフォルダ名は設定値 `FOLDER_PREFIX_SHORTS` / `FOLDER_PREFIX_LONG` / `FOLDER_PREFIX_MEETING` に正規化する。旧表記の `short_` / `shorts_` / `long_` / `meeting_` は読み取り・履歴・アップロード判定では後方互換として受け入れるが、新規生成では設定済みプレフィックスへ直す。

Analytics データは `metadata.db` の `analytics_snapshots` テーブルに格納する。

### API

- `GET /api/channels` — プロファイル一覧（is_active 先頭、認証状態と投稿予約スロット設定を含む）
- `GET /api/channels/current` — アクティブプロファイル + OAuth 登録状態（bool のみ）
- `POST /api/channels` — 作成。チャンネル別投稿予約スロットも同時保存
- `PUT /api/channels/{id}` — 更新。チャンネル別投稿予約スロットも同時保存
- `POST /api/channels/{id}/activate` — アクティブ化（トランザクションで is_active を排他切替）
- `POST /api/channels/{id}/validate` — プロファイル + genre_profile の存在チェック
- `DELETE /api/channels/{id}` — 削除（confirmed=true 必須。アクティブは削除不可）
- `GET /api/channels/prompt-profiles` — 利用可能な genre_profile 一覧

既存 DB で `profile_id` / `genre_profile` / `output_root` がチャンネルハンドルと異なる場合は、`channel_handle` を正として `@` なしのハンドル名へ移行する。関連する `encrypted_secrets` / `prompt_templates` / `bgm_assets` の `profile_id` も同時に移行し、既存の genre_profile フォルダはハンドル名へコピーする。
旧仕様で `default` に保存されていた `google_api_key` / `openai_api_key` / `hf_token` / `youtube_client_secrets` は、未登録の各 channel profile へ暗号化済みのままコピーする。YouTube OAuth token はチャンネル固有のためコピーしない。
既存チャンネルに `channel_schedule_settings` がない場合は起動・保存時に自動作成する。2026-06-06 のスロット変更では、既存チャンネルの設定も Shorts 12:00 / 21:00、Long 22:00 へ更新する。

### `prompt_templates` テーブル（`data/settings.db`）

プロンプトテンプレートは channel profile 単位で管理する。テンプレートの使用可否は `profile_id` が主キー。

| カラム | 型 | 説明 |
|---|---|---|
| `template_id` | TEXT PK | UUID |
| `profile_id` | TEXT FK | channel_profiles.profile_id |
| `template_name` | TEXT | テンプレート名（profile_id 内でユニーク） |
| `template_kind` | TEXT | `script` / `title` / `meeting` |
| `genre_profile` | TEXT | 参考情報（seed 元ジャンル）。使用可否の主キーは profile_id |
| `is_default` | INTEGER | (profile_id, template_kind) 単位で1件のみ |
| `is_enabled` | INTEGER | 0=無効 |
| `system_rules` | TEXT | ジャンル固有のチャンネルルール（script_context.md 相当） |
| `script_rules` | TEXT | 共通ルール（script 種別のみ・COMMON_SCRIPT_RULES 等） |
| `title_rules` | TEXT | タイトル案ルール（title 種別のみ） |
| `meeting_rules` | TEXT | ネタ会議共通ルール（meeting 種別のみ） |
| `ng_rules` | TEXT | NG ルール（任意） |
| `default_hashtags` | TEXT | デフォルトハッシュタグ |
| `default_playlist_category` | TEXT | デフォルト再生リストカテゴリ |
| `created_at` / `updated_at` | TEXT | ISO8601 |

制約: `(profile_id, template_kind)` に `is_default=1` は UNIQUE partial index で保証。

#### API

- `GET /api/prompt-templates` — active profile のテンプレート一覧（`?kind=script` で絞り込み可）
- `POST /api/prompt-templates` — active profile にテンプレート作成
- `GET /api/prompt-templates/{id}` — 取得（active profile 所属のみ）
- `PUT /api/prompt-templates/{id}` — 更新（active profile 所属のみ）
- `POST /api/prompt-templates/{id}/set-default` — デフォルト設定
- `POST /api/prompt-templates/{id}/clone` — 別 profile へ複製
- `DELETE /api/prompt-templates/{id}` — 削除（active profile 所属のみ）
- `POST /api/prompt-templates/seed` — 全 profile へのファイルからの seed 実行（冪等）

別 profile の template_id を指定した場合は 403 を返す。

### プロンプトプロファイル構成

```
config/prompt_profiles/
  genres/
    food_trivia/
      profile.yaml          ← genre_profile 設定（hashtag / playlist suffix 等）
      script_context.md     ← チャンネルコンテキスト・方針・タグルール
      title_context.md      ← タイトル案生成プロンプト
      meeting_context.md    ← ネタ会議プロンプト
      playlist_categories.md← 再生リストカテゴリ名
      used_topics.txt       ← 使用済みトピック
    urban_legend/           ← 同構成
    zundamon_kowai/         ← 同構成
      channel_description.md← YouTubeチャンネル説明文
      shorts_description.md ← Shorts投稿時の既定説明文
      long_description.md   ← Long投稿時の既定説明文
      ng_rules.md           ← 実話・地名・事件の断定を防ぐ専用NGルール
    zunkami/                ← 同構成
```

`genres/{genre_profile}/` ファイルは起動時 seed 専用。実行時は DB テンプレートを参照する。genre_profile が存在しない場合はエラー停止（別ジャンルへのフォールバック禁止）。

#### `zundamon_kowai` の怪談寄り移行

- 既存の都市伝説動画・履歴・再生リストカテゴリは削除しない。新規生成だけを怪談寄りへ段階移行する。
- 生成比率の目安は、実話ベース・真偽不明怪談35%、地域・場所怪談25%、昭和平成の噂20%、有名都市伝説15%、創作怪談・意味怖5%。
- ネタ出しとタイトル案では「実話風怪談」「地域怪談」「昭和平成の噂」「ネット実話系怪談」「場所怪談」を利用し、既存テーマ重複を避ける。実績が弱い案は「新規開拓枠」と明記し、TOP5には横展開元と実績根拠数値を含める。
- Shortsは24〜27セリフ、本文280〜330文字、平均11.5文字以上、10文字以下4行以内を維持し、怖い核を1つに絞る。真偽不明表現、広まった理由、最後の余韻を必須とする。
- Longは怪談の基本形、類似パターン、実話らしく語られた理由、真偽不明点、現実的説明、広まった理由、怖さの本質を扱い、犯罪事件解説へ寄せない。
- 投稿時の説明文は `shorts_description.md` / `long_description.md` をそのまま使用し、怪談向け免責、VOICEVOXクレジット、形式別ハッシュタグを統一する。
- 起動時seedは旧都市伝説テンプレートを削除・上書きせず、「怪談寄り」台本・タイトル・ネタ会議テンプレートを追加してデフォルトにする。既に怪談寄りテンプレートがある場合だけ内容を更新する。
- 生成前チェックは実話・死亡・呪い・危険・犯人などの断定表現をエラーにし、真偽不明・噂・怪談としての表現がない台本もエラーにする。このチェックは `zundamon_kowai` のみに適用し、`zunkami` へ影響させない。
- 動画タグは先頭を `ずんだもん,ゆっくり解説,VOICEVOX` に固定し、怪談向け基本タグと題材別タグを合わせて10〜15件にする。雑学・豆知識・トリビア・食べ物系タグは生成時とYouTubeアップロード直前の両方で除去する。この正規化は `zundamon_kowai` のみに適用する。

### チャンネル登録・設定

チャンネルは設定画面の「チャンネル」タブまたは `/api/channels` で登録する。保存時に `channel_handle` から `@` を除いた小文字を `profile_id` として使い、`genre_profile` と `output_root` も同じ値へ統一する。チャンネル固有の APIキー・YouTube client_secrets・BGM・投稿予約スロットは profile_id 単位で保存する。

- Web UI 全画面上部のバナー（sticky）に active channel 名・ハンドルを常時表示する。ドロップダウンで別チャンネルへ切替可能。
- 切替ボタン押下 → `POST /api/channels/{id}/activate` → 成功後 `location.reload()` で全画面更新。
- active channel がない場合は「チャンネル未設定」エラーをバナーに表示。YouTube 操作（アップロード・Analytics）は不可。
- 設定画面の「チャンネル」タブ（`/settings#channels`）でチャンネルの追加・編集・削除・切替が可能。
- アップロード API（`POST /api/upload`、`POST /api/upload/batch`）はチャンネル未設定時に `400` を返す。

## DB アーキテクチャ

### 概要

すべての状態を SQLite で管理する。

| DB ファイル | 用途 |
|---|---|
| `output/{profile_id}/000_data/metadata.db` | 動画メタデータ・YouTube 状態・Analytics・ジョブ履歴（profile 別） |
| `data/settings.db` | アプリ設定（非認証情報）+ 認証情報（AES-GCM暗号化） |

### 認証情報管理 (`data/settings.db` — `encrypted_secrets` テーブル)

APIキー・OAuthトークン・client_secrets を AES-GCM で暗号化して保存する。
`.env` / `client_secrets.json` / `token.json` / `token_analytics.json` は認証情報の正本として使用しない。

#### マスターキー管理

| 環境 | 方式 |
|---|---|
| Windows | DPAPI (`CryptProtectData`) で保護した `data/secret_master.key` |
| macOS/Linux | `keyring` / `NVF_MASTER_KEY` 環境変数（hex 32 byte） |

マスターキーが取得できない場合は fail closed（保存・読み込み不可）。

#### `encrypted_secrets` テーブル

| 列 | 型 | 説明 |
|---|---|---|
| `secret_id` | TEXT PK | `SHA256(profile_id:secret_type)[:32]` |
| `profile_id` | TEXT | チャンネル識別子（チャンネルハンドルから `@` を除いた値） |
| `secret_type` | TEXT | `google_api_key` / `openai_api_key` / `hf_token` / `youtube_client_secrets` / `youtube_upload_token` / `youtube_analytics_token` |
| `encrypted_value` | BLOB | AES-GCM 暗号文 |
| `nonce` | BLOB | 12 byte ランダム nonce（保存ごとに新規生成） |
| `salt` | BLOB | 将来の鍵導出用（現在は NULL） |
| `key_version` | INTEGER | マスターキーバージョン（現在は 1） |
| `created_at` | TEXT | ISO8601 UTC |
| `updated_at` | TEXT | ISO8601 UTC |

**仕様:**
- `load_secret()` 以外では復号しない
- 復号した値をログ・レスポンス・例外メッセージに含めない
- OAuth/API 呼び出し直前にのみ復号する
- `has_secret()` は DB 存在確認のみ（復号しない）
- OAuth refresh 後のトークンは `save_secret()` で DB へ再保存する
- `token.json` / `token_analytics.json` を恒久ファイルとして新規作成しない

### DB 正本仕様

- 動画メタ・YouTube 状態・Analytics・ジョブ履歴は `metadata.db` が正本。
- アプリ設定と認証情報は `data/settings.db` が正本。
- 認証情報の値をログ・レスポンス・例外メッセージに含めない。

| 旧ファイル | 現行の保存先 | 状態 |
|---|---|---|
| `.env`（認証情報） | `data/settings.db`（`encrypted_secrets` テーブル・AES-GCM暗号化） | 廃止完了 |
| `client_secrets.json` / `token.json` / `token_analytics.json` | `data/settings.db`（`encrypted_secrets` テーブル） | 廃止完了 |

---

### `output/{profile_id}/000_data/metadata.db` テーブル定義

現在のスキーマバージョン: **7**

#### `videos` — 動画基本情報

| 列 | 型 | 説明 |
|---|---|---|
| `local_id` | TEXT PK | 出力フォルダ名（例: `Shorts_りんご_20260601_abc123`） |
| `output_dir` | TEXT | 絶対パス |
| `title` | TEXT | 動画タイトル |
| `video_type` | TEXT | Shorts / Long / ネタ会議_Shorts など |
| `created_at` | TEXT | JST ISO 8601 |
| `updated_at` | TEXT | JST ISO 8601 |
| `script_path` | TEXT | 旧 `script.txt` の絶対パス（廃止済み・新規行は未設定/NULL） |
| `mp4_path` | TEXT | 生成 MP4 の絶対パス |
| `thumbnail_path` | TEXT | サムネイル PNG パス |
| `script_content` | TEXT | 台本本文の正本（v2 追加）。`script.txt` ファイルは廃止し、本カラムが唯一の正本 |

#### `render_info` — レンダリング設定・メタデータ

| 列 | 型 | 説明 |
|---|---|---|
| `local_id` | TEXT PK | 動画フォルダ名 |
| `render_engine` | TEXT | "native" |
| `video_title` | TEXT | YouTube タイトル |
| `description` | TEXT | YouTube 説明文 |
| `tags` | TEXT | JSON 配列 |
| `video_format` | TEXT | "Shorts" / "Long" |
| `screen_format` | TEXT | "vertical" / "horizontal" |
| `playlist_categories` | TEXT | JSON 配列 |
| `native_renderer_json` | TEXT | native レンダラー設定（JSON） |
| `estimated_duration_sec` | REAL | 推定尺（秒） |
| `actual_duration_sec` | REAL | 実際の尺（秒） |
| `actual_duration_status` | TEXT | "ideal" / "ok_but_short" など |
| `loudnorm_enabled` | INTEGER | 0/1 |
| `loudnorm_i` / `loudnorm_tp` / `loudnorm_lra` | REAL | loudnorm 設定値 |
| `motion_effects_enabled` | INTEGER | 0/1 |
| `motion_effects_fallback_count` | INTEGER | fallback セグメント数 |
| `bgm_mode` | TEXT | `profile_default` / `selected` / `none` |
| `bgm_id` | TEXT | `bgm_assets.bgm_id` |
| `bgm_display_name` | TEXT | レンダー時のBGM表示名 |
| `bgm_file_path` | TEXT | レンダー時のBGM実ファイル |
| `bgm_volume_db` | REAL | レンダー時のBGM音量(dB) |
| `bgm_loop_enabled` | INTEGER | 0/1 |

#### `image_replacements` — 画像手動差し替え履歴

| 列 | 型 | 説明 |
|---|---|---|
| `id` | INTEGER PK | 差し替え履歴ID |
| `local_id` | TEXT | 動画フォルダ名 |
| `target_rel_path` | TEXT | 差し替え対象の相対パス |
| `target_kind` | TEXT | `thumbnail` / `thumbnail_ab` / `background` |
| `source_type` | TEXT | `manual_upload` / `restore` |
| `backup_file_path` | TEXT | 復元用バックアップ画像 |
| `applied_file_path` | TEXT | 適用先画像 |
| `original_width` / `original_height` | INTEGER | 適用前サイズ |
| `applied_width` / `applied_height` | INTEGER | 適用後サイズ |
| `status` | TEXT | `applied` / `restored` |
| `created_at` | TEXT | 実行日時 |
| `note` | TEXT | 補足 |

#### `bgm_assets` — チャンネル別BGM（`data/settings.db`）

| 列 | 型 | 説明 |
|---|---|---|
| `bgm_id` | TEXT PK | BGM ID |
| `profile_id` | TEXT | channel profile ID |
| `display_name` | TEXT | 表示名 |
| `file_path` | TEXT | profile 配下へコピーした実ファイル |
| `default_volume_db` | REAL | 既定音量(dB) |
| `loop_enabled` | INTEGER | 0/1 |
| `is_enabled` | INTEGER | 0/1 |
| `is_default` | INTEGER | チャンネル既定BGMなら1 |
| `duration_sec` | REAL | ffprobe で取得した再生時間 |
| `created_at` / `updated_at` | TEXT | 登録・更新日時 |

#### `video_metadata` — 台本由来のメタ情報・CTA ポリシー

| 列 | 型 | 説明 |
|---|---|---|
| `local_id` | TEXT PK FK→videos | |
| `food_name` | TEXT | 食材・トピック名 |
| `topic_key` | TEXT | トピックキー |
| `genre` | TEXT | ジャンル |
| `character_pattern` | TEXT | キャラ構成パターン |
| `generation_type` | TEXT | 新規 / 横展開 / 品質改善版 など |
| `source_video_title` | TEXT | 横展開元タイトル |
| `purpose` | TEXT | 生成目的 |
| `thumbnail_text` | TEXT | サムネイルテキスト |
| `fixed_comment` | TEXT | 固定コメント |
| `description` | TEXT | YouTube 説明文 |
| `tags` | TEXT | JSON 配列 |
| `playlist_categories` | TEXT | JSON 配列 |
| `video_format` | TEXT | Shorts / Long |
| `screen_format` | TEXT | |
| `cta_shorts_loop_priority` | INTEGER | 0/1（v4） |
| `cta_direct_next_video_allowed` | INTEGER | 0/1（v4） |
| `cta_topic_request` | TEXT | "blocked" / "allowed"（v4） |
| `cta_topic_request_reason` | TEXT | （v4） |
| `cta_final_type` | TEXT | "loop" / "channel"（v4） |

#### `youtube_status` — YouTube 投稿・公開状態

| 列 | 型 | 説明 |
|---|---|---|
| `local_id` | TEXT PK FK→videos | |
| `youtube_video_id` | TEXT UNIQUE | YouTube 動画 ID |
| `publish_status` | TEXT | "private" / "scheduled" / "published" |
| `publish_at` | TEXT | 公開予定日時（JST ISO 8601） |
| `uploaded_at` | TEXT | アップロード日時 |
| `published_at` | TEXT | 実際の公開日時 |
| `privacy_status` | TEXT | |
| `fixed_comment_posted` | INTEGER | 0/1 |
| `fixed_comment_id` | TEXT | |
| `playlist_registered` | INTEGER | 0/1 |

#### `analytics_snapshots` — YouTube Analytics スナップショット

| 列 | 型 | 説明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `youtube_video_id` | TEXT | |
| `collected_at` | TEXT | 取得日時（JST ISO 8601） |
| `window_days` | INTEGER | 集計期間（日数） |
| `views` | INTEGER | |
| `average_view_duration` | REAL | 秒 |
| `average_percentage_viewed` | REAL | % |
| `likes` / `dislikes` | INTEGER | （v3） |
| `comments` | INTEGER | |
| `subscribers_gained` / `subscribers_lost` / `subscribers_net` | INTEGER | （v3） |
| `impressions` / `ctr` | INTEGER / REAL | （v3） |
| `like_rate` / `dislike_rate` | REAL | （v3） |
| `score` | TEXT | "S" / "A" / "B" / "C" など |
| `action` | TEXT | "継続" / "改善" など |
| `analysis_status` | TEXT | |
| `is_provisional` / `audio_cutoff_risk` / `blacklist_candidate` | INTEGER | 0/1（v3） |
| `weak_reason` / `avoid_pattern` | TEXT | （v3） |
| UNIQUE | `(youtube_video_id, collected_at, window_days)` | |

Analytics 取得（`save_score_files()`）のたびに自動 upsert される。

YouTube Data API を正としてDBを補完・更新する場合は `sync_youtube_statuses_from_api(delete_missing=True)` を使う。YouTube側で手動変更されたタイトル・公開状態・公開予定日時・実公開日時・動画種別は `videos` / `render_info` / `youtube_status` に書き戻す。YouTube側で削除済みの既知動画IDは `delete_missing=True` 指定時にDBから関連レコードごと削除する。

#### `playlists` — 再生リスト登録状態

| 列 | 型 | 説明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `playlist_name` | TEXT | |
| `playlist_id` | TEXT | YouTube 再生リスト ID |
| `youtube_video_id` | TEXT | |
| `local_id` | TEXT | |
| `registered_at` | TEXT | |
| `status` | TEXT | "registered" |
| UNIQUE | `(playlist_name, youtube_video_id)` | |

#### `topic_history` — トピック重複チェック

| 列 | 型 | 説明 |
|---|---|---|
| `local_id` | TEXT PK | |
| `topic_key` | TEXT | |
| `food_name` | TEXT | |
| `title` | TEXT | |
| `youtube_video_id` | TEXT | |
| `status` | TEXT | |
| `created_at` | TEXT | |

#### `script_quality` — 台本品質スコア・レビュー結果

| 列 | 型 | 説明 |
|---|---|---|
| `local_id` | TEXT PK FK→videos | |
| `dialogue_lines` | INTEGER | |
| `total_chars` / `avg_chars` | INTEGER / REAL | |
| `short_line_count` | INTEGER | |
| `estimated_duration` / `actual_duration` | REAL | 秒 |
| `actual_duration_status` | TEXT | "ideal" / "warning" など |
| `opening_score` | REAL | オープニングスコア |
| `opening_score_status` | TEXT | （v4） |
| `opening_rewrite_needed` | INTEGER | 0/1（v4） |
| `final_review_score` | REAL | |
| `validation_status` | TEXT | |
| `validation_errors_json` | TEXT | |
| `final_review_skipped` | INTEGER | 0/1（v4） |
| `final_review_reason` | TEXT | （v4） |
| `final_review_stage` | TEXT | （v4） |
| `final_review_model` | TEXT | （v4） |
| `opening_review_debug` | TEXT | Ollama冒頭レビューの採点デバッグ情報JSON（v5）。model / prompt_version / raw_response / parsed_score / parsed_subscores / warning_text / fix_target / created_at |

#### `jobs` — バックグラウンドジョブ履歴

| 列 | 型 | 説明 |
|---|---|---|
| `job_id` | TEXT PK | UUID |
| `job_type` | TEXT | "upload" / "generate" / "analytics_import" など |
| `profile_id` | TEXT | ジョブ投入時の channel profile ID |
| `status` | TEXT | "queued" / "running" / "success" / "failed" / "cancelled" |
| `progress_text` | TEXT | 最新進捗メッセージ |
| `started_at` / `finished_at` | TEXT | JST ISO 8601 |
| `logs_json` | TEXT | `[{time, tag, message}, ...]` の JSON 配列 |
| `result_json` | TEXT | 結果 JSON |
| `error` | TEXT | エラーメッセージ |
| `params_json` | TEXT | ジョブ実行パラメータ |
| `cancel_requested` | INTEGER | 0/1。キャンセル要求フラグ |
| `heartbeat_at` | TEXT | runner が更新する最終生存時刻 |
| `runner_pid` | INTEGER | 実行中 runner のプロセスID |
| `created_at` | TEXT | |

保持件数は `JOB_LOG_MAX_JOBS`（既定 300）。古い順に自動削除される。生成・レンダーの `queued` は `workers.runner` が原子的に claim し、起動時に前回セッションで残った未実行 `queued` を `cancelled` に破棄する。

#### `image_generation_failures` — 背景画像生成の失敗記録（v6）

| 列 | 型 | 説明 |
|---|---|---|
| `id` | INTEGER PK | |
| `local_id` | TEXT | 動画フォルダ名 |
| `failed_index` / `total_backgrounds` | INTEGER | 失敗した背景番号 / 総数（例 4/8） |
| `model` / `backend` | TEXT | 使用モデル / バックエンド（nanobanana 等） |
| `status_code` | INTEGER | HTTP ステータス（503 など） |
| `category` | TEXT | auth / quota / api_busy / generic |
| `error_code` | TEXT | 中央カタログのエラーコード（`E-IMG-BUSY` など。v7） |
| `error_message` | TEXT | エラーメッセージ |
| `prompt` | TEXT | 失敗時の背景プロンプト |
| `retry_recommended` | INTEGER | 0/1（503・429 は 1） |
| `failed_at` | TEXT | JST ISO 8601 |

背景生成開始時に対象動画の旧記録をクリアし、失敗ごとに追記する。`_meta/*.json` には保存しない。

---

### `data/settings.db` テーブル定義

主なテーブル: `channel_profiles` / `encrypted_secrets` / `settings` / `prompt_templates` / `bgm_assets` / `channel_schedule_settings` / `reading_dictionary_entries` / `reading_candidates`

#### `settings` — アプリ設定

| 列 | 型 | 説明 |
|---|---|---|
| `key` | TEXT PK | 環境変数名（例: `CHANNEL_NAME`） |
| `value` | TEXT | 設定値（文字列） |

`.env` の非認証設定を起動時に自動移行（`settings_store.bootstrap_from_env()`）。
以降は設定画面（`/settings`）から保存する。認証情報（`GOOGLE_API_KEY` / `OPENAI_API_KEY` / `HF_TOKEN` / YouTube OAuth）は `encrypted_secrets` テーブルが正本。`.env` は正本ではなく、起動時固定値や未移行の手元設定が残る場合も新規利用しない。

#### `reading_dictionary_entries` — よみがな辞書

| 列 | 型 | 説明 |
|---|---|---|
| `dict_type` | TEXT | `base`（手動） / `user`（自動学習） |
| `word` | TEXT | 表記 |
| `reading` | TEXT | 読み |
| `updated_at` | TEXT | 更新日時 |

PRIMARY KEY は `(dict_type, word)`。同じ表記が `base` と `user` に重複した場合は `base` を優先し、`user` 側は表示・保存対象から除外する。

#### `reading_candidates` — 読み補正候補

| 列 | 型 | 説明 |
|---|---|---|
| `word` | TEXT PK | 表記 |
| `reading` | TEXT | 候補読み |
| `reason` | TEXT | 候補化理由 |
| `source` | TEXT | 由来 |
| `auto_applied` | INTEGER | 自動適用済みフラグ |
| `review_required` | INTEGER | 確認要否 |
| `updated_at` | TEXT | 更新日時 |

`reading_dictionary_seed_state` は初期 seed 投入済みかを記録する内部テーブル。新規DBでは `core/reading_dictionary_seed.py` の初期データを投入し、既存DBでは既存データを尊重する。

---

### スキーマバージョン履歴

| バージョン | 変更内容 |
|---|---|
| 1 | 初期スキーマ（videos / video_metadata / youtube_status / analytics_snapshots / playlists / topic_history / script_quality） |
| 2 | `videos.script_content` 追加 |
| 3 | `analytics_snapshots` に dislikes / impressions / ctr など 11 列追加 |
| 4 | `render_info` / `jobs` テーブル新設。`video_metadata` に CTA 列追加。`script_quality` に opening/final review 列追加 |
| 5 | `script_quality.opening_review_debug` 追加（Ollama冒頭レビューの採点デバッグJSON） |
| 6 | `image_generation_failures` テーブル新設（背景画像生成の失敗記録／503混雑など） |
| 7 | `image_generation_failures.error_code` 追加（中央カタログのエラーコード） |

マイグレーションは `initialize_db()` が起動時に自動適用する。

---

### 主要 API 関数（`core/metadata_db.py`）

| 関数 | 用途 |
|---|---|
| `initialize_db()` | DB 初期化・スキーマ移行（起動時に自動呼び出し） |
| `sync_folder_to_db(output_dir)` | 動画フォルダを全テーブルに同期 |
| `upsert_render_info(local_id, data)` | render_info テーブルへの upsert |
| `get_render_info(local_id)` | render_info をフォルダ名で取得 |
| `upsert_cta_policy(local_id, policy)` | CTA ポリシーを video_metadata に保存 |
| `get_cta_policy(local_id)` | CTA ポリシーを取得 |
| `upsert_opening_review(local_id, data)` | オープニングレビューを script_quality に保存 |
| `upsert_final_review(local_id, review)` | 最終レビューを script_quality に保存 |
| `upsert_job(job_dict)` | ジョブを jobs テーブルに upsert |
| `load_jobs_from_db(max_n)` | ジョブ履歴を新しい順で返す |
| `delete_old_jobs(keep_n)` | 古いジョブを削除して keep_n 件を維持 |
| `sync_youtube_statuses_from_api(delete_missing)` | YouTube Data API を正として動画DBのタイトル・公開状態・公開日時を更新し、削除済み動画を必要に応じてDBから削除 |
| `insert_analytics_snapshot(video_id, ...)` | Analytics スナップショットを upsert |
| `delete_video(local_id)` | 全テーブルから該当レコードを削除 |
| `get_videos(...)` | 動画一覧を条件付きで取得（管理画面用） |
| `get_stats()` | 集計サマリー（total / uploaded / published など） |
| `get_duplicate_topics()` | トピック重複チェック |
