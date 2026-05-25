# AGENTS.md — Codex/Claude Code 向け作業ガイド（ルール正本）

このファイルが唯一のルール正本です。`CLAUDE.md` はこのファイルへのリダイレクトのみです。ルールを追加・変更する場合はこのファイルだけを編集してください。

## 最重要運用ルール

- `AGENTS.md` はすべて日本語で記述する。英語セクション・英語コメントは追加しない。既存の英語記述を見つけたら日本語に置き換える。
- ルール正本は `AGENTS.md` 1本。`CLAUDE.md` はリダイレクトのみなので編集しない。恒久ルールはすべてこのファイルに追記する。
- 仕様、画面、プロンプト、設定、YouTube連携、Analytics判定、生成フローを変更した場合は、必ずドキュメントも同時に最新化する。
- 基本は `SPEC.md` を最新仕様の正とし、大きめの変更は `CHANGELOG.md` にも履歴を残す。
- セットアップ、APIキー、設定ファイル、ローカル差し替え運用に影響する変更は `README.md` も更新する。
- ドキュメント更新が不要な軽微修正の場合でも、不要と判断した理由を作業完了時に明記する。
- PowerShellで日本語ファイルを確認するときは、文字化けを避けるためUTF-8を明示する。`$OutputEncoding=[Text.UTF8Encoding]::new($false); Get-Content -Encoding UTF8 ...`、`$env:PYTHONIOENCODING='utf-8'; py -3 -c "... Path(...).read_text(encoding='utf-8') ..."`、`rg`、`git diff` を優先する。
- PowerShell表示が文字化けしても、すぐにソース破損と判断しない。UTF-8で読み直してから判断する。
- 常に Codex / Claude の利用クレジット消費を抑えて作業する。不要な長文出力、重複調査、過剰なファイル読み込み、不要な並列探索、同じ確認のやり直しを避ける。
- まず `rg`、差分確認、必要最小限のファイル読み取り、軽い単体テストで判断する。大きい調査が必要な場合も、読む範囲を絞り、分かったことを短くまとめる。
- ChatGPT API と Google API（Gemini / Nano Banana 画像生成など）は費用が発生しやすいため、ユーザー指示または運用上の明確な必要がある場合だけ実行する。
- ローカルLLM、ローカル処理、YouTube API はコストが実質かからないため、確認・テスト・運用上必要なら積極的に使ってよい。ただし同じ取得や更新を無意味に繰り返さない。
- 既に未コミット変更がある場合は、ユーザーまたは別エージェントの作業として扱い、勝手に巻き戻さない。コミット時は目的に関係する差分だけをステージする。
- 手作業のファイル編集は原則 `apply_patch` で行い、検索はまず `rg` / `rg --files` を使う。
- フォールバック処理は、ユーザーが明示した場合または既存仕様で明記されている場合を除き、基本的に追加しない。失敗時は原因が分かるエラーとして止める。
- ファイルポインタ、ネットワーク接続、画像/動画オブジェクト、subprocess、ブラウザ/GUIハンドルなどのリソースは明示的に解放する。`with`、`close()`、`terminate()`、一時ファイル削除などを使い、長時間処理では不要な大きい参照を手放してメモリも解放する。
- このリポジトリは開発環境として扱うため、`core/prompt_parts/local/` を更新したら常に対応する `samples/prompt_parts/` へコピーして同期する。localだけに残さない。
- ChatGPT API と Google API（Gemini / Nano Banana 画像生成など）を使う動画生成・画像生成・レビューは、費用に注意して必要時だけ実行する。ローカルLLMとYouTube APIは必要な検証・運用であれば積極的に使ってよい。
- 数値・座標・倍率・閾値・フラグなど「設定として変えうる値」はソースコードにハードコードしない。必ず `config.py` に `os.environ.get(...)` 付きで定数として定義する。ループインデックスや内部カウンタなど実装上の定数は対象外。
- `config.py` の各定数には必ず末尾コメント（`# 説明`）を付ける。新規追加・変更時もコメントを省略しない。
- native立ち絵に表情PNG（`expression` 指定）を使用している場合、口パク・まばたきの差分オーバーレイを同セグメントで無効化する。表情PNGはPSDから合成した専用口・目レイヤーを含むため、base.pngとの差分オーバーレイと重ねると二重口・二重目が生じる。

詳細仕様は [SPEC.md](SPEC.md) を参照。ここには作業上の注意点だけを書く。

## プロジェクト概要

「ずんだもんとめたんの食べ物雑学堂」YouTube チャンネル向け動画自動生成ツール。
台本 → VOICEVOX音声 → Nano Banana背景画像 → native MP4 → YouTubeアップロード。

## 実行環境

- Windows / Mac を想定する。ffmpeg/native生成を主経路とし、YMM4プロジェクト出力は廃止済み。
- Python 仮想環境: `.venv/`
- 起動: `python gui.py`
- VOICEVOX をローカルで起動しておく必要がある（`http://localhost:50021`）

## 主要ファイル

