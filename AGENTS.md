# AGENTS.md — Claude Code / AI エージェント向け作業ガイド（ルール正本）

このファイルが唯一のルール正本です。`CLAUDE.md` はこのファイルへのリダイレクトのみです。ルールを追加・変更する場合はこのファイルだけを編集してください。

## 最重要運用ルール

- `AGENTS.md` はすべて日本語で記述する。英語セクション・英語コメントは追加しない。既存の英語記述を見つけたら日本語に置き換える。
- ルールに反する記述・命名・コメント・dead codeを発見した場合は、その場で修正して作業完了後に事後報告する。都度確認を求めない。
- ルール正本は `AGENTS.md` 1本。`CLAUDE.md` はリダイレクトのみなので編集しない。恒久ルールはすべてこのファイルに追記する。
- **ドキュメントは常に最新を保つ。コード・スクリプト・設定・依存関係・フォルダ構成など、README や SPEC.md に記載のある内容を変更したら、必ず同じ作業内でドキュメントも更新してコミットする。ユーザーから指摘されてから直すのは禁止。**
- 対象ドキュメントの目安: 仕様・画面・プロンプト・設定・生成フロー → `SPEC.md`、大きな変更 → `CHANGELOG.md`、起動手順・セットアップ・スクリプト名・APIキー・依存関係 → `README.md`。
- ドキュメント更新が本当に不要な軽微修正の場合のみ、不要と判断した理由を作業完了時に明記する。
- PowerShellで日本語ファイルを確認するときは、文字化けを避けるためUTF-8を明示する。`$OutputEncoding=[Text.UTF8Encoding]::new($false); Get-Content -Encoding UTF8 ...`、`$env:PYTHONIOENCODING='utf-8'; python -c "... Path(...).read_text(encoding='utf-8') ..."`（Windowsは `py -3`）、`rg`、`git diff` を優先する。
- PowerShell表示が文字化けしても、すぐにソース破損と判断しない。UTF-8で読み直してから判断する。
- 常に Codex / Claude の利用クレジット消費を抑えて作業する。不要な長文出力、重複調査、過剰なファイル読み込み、不要な並列探索、同じ確認のやり直しを避ける。
- まず `rg`、差分確認、必要最小限のファイル読み取り、軽い単体テストで判断する。大きい調査が必要な場合も、読む範囲を絞り、分かったことを短くまとめる。
- ChatGPT API と Google API（Gemini / Nano Banana 画像生成など）は費用が発生するため、ユーザー指示または運用上の明確な必要がある場合だけ実行する。ローカルLLM・ローカル処理・YouTube API はコストが実質かからないため必要なら積極的に使ってよい。ただし同じ取得や更新を無意味に繰り返さない。
- 既に未コミット変更がある場合は、ユーザーまたは別エージェントの作業として扱い、勝手に巻き戻さない。コミット時は目的に関係する差分だけをステージする。
- ファイル編集は `Edit` ツール（Claude Code）または `apply_patch`（Codex）を使う。検索はまず `rg` / `rg --files` を使う。
- **エラーはすべてそのまま例外として上位に伝播させる。`except Exception: pass` / `except Exception: return default` のようなサイレントスキップ・無言フォールバック・無言デフォルト降格は禁止。** 失敗時は原因が分かるエラーとして即中止する。フォールバック処理はユーザーが明示的に許可した場合のみ実装し、その箇所に `# フォールバック許可: 理由` コメントを付ける。
- ファイルポインタ、ネットワーク接続、画像/動画オブジェクト、subprocess、ブラウザ/GUIハンドルなどのリソースは明示的に解放する。`with`、`close()`、`terminate()`、一時ファイル削除などを使い、長時間処理では不要な大きい参照を手放してメモリも解放する。
- このリポジトリは開発環境として扱うため、`config/prompt_parts/local/` を更新したら常に対応する `config/samples/prompt_parts/` へコピーして同期する。localだけに残さない。
- 数値・座標・倍率・閾値・フラグなど「設定として変えうる値」はソースコードにハードコードしない。必ず `config/config.py` に `os.environ.get(...)` 付きで定数として定義する。ループインデックスや内部カウンタなど実装上の定数は対象外。
- `config/config.py` の各定数には必ず末尾コメント（`# 説明`）を付ける。新規追加・変更時もコメントを省略しない。
- native立ち絵に表情PNG（`expression` 指定）を使用している場合、口パク・まばたきの差分オーバーレイを同セグメントで無効化する。表情PNGはPSDから合成した専用口・目レイヤーを含むため、base.pngとの差分オーバーレイと重ねると二重口・二重目が生じる。
詳細仕様は [SPEC.md](SPEC.md) を参照。ここには作業上の注意点だけを書く。

## Web UI 作業時の注意点

- Web UI は `127.0.0.1` のみバインドする。外部公開・認証なし運用は禁止。
- `.env` / `client_secrets.json` / `token.json` / `token_analytics.json` の中身をレスポンスやログへ絶対に含めない。APIキー設定はbool（有無）のみ返す。
- Web UI を唯一の操作入口とする。`workers/main.py` は生成パイプラインとして使い、旧Tkinter GUI/CLI導線を復活させない。
- 長時間処理はすべて `job_manager.py` でジョブ化する。HTTPリクエスト内で直接待たない。
- output/ 配下のファイルアクセスは `security.py: safe_output_path()` を必ず通す。
- 破壊的操作（アップロード・固定コメント・スケジュール変更）は `confirmed=true` 必須 + 画面確認ダイアログ必須。
- 実装が不安定な機能は `[DISABLED]` / `[dry-run]` として画面とコードコメントに明記し、無効ではなくユーザーに理由を提示する。
- テストは `tests/test_web.py` で行う。外部API実通信が必要なテストはモックまたはskip可能にする。
- Starlette 1.1.0以降: `TemplateResponse(request, name, context)` の引数順に従う（旧API `TemplateResponse(name, {request: ...})` は使わない）。
- 設定画面で保存した値はアプリ再起動なしで即時反映する。`config_service._apply_runtime_updates()` で `setattr(cfg, key, value)` と `sys.modules` 全走査による伝搬を行う。`WEB_UI_PORT` など「アプリ起動時に固定されるパラメータ」だけを例外とし、それらは EDITABLE_CONFIG から除外する。UI上に「再起動後に反映」という文言を出さない。

