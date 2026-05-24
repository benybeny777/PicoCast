# YMM4 Auto Video Factory

「ずんだもんとめたんの食べ物雑学堂」向けに、食べ物雑学の解説動画を台本から VOICEVOX音声・背景画像・ffmpeg/native動画・YMM4確認用プロジェクトまで自動生成するツールです。

## 主な機能

- 台本貼り付けから `.ymmp` を自動生成
- Shorts / ロングを `動画形式:` から自動判定
- `━━ 動画1 ━━` や `動画形式:` が複数ある台本を分割して一括生成
- YouTube NG ワードをマイルド表現へ自動置換
- VOICEVOX 音声は Shorts(YMM4): 冒頭2.0倍速・本編1.65倍速 / Shorts(native): 冒頭1.40倍速・本編1.25倍速、ロング: 冒頭1.6倍速・本編1.35倍速で生成
- 背景指定がセリフの後に来る台本も自動で補正
- BGMer「のほほん」を固定 BGM として自動追加
- 生成履歴から複数選択して再生成 / YouTube アップロード
- YouTubeアップロード選択画面は、アップロード可能な `.mp4` がある履歴だけを表示
- 画像確認画面でサムネイル・背景を確認し、選択した画像だけ再生成
- `AI台本作成` ボタンで食べ物雑学特化の台本生成プロンプトをコピー
- `Shortsタイトル案` / `Longタイトル案` ボタンで既存タイトル・Analytics実績データを反映したタイトル案プロンプトをコピー
- 作業中止ボタンで生成処理を即時キャンセル
- YouTube 予約投稿: Shorts は毎日 7:00 / 12:00 / 19:00、Long は毎日 21:00（土日は追加で 12:00）(JST) に自動割り当て
- vidIQキーワード分析に基づき、YouTubeタグ欄へ `食べ物 雑学` / `雑学 ショート` / `ゆっくり解説 食べ物` などを自動補完。題材別タグを追加し、実際に使ったタグを `_meta/youtube_metadata.json` に保存
- `📅 スケジュール` ボタンで予約中＋直近90日の公開済み動画を一覧表示。公開日時は YouTube API 同期値を使用。削除・公開予定変更・スロット詰め直し対応。Shorts/Long・予定/公開済みで絞り込み可
- `📊 アナリティクス` ボタンで YouTube Analytics API から動画・チャンネル指標を取得。チャンネル全動画を対象に S/A/B/C/D スコアリング（Shorts / ShortLong / Long 別）、公開予約・非公開は分類表示、高評価率・横展開用サマリー、2026-05-16以前の音切れリスク動画の品質改善候補を確認
- `💬 固定コメント` ボタンでアップロード済み動画に固定コメント用コメントを投稿し、確認用の動画リンクを表示
- 主要ボタンにカーソルを合わせると機能概要を表示
- `Long節約` チェックボックスで Long の背景生成を最大 16 枚に制限（台本で `背景: 前と同じ` と書くと前の背景を継続使用）
- `SD生成` チェックボックスで画像を縮小サイズで生成して拡大セット（API コスト削減。デフォルト OFF）

## セットアップ

Windows / Mac の両方を想定しています。ffmpeg/native生成を主経路とし、YMM4は確認用 `.ymmp` 生成までを扱います。

1. VOICEVOX をインストール
2. 必要に応じて YukkuriMovieMaker v4 をインストール（確認用 `.ymmp` を開く場合）
3. APIキーとOAuth設定を用意
4. プロンプト設定を確認する
   - 初期状態は食べ物用設定でそのまま動きます
   - 別ジャンルで使う場合は、必ず `core/prompt_parts/local/` に個人用プロンプト設定を置きます
   - 食べ物用設定を明示的に復元する場合:
     ```powershell
     New-Item -ItemType Directory -Force -Path core\prompt_parts\local
     Copy-Item -Path samples\prompt_parts\food\* -Destination core\prompt_parts\local\ -Force
     ```
5. Python 依存を入れる

