import ast
import os
from dotenv import load_dotenv
load_dotenv()

_ENV_VALUE_QUOTES = "\"'`´‘’“”＇＂"


def _clean_env_choice(value: str) -> str:
    """設定画面に出す選択肢から、.env由来の余分な引用符を取り除く。"""
    cleaned = str(value).strip()
    while len(cleaned) >= 2 and cleaned[0] in _ENV_VALUE_QUOTES and cleaned[-1] in _ENV_VALUE_QUOTES:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _split_env_choices(value: str) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(choice for raw in value if (choice := _clean_env_choice(raw)))
    text = str(value).strip()
    if text.startswith(("[", "(")) and text.endswith(("]", ")")):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, (list, tuple)):
            return tuple(choice for raw in parsed if (choice := _clean_env_choice(raw)))
    return tuple(choice for raw in text.split(",") if (choice := _clean_env_choice(raw)))


# ───────────────────────────────────────────────
# VOICEVOX
# ───────────────────────────────────────────────
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://localhost:50021")  # VOICEVOX エンジン API エンドポイント
VOICEVOX_PATH = os.environ.get("VOICEVOX_PATH", "")                     # VOICEVOX 自動起動用パス（空=手動起動）

# ───────────────────────────────────────────────
# 音声速度 — native レンダラー用（字幕追従ズレ対策でやや遅め）
# ───────────────────────────────────────────────
NATIVE_SHORTS_BODY_VOICE_SPEED  = float(os.environ.get("NATIVE_SHORTS_BODY_VOICE_SPEED",  "1.25"))  # Shorts 本編
NATIVE_SHORTS_INTRO_VOICE_SPEED = float(os.environ.get("NATIVE_SHORTS_INTRO_VOICE_SPEED", "1.40"))  # Shorts 冒頭
NATIVE_LONG_BODY_VOICE_SPEED    = float(os.environ.get("NATIVE_LONG_BODY_VOICE_SPEED",    "1.20"))  # Long 本編
NATIVE_LONG_INTRO_VOICE_SPEED   = float(os.environ.get("NATIVE_LONG_INTRO_VOICE_SPEED",   "1.40"))  # Long 冒頭
VOICE_SPEED_SCALE = NATIVE_SHORTS_BODY_VOICE_SPEED  # VOICEVOX API のデフォルト値。生成時は用途別速度を明示指定する
VOICE_POST_PHONEME_LENGTH = 0.0  # 各音声 WAV 末尾に追加する無音（秒）。0 = 無効

# 冒頭速度切り替えモード
VOICE_INTRO_FAST_LINES = int(os.environ.get("VOICE_INTRO_FAST_LINES", "3"))                     # line_count モード: 冒頭 N 行をイントロ速度にする

# native Shorts 速度許容範囲（プリフライトチェック用）
NATIVE_SHORTS_INTRO_VOICE_SPEED_MIN = 1.35
NATIVE_SHORTS_INTRO_VOICE_SPEED_MAX = 1.45
NATIVE_SHORTS_BODY_VOICE_SPEED_MIN  = 1.20
NATIVE_SHORTS_BODY_VOICE_SPEED_MAX  = 1.30

# ───────────────────────────────────────────────
# native 音声 loudnorm（BGM+ナレーション合成後の最終 MP4 に適用）
# ───────────────────────────────────────────────
NATIVE_AUDIO_LOUDNORM_ENABLED = os.environ.get("NATIVE_AUDIO_LOUDNORM_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")  # loudnorm 有効/無効
NATIVE_AUDIO_LOUDNORM_I  = float(os.environ.get("NATIVE_AUDIO_LOUDNORM_I",   "-15"))   # Integrated loudness 目標 (LUFS)
NATIVE_AUDIO_LOUDNORM_TP = float(os.environ.get("NATIVE_AUDIO_LOUDNORM_TP",  "-1.5"))  # True Peak 上限 (dBTP)
NATIVE_AUDIO_LOUDNORM_LRA = float(os.environ.get("NATIVE_AUDIO_LOUDNORM_LRA", "6"))    # Loudness Range 目標 (LU)

# ───────────────────────────────────────────────
# native セリフ間無音（秒）
# ───────────────────────────────────────────────
NATIVE_MIN_SILENCE_BETWEEN_LINES     = float(os.environ.get("NATIVE_MIN_SILENCE_BETWEEN_LINES",     "0.10"))  # 許容最小値
NATIVE_DEFAULT_SILENCE_BETWEEN_LINES = float(os.environ.get("NATIVE_DEFAULT_SILENCE_BETWEEN_LINES", "0.12"))  # 通常セリフ間
NATIVE_SCENE_CHANGE_SILENCE          = float(os.environ.get("NATIVE_SCENE_CHANGE_SILENCE",          "0.18"))  # 背景切り替え時
NATIVE_MAX_NORMAL_SILENCE            = float(os.environ.get("NATIVE_MAX_NORMAL_SILENCE",            "0.35"))  # この値超は警告
NATIVE_WARNING_SILENCE               = float(os.environ.get("NATIVE_WARNING_SILENCE",               "0.50"))  # この値超は要確認

# ───────────────────────────────────────────────
# native BGM 音量
# ───────────────────────────────────────────────
NATIVE_BGM_VOLUME_DB = float(os.environ.get("NATIVE_BGM_VOLUME_DB", "-20"))  # native 出力の BGM 音量 (dB)

