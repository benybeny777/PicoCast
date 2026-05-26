# Native Video Factory

「ずんだもんとめたんの食べ物雑学堂」向けに、食べ物雑学の解説動画を台本から VOICEVOX音声・背景画像・ffmpeg/native MP4まで自動生成するローカルWebツールです。

## 主な機能

- ローカルWeb UIで台本貼り付けから native MP4 を自動生成
- Shorts / ロングを `動画形式:` から自動判定
- `━━ 動画1 ━━` や `動画形式:` が複数ある台本を分割して一括生成
- YouTube NG ワードをマイルド表現へ自動置換
- VOICEVOX 音声は Shorts(native): 冒頭1.40倍速・本編1.25倍速、ロング(native): 冒頭1.40倍速・本編1.20倍速で生成
- 背景指定がセリフの後に来る台本も自動で補正
- BGMer「のほほん」を固定 BGM として自動追加
- 生成履歴から複数選択して再生成 / native MP4化 / YouTube アップロード
- YouTubeアップロード選択画面は、アップロード可能な `.mp4` がある履歴だけを表示
- 画像確認画面でサムネイル・背景を確認し、選択した画像だけ再生成
- Web UIから食べ物雑学特化の台本生成プロンプトをコピー
- Web UIから既存タイトル・Analytics実績データを反映した `Shortsタイトル案` / `Longタイトル案` プロンプトをコピー
- 作業中止ボタンで生成処理を即時キャンセル
- YouTube 予約投稿: Shorts は毎日 7:00 / 12:00 / 19:00、Long は毎日 21:00（土日は追加で 12:00）(JST) に自動割り当て
- vidIQキーワード分析に基づき、YouTubeタグ欄へ `食べ物 雑学` / `雑学 ショート` / `ゆっくり解説 食べ物` などを自動補完。題材別タグを追加し、実際に使ったタグを `_meta/youtube_metadata.json` に保存
- スケジュール画面で予約中＋直近90日の公開済み動画を一覧表示。公開日時は YouTube API 同期値を使用。公開予定変更・スロット詰め直し対応。Shorts/Long・予定/公開済みで絞り込み可
- Analytics画面で YouTube Analytics API から動画・チャンネル指標を取得。チャンネル全動画を対象に S/A/B/C/D スコアリング（Shorts / ShortLong / Long 別）、公開予約・非公開は分類表示、高評価率・横展開用サマリー、2026-05-16以前の音切れリスク動画の品質改善候補を確認
- 固定コメント画面でアップロード済み動画に固定コメント用コメントを投稿し、確認用の動画リンクを表示
- `LongサムネAB` チェックボックスで Long の A/B/C サムネ候補を生成
- `Long節約` チェックボックスで Long の背景生成を最大 16 枚に制限（台本で `背景: 前と同じ` と書くと前の背景を継続使用）
- `SD生成` チェックボックスで画像を縮小サイズで生成して拡大セット（API コスト削減。デフォルト OFF）
- `背景再利用` チェックボックスで既存背景を活かした再生成に対応
- native Shorts は背景のゆっくりズーム/パン、話者の軽いバウンス、`テロップ:` 行のポップ表示、短いツッコミ/疑問場面のシェイク・アイコンを自動で追加

## セットアップ

Windows / Mac の両方を想定しています。ffmpeg/native生成を主経路とし、YMM4プロジェクト出力は廃止済みです。

1. VOICEVOX をインストール
2. APIキーとOAuth設定を用意
3. プロンプト設定を確認する
   - 初期状態は食べ物用設定でそのまま動きます
   - 別ジャンルで使う場合は、必ず `core/prompt_parts/local/` に個人用プロンプト設定を置きます
   - 食べ物用設定を明示的に復元する場合:
     ```powershell
     New-Item -ItemType Directory -Force -Path core\prompt_parts\local
     Copy-Item -Path samples\prompt_parts\food\* -Destination core\prompt_parts\local\ -Force
     ```
4. Python 依存を入れる

```bash
pip install --upgrade requests google-genai python-dotenv Pillow google-api-python-client google-auth-oauthlib openai fastapi "uvicorn[standard]" jinja2 python-multipart
```

### APIキー・OAuth

`.env` をリポジトリ直下に作り、必要なキーを入れます。

```env
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
```

