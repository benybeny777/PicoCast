# CLAUDE.md — Codex/Claude Code 向け作業ガイド

詳細仕様は [SPEC.md](SPEC.md) を参照。ここには作業上の注意点だけを書く。

## プロジェクト概要

「ずんだもんとめたんの食べ物雑学堂」YouTube チャンネル向け動画自動生成ツール。  
台本 → VOICEVOX音声 → Nano Banana背景画像 → YMM4プロジェクト → YouTubeアップロード。

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
| `core/opening_quality.py` | 冒頭品質レビュー（ローカル + Ollama + ChatGPT） |
| `core/upload_scheduler.py` | アップロードスロット管理 |
| `core/script_prompts.py` | Gemini台本生成プロンプト構築 |

## 出力フォルダ構造

```
output/{テーマ名}/
├── script.txt
├── {テーマ名}.ymmp
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

### 説明文処理
- VOICEVOXクレジット手書き行は自動除去（警告なし）
- `_VOICEVOX_CREDIT` / `_CHANNEL_FOOTER` を末尾に自動付与

### YMM4自動操作
- `core/ymm4_renderer.py` はGUI操作自動化。YMM4のUIが変わると壊れる
- テストやデバッグで `.ymmp` 生成だけ試す場合は `run_pipeline(..., render=False)` 相当の流れで

### gitignore対象（コミット禁止）
- `output/` 全体
- `.env`
- `client_secrets.json`
- `token.json`