# ───────────────────────────────────────────────
# キャラクター表示 — 腰から上モード（native 共通）
# ───────────────────────────────────────────────
CHARACTER_UPPER_BODY_MODE              = os.environ.get("CHARACTER_UPPER_BODY_MODE", "1").strip().lower() in ("1", "true", "yes", "on")  # 有効で腰から上表示
CHARACTER_UPPER_BODY_SCALE             = float(os.environ.get("CHARACTER_UPPER_BODY_SCALE",             "1.55"))  # Long: キャラ拡大倍率
CHARACTER_UPPER_BODY_SHORTS_SCALE      = float(os.environ.get("CHARACTER_UPPER_BODY_SHORTS_SCALE",      "1.15"))  # Shorts: キャラ拡大倍率（縦画面は幅が狭いため Long より小さく）
CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET   = int(os.environ.get("CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET",   "250"))    # Shorts: 下方向シフト量 (px)
CHARACTER_UPPER_BODY_LONG_Y_OFFSET     = int(os.environ.get("CHARACTER_UPPER_BODY_LONG_Y_OFFSET",     "400"))    # Long: 下方向シフト量 (px)

# キャラクター表示 — native Shorts 非腰上モード時の倍率（CHARACTER_UPPER_BODY_MODE=0 のときのみ使用）
NATIVE_SHORTS_CHARACTER_SCALE = float(os.environ.get("NATIVE_SHORTS_CHARACTER_SCALE", "1.05"))

# ───────────────────────────────────────────────
# native Shorts スクリプト品質チェック閾値
# ───────────────────────────────────────────────
NATIVE_SHORTS_ESTIMATE_BASE_CPS   = float(os.environ.get("NATIVE_SHORTS_ESTIMATE_BASE_CPS",   "5.4"))   # 推定尺計算の基準文字数/秒
NATIVE_SHORTS_CHARS_MUST_FIX_MIN  = int(os.environ.get("NATIVE_SHORTS_CHARS_MUST_FIX_MIN",  "260"))    # これ未満の総文字数は must_fix
NATIVE_SHORTS_TARGET_CHARS_MIN    = int(os.environ.get("NATIVE_SHORTS_TARGET_CHARS_MIN",    "280"))    # 目標文字数の下限
NATIVE_SHORTS_TARGET_CHARS_MAX    = int(os.environ.get("NATIVE_SHORTS_TARGET_CHARS_MAX",    "330"))    # 目標文字数の上限
NATIVE_SHORTS_AVG_CHARS_MIN       = float(os.environ.get("NATIVE_SHORTS_AVG_CHARS_MIN",     "11.5"))   # 1行あたり平均文字数の下限
NATIVE_SHORTS_SHORT_LINE_MAX      = int(os.environ.get("NATIVE_SHORTS_SHORT_LINE_MAX",      "4"))      # 短すぎる行（≤4文字）の最大許容数

# native Shorts セリフ数ルール
NATIVE_SHORTS_LINES_IDEAL_MIN  = 22   # 理想セリフ数: 下限
NATIVE_SHORTS_LINES_IDEAL_MAX  = 28   # 理想セリフ数: 上限
NATIVE_SHORTS_LINES_TARGET_MIN = int(os.environ.get("NATIVE_SHORTS_LINES_TARGET_MIN", "24"))  # 目標セリフ数: 下限
NATIVE_SHORTS_LINES_TARGET_MAX = int(os.environ.get("NATIVE_SHORTS_LINES_TARGET_MAX", "27"))  # 目標セリフ数: 上限
NATIVE_SHORTS_LINES_WARNING    = 29   # 29〜30行: warning
NATIVE_SHORTS_LINES_MUST_FIX   = 31  # 31行以上: must_fix

# ───────────────────────────────────────────────
# API キー・外部 LLM
# ───────────────────────────────────────────────
GOOGLE_API_KEY  = os.environ.get("GOOGLE_API_KEY", "")   # Google AI Studio キー（Gemini / 画像生成）
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY", "")   # OpenAI キー（ChatGPT 台本レビュー）

# 冒頭品質レビュー（Ollama）
OPENING_REVIEW_USE_LLM      = os.environ.get("OPENING_REVIEW_USE_LLM",      "1").strip().lower() in ("1", "true", "yes", "on")  # Ollama レビュー有効/無効
OPENING_REVIEW_PROVIDER     = os.environ.get("OPENING_REVIEW_PROVIDER",     "ollama").strip().lower()                            # 現状 "ollama" 固定
OPENING_REVIEW_MODEL        = os.environ.get("OPENING_REVIEW_MODEL",        "qwen3:8b")                                          # レビューモデル
OPENING_REVIEW_AUTO_REWRITE = os.environ.get("OPENING_REVIEW_AUTO_REWRITE", "1").strip().lower() in ("1", "true", "yes", "on")  # スコア不足時に自動リライトするか
OPENING_SCORE_ABORT_THRESHOLD      = int(os.environ.get("OPENING_SCORE_ABORT_THRESHOLD",      "80"))  # これ未満: warning 扱い
OPENING_SCORE_HARD_ABORT_THRESHOLD = int(os.environ.get("OPENING_SCORE_HARD_ABORT_THRESHOLD", "70"))  # これ未満: 処理中止
OPENING_REVIEW_MAX_LLM_RETRIES     = int(os.environ.get("OPENING_REVIEW_MAX_LLM_RETRIES",     "1"))   # LLM リトライ上限
OLLAMA_BASE_URL              = os.environ.get("OLLAMA_BASE_URL",              "http://localhost:11434")  # Ollama API エンドポイント
OLLAMA_REVIEW_MODEL          = os.environ.get("OLLAMA_REVIEW_MODEL",          "qwen3:8b")               # 冒頭レビューモデル
OLLAMA_REWRITE_MODEL         = os.environ.get("OLLAMA_REWRITE_MODEL",         "qwen3:8b")               # 冒頭リライトモデル
OLLAMA_TRANSLATE_MODEL       = os.environ.get("OLLAMA_TRANSLATE_MODEL",       "qwen3:8b")               # SD プロンプト日→英翻訳モデル

