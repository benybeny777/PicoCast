# CLAUDE.md — Codex/Claude Code 向け作業ガイド

## 最重要運用ルール

- `CLAUDE.md` と `AGENTS.md` は常に同期する。Claude/Codex向けの恒久ルールを追加・変更した場合は、同じ内容を両方に反映する。
- Codex側の作業ガイドは `AGENTS.md`、Claude側の作業ガイドは `CLAUDE.md`。片方だけにしか書かれていない運用ルールを見つけたら、作業の一部としてもう片方へ追記する。
- 仕様、画面、プロンプト、設定、YouTube連携、Analytics判定、生成フローを変更した場合は、必ずドキュメントも同時に最新化する。
- 基本は `SPEC.md` を最新仕様の正とし、大きめの変更は `CHANGELOG.md` にも履歴を残す。
- セットアップ、APIキー、設定ファイル、ローカル差し替え運用に影響する変更は `README.md` も更新する。
- ドキュメント更新が不要な軽微修正の場合でも、不要と判断した理由を作業完了時に明記する。
- PowerShellで日本語ファイルを確認するときは、文字化けを避けるためUTF-8を明示する。`$OutputEncoding=[Text.UTF8Encoding]::new($false); Get-Content -Encoding UTF8 ...`、`$env:PYTHONIOENCODING='utf-8'; py -3 -c "... Path(...).read_text(encoding='utf-8') ..."`、`rg`、`git diff` を優先する。
- PowerShell表示が文字化けしても、すぐにソース破損と判断しない。UTF-8で読み直してから判断する。
- 常に Codex / Claude の利用クレジット消費を抑えて作業する。不要な長文出力、重複調査、過剰なファイル読み込み、不要な並列探索、同じ確認のやり直しを避ける。
- まず `rg`、差分確認、必要最小限のファイル読み取り、軽い単体テストで判断する。大きい調査が必要な場合も、読む範囲を絞り、分かったことを短くまとめる。
- 動画生成・画像生成・LLMレビューなど費用が大きくなりやすい操作は必要時だけ実行する。YouTube APIは運用上必要なら使ってよいが、同じ取得や更新を無意味に繰り返さない。
- 既に未コミット変更がある場合は、ユーザーまたは別エージェントの作業として扱い、勝手に巻き戻さない。コミット時は目的に関係する差分だけをステージする。
- 手作業のファイル編集は原則 `apply_patch` で行い、検索はまず `rg` / `rg --files` を使う。
- このリポジトリは開発環境として扱うため、`core/prompt_parts/local/` を更新したら常に対応する `samples/prompt_parts/` へコピーして同期する。localだけに残さない。
- 動画生成・画像生成・LLMレビュー・YouTube更新など費用や外部副作用がある処理は、ユーザー指示または運用上の必要がある場合だけ実行する。

詳細仕様は [SPEC.md](SPEC.md) を参照。ここには作業上の注意点だけを書く。

## プロジェクト概要

「ずんだもんとめたんの食べ物雑学堂」YouTube チャンネル向け動画自動生成ツール。  
台本 → VOICEVOX音声 → Nano Banana背景画像 → YMM4プロジェクト/native MP4 → YouTubeアップロード。

## 実行環境

- Windows専用（pywinauto / YMM4 GUI自動操作を使用）
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
| `core/ymmp_editor.py` | YMM4 `.ymmp` プロジェクト編集 |
| `core/native_renderer.py` | ffmpeg/native MP4レンダラー |
| `core/opening_quality.py` | 冒頭品質レビュー（ローカル + Ollama + ChatGPT） |
| `core/upload_scheduler.py` | アップロードスロット管理 |
| `core/upload_records.py` | アップロード記録参照 |
| `core/script_prompts.py` | Gemini台本生成プロンプト構築 |

## 出力フォルダ構造

