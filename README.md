# YMM4 Auto Video Factory

「ずんだもんとめたんの食べ物雑学堂」向けに、食べ物雑学の解説動画を台本から YMM4 プロジェクトまで自動生成するツールです。

## 主な機能

- 台本貼り付けから `.ymmp` を自動生成
- Shorts / ロングを `動画形式:` から自動判定
- `━━ 動画1 ━━` や `動画形式:` が複数ある台本を分割して一括生成
- YouTube NG ワードをマイルド表現へ自動置換
- VOICEVOX 音声は Shorts: 冒頭2.0倍速・本編1.65倍速、ロング: 冒頭1.6倍速・本編1.35倍速で生成
- 背景指定がセリフの後に来る台本も自動で補正
- BGMer「のほほん」を固定 BGM として自動追加
- 生成履歴から複数選択して再生成 / YouTube アップロード
- 画像確認画面でサムネイル・背景を確認し、選択した画像だけ再生成
- `AI台本作成` ボタンで食べ物雑学特化の台本生成プロンプトをコピー
- `Shortsタイトル案` / `Longタイトル案` ボタンで既存タイトル・Analytics実績データを反映したタイトル案プロンプトをコピー
- 作業中止ボタンで生成処理を即時キャンセル
- YouTube 予約投稿: Shorts は毎日 7:00 / 12:00 / 19:00、Long は毎日 21:00（土日は追加で 12:00）(JST) に自動割り当て
- `📅 スケジュール` ボタンでアップロード予定・済みの一覧確認・削除・公開予定変更・手動公開済み処理、`スロット詰め直し` で未来スロットを現在から最速に前詰め
- `📊 アナリティクス` ボタンで YouTube Analytics API から動画・チャンネル指標を取得。チャンネル全動画を対象に S/A/B/C/D スコアリング（Shorts / ShortLong / Long 別）、公開予約・非公開は分類表示、高評価率・横展開用サマリーを確認
- `💬 固定コメント` ボタンでアップロード済み動画に固定コメント用コメントを投稿し、確認用の動画リンクを表示
- 主要ボタンにカーソルを合わせると機能概要を表示

## セットアップ

1. VOICEVOX をインストール
2. YukkuriMovieMaker v4 をインストール
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
pip install requests google-genai python-dotenv pywinauto Pillow google-api-python-client google-auth-oauthlib
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
7. `動画出力` で YMM4 から MP4 を書き出す
8. `YouTubeアップ` で履歴から動画を選んでアップロード
9. 必要なら `💬 固定コメント` で公開済み動画へコメントを投稿し、Studio側でピン留め

`Shortsタイトル案` / `Longタイトル案` は直近の `output/analytics_score_*.tsv` がある場合、その実績データをプロンプトへ自動で差し込みます。実績データがない場合は新規開拓枠として扱う指示になります。

## 台本フォーマット

```text
動画形式: Shorts
動画タイトル: タイトル
サムネ文字: ヤバい
説明文: YouTube説明文（VOICEVOXクレジット不要・自動付与）
タグ: ずんだもん,ゆっくり解説,雑学

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

- `output/`, `.env`, `client_secrets.json`, `token.json`, `token_analytics.json` は Git 管理外です。
- `core/prompt_parts/local/` は個人用プロンプト差し替え欄です。Git管理外なので、別ジャンル担当者のネタ設定と混ざりません。
- 初回セットアップではプロンプト設定を必ず確認します。食べ物用ならGit管理側の設定でそのまま動き、別ジャンルで使う人は必ず `local/` に差し替えファイルを置きます。
- 食べ物用の復元サンプルは `samples/prompt_parts/food/`、サンプル台本は `samples/scripts/` にあります。
- `local/` を消した場合は、`samples/prompt_parts/food/` の中身を `core/prompt_parts/local/` へコピーすると食べ物用設定を戻せます。
- YouTube アップロードには Google OAuth 用の `client_secrets.json` が必要です。
- 詳細仕様・操作手順は [SPEC.md](SPEC.md) を参照してください。
- 大きめの変更履歴は [CHANGELOG.md](CHANGELOG.md) に残します。
