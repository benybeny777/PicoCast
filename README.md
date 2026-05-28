<div align="center">
  <h1>🎥 Native Video Factory</h1>
  <p><strong>「ずんだもんとめたんの食べ物雑学堂」向け、台本からの全自動動画生成・投稿システム</strong></p>

  ![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)
  ![VOICEVOX](https://img.shields.io/badge/VOICEVOX-Supported-green?style=for-the-badge)
  ![FastAPI](https://img.shields.io/badge/FastAPI-Framework-009688?style=for-the-badge&logo=fastapi)
  ![ffmpeg](https://img.shields.io/badge/ffmpeg-Native_Render-black?style=for-the-badge&logo=ffmpeg)
</div>

<br />

> 台本を入力するだけで、**VOICEVOXによる音声合成**、**Nano Banana / Stable Diffusion WebUI による背景画像・サムネイル生成**、**ffmpegによる高品質なネイティブMP4動画のレンダリング**、そして**YouTubeへの予約投稿・アナリティクス分析**までをシームレスに行うことができるローカルWebツールです。

---

## 📑 目次

- [🔄 システム処理フロー](#-システム処理フロー)
- [🚀 クイックスタート](#-クイックスタート)
- [🖥 開発環境](#-開発環境)
- [🛠 前提条件 (Prerequisites)](#-前提条件-prerequisites)
- [📦 セットアップ手順](#-セットアップ手順)
- [💻 起動方法と起動オプション](#-起動方法と起動オプション)
- [📝 基本のワークフロー](#-基本のワークフロー)
- [📜 台本フォーマット](#-台本フォーマット)
- [⚙️ 主な設定値 (config.py)](#️-主な設定値-configpy)
- [⚠️ 注意・制約事項](#️-注意制約事項)
- [📢 CTA/Long動画の運用ポリシー](#-ctalong動画の運用ポリシー)

---

## 🔄 システム処理フロー

本システムは、以下のパイプラインに沿って動画を完全自動で生成・投稿します。

```mermaid
graph TD
    A[台本入力・一括処理] --> B[品質レビュー・チェック<br/>ローカル & Ollama & ChatGPT]
    B -->|修正必要/Must Fix| A
    B -->|品質クリア| C[よみがな正規化<br/>SudachiPy + 自前辞書]
    C --> D[音声生成 WAV<br/>VOICEVOX]
    C --> E[背景生成 PNG<br/>Gemini / Stable Diffusion WebUI]
    C --> T[サムネ生成 PNG<br/>Gemini / Stable Diffusion WebUI]
    D --> F[ネイティブレンダリング<br/>ffmpeg]
    E --> F
    T --> F
    F --> G[実尺評価 & 実績保存<br/>native MP4 / _meta]
    G --> H[YouTube予約アップロード<br/>OAuth / スロット管理]
    H --> I[固定コメント投稿]
    I --> J[Analytics スコアリング<br/>S/A/B/C/D 評価]
    J -->|実績データをタイトル案プロンプトへフィードバック| A
```

---

## 🚀 クイックスタート

通常運用では、リポジトリ直下の起動スクリプトから起動する方法を推奨します。仮想環境の Python を直接指定して Web UI を起動し、ブラウザも自動で開きます。

1. **VOICEVOX を起動**しておきます（デフォルトポート: `50021`）。
2. リポジトリ直下の起動スクリプトをダブルクリック、またはターミナルから起動します。
   
   **Windows:**
   ```powershell
   .\start.bat
   ```
   **macOS:**
   ```bash
   ./start.command
   ```
3. 自動的にブラウザが立ち上がり、`http://127.0.0.1:58080` にアクセスできます。

> [!NOTE]
> `start.bat` / `start.command` は内部で `python -m web_app.app --open-browser --reload` を実行しています。普段の操作入口はローカル Web UI です。

---

## 🖥 開発環境

本プロジェクトの主開発機（Windows）の環境です。動作確認はこの構成を基準としています。

| 項目 | 詳細 |
| :--- | :--- |
| OS | Windows 11 Home |
| CPU | Intel Core 7 240H（10コア / 16スレッド） |
| RAM | 32 GB |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU（NVENC 対応） |
| Python | 3.11.9（`.venv` 仮想環境） |
| ffmpeg | 8.0.1 full build（[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 版） |
| デフォルトエンコーダ | `h264_nvenc`（`NATIVE_FFMPEG_ENCODER` 未設定時） |

> [!NOTE]
> macOS 環境での動作については [クイックスタート](#-クイックスタート) および [セットアップ手順](#-セットアップ手順) の macOS 向け手順を参照してください。

---

## 🛠 前提条件 (Prerequisites)

本ツールを使用するには、以下の外部ソフトウェアがローカル環境に導入されている必要があります。

- 🐍 **Python 3.10 以上** (本プロジェクトでは `.venv` 仮想環境を使用します)
- 🗣️ **VOICEVOX** ([公式ホームページ](https://voicevox.nero.ne.jp/)からダウンロード)
- 🎬 **ffmpeg** (パスを通しておくか、環境変数 `FFMPEG_BIN` にバイナリパスを指定してください)
- 🧠 **Ollama** (冒頭品質レビューに利用。デフォルトモデル: `qwen3:8b`)

---

## 📦 セットアップ手順

### Step 1. 仮想環境と依存パッケージの準備

システムの Python ではなく、プロジェクト専用の `.venv` を使います。既に `.venv` が用意済みなら作成手順は不要です。

<details>
<summary><b>仮想環境の作成方法 (クリックして展開)</b></summary>

**Windows:**
```powershell
py -3 -m venv .venv
```

**macOS:**
```bash
python3 -m venv .venv
```
</details>

**依存関係のインストール:**
- **PowerShell:**
  ```powershell
  .venv\Scripts\Activate.ps1
  pip install --upgrade -r requirements.txt
  ```
- **cmd:**
  ```cmd
  .venv\Scripts\activate.bat
  pip install --upgrade -r requirements.txt
  ```
- **macOS:**
  ```bash
  .venv/bin/python -m pip install --upgrade -r requirements.txt
  ```

### Step 2. APIキーとOAuth設定ファイルの配置

リポジトリ直下に環境設定ファイル `.env` を作成し、各種APIキーを設定します。

```env
GOOGLE_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key
HF_TOKEN=your_huggingface_token
```

| キー | 用途 |
|:---|:---|
| `GOOGLE_API_KEY` | Google AI Studio (Gemini API)。台本や背景画像の生成に使用。 |
| `OPENAI_API_KEY` | OpenAI Platform。ChatGPT による台本の生成前最終レビューに使用。 |
| `HF_TOKEN` | Hugging Face トークン。Stable Diffusion WebUI モデルの自動ダウンロード時に使用（任意）。 |

- **`client_secrets.json`:** YouTube API 利用のための OAuth 2.0 クライアント認証情報。Google Cloud Console からダウンロードし、**リポジトリ直下**に配置してください。

> [!IMPORTANT]
> `client_secrets.json`, `.env`, `token.json`, `token_analytics.json` は個人情報やAPIキーを含むため、**絶対に Git にコミットしないでください**。

### Step 3. プロンプト設定の確認

初期状態では、「食べ物雑学」用の設定が適用されます。別ジャンルで運用する場合は、`core/prompt_parts/local/` ディレクトリを作成し、そこに個人用プロンプト部品を配置してください。

### Step 4. Stable Diffusion WebUI で画像生成する場合

Gemini / Nano Banana の代替として、APIキーなしでローカルに画像生成したい場合に使用します。

- Stable Diffusion WebUI を `--api` オプション付きで起動してください（例: `webui.bat --api`）。
- APIが `http://127.0.0.1:7860` で応答している必要があります。

**.env 設定例:**
```env
IMAGE_BACKEND=sd_webui
SD_WEBUI_BASE_URL=http://127.0.0.1:7860
SD_WEBUI_MODEL=
SD_WEBUI_SAMPLER=DPM++ 2M Karras
SD_WEBUI_STEPS=24
SD_WEBUI_WIDTH=1024
SD_WEBUI_HEIGHT=576
```

> [!TIP]
> `IMAGE_BACKEND=sd_webui` のとき、Stable Diffusion WebUI が未起動であれば画像生成は**停止**します。自動切替は行われません。

---

## 💻 起動方法と起動オプション

### 手動起動（トラブル対応・開発用）

ポート変更やリロード設定を自分で指定したい場合だけ、仮想環境の Python を直接実行します。

```powershell
# 自動でブラウザを開く場合
.\.venv\Scripts\python.exe -m web_app.app --open-browser

# 開発用（自動リロード有効）
.\.venv\Scripts\python.exe -m web_app.app --reload --open-browser
```

### 主要な起動引数

| オプション | 説明 |
| :--- | :--- |
| `--port N` | ポートを指定して起動（デフォルト: `58080`） |
| `--auto-port` | 競合時、自動的に次の空きポートを探して起動 |
| `--open-browser` | サーバー起動後、自動的にウェブブラウザを開く |
| `--reload` | ソースコード変更検知で自動再起動（開発向け） |

---

## 📝 基本のワークフロー

1. **起動:** VOICEVOXを起動し、起動スクリプトでWeb UIを開く。
2. **実績同期:** `Analytics` 画面で YouTube 実績データを取得。
3. **タイトル作成:** 実績を基に AI にタイトル案を出させる。
4. **台本作成:** 採用したタイトルから AI に台本を作成させる。
5. **生成:** 台本を貼り付け、`生成開始` を押す。
6. **確認:** `履歴` または `画像確認・再生成` 画面でサムネイルと背景画像を確認・調整。
7. **アップロード:** YouTube 予約スロットへ投稿。
8. **コメント投稿:** `固定コメント` 画面で公開済み動画にコメント。
9. **スケジュール:** YouTube 側の予約状態を同期。

---

## 📜 台本フォーマット

台本テキストの先頭に動画のメタ情報を定義し、空行を挟んでセリフや演出を記述します。

```text
動画形式: Shorts
動画タイトル: チョコは500年間ずっと飲み物だった
サムネ文字: 飲み物
説明文: チョコレートの驚きの歴史を解説！
タグ: ずんだもん,ゆっくり解説,VOICEVOX,食べ物 雑学,雑学 ショート
生成区分: 横展開

背景: 漫画風イラスト調。ヨーロッパの古い街並み。
ずんだもん(ノーマル): チョコは昔、薬の飲み物だったのだ！
四国めたん(ツンツン): えーっ！薬ですの！？
テロップ: 薬だった！
```

- **`()`**: VOICEVOX のスタイル指定
- **`[]`**: ネイティブ立ち絵の表情指定
- **複数処理**: `━━ 動画1 ━━` で区切ることで一括処理可能。

---

## ⚙️ 主な設定値 (config.py)

優先順位は **`.env` / 環境変数 > `config.py` の既定値** です。

| 設定項目 | 既定値 | 説明 |
| :--- | :--- | :--- |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | 台本生成用のAIモデル |
| `NANOBANANA_PRO_MODEL` | `gemini-3-pro-image-preview` | 背景・サムネの高品質モデル |
| `NATIVE_AUDIO_LOUDNORM_ENABLED`| `True` | ラウドネス正規化の適用 |
| `MAX_BACKGROUNDS_SHORTS` | `9` | Shorts 1本あたりの最大背景枚数 |

---

## ⚠️ 注意・制約事項

- **ローカル限定:** Web UI は `127.0.0.1` で使う前提です。外部公開しないでください。
- **外部API費用:** ChatGPT API と Google API は費用が発生する場合があります。

---

## 📢 CTA/Long動画の運用ポリシー

- **Shorts本編のループ視聴優先:** 直接的な誘導セリフは警告対象。「ネタ募集CTA」は既定で5本に1本のみ許可。
- **Long動画の目次:** 概要欄用の `【目次】(0:00形式)` チャプターマーカーを自動追加。
- **Longサムネイル A/B テスト:** 3パターンのサムネイル画像を自動出力し YouTube Studio でのテストをサポート。


