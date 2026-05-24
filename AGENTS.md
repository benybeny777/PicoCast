# AGENTS.md — Codex/Claude Code 向け作業ガイド

このファイルは Codex 用の作業ガイドです。Claude 用の `CLAUDE.md` と常に同期してください。

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

```text
output/{テーマ名}/
├── script.txt
├── {テーマ名}.ymmp
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

### YMM4自動操作

- `core/ymm4_renderer.py` はGUI操作自動化。YMM4のUIが変わると壊れる
- テストやデバッグで `.ymmp` 生成だけ試す場合は `run_pipeline(..., render=False)` 相当の流れで

### gitignore対象（コミット禁止）

- `output/` 全体
- `.env`
- `client_secrets.json`
- `token.json`
- `token_analytics.json`
