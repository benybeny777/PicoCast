# 🤖 AI Handover Document: YMM4 Auto Video Factory

このドキュメントは、本プロジェクト（yukkurijidou）のさらなる開発を継続するAIエージェント向けの引き継ぎ資料です。

---

## 1. プロジェクト概要

**名称:** YMM4 Auto Video Factory  
**目的:** 台本生成から音声合成、背景画像生成、YMM4プロジェクト組み立て、動画出力、YouTubeアップロードまでを全自動化する。  
**対象フォーマット:** YouTube Shorts（1080×1920）および通常動画（1920×1080）。

---

## 2. システムアーキテクチャ

`main.py` がパイプライン全体を制御します。

### パイプライン全体フロー

```
台本テキスト (GUI貼り付け)
  → ai_generator.py   : Gemini でメタデータ補完・台本整形
  → parser.py         : 構造化データへ変換
  → voicevox.py       : 音声WAV生成
  → image_generator.py: 背景画像・サムネイル生成（Nano Banana）
  → ymmp_editor.py    : .ymmp ファイル組み立て
  → [ymm4_renderer.py]: YMM4 GUI 自動操作で動画出力（任意）
  → youtube_uploader.py: YouTube アップロード（任意）
```

### コアモジュール (`core/`)

| ファイル | 役割 |
|---|---|
| `ai_generator.py` | Gemini Flash/Pro でメタデータ・台本生成 |
| `parser.py` | テキスト台本を構造化データへパース |
| `image_generator.py` | Nano Banana（Gemini画像生成）で背景・サムネイル生成 |
| `voicevox.py` | VOICEVOX API で音声WAV生成（uuid ファイル名） |
| `ymmp_editor.py` | YMM4 JSONプロジェクト構造を操作 |
| `ymm4_renderer.py` | pywinauto でYMM4 GUIを自動操作、動画出力を実行 |
| `youtube_uploader.py` | Google OAuth2 経由でYouTube アップロード |

### 設定 (`config.py`)

- Google API キー、VOICEVOX URL/パス、キャラクター設定（Speaker ID）、出力先DIR、MAX_BACKGROUNDS を集約
- 環境変数は `.env` ファイルから読み込み（`GOOGLE_API_KEY` 必須）

---

## 3. 重要な実装詳細

### Shorts / ロング判定

`main.py:_detect_is_shorts()` が台本内の `動画形式: Shorts` 行を検出して自動判定。  
- Shorts: 1080×1920、立ち絵X±200px・Y=700（画面下部86%）
- ロング: 1920×1080、立ち絵X±450px・Y=0（中央）

### 立ち絵配置ルール（TachieItem）

- **全キャラ共通フレーム3開始**: `TACHIE_START_FRAME = 3`、`effective_start = max(start, 3)` でクリップ
- セリフ間のギャップは `ノーマル` で埋めてマージ
- フレーム0〜2 は ymmp の初期化フレームとして空白にする（YMM4表示バグ回避）

### Nano Banana（画像生成）

- **PIL合成なし**: テキストも含めてプロンプトに指示し、Nano Banana が画像内に直接描画
- 背景: `_apply_bottom_gradient()` で下部50%（Shorts時60%）をグラデーション暗転（立ち絵エリア確保）
- サムネイル: Nano Banana Pro で生成

### YMM4 自動レンダリング（`ymm4_renderer.py`）

YMM4 はCLIレンダリング非対応のため pywinauto（UIA バックエンド）でGUI自動操作：
1. `YukkuriMovieMaker.exe <ymmp_path>` でファイルを開きながら起動
2. ツールバーの「動画出力」ボタンをUIAutomation で検索してクリック
3. 出力設定ダイアログの「出力開始」ボタンをクリック
4. 完了ダイアログを検知して結果を返す

**UIツリー確認コマンド**（YMM4起動中に実行）:
```bash
python core/ymm4_renderer.py --inspect
```

### YMM4 プロジェクト JSON 構造

- `.ymmp` = JSON（UTF-8 with BOM）
- 各アイテムは `$type` フィールドで種別識別
- `CharacterId` は UUID、`character_templates.json` から読み込み
- **Volume スケール**: 0〜200（UI上100% = 値200、BGM20% = 値40）
- **TachieItem アニメーション値**: `{"Aliases":null,"Values":[<value>]}` 形式

---

## 4. ファイル・ディレクトリ構成

```
yukkurijidou/
├── main.py                   # パイプライン本体
├── gui.py                    # tkinter GUI
├── config.py                 # 設定（APIキー、キャラクター等）
├── core/
│   ├── ai_generator.py
│   ├── parser.py
│   ├── image_generator.py
│   ├── voicevox.py
│   ├── ymmp_editor.py
│   ├── ymm4_renderer.py      # YMM4 GUI自動操作
│   ├── youtube_uploader.py
│   └── character_templates.json
├── output/                   # 生成物（.gitignore 対象）
│   └── <動画タイトル>/
│       ├── *.ymmp
│       ├── script.txt
│       ├── thumbnail.png
│       ├── metadata.txt
│       ├── audio/
│       └── backgrounds/
└── .env                      # GOOGLE_API_KEY（.gitignore 対象）
```

---

## 5. 技術スタック & 依存関係

| ライブラリ | 用途 |
|---|---|
| `google-genai` | Gemini（台本生成・Nano Banana画像生成） |
| `requests` | VOICEVOX API 通信 |
| `Pillow` | 背景画像後処理（グラデーション合成） |
| `python-dotenv` | .env 読み込み |
| `pywinauto` | YMM4 GUI自動操作（動画出力） |
| `google-auth-*` / `google-api-python-client` | YouTube アップロード |

外部ツール:
- **VOICEVOX** `C:\Program Files\VOICEVOX\VOICEVOX.exe`（必須）
- **YMM4 v4.52.x** `C:\00_PG\YukkuriMovieMaker_v4\YukkuriMovieMaker.exe`

---

## 6. 注意事項・落とし穴

- `ymm4_renderer.py` のUIツリー制御名はYMM4のバージョンアップで変わる可能性がある。動作しない場合は `--inspect` で確認すること
- `.gitignore` で `output/`、`.env`、`client_secrets.json`、`token.json` を除外済み
- `MAX_BACKGROUNDS = 7`（config.py）: コスト制御のため1動画あたりの背景生成上限

---

## 7. 今後の開発課題

1. **ymm4_renderer.py の実機検証**: 初回起動時に `--inspect` でUIツリーを確認し、必要なら制御名を修正
2. **BGM自動選定**: シーンに合わせた動的BGM切り替え
3. **キャラクター自動増員**: 新VOICEVOX キャラのテンプレート自動生成
4. **バッチ動画出力**: 複数ymmpを順次自動レンダリングするバッチ機能