# ───────────────────────────────────────────────
# 画像生成バックエンド統合設定
# ───────────────────────────────────────────────
IMAGE_BACKEND = os.environ.get("IMAGE_BACKEND", "gemini").strip().lower()  # 画像生成バックエンド（gemini / sd_webui）
SD_WEBUI_BASE_URL = os.environ.get("SD_WEBUI_BASE_URL", "http://127.0.0.1:7860")  # Stable Diffusion WebUI Forge / A1111 API URL
SD_WEBUI_TIMEOUT_SEC = int(os.environ.get("SD_WEBUI_TIMEOUT_SEC", "180"))          # SD WebUI API タイムアウト(秒)
SD_WEBUI_MODEL = os.environ.get("SD_WEBUI_MODEL", "")                              # SD WebUI で使用するモデル名（空=起動中モデルをそのまま使用）
SD_WEBUI_SAMPLER = os.environ.get("SD_WEBUI_SAMPLER", "DPM++ 2M Karras")           # SD WebUI サンプラー名
SD_WEBUI_STEPS = int(os.environ.get("SD_WEBUI_STEPS", "24"))                       # SD WebUI 生成ステップ数
SD_WEBUI_CFG_SCALE = float(os.environ.get("SD_WEBUI_CFG_SCALE", "7"))              # SD WebUI CFGスケール
SD_WEBUI_WIDTH = int(os.environ.get("SD_WEBUI_WIDTH", "1024"))                     # SD WebUI 出力幅(px) — 背景デフォルト
SD_WEBUI_HEIGHT = int(os.environ.get("SD_WEBUI_HEIGHT", "576"))                    # SD WebUI 出力高さ(px) — 背景デフォルト
SD_WEBUI_NEGATIVE_PROMPT = os.environ.get(                                         # SD WebUI ネガティブプロンプト（人物・低品質抑制）
    "SD_WEBUI_NEGATIVE_PROMPT",
    "people, human, person, face, hands, photorealistic, realistic photo, "
    "bad anatomy, blurry, low quality, watermark, signature, logo, "
    "unreadable text, garbled text",
)
SD_WEBUI_ROOT = os.environ.get("SD_WEBUI_ROOT", "")                                # SD WebUI / Forge 本体ルートディレクトリ（例: C:\sd.webui\webui）
SD_MODEL_MANIFEST_PATH = os.environ.get(                                            # SD WebUI モデルマニフェストパス（空=同梱既定値を使用）
    "SD_MODEL_MANIFEST_PATH",
    os.path.join(os.path.dirname(__file__), "assets", "sd_webui", "model_manifest.json"),
)
AUTO_DOWNLOAD_SD_MODELS = os.environ.get("AUTO_DOWNLOAD_SD_MODELS", "0").strip().lower() in ("1", "true", "yes", "on")  # 未導入モデルの自動ダウンロード許可（0=停止/手動のみ, 1=自動可）
HF_TOKEN = os.environ.get("HF_TOKEN", "")                                           # Hugging Face アクセストークン（認証付きモデルのダウンロードに使用）


OLLAMA_REWRITE_FALLBACK_MODEL = os.environ.get("OLLAMA_REWRITE_FALLBACK_MODEL", "gemma4:e4b")           # リライト失敗時のフォールバックモデル
OPENING_REWRITE_MAX_FALLBACKS = int(os.environ.get("OPENING_REWRITE_MAX_FALLBACKS", "1"))               # フォールバック試行上限

# ChatGPT 生成前レビュー
OPENAI_FINAL_REVIEW_ENABLED  = os.environ.get("OPENAI_FINAL_REVIEW_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")  # レビュー有効/無効
OPENAI_FINAL_REVIEW_MODEL    = os.environ.get("OPENAI_FINAL_REVIEW_MODEL",   "gpt-5.2")                                          # レビューモデル
SHORT_FULL_SCRIPT_REVIEW     = os.environ.get("SHORT_FULL_SCRIPT_REVIEW",    "1").strip().lower() in ("1", "true", "yes", "on")  # Shorts 全文レビュー
LONG_FULL_SCRIPT_REVIEW      = os.environ.get("LONG_FULL_SCRIPT_REVIEW",     "0").strip().lower() in ("1", "true", "yes", "on")  # Long 全文レビュー（重いため OFF）
AUTO_FULL_REWRITE_ENABLED    = os.environ.get("AUTO_FULL_REWRITE_ENABLED",   "0").strip().lower() in ("1", "true", "yes", "on")  # must_fix 時に自動全文リライトするか

# ───────────────────────────────────────────────
# よみがな正規化（VOICEVOX 誤読対策 / SudachiPy + 自前辞書）
# ───────────────────────────────────────────────
# [DEPRECATED] LLM全文読み補正は廃止されました
# VOICE_READING_NORMALIZE_ENABLED    = os.environ.get("VOICE_READING_NORMALIZE_ENABLED",    "1").strip().lower() in ("1", "true", "yes", "on")
# VOICE_READING_NORMALIZE_MODEL      = os.environ.get("VOICE_READING_NORMALIZE_MODEL",      "qwen2.5:7b-instruct")
# VOICE_READING_NORMALIZE_OLLAMA_URL = os.environ.get("VOICE_READING_NORMALIZE_OLLAMA_URL", "http://localhost:11434")