```bash
pip install --upgrade requests google-genai python-dotenv Pillow google-api-python-client google-auth-oauthlib openai
```

### APIキー・OAuth

`.env` をリポジトリ直下に作り、必要なキーを入れます。

```env
GOOGLE_API_KEY=...
OPENAI_API_KEY=...
OPENAI_FINAL_REVIEW_MODEL=gpt-5.2
GEMINI_MODEL=gemini-3.1-pro-preview
NANOBANANA_PRO_MODEL=gemini-3-pro-image-preview
NANOBANANA_FLASH_MODEL=gemini-3.1-flash-image-preview
NATIVE_AUDIO_LOUDNORM_ENABLED=1
NATIVE_AUDIO_LOUDNORM_I=-15
NATIVE_AUDIO_LOUDNORM_TP=-1.5
NATIVE_AUDIO_LOUDNORM_LRA=6
NATIVE_BGM_VOLUME_DB=-20
NATIVE_SHORTS_CHARACTER_SCALE=1.05
LONG_UPLOAD_PLAYLIST_NAME=ロング動画
```

- `GOOGLE_API_KEY`: Google AI Studio の API keys で作成します。台本生成・画像生成で使います。
- `OPENAI_API_KEY`: OpenAI Platform の API keys で作成します。ChatGPT生成前レビューで使います。
- `OPENAI_FINAL_REVIEW_MODEL` / `GEMINI_MODEL` / `NANOBANANA_*_MODEL`: 任意。外部API側のモデル更新に追随するため、`.env` で差し替えできます。
- `LONG_UPLOAD_PLAYLIST_NAME`: 任意。Longアップロード成功後、名前が完全一致する自チャンネルの再生リストへ自動追加します。未設定時は `ロング動画` を使います。空にすると無効です。
- `client_secrets.json`: Google Cloud Console で YouTube Data API v3 / YouTube Analytics API を有効化し、OAuthクライアントID（デスクトップアプリ）を作成してJSONをダウンロードします。ファイル名を `client_secrets.json` にしてリポジトリ直下へ置きます。
- 初回の `YouTubeアップ` / `📊 アナリティクス` 実行時にブラウザ認証が開き、`token.json` / `token_analytics.json` が自動作成されます。
- Google OAuth設定後、YouTube Studioで本人確認が頻発することがあります。その場合は、チャンネルのGoogleアカウントのセキュリティ項目でOAuth連携が警告扱いになっていないか確認し、警告を確認・承認すると本人確認が出なくなることがあります。

取得先:
- Google AI Studio API key: https://aistudio.google.com/apikey
- OpenAI API key: https://platform.openai.com/api-keys
- Google Cloud APIライブラリ: https://console.cloud.google.com/apis/library
- Google Cloud 認証情報: https://console.cloud.google.com/apis/credentials

`client_secrets.json`、`token.json`、`token_analytics.json`、`.env` はGit管理外です。

## 起動

```bash
python gui.py
```

## 基本の使い方

1. 必要に応じて `📊 アナリティクス` で実績データを取得
2. `Shortsタイトル案` ボタンでShorts寄りのタイトル案作成プロンプトをコピーし、候補を作成
   - Long候補だけを出したい場合は `Longタイトル案` を使う
3. `AI台本作成` ボタンで台本作成プロンプトをコピーし、採用タイトルから台本を作成
4. GUI の台本欄に貼り付け
5. `🎬 生成` を押す
6. 必要なら `画像確認` で画像を見直す
7. native MP4を確認する（YMM4は必要に応じて `.ymmp` 確認に使う）
8. `YouTubeアップ` で履歴から動画を選んでアップロード（MP4なしの履歴は表示されません）
9. 必要なら `💬 固定コメント` で公開済み動画へコメントを投稿し、Studio側でピン留め

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
四国めたん(ツンツン): セリフ
```

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

- YMM4を使わない実験レンダラーの実装概要と段階別ロードマップは `docs/YMM_FREE_RENDERER.md` を参照してください。
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