```
output/{テーマ名}/
├── script.txt
├── {テーマ名}.ymmp
├── {テーマ名}_native.mp4      ← native出力時
├── thumbnails/          ← サムネイル画像はここ
│   ├── thumbnail.png
│   └── {テーマ名}_thumbnail_A/B/C.png  (Longのみ)
├── _meta/               ← レビュー結果・メタデータはここ
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

### YMM4自動操作
- `core/ymm4_renderer.py` はGUI操作自動化。YMM4のUIが変わると壊れる
- テストやデバッグで `.ymmp` 生成だけ試す場合は `run_pipeline(..., render=False)` 相当の流れで

### gitignore対象（コミット禁止）
- `output/` 全体
- `.env`
- `client_secrets.json`
- `token.json`
- `token_analytics.json`

## 2026-05-18 Note

- Shorts duration status is now more granular:
  - `ideal`: 38-50s
  - `ok_but_short`: 35-37s
  - `ok_but_long`: 51-55s
  - `warning`: 32-34s or 56-58s
  - `needs_review`: outside those ranges
- GUI pre-run estimate and final duration log both show "OKだけど長め" for 51-55s, so 54-55s no longer looks like plain OK.
- LLM wait visibility:
  - `main.py` now logs when Ollama opening review starts/finishes.
  - `main.py` now logs when Ollama opening rewrite starts.
  - `main.py` now logs when ChatGPT final review starts.
- Bulk preflight check:
  - `gui.py` adds `LLM/尺チェック` button.
  - It checks all scripts currently pasted in the text area without generating assets.
  - For each script it runs Ollama opening review and estimated duration review, then logs a summary.
  - After completion, it copies an AI correction request report to the clipboard.
- Score log visibility:
  - `gui.py` score tags now use colored backgrounds: green for strong, yellow for warning, red for low.
  - Score lines now use `■■■ ... ■■■` markers instead of only line separators.
  - Opening score threshold is 80. Ollama rewrite candidates are re-scored locally and are only applied when the post-rewrite score is 80 or higher.
  - Opening scores below 70, or scores with critical errors, are treated as `llm_review_required`.
  - If the pipeline stops because the opening has critical errors or is below 70, the GUI reports it as `要修正` instead of `成功`.
  - If the primary Ollama rewrite model fails to produce a 70+ candidate with no critical errors, the pipeline tries one fallback rewrite model (`gemma4:e4b` by default) once.
- Script prompt:
  - `core/script_generation_prompt.txt` now includes an "LLM冒頭チェック通過ルール" section.
  - It requires Shorts first dialogue to include the food name, clear surprise, and a complete conclusion, with thumbnail/telop/opening meaning aligned.
- Image review:
  - Thumbnail cards in the image review dialog now have a prompt edit button.
  - Saving an edited thumbnail prompt marks that thumbnail for regeneration and writes the prompt file for later reuse.
- ChatGPT review flow:
  - ChatGPT review now runs before image/voice/YMM4 generation.
  - It uses estimated duration, opening review, title/thumbnail, and script content. Must-fix items, score below 70, review failure, or review skip stops before asset generation.
  - Actual VOICEVOX duration is still measured after voice generation and logged for human judgment.
- LLM check relaxation:
  - Opening 80+ is a clean pass, 70-79 can pass as warning if there are no critical errors, and below 70 stops.
  - Critical opening errors are first-line food missing, incomplete first line, no first-line surprise, 4 same-speaker lines in a row, or 21+ Shorts dialogue lines.
  - Pre-generation ChatGPT review stops on `must_fix` or score below 70. `publish_ok=false` without `must_fix` is logged as a warning instead of stopping.
  - Estimated Shorts duration under 35s or over 55s still stops before asset generation.
- Analytics:
  - `core/youtube_analytics.py` fetches video-level YouTube Analytics for 7/28/90 day windows.
  - `core/analytics_score.py` scores videos with rule-based S/A/B/C/D ratings and action labels.
  - GUI has a separate `📊 アナリティクス` window with colored score rows, TSV copy, AI-analysis copy, and `output/analytics_score_YYYYMMDD.{json,tsv}` export.
