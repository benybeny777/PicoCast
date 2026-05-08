# 🤖 AI Handover Document: YMM4 Auto Video Factory

このドキュメントは、本プロジェクト（yukkurijidou）のさらなる開発を継続するAIエージェント向けの引き継ぎ資料です。システムの全体像、アーキテクチャ、および重要な実装上の注意点をまとめています。

---

## 1. プロジェクト概要
**名称:** YMM4 Auto Video Factory
**目的:** 台本生成から音声合成、画像生成、BGM選定までを統合し、ゆっくり実況・解説動画用の YMM4 プロジェクトファイル（`.ymmp`）を全自動で生成する。
**主要ターゲット:** YouTube Shorts（1080x1920）および通常動画（1920x1080）。

---

## 2. システムアーキテクチャ
プロジェクトはモジュール化されており、`main.py` がパイプライン全体を制御します。

### 核心コンポーネント (`core/`)
- **`ai_generator.py`**: LLM（Gemini Flash/Pro, Ollama）を使用して動画台本を生成。
- **`parser.py`**: テキスト形式の台本を解析し、構造化データに変換。
- **`image_generator.py`**: Google GenAI（Nano Banana）を使用して背景画像を生成。毎回新規生成でキャッシュなし。
- **`audio_generator.py`**: BGMファイル管理を担当。
- **`voicevox.py`**: VOICEVOX API を叩き、キャラクター音声を生成。毎回新規生成（uuid ファイル名）。
- **`ymmp_editor.py`**: YMM4 の JSON 構造を操作し、`.ymmp` ファイルを構築。

### 設定 (`config.py`)
- APIキー（Google AI）、ローカルエンジンのURL/パス、キャラクター設定（Speaker ID）を集約。

---

## 3. 重要コンセプト

### 「Nano Banana」エコシステム
背景画像の中にテロップ（強調文字）を直接描き込む手法を指します。
- `ai_generator.py` のシステムプロンプトで、背景生成指示に `"TEXT"` を含めるよう厳格に指示しています。
- これにより、フォントと背景が完全に調和した高品質なビジュアルを実現します。

### セーフゾーン設計
YouTube Shorts 等のUI（いいねボタン等）に文字が被らないよう、画像生成プロンプトやテロップ配置において「中央配置」を重視しています。

### キャッシュなし設計
音声・背景画像ともにキャッシュは行わず、毎回新規生成する設計。
- **音声**: `uuid` ベースのファイル名で `audio/` に保存。
- **背景画像**: Nano Banana で毎回生成し `backgrounds/` に保存。

---

## 4. 開発者（AI）向けガイドライン

### 台本解析 (`parser.py`)
- `Character(Emotion): Text` の形式を基本とします。
- `背景: prompt` タグでシーン切り替えを検知します。
- 正規表現によるパースを行っているため、LLMへの出力形式指示は非常に重要です。

### YMM4 プロジェクト操作 (`ymmp_editor.py`)
- `.ymmp` は JSON 形式（UTF-8 with BOM）です。
- 各アイテム（`VoiceItem`, `ImageItem` 等）は `$type` フィールドで識別されます。
- `CharacterId` は UUID で管理されており、`character_templates.json` から設定を読み込むことで、立ち絵の配置位置や表情設定を維持しています。
- **Volume スケール**: YMM4 の Volume 値は 0〜200（200 = UI上100%）。`character_templates.json` の Volume も同スケール。BGM AudioItem も同様（UI上20% = 値40）。

### エラー処理と自己修復
- 生成された台本が空だったり、キャラクター名が不明な場合は `ScriptParser.validate` で検知します。
- LLMには「テロップタグを廃止し、背景指示に含める」というルールを徹底させてください。

---

## 5. 技術スタック & 依存関係
- **Python 3.10+** (`requests`, `google-genai`, `Pillow`, `python-dotenv`)
- **VOICEVOX**: ローカル音声合成エンジン（必須）。
- **Google GenAI (Nano Banana)**: 台本・背景画像生成（`.env` に `GOOGLE_API_KEY` 設定）。
- **Ollama**: ローカルLLMエンジン（フォールバック用、任意）。
- **Yukkuri Movie Maker 4 (YMM4)**: 最終出力先の編集ソフト。

---

## 6. 今後の開発課題
1.  **ComfyUI ワークフローの動的切り替え**: スタイルに応じたワークフロー JSON の切り替え。
2.  **BGM生成の高度化**: Stable Audio 等を利用した、シーンに合わせたBGM生成。
3.  **キャラクターの自動増員**: 新しい VOICEVOX キャラクターが登場した際の、テンプレート自動生成機能。
4.  **UI/UXの改善**: `gui.py` のプレビュー機能の強化。

---

## 💡 AIへのメッセージ
このプロジェクトは「爆速で高品質な動画を量産する」ことを至上命題としています。
コードを修正・拡張する際は、常に **「自動化の徹底」** と **「ビジュアルの美しさ（Nano Banana）」** を意識してください。
特に `ymmp_editor.py` の JSON 構造は非常にデリケートなため、変更時は既存のプロジェクトファイルとの互換性に注意してください。