# 新しい読み補正モード: "off", "dictionary", "safe_auto"
VOICE_READING_MODE = os.environ.get("VOICE_READING_MODE", "safe_auto")  # 読み補正モード
VOICE_READING_BASE_DICT_PATH = os.environ.get("VOICE_READING_BASE_DICT_PATH", "data/reading_dictionary_base.json")  # 同梱読み辞書パス
VOICE_READING_USER_DICT_PATH = os.environ.get("VOICE_READING_USER_DICT_PATH", "data/reading_dictionary_user.json")  # ユーザー読み辞書パス
VOICE_READING_CANDIDATES_PATH = os.environ.get("VOICE_READING_CANDIDATES_PATH", "data/reading_candidates.json")  # 読み補正候補保存パス

# ───────────────────────────────────────────────
# Google AI モデル（Nano Banana Suite）
# ───────────────────────────────────────────────
GEMINI_MODEL          = os.environ.get("GEMINI_MODEL",          "gemini-3.1-pro-preview")       # 台本生成モデル
NANOBANANA_PRO_MODEL  = os.environ.get("NANOBANANA_PRO_MODEL",  "gemini-3-pro-image-preview")   # 背景・サムネ生成（高品質）
NANOBANANA_FLASH_MODEL = os.environ.get("NANOBANANA_FLASH_MODEL", "gemini-3.1-flash-image-preview")  # 背景・サムネ生成（高速）
SD_SIZE_IMAGE_SCALE   = float(os.environ.get("SD_SIZE_IMAGE_SCALE", "0.5"))                     # SD 生成モード: 縮小倍率（生成後に拡大）


# ───────────────────────────────────────────────
# キャラクター定義（VOICEVOX スピーカー ID）
# ───────────────────────────────────────────────
CHARACTERS = {
    "ずんだもん": {
        "speaker_id": 3,
        "name": "ずんだもん",
        "styles": {
            "ノーマル": 3, "あまあま": 1, "ツンツン": 7, "セクシー": 5, "ささやき": 22, "ヒソヒソ": 38
        }
    },
    "めたん": {
        "speaker_id": 2,
        "name": "四国めたん",
        "styles": {
            "ノーマル": 2, "あまあま": 0, "ツンツン": 6, "セクシー": 4, "ささやき": 36, "ヒソヒソ": 37
        }
    },
}

# ───────────────────────────────────────────────
# 動画・ffmpeg 基本設定
# ───────────────────────────────────────────────
VIDEO_FPS  = 30                                                  # 出力フレームレート
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")             # ffmpeg バイナリパス
NATIVE_FFMPEG_TIMEOUT_SEC = float(os.environ.get("NATIVE_FFMPEG_TIMEOUT_SEC", "900"))  # nativeレンダーのffmpeg 1コマンド最大実行秒数
NATIVE_FFPROBE_TIMEOUT_SEC = float(os.environ.get("NATIVE_FFPROBE_TIMEOUT_SEC", "30"))  # nativeレンダーのffprobe 最大実行秒数

# Shorts 先頭サムネイルフレーム保持数（1〜5フレーム。デフォルト3≒0.1秒）
# 1=0.033s(最小), 3=0.100s(標準), 5=0.167s(サムネ重視)
# 不正値・空文字は3にフォールバック。1未満→1、5超→5にクランプ。Long には影響しない
try:
    _thumbnail_hold_raw = int(os.environ.get("THUMBNAIL_HOLD_FRAMES_SHORTS", "3"))
except (ValueError, TypeError):
    _thumbnail_hold_raw = 3
THUMBNAIL_HOLD_FRAMES_SHORTS: int = max(1, min(5, _thumbnail_hold_raw))  # Shorts先頭サムネ保持フレーム数
ASSETS_DIR        = os.path.join(os.path.dirname(__file__), "assets")
CHARACTER_PNG_DIR = os.path.join(ASSETS_DIR, "characters")      # キャラ PNG 格納ディレクトリ
CHARACTER_PSD_DIR = os.path.join(CHARACTER_PNG_DIR, "psd")      # キャラ PSD 格納ディレクトリ
ZUNDAMON_PSD_PATH = os.environ.get("ZUNDAMON_PSD_PATH", os.path.join(CHARACTER_PSD_DIR, "zundamon.psd"))
METAN_PSD_PATH    = os.environ.get("METAN_PSD_PATH",    os.path.join(CHARACTER_PSD_DIR, "metan.psd"))
CHARACTER_PNGS = {
    "ずんだもん": os.path.join(CHARACTER_PNG_DIR, "zundamon.png"),
    "四国めたん": os.path.join(CHARACTER_PNG_DIR, "metan.png"),
}
CHARACTER_EXPRESSION_PNGS = {
    "ずんだもん": {
        "驚き": os.environ.get("ZUNDAMON_EXPRESSION_SURPRISE_PNG", os.path.join(CHARACTER_PNG_DIR, "zundamon_surprise.png")),
        "焦り": os.environ.get("ZUNDAMON_EXPRESSION_PANIC_PNG", os.path.join(CHARACTER_PNG_DIR, "zundamon_panic.png")),
        "得意げ": os.environ.get("ZUNDAMON_EXPRESSION_CONFIDENT_PNG", os.path.join(CHARACTER_PNG_DIR, "zundamon_confident.png")),
        "困惑": os.environ.get("ZUNDAMON_EXPRESSION_CONFUSED_PNG", os.path.join(CHARACTER_PNG_DIR, "zundamon_confused.png")),
        "にやけ": os.environ.get("ZUNDAMON_EXPRESSION_SMIRK_PNG", os.path.join(CHARACTER_PNG_DIR, "zundamon_smirk.png")),
    },
    "四国めたん": {
        "驚き": os.environ.get("METAN_EXPRESSION_SURPRISE_PNG", os.path.join(CHARACTER_PNG_DIR, "metan_surprise.png")),
        "呆れ": os.environ.get("METAN_EXPRESSION_EXASPERATED_PNG", os.path.join(CHARACTER_PNG_DIR, "metan_exasperated.png")),
        "ジト目": os.environ.get("METAN_EXPRESSION_SUSPICIOUS_PNG", os.path.join(CHARACTER_PNG_DIR, "metan_suspicious.png")),
        "ドン引き": os.environ.get("METAN_EXPRESSION_APPALLED_PNG", os.path.join(CHARACTER_PNG_DIR, "metan_appalled.png")),
        "ニヤリ": os.environ.get("METAN_EXPRESSION_SMIRK_PNG", os.path.join(CHARACTER_PNG_DIR, "metan_smirk.png")),
    },
}
THUMBNAIL_CHARACTER_PNGS = {                                     # サムネイル生成時に使うキャラ画像
    "ずんだもん": os.path.join(CHARACTER_PNG_DIR, "zundamon.png"),
    "四国めたん": os.path.join(CHARACTER_PNG_DIR, "metan.png"),
}