## プロジェクト概要

「ずんだもんとめたんの食べ物雑学堂」YouTube チャンネル向け動画自動生成ツール。
台本 → VOICEVOX音声 → Nano Banana背景画像 → native MP4 → YouTubeアップロード。

## 実行環境

- Windows / Mac を想定する。ffmpeg/native生成を主経路とし、YMM4プロジェクト出力は廃止済み。
- Python 仮想環境: `.venv/`
- 起動: 通常は `start.bat` 推奨（手動起動時は `python -m web_app.app --open-browser`）
- VOICEVOX をローカルで起動しておく必要がある（`http://localhost:50021`）

## 主要ファイル

| ファイル | 役割 |
|---|---|
| `web_app/app.py` | FastAPI Web UI エントリポイント |
| `workers/main.py` | `run_pipeline()` — Web UI から呼ぶ1本分の動画生成パイプライン |
| `config/config.py` | 定数・設定（音声速度・モデル名・パスなど） |
| `core/parser.py` | 台本パーサー `ScriptParser` |
| `core/ai_generator.py` | Gemini台本生成・画像プロンプト強化 |
| `core/voicevox.py` | VOICEVOX音声生成 |
| `core/image_generator.py` | Nano Banana背景・サムネ生成 |
| `core/native_renderer.py` | ffmpeg/native MP4レンダラー |
| `core/opening_quality.py` | 冒頭品質レビュー（ローカル + Ollama + ChatGPT） |
| `core/upload_scheduler.py` | アップロードスロット管理 |
| `core/upload_records.py` | アップロード記録参照 |
| `core/script_prompts.py` | Gemini台本生成プロンプト構築 |
| `core/youtube_analytics.py` | YouTube Analytics API取得 |
| `core/analytics_score.py` | Analytics評価・スコアリング・TSV保存 |
| `core/output_paths.py` | 出力パスの集約・マイグレーション |

## 出力フォルダ構造

```text
output/{テーマ名}/
├── script.txt
├── {テーマ名}_native.mp4      ← native出力時
├── thumbnails/
│   ├── thumbnail.png
│   └── {テーマ名}_thumbnail_A/B/C.png  (Longのみ)
├── _meta/
│   ├── metadata.txt
│   ├── opening_review.json
│   ├── duration_review.json
│   ├── final_review.json
│   ├── render_info.json
│   ├── upload_record.json
│   ├── thumbnail_ab_test.json  (Longのみ)
│   └── title_ab_test.json      (Longのみ)
├── audio/
└── backgrounds/
```

## 重要な規約・注意点

### ScriptParser

- メタタイプの判定には必ず `ScriptParser.META_TYPES` を使う（Web UI / `workers/main.py` で共有）
- `parse_string(text)` はメモリ内処理（tempfileを使わない）

### アップロードスロット

- Shorts: 毎日 7/12/19時
- Long: 毎日 21時、土日は追加で 12時
- スロット定数は `LONG_SLOTS_WEEKDAY` / `LONG_SLOTS_WEEKEND`（`LONG_SLOTS` という名前は廃止）
- 予約枠の空き判断と詰め直しはYouTube側の予約状態を正として扱う

### 説明文処理

- VOICEVOXクレジット手書き行は自動除去（警告なし）
- `_VOICEVOX_CREDIT` / `_CHANNEL_FOOTER` を末尾に自動付与

### native Shorts字幕

- 通常字幕は白文字を基本にし、話者差はフチ色で表現する
- ずんだもん: 白文字 + 濃緑の内フチ + 黒外フチ
- 四国めたん: 白文字 + 濃ピンク紫の内フチ + 黒外フチ
- 背景が複雑でも読めるよう、半透明黒帯は残す
- 色付き字幕は全文ではなく重要語の強調に限定する

### gitignore対象（コミット禁止）

- `output/` 全体
- `dev/` — 開発用テストファイル（後述）
- `.env`
- `client_secrets.json`
- `token.json`
- `token_analytics.json`
- 認証情報、APIキー、OAuthトークン、秘密鍵、Cookie、個人用設定などのシークレットはファイル名に関わらずコミット禁止。ドキュメントやログにも値を記載しない。

### テスト用ファイルの置き場所

- 動作確認用の一時画像・動画・スクリプトなど「リポジトリに入れたくないテスト系ファイル」はすべて `dev/` フォルダに置く。
- `dev/` は `.gitignore` で除外済みのため、コミットされない。
- `assets/` 直下やサブフォルダにテスト画像を置かない。テスト用途のものは必ず `dev/` に移動してから使う。

## 期限付きメンテナンス予定

期限が来たら実施すること。詳細は [MAINTENANCE.md](MAINTENANCE.md) を参照。

| 期限 | 内容 | 詳細 |
|---|---|---|
| 2026-06-29 | 旧フォルダプレフィックス `[Shorts]`/`[Long]`/`[ネタ会議]` の後方互換コードを削除 | [MAINTENANCE.md#prefix-cleanup](MAINTENANCE.md#2026-06-29-旧フォルダプレフィックス互換コードの削除) |