- `GOOGLE_API_KEY`: Google AI Studio の API keys で作成します。台本生成・画像生成で使います。
- `OPENAI_API_KEY`: OpenAI Platform の API keys で作成します。ChatGPT生成前レビューで使います。
- `client_secrets.json`: Google Cloud Console で YouTube Data API v3 / YouTube Analytics API を有効化し、OAuthクライアントID（デスクトップアプリ）を作成してJSONをダウンロードします。ファイル名を `client_secrets.json` にしてリポジトリ直下へ置きます。
- 初回の `YouTubeアップ` / `📊 アナリティクス` 実行時にブラウザ認証が開き、`token.json` / `token_analytics.json` が自動作成されます。
- Google OAuth設定後、YouTube Studioで本人確認が頻発することがあります。その場合は、チャンネルのGoogleアカウントのセキュリティ項目でOAuth連携が警告扱いになっていないか確認し、警告を確認・承認すると本人確認が出なくなることがあります。

取得先:
- Google AI Studio API key: https://aistudio.google.com/apikey
- OpenAI API key: https://platform.openai.com/api-keys
- Google Cloud APIライブラリ: https://console.cloud.google.com/apis/library
- Google Cloud 認証情報: https://console.cloud.google.com/apis/credentials

`client_secrets.json`、`token.json`、`token_analytics.json`、`.env` はGit管理外です。

### 主な設定値

APIキーやOAuthファイルなどの認証情報以外は、原則として [config.py](config.py) の既定値を使います。必要な場合だけ `.env` または環境変数で上書きできます。

| 設定名 | 既定値 | 用途 |
| --- | --- | --- |
| `OPENAI_FINAL_REVIEW_MODEL` | `gpt-5.2` | ChatGPT生成前レビューのモデル |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | 台本生成モデル |
| `NANOBANANA_PRO_MODEL` | `gemini-3-pro-image-preview` | 背景・サムネ生成の高品質モデル |
| `NANOBANANA_FLASH_MODEL` | `gemini-3.1-flash-image-preview` | 背景・サムネ生成の高速モデル |
| `NATIVE_AUDIO_LOUDNORM_ENABLED` | `1` | native MP4の最終音声にloudnormを適用 |
| `NATIVE_AUDIO_LOUDNORM_I` | `-15` | loudnormのIntegrated loudness目標 |
| `NATIVE_AUDIO_LOUDNORM_TP` | `-1.5` | loudnormのTrue Peak上限 |
| `NATIVE_AUDIO_LOUDNORM_LRA` | `6` | loudnormのLoudness Range目標 |
| `NATIVE_BGM_VOLUME_DB` | `-20` | native出力のBGM音量 |
| `NATIVE_SHORTS_CHARACTER_SCALE` | `1.05` | native Shortsのキャラ倍率 |
| `NATIVE_ENABLE_MOTION_EFFECTS` | `1` | native Shorts軽量エフェクト全体の有効/無効 |
| `NATIVE_ENABLE_BG_KEN_BURNS` | `1` | 背景のゆっくりズーム/パン |
| `NATIVE_ENABLE_CHARACTER_BOUNCE` | `1` | 話者キャラの軽いバウンス |
| `NATIVE_ENABLE_POP_TELOP` | `1` | `テロップ:` 行のポップ表示 |
| `NATIVE_ENABLE_SHAKE` | `1` | ツッコミ/驚き場面の軽いシェイク |
| `NATIVE_MAX_SHAKE_COUNT_SHORTS` | `4` | Shorts 1本あたりのシェイク上限 |
| `NATIVE_MAX_ICON_COUNT_SHORTS` | `4` | Shorts 1本あたりの疑問/驚きアイコン上限 |
| `NATIVE_BG_ZOOM_MAX` | `1.06` | 背景Ken Burnsの最大拡大倍率 |
| `WEB_APP_NAME` | `Native Video Factory` | Web UIの表示アプリ名 |
| `WEB_UI_HOST` | `127.0.0.1` | Web UIのバインドホスト。外部公開はしない |
| `WEB_UI_PORT` | `58080` | Web UIのポート番号 |
| `WEB_DEFAULT_IMAGE_STYLE` | `通常` | Web UI生成画面の既定画像スタイル |
| `WEB_IMAGE_STYLE_CHOICES` | `通常,アニメ,水彩` | Web UI生成画面の画像スタイル選択肢 |
| `WEB_DEFAULT_REUSE_BACKGROUNDS` | `0` | Web UI生成画面の背景再利用既定値 |
| `WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST` | `0` | Web UI生成画面のLongサムネAB既定値 |
| `WEB_DEFAULT_LONG_BUDGET_MODE` | `0` | Web UI生成画面のLong節約既定値 |
| `WEB_DEFAULT_SD_SIZE_MODE` | `0` | Web UI生成画面のSD生成既定値 |
| `WEB_JOB_POLL_INTERVAL_MS` | `2000` | Web UIのジョブ状態更新間隔(ms) |
| `WEB_SUCCESS_RELOAD_DELAY_MS` | `1500` | Web UIのジョブ成功後再読み込み待ち時間(ms) |
| `WEB_TOAST_VISIBLE_MS` | `2000` | Web UIのトースト表示時間(ms) |
| `WEB_TOAST_HIDE_DELAY_MS` | `420` | Web UIのトースト非表示待ち時間(ms) |
| `WEB_VOICEVOX_CHECK_TIMEOUT_SEC` | `2.0` | Web UIのVOICEVOX疎通確認タイムアウト(秒) |
| `WEB_FFMPEG_CHECK_TIMEOUT_SEC` | `5.0` | Web UIのffmpeg疎通確認タイムアウト(秒) |
| `LONG_UPLOAD_PLAYLIST_NAME` | `ロング動画` | Longアップロード成功後に追加する再生リスト名。空にすると無効 |