# ───────────────────────────────────────────────
# native ffmpeg エンコーダ設定
# ───────────────────────────────────────────────
NATIVE_FFMPEG_ENCODER = os.environ.get("NATIVE_FFMPEG_ENCODER", "h264_nvenc").strip()  # エンコーダ（NVENC / libx264 等）
NATIVE_FFMPEG_PRESET  = os.environ.get("NATIVE_FFMPEG_PRESET", "p5" if NATIVE_FFMPEG_ENCODER in ("h264_nvenc", "hevc_nvenc") else "veryfast")  # エンコードプリセット
NATIVE_FFMPEG_CRF     = os.environ.get("NATIVE_FFMPEG_CRF",     "20")          # CRF 値（libx264 用）
NATIVE_FFMPEG_CQ      = os.environ.get("NATIVE_FFMPEG_CQ",      "23")          # CQ 値（NVENC 用）

# ───────────────────────────────────────────────
# native キャラクター描画
# ───────────────────────────────────────────────
NATIVE_RENDER_CHARACTERS = os.environ.get("NATIVE_RENDER_CHARACTERS", "1").strip().lower() in ("1", "true", "yes", "on")  # キャラ描画 有効/無効
NATIVE_ENABLE_LIPSYNC    = os.environ.get("NATIVE_ENABLE_LIPSYNC",    "1").strip().lower() in ("1", "true", "yes", "on")  # リップシンク有効/無効
NATIVE_ENABLE_BLINK      = os.environ.get("NATIVE_ENABLE_BLINK",      "1").strip().lower() in ("1", "true", "yes", "on")  # まばたき有効/無効

# キャラクター位置・サイズ（native）
NATIVE_CHARACTER_HEIGHT_SHORTS       = int(os.environ.get("NATIVE_CHARACTER_HEIGHT_SHORTS",       "1000"))  # Shorts: キャラ基本高さ (px)
NATIVE_CHARACTER_HEIGHT_LONG         = int(os.environ.get("NATIVE_CHARACTER_HEIGHT_LONG",         "598"))   # Long: キャラ基本高さ (px)
NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS = int(os.environ.get("NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS", "-360"))  # Shorts: 下マージン (px, 負=画面外下)
NATIVE_CHARACTER_SIDE_MARGIN_SHORTS   = int(os.environ.get("NATIVE_CHARACTER_SIDE_MARGIN_SHORTS",   "-80"))   # Shorts: 左右マージン (px, 負=画面外)
NATIVE_CHARACTER_BOTTOM_MARGIN_LONG   = int(os.environ.get("NATIVE_CHARACTER_BOTTOM_MARGIN_LONG",   "40"))    # Long: 下マージン (px)
NATIVE_CHARACTER_SIDE_MARGIN_LONG     = int(os.environ.get("NATIVE_CHARACTER_SIDE_MARGIN_LONG",     "-40"))   # Long: 左右マージン (px, 負=画面外)

# ───────────────────────────────────────────────
# native 背景トランジション
# ───────────────────────────────────────────────
NATIVE_BACKGROUND_TRANSITION     = os.environ.get("NATIVE_BACKGROUND_TRANSITION",     "fade").strip().lower()  # トランジション種別（"fade" / "none"）
NATIVE_BACKGROUND_TRANSITION_SEC = float(os.environ.get("NATIVE_BACKGROUND_TRANSITION_SEC", "0.18"))           # フェード時間 (秒)