| ファイル | 役割 |
|---|---|
| `gui.py` | Tkinter GUI。ユーザー操作・バッチ処理・アップロード |
| `main.py` | `run_pipeline()` — 1本分の動画生成パイプライン |
| `config.py` | 定数・設定（音声速度・モデル名・パスなど） |
| `core/parser.py` | 台本パーサー `ScriptParser` |
| `core/ai_generator.py` | Gemini台本生成・画像プロンプト強化 |
| `core/voicevox.py` | VOICEVOX音声生成 |
| `core/image_generator.py` | Nano Banana背景・サムネ生成 |
| `core/ymmp_editor.py` | 旧YMM4タイムライン互換の内部編集ヘルパー |
| `core/native_renderer.py` | ffmpeg/native MP4レンダラー |
| `core/opening_quality.py` | 冒頭品質レビュー（ローカル + Ollama + ChatGPT） |
| `core/upload_scheduler.py` | アップロードスロット管理 |
| `core/upload_records.py` | アップロード記録参照 |
| `core/script_prompts.py` | Gemini台本生成プロンプト構築 |

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
│   ├── upload_record.json
│   ├── thumbnail_ab_test.json  (Longのみ)
│   └── title_ab_test.json      (Longのみ)
├── audio/
└── backgrounds/
```

## 重要な規約・注意点

### ScriptParser

- メタタイプの判定には必ず `ScriptParser.META_TYPES` を使う（`gui.py` / `main.py` 両方で共有）
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

## 2026-05-18 変更メモ

- Shorts 尺ステータスをより細かく分類:
  - `ideal`: 38〜50秒
  - `ok_but_short`: 35〜37秒
  - `ok_but_long`: 51〜55秒
  - `warning`: 32〜34秒 または 56〜58秒
  - `needs_review`: それ以外
- GUI の事前推定尺と最終尺ログの両方で 51〜55秒を「OKだけど長め」と表示（54〜55秒が普通のOKに見えないようにした）
- LLM処理中の表示改善:
  - `main.py` に Ollama 冒頭レビュー開始・終了ログを追加
  - `main.py` に Ollama 冒頭書き直し開始ログを追加
  - `main.py` に ChatGPT 最終レビュー開始ログを追加
- 一括事前チェック（LLM/尺チェックボタン）:
  - `gui.py` に `LLM/尺チェック` ボタンを追加
  - 台本欄に貼り付けた全台本をアセット生成なしでチェック
  - 各台本について Ollama 冒頭レビューと推定尺レビューを実行してサマリーをログ表示
  - 完了後、AI修正依頼レポートをクリップボードにコピー
- スコアログの視認性改善:
  - `gui.py` のスコアタグに色付き背景を追加（強い→緑、警告→黄、低→赤）
  - スコア行に `■■■ ... ■■■` マーカーを追加
  - 冒頭スコア閾値は80。Ollama書き直し候補はローカル再採点し、書き直し後スコアが80以上の場合のみ採用
  - 冒頭スコア70未満またはクリティカルエラーがある場合は `llm_review_required` として扱う
  - 冒頭のクリティカルエラーまたは70未満でパイプラインが停止した場合、GUIは `成功` ではなく `要修正` と表示
  - 主Ollamaモデルがクリティカルエラーなしの70以上候補を出せなかった場合、フォールバックモデル（デフォルト `gemma4:e4b`）を1回だけ試みる
- 台本プロンプト:
  - `core/script_generation_prompt.txt` に「LLM冒頭チェック通過ルール」セクションを追加
  - Shorts1行目に食べ物名・明確な驚き・完結した結論を入れ、サムネ・テロップ・冒頭の意味を一致させることを要求
- 画像レビュー:
  - 画像レビューダイアログのサムネカードにプロンプト編集ボタンを追加
  - 編集したサムネプロンプトを保存すると、そのサムネが再生成対象にマークされ、プロンプトファイルが保存される
- ChatGPT最終レビューフロー:
  - ChatGPT最終レビューを画像・音声・native MP4生成の前に実行するよう変更
  - 推定尺・冒頭レビュー・タイトル/サムネ・台本内容を使用。must_fix、スコア70未満、レビュー失敗、レビュースキップはアセット生成前に停止
  - VOICEVOX実尺計測は音声生成後に引き続き行い、人間判断用にログ記録
- LLMチェック緩和:
  - 冒頭80以上は通過、70〜79はクリティカルエラーなしなら警告として通過、70未満は停止
  - クリティカルエラー: 1行目の食べ物名欠如、1行目の不完全、1行目に驚きなし、同話者4行連続、Shorts21行以上
  - 事前ChatGPTレビューは `must_fix` またはスコア70未満で停止。`must_fix` なしの `publish_ok=false` は警告としてログに残す
  - 推定Shorts尺35秒未満または55秒超はアセット生成前に停止
- アナリティクス:
  - `core/youtube_analytics.py` で動画別YouTube Analyticsを7/28/90日ウィンドウで取得
  - `core/analytics_score.py` でルールベースのS/A/B/C/D評価とactionラベルを付与
  - GUIに独立した `📊 アナリティクス` ウィンドウを追加（色付きスコア行、TSVコピー、AI分析コピー、`output/analytics_score_YYYYMMDD.{json,tsv}` 保存）