## 起動

### ローカル Web UI

```bash
python -m web_app.app
```

起動後、ブラウザで `http://127.0.0.1:58080` を開きます。ポートを変える場合は `--port` または `WEB_UI_PORT` を使います。

起動時にブラウザを自動で開くには `--open-browser` を付けます。

```bash
python -m web_app.app --open-browser
```

Windowsでは `start.bat` からも同じWeb UIを起動できます。

**セキュリティ注意:**
- Web UI は **127.0.0.1 のみ**にバインドします。外部には公開しません。
- `.env` / `client_secrets.json` / `token.json` / `token_analytics.json` の中身は Web 画面に**絶対に表示されません**。
- 旧Tkinter GUI / CLI生成入口は廃止済みです。操作はWeb UIに一本化しています。

### Web UI でできること

| 画面 | 機能 |
|---|---|
| ダッシュボード | サービス接続状態、統計、直近履歴、クイックアクション |
| 台本貼り付け / 生成 | 台本入力 → 生成ジョブ開始 → ログ表示 |
| LLM/尺チェック | 台本の冒頭品質・推定尺・AI評価を確認 |
| 生成履歴 | output/ 配下の履歴一覧・詳細表示・履歴から複数再生成・native MP4化 |
| 画像確認 / 再生成 | サムネイル・背景画像の確認、プロンプト編集、選択画像の再生成 |
| Analytics | YouTube Analytics データの表示・取得 |
| スケジュール | 予約中動画一覧・YouTube同期 |
| アップロード | MP4がある履歴をYouTubeにアップロード |
| 固定コメント | アップロード済み動画への固定コメント投稿 |
| 設定 / サービス確認 | VOICEVOX診断、非秘密設定の変更、最下部でAPIキー状態確認・変更 |
| ログ | バックグラウンドジョブのログ確認 |

### Web UI の追加パッケージ

上記のセットアップ用 `pip install` に含まれています。既存環境へ追加する場合だけ、`fastapi` / `uvicorn[standard]` / `jinja2` / `python-multipart` を入れてください。

### 販売・配布時の注意

- Web UI はローカル専用です。SaaS 化・外部公開する場合は認証機構を別途追加してください。
- `.env` や OAuth トークンはGit管理外です。配布パッケージには含めないでください。

## 基本の使い方

1. 必要に応じて `📊 アナリティクス` で実績データを取得
2. Web UIの `Shortsタイトル案` でShorts寄りのタイトル案作成プロンプトをコピーし、候補を作成
   - Long候補だけを出したい場合は `Longタイトル案` を使う