# ───────────────────────────────────────────────
# native Shorts 軽量モーション演出
# ───────────────────────────────────────────────
NATIVE_ENABLE_MOTION_EFFECTS = os.environ.get("NATIVE_ENABLE_MOTION_EFFECTS", "1").strip().lower() in ("1", "true", "yes", "on")  # native Shorts の軽量演出全体
NATIVE_ENABLE_BG_KEN_BURNS = os.environ.get("NATIVE_ENABLE_BG_KEN_BURNS", "1").strip().lower() in ("1", "true", "yes", "on")  # 背景のゆっくりズーム/パン
NATIVE_ENABLE_CHARACTER_BOUNCE = os.environ.get("NATIVE_ENABLE_CHARACTER_BOUNCE", "1").strip().lower() in ("1", "true", "yes", "on")  # 話者開始時の軽いバウンス
NATIVE_ENABLE_POP_TELOP = os.environ.get("NATIVE_ENABLE_POP_TELOP", "1").strip().lower() in ("1", "true", "yes", "on")  # テロップ行のポップ表示
NATIVE_ENABLE_SHAKE = os.environ.get("NATIVE_ENABLE_SHAKE", "1").strip().lower() in ("1", "true", "yes", "on")  # ツッコミ/驚き時の軽い画面揺れ
NATIVE_MAX_SHAKE_COUNT_SHORTS = int(os.environ.get("NATIVE_MAX_SHAKE_COUNT_SHORTS", "4"))  # Shorts 1本あたりのシェイク最大回数
NATIVE_MAX_ICON_COUNT_SHORTS = int(os.environ.get("NATIVE_MAX_ICON_COUNT_SHORTS", "4"))  # Shorts 1本あたりの疑問/驚きアイコン最大回数
NATIVE_BG_ZOOM_MAX = float(os.environ.get("NATIVE_BG_ZOOM_MAX", "1.06"))  # 背景Ken Burnsの最大拡大倍率

# ───────────────────────────────────────────────
# native 字幕スタイル
# ───────────────────────────────────────────────
NATIVE_SUBTITLE_OFFSET_SEC        = float(os.environ.get("NATIVE_SUBTITLE_OFFSET_SEC",        "0"))     # 字幕の開始タイミング補正 (秒)
NATIVE_SUBTITLE_FONT              = os.environ.get("NATIVE_SUBTITLE_FONT", "ラノベPOP v2")               # 字幕フォント名
NATIVE_SUBTITLE_FONT_SIZE_SHORTS  = int(os.environ.get("NATIVE_SUBTITLE_FONT_SIZE_SHORTS",  "64"))      # Shorts: 基本フォントサイズ (px)
NATIVE_SUBTITLE_FONT_SIZE_LONG    = int(os.environ.get("NATIVE_SUBTITLE_FONT_SIZE_LONG",    "52"))      # Long: 基本フォントサイズ (px)
NATIVE_SUBTITLE_FONT_SCALE        = float(os.environ.get("NATIVE_SUBTITLE_FONT_SCALE",      "1.4"))     # フォントサイズ倍率（FONT_SIZE × FONT_SCALE が実際のサイズ）
NATIVE_SUBTITLE_ALIGNMENT_SHORTS  = int(os.environ.get("NATIVE_SUBTITLE_ALIGNMENT_SHORTS",  "5"))       # Shorts: ASS alignment（5=中央中段）
NATIVE_SUBTITLE_ALIGNMENT_LONG    = int(os.environ.get("NATIVE_SUBTITLE_ALIGNMENT_LONG",    "2"))       # Long: ASS alignment（2=中央下段）
NATIVE_SUBTITLE_MARGIN_V_SHORTS   = int(os.environ.get("NATIVE_SUBTITLE_MARGIN_V_SHORTS",   "520"))     # Shorts: 縦マージン (px)
NATIVE_SUBTITLE_MARGIN_V_LONG     = int(os.environ.get("NATIVE_SUBTITLE_MARGIN_V_LONG",     "90"))      # Long: 縦マージン (px)
NATIVE_SUBTITLE_Y_OFFSET_SHORTS   = int(os.environ.get("NATIVE_SUBTITLE_Y_OFFSET_SHORTS",   "70"))      # Shorts: 字幕 Y 追加オフセット (px)
NATIVE_SUBTITLE_Y_OFFSET_LONG     = int(os.environ.get("NATIVE_SUBTITLE_Y_OFFSET_LONG",     "0"))       # Long: 字幕 Y 追加オフセット (px)
NATIVE_SUBTITLE_STROKE_WIDTH      = int(os.environ.get("NATIVE_SUBTITLE_STROKE_WIDTH",      "9"))       # 内フチ幅 (px)
NATIVE_SUBTITLE_OUTER_STROKE_WIDTH = int(os.environ.get("NATIVE_SUBTITLE_OUTER_STROKE_WIDTH", str(NATIVE_SUBTITLE_STROKE_WIDTH + 4)))  # 外フチ幅 (px)。デフォルトは内フチ+4
NATIVE_SUBTITLE_PADDING_Y         = int(os.environ.get("NATIVE_SUBTITLE_PADDING_Y",         "8"))       # 字幕帯の上下パディング (px)
NATIVE_SUBTITLE_BOX_LINE_HEIGHT   = float(os.environ.get("NATIVE_SUBTITLE_BOX_LINE_HEIGHT", "1.75"))    # 字幕帯高さ = font_size × この値 + PADDING_Y×2
NATIVE_SUBTITLE_BOX_SHORTS        = os.environ.get("NATIVE_SUBTITLE_BOX_SHORTS", "1").strip().lower() in ("1", "true", "yes", "on")  # Shorts: 半透明帯を表示するか
NATIVE_SUBTITLE_BOX_ALPHA         = float(os.environ.get("NATIVE_SUBTITLE_BOX_ALPHA", os.environ.get("NATIVE_SUBTITLE_BOX_OPACITY_SHORTS", "0.60")))  # 帯の不透明度 (0=透明 1=不透明)
NATIVE_SUBTITLE_BOX_OPACITY_SHORTS = NATIVE_SUBTITLE_BOX_ALPHA  # 旧名エイリアス

# ───────────────────────────────────────────────
# アナリティクス — チャンネル固有注記
# ───────────────────────────────────────────────
ANALYTICS_CHANNEL_REMAKE_DATE = "2026-05-15"  # チャンネルリメイク実稼働開始日（この日以前は旧チャンネル時代）
ANALYTICS_CHANNEL_LEGACY_NOTE = (             # 旧チャンネル時代の登録者に関する注記（AI分析・GUI表示用）
    "旧チャンネル時代にインド向け広告で集めた登録者が離脱している可能性あり。"
    "チャンネルリメイク実稼働は2026/5/15以降のため、それ以前投稿分の離脱数値は参考値扱い。"
)

# ───────────────────────────────────────────────
# タイムライン・尺計算用定数
# ───────────────────────────────────────────────
TRANSITION_SEC            = 0.3   # 背景クロスフェード時間（秒）
VOICE_TAIL_SAFETY_SEC     = 0.5   # 音声WAV末尾の安全余裕（秒）
NATIVE_INTER_DIALOGUE_GAP_SEC = 0.0  # nativeレンダラーのセリフ間追加ギャップ（秒）

# ───────────────────────────────────────────────
# BGM
# ───────────────────────────────────────────────
BGM_FILE = os.environ.get("BGM_FILE", "nohohon_long_BPM97.mp3")
BGM_PATH = os.path.join(ASSETS_DIR, "bgm", BGM_FILE) if BGM_FILE else ""

# ───────────────────────────────────────────────
# 出力ディレクトリ・ファイルパス
# ───────────────────────────────────────────────
OUTPUT_DIR            = os.environ.get("OUTPUT_DIR",            "output")
OUTPUT_DATA_DIR       = os.environ.get("OUTPUT_DATA_DIR",       os.path.join(OUTPUT_DIR, "000_data"))
OUTPUT_ANALYTICS_DIR  = os.environ.get("OUTPUT_ANALYTICS_DIR",  os.path.join(OUTPUT_DIR, "000_analytics"))
OUTPUT_LEGACY_DIR     = os.environ.get("OUTPUT_LEGACY_DIR",     os.path.join(OUTPUT_DIR, "000_legacy"))
UPLOAD_RECORDS_FILE   = os.environ.get("UPLOAD_RECORDS_FILE",   os.path.join(OUTPUT_DATA_DIR, "upload_records.json"))
UPLOADED_TITLES_FILE  = os.environ.get("UPLOADED_TITLES_FILE",  os.path.join(OUTPUT_DATA_DIR, "uploaded_titles.txt"))

# ───────────────────────────────────────────────
# YouTube / アップロード設定
# ───────────────────────────────────────────────
LONG_THUMBNAIL_AB_TEST     = os.environ.get("LONG_THUMBNAIL_AB_TEST",     "0").strip().lower() in ("1", "true", "yes", "on")  # Long サムネ A/B テスト（OFF: A のみ生成）
LONG_UPLOAD_PLAYLIST_NAME  = os.environ.get("LONG_UPLOAD_PLAYLIST_NAME",  "ロング動画").strip()  # Long アップロード後に自動追加する再生リスト名（空で無効）
TOPIC_REQUEST_CTA_EVERY_N  = int(os.environ.get("TOPIC_REQUEST_CTA_EVERY_N", "5"))  # Shorts新規/横展開のネタ募集CTAを許可する間隔（N本に1本、0で自動付与なし）

# ───────────────────────────────────────────────
# 背景画像生成枚数上限
# Shorts: 3〜5 秒ごとに切り替えが理想
# Long: 5〜7 秒ごと。10 秒以上同一背景は避ける
# Long節約モード: 新規生成を最大 16 枚に制限（台本で「背景: 前と同じ」を使うとカウント外）
# ───────────────────────────────────────────────
MAX_BACKGROUNDS_SHORTS      = int(os.environ.get("MAX_BACKGROUNDS_SHORTS",      "9"))   # Shorts: 最大背景枚数
MAX_BACKGROUNDS_LONG        = int(os.environ.get("MAX_BACKGROUNDS_LONG",        "90"))  # Long: 最大背景枚数（通常モード）
MAX_BACKGROUNDS_LONG_BUDGET = int(os.environ.get("MAX_BACKGROUNDS_LONG_BUDGET", "16"))  # Long: 最大背景枚数（節約モード）
MAX_BACKGROUNDS             = MAX_BACKGROUNDS_SHORTS  # 後方互換エイリアス