3. Web UIの `AI台本作成` で台本作成プロンプトをコピーし、採用タイトルから台本を作成
4. Web UI の台本欄に貼り付け
5. 生成を開始する
6. 必要なら `画像確認` で画像を見直す
7. native MP4を確認する
8. アップロード画面で履歴から動画を選んでアップロード（MP4なしの履歴は表示されません）
9. 必要なら固定コメント画面で公開済み動画へコメントを投稿し、Studio側でピン留め

`Shortsタイトル案` / `Longタイトル案` は直近の `output/000_analytics/analytics_score_*.tsv` がある場合、その実績データをプロンプトへ自動で差し込みます。実績データがない場合は新規開拓枠として扱う指示になります。

## 台本フォーマット

```text
動画形式: Shorts
動画タイトル: タイトル
サムネ文字: ヤバい
説明文: YouTube説明文（VOICEVOXクレジット不要・自動付与）
タグ: ずんだもん,ゆっくり解説,VOICEVOX,食べ物 雑学,雑学 ショート
生成区分: 横展開
元動画: 昔のコーラに入ってた危険な粉の正体
目的: 薬だった飲み物系

背景: 場面説明、漫画風、画面上部に"テロップ"を描画
ずんだもん(ノーマル): セリフ
四国めたん(ツンツン)[ジト目]: セリフ
```

`()` はVOICEVOXの声スタイル、`[]` はnative立ち絵の画面表情です。`[]` は必要な場面だけ使います。

複数動画をまとめて貼る場合は区切り記号に対応しています。

```text
━━ 動画1：ショート版 ━━
動画形式: Shorts
...

━━ 動画2：ロング版 ━━
動画形式: ロング
...
```

## 注意

- YMM4プロジェクト出力は廃止済みです。生成・アップロード候補は native MP4 のみを対象にします。
- 旧Tkinter GUI と `main.py` の直接CLI生成入口は廃止済みです。操作入口はローカルWeb UIのみです。
- `output/`, `.env`, `client_secrets.json`, `token.json`, `token_analytics.json` は Git 管理外です。
- アップロード記録は各動画フォルダの `_meta/upload_record.json` に残します。予約・公開状態の正はYouTube側なので、スケジュール画面や詰め直しはYouTube APIの状態を参照します。`output/000_uploaded/` はアップロード済み生成物の保管場所です。
- `OUTPUT_DIR` / `OUTPUT_DATA_DIR` / `OUTPUT_ANALYTICS_DIR` / `OUTPUT_LEGACY_DIR` / `UPLOAD_RECORDS_FILE` / `UPLOADED_TITLES_FILE` は `.env` または環境変数で変更できます。
- `output/000_backups/` は再生成時の退避先です。同一テーマは最新1世代だけ残し、アップロード成功後はそのテーマのバックアップを自動削除します。
- `core/prompt_parts/local/` は個人用プロンプト差し替え欄です。Git管理外なので、別ジャンル担当者のネタ設定と混ざりません。
- 初回セットアップではプロンプト設定を必ず確認します。食べ物用ならGit管理側の設定でそのまま動き、別ジャンルで使う人は必ず `local/` に差し替えファイルを置きます。
- 食べ物用の復元サンプルは `samples/prompt_parts/food/`、サンプル台本は `samples/scripts/` にあります。
- `local/` を消した場合は、`samples/prompt_parts/food/` の中身を `core/prompt_parts/local/` へコピーすると食べ物用設定を戻せます。
- YouTube アップロードには Google OAuth 用の `client_secrets.json` が必要です。
- 詳細仕様・操作手順は [SPEC.md](SPEC.md) を参照してください。
- 大きめの変更履歴は [CHANGELOG.md](CHANGELOG.md) に残します。
## CTA/Long運用メモ

- Shorts本編はループ視聴優先です。アプリは一括生成時に `ネタ募集CTA: 許可 / 禁止` を台本へ差し込み、5本以上のShorts同時生成でもネタ募集CTAは最大1本だけにします。
- Shorts台本に `次回は` / `次の動画` / `他の動画も見て` / `チャンネル登録お願いします` などの直接誘導がある場合、生成前チェックで警告します。Longでは関連動画誘導を許可します。
- Longアップロード時は説明欄末尾にYouTubeチャプター形式の `【目次】` を自動追加できます。方針は `_meta/cta_policy.json` と `_meta/youtube_metadata.json` に保存されます。