# ───────────────────────────────────────────────
# ローカル Web UI
# ───────────────────────────────────────────────
WEB_APP_NAME = os.environ.get("WEB_APP_NAME", "Native Video Factory")  # Web UI の表示アプリ名
WEB_UI_HOST = os.environ.get("WEB_UI_HOST", "127.0.0.1")  # バインドホスト（外部公開禁止）
WEB_UI_PORT = int(os.environ.get("WEB_UI_PORT", "58080"))  # ポート番号（他アプリと競合しにくい高番号）
WEB_DEFAULT_IMAGE_STYLE = _clean_env_choice(os.environ.get("WEB_DEFAULT_IMAGE_STYLE", "アニメ"))  # Web UI の既定画像スタイル
WEB_IMAGE_STYLE_CHOICES = _split_env_choices(os.environ.get("WEB_IMAGE_STYLE_CHOICES", "通常,アニメ,水彩"))  # Web UI 画像スタイル選択肢
WEB_DEFAULT_REUSE_BACKGROUNDS = os.environ.get("WEB_DEFAULT_REUSE_BACKGROUNDS", "1").strip().lower() in ("1", "true", "yes", "on")  # Web UI 生成時の背景再利用既定値
WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST = os.environ.get("WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST", "0").strip().lower() in ("1", "true", "yes", "on")  # Web UI 生成時のLongサムネAB既定値
WEB_DEFAULT_LONG_BUDGET_MODE = os.environ.get("WEB_DEFAULT_LONG_BUDGET_MODE", "0").strip().lower() in ("1", "true", "yes", "on")  # Web UI 生成時のLong節約既定値
WEB_DEFAULT_SD_SIZE_MODE = os.environ.get("WEB_DEFAULT_SD_SIZE_MODE", "0").strip().lower() in ("1", "true", "yes", "on")  # Web UI 生成時の縮小生成既定値
WEB_JOB_POLL_INTERVAL_MS = int(os.environ.get("WEB_JOB_POLL_INTERVAL_MS", "2000"))  # Web UI のジョブポーリング間隔(ms)
WEB_SUCCESS_RELOAD_DELAY_MS = int(os.environ.get("WEB_SUCCESS_RELOAD_DELAY_MS", "1500"))  # Web UI ジョブ成功後の再読み込み待ち時間(ms)
WEB_TOAST_VISIBLE_MS = int(os.environ.get("WEB_TOAST_VISIBLE_MS", "2000"))  # Web UI トースト表示時間(ms)
WEB_TOAST_HIDE_DELAY_MS = int(os.environ.get("WEB_TOAST_HIDE_DELAY_MS", "420"))  # Web UI トースト非表示待ち時間(ms)
WEB_VOICEVOX_CHECK_TIMEOUT_SEC = float(os.environ.get("WEB_VOICEVOX_CHECK_TIMEOUT_SEC", "2.0"))  # Web UI のVOICEVOX疎通確認タイムアウト(秒)
WEB_FFMPEG_CHECK_TIMEOUT_SEC = float(os.environ.get("WEB_FFMPEG_CHECK_TIMEOUT_SEC", "5.0"))  # Web UI のffmpeg疎通確認タイムアウト(秒)
DEBUG_LOG_ENABLED = os.environ.get("DEBUG_LOG_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")  # デバッグログ出力の有効/無効
DEBUG_LOG_DIR = os.environ.get("DEBUG_LOG_DIR", os.path.join(OUTPUT_DATA_DIR, "debug_logs"))  # デバッグログ保存ディレクトリ
DEBUG_LOG_RETENTION_DAYS = int(os.environ.get("DEBUG_LOG_RETENTION_DAYS", "3"))  # デバッグログ保持日数
DEBUG_LOG_LEVEL = os.environ.get("DEBUG_LOG_LEVEL", "DEBUG").strip().upper()  # デバッグログ出力レベル
DEBUG_LOG_VIEW_LINES = int(os.environ.get("DEBUG_LOG_VIEW_LINES", "400"))  # Web UIログ画面に表示する最大行数

# ───────────────────────────────────────────────
# API接続・タイムアウト設定
# ───────────────────────────────────────────────
VOICEVOX_CONNECTION_TIMEOUT_SEC = float(os.environ.get("VOICEVOX_CONNECTION_TIMEOUT_SEC", "5.0"))  # VOICEVOX接続確認タイムアウト（秒）
VOICEVOX_QUERY_TIMEOUT_SEC = float(os.environ.get("VOICEVOX_QUERY_TIMEOUT_SEC", "10.0"))            # VOICEVOXクエリ生成タイムアウト（秒）
VOICEVOX_SYNTHESIS_TIMEOUT_SEC = float(os.environ.get("VOICEVOX_SYNTHESIS_TIMEOUT_SEC", "120.0"))    # VOICEVOX音声合成タイムアウト（秒）
# READING_NORMALIZE_CHECK_TIMEOUT_SEC / READING_NORMALIZE_CHAT_TIMEOUT_SEC は
# Ollama方式のよみがな正規化（廃止済み）で使用していた設定。SudachiPy方式では不使用。

# ───────────────────────────────────────────────
# native レンダラー演出パラメータ
# ───────────────────────────────────────────────
NATIVE_SHAKE_AMP_X = int(os.environ.get("NATIVE_SHAKE_AMP_X", "7"))                                  # 画面シェイクの水平方向振幅(px)
NATIVE_SHAKE_AMP_Y = int(os.environ.get("NATIVE_SHAKE_AMP_Y", "5"))                                  # 画面シェイクの垂直方向振幅(px)
NATIVE_CHARACTER_BOUNCE_SEC = float(os.environ.get("NATIVE_CHARACTER_BOUNCE_SEC", "0.22"))          # キャラクターバウンス演出時間(秒)
NATIVE_TELOP_POP_START_SEC = float(os.environ.get("NATIVE_TELOP_POP_START_SEC", "0.05"))            # ポップテロップの表示開始ディレイ(秒)
NATIVE_TELOP_POP_MAX_SEC = float(os.environ.get("NATIVE_TELOP_POP_MAX_SEC", "1.5"))                  # ポップテロップの最大表示持続時間(秒)

# ───────────────────────────────────────────────
# 固定コメント自動投稿
# ───────────────────────────────────────────────
AUTO_FIXED_COMMENT_ENABLED       = os.environ.get("AUTO_FIXED_COMMENT_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")
AUTO_FIXED_COMMENT_CHECK_INTERVAL_SEC = int(os.environ.get("AUTO_FIXED_COMMENT_CHECK_INTERVAL_SEC", "600"))  # 確認間隔（秒）既定10分

# ───────────────────────────────────────────────
# ジョブログ永続化
# ───────────────────────────────────────────────
JOB_LOG_DIR      = os.environ.get("JOB_LOG_DIR",      os.path.join(OUTPUT_DATA_DIR, "job_logs"))  # ジョブログ保存ディレクトリ
JOB_LOG_MAX_JOBS = int(os.environ.get("JOB_LOG_MAX_JOBS", "300"))                                  # 保持する最大ジョブ件数
