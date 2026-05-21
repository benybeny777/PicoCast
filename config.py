import os
from dotenv import load_dotenv
load_dotenv()

VOICEVOX_URL = "http://localhost:50021"
VOICEVOX_PATH = r"C:\Users\benyb\AppData\Local\Programs\VOICEVOX\VOICEVOX.exe"
VOICE_SPEED_SCALE_SHORTS = 1.65
VOICE_INTRO_SPEED_SCALE_SHORTS = 2.0
VOICE_SPEED_SCALE_LONG = 1.35
VOICE_INTRO_SPEED_SCALE_LONG = 1.6
VOICE_INTRO_FAST_SECONDS = 5.0
# Backward-compatible aliases. Runtime selection uses the Shorts/Long values above.
VOICE_SPEED_SCALE = VOICE_SPEED_SCALE_SHORTS
VOICE_INTRO_SPEED_SCALE = VOICE_INTRO_SPEED_SCALE_SHORTS
VOICE_POST_PHONEME_LENGTH = 0.0  # 各音声WAVの末尾に追加する無音（秒）
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENING_REVIEW_USE_LLM = os.environ.get("OPENING_REVIEW_USE_LLM", "1").strip().lower() in ("1", "true", "yes", "on")
OPENING_REVIEW_PROVIDER = os.environ.get("OPENING_REVIEW_PROVIDER", "ollama").strip().lower()
OPENING_REVIEW_MODEL = os.environ.get("OPENING_REVIEW_MODEL", "qwen3:8b")
OPENING_REVIEW_AUTO_REWRITE = os.environ.get("OPENING_REVIEW_AUTO_REWRITE", "1").strip().lower() in ("1", "true", "yes", "on")
OPENING_SCORE_ABORT_THRESHOLD = int(os.environ.get("OPENING_SCORE_ABORT_THRESHOLD", "80"))  # これ未満は処理中止
OPENING_SCORE_HARD_ABORT_THRESHOLD = int(os.environ.get("OPENING_SCORE_HARD_ABORT_THRESHOLD", "70"))  # これ未満は重大エラー扱い
OPENING_REVIEW_MAX_LLM_RETRIES = int(os.environ.get("OPENING_REVIEW_MAX_LLM_RETRIES", "1"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_REVIEW_MODEL = os.environ.get("OLLAMA_REVIEW_MODEL", "qwen3:8b")
OLLAMA_REWRITE_MODEL = os.environ.get("OLLAMA_REWRITE_MODEL", "qwen3:8b")
OLLAMA_REWRITE_FALLBACK_MODEL = os.environ.get("OLLAMA_REWRITE_FALLBACK_MODEL", "gemma4:e4b")
OPENING_REWRITE_MAX_FALLBACKS = int(os.environ.get("OPENING_REWRITE_MAX_FALLBACKS", "1"))
OPENAI_FINAL_REVIEW_ENABLED = os.environ.get("OPENAI_FINAL_REVIEW_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
OPENAI_FINAL_REVIEW_MODEL = os.environ.get("OPENAI_FINAL_REVIEW_MODEL", "gpt-5.4-mini")
SHORT_FULL_SCRIPT_REVIEW = os.environ.get("SHORT_FULL_SCRIPT_REVIEW", "1").strip().lower() in ("1", "true", "yes", "on")
LONG_FULL_SCRIPT_REVIEW = os.environ.get("LONG_FULL_SCRIPT_REVIEW", "0").strip().lower() in ("1", "true", "yes", "on")
AUTO_FULL_REWRITE_ENABLED = os.environ.get("AUTO_FULL_REWRITE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

# Google AI Models (Nano Banana Suite)
GEMINI_MODEL = "gemini-3.1-pro-preview"
NANOBANANA_PRO_MODEL = "gemini-3-pro-image-preview"
NANOBANANA_FLASH_MODEL = "gemini-3.1-flash-image-preview"

# Character Mapping
# Speaker IDs:
# 3: Zundamon (Normal)
# 2: Shikoku Metan (Normal)
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

VIDEO_FPS = 30
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
CHARACTER_PNG_DIR = os.path.join(ASSETS_DIR, "characters")
CHARACTER_PSD_DIR = os.path.join(CHARACTER_PNG_DIR, "psd")
NATIVE_SUBTITLE_OFFSET_SEC = float(os.environ.get("NATIVE_SUBTITLE_OFFSET_SEC", "0"))
NATIVE_FFMPEG_ENCODER = os.environ.get("NATIVE_FFMPEG_ENCODER", "h264_nvenc")
NATIVE_FFMPEG_PRESET = os.environ.get("NATIVE_FFMPEG_PRESET", "p5")
NATIVE_FFMPEG_CRF = os.environ.get("NATIVE_FFMPEG_CRF", "20")
NATIVE_FFMPEG_CQ = os.environ.get("NATIVE_FFMPEG_CQ", "23")
NATIVE_RENDER_CHARACTERS = os.environ.get("NATIVE_RENDER_CHARACTERS", "1").strip().lower() in ("1", "true", "yes", "on")
NATIVE_ENABLE_LIPSYNC = os.environ.get("NATIVE_ENABLE_LIPSYNC", "1").strip().lower() in ("1", "true", "yes", "on")
NATIVE_ENABLE_BLINK = os.environ.get("NATIVE_ENABLE_BLINK", "1").strip().lower() in ("1", "true", "yes", "on")
NATIVE_BACKGROUND_TRANSITION = os.environ.get("NATIVE_BACKGROUND_TRANSITION", "fade").strip().lower()
NATIVE_BACKGROUND_TRANSITION_SEC = float(os.environ.get("NATIVE_BACKGROUND_TRANSITION_SEC", "0.18"))
NATIVE_SUBTITLE_FONT = os.environ.get("NATIVE_SUBTITLE_FONT", "\u30e9\u30ce\u30d9POP v2")
NATIVE_SUBTITLE_MARGIN_V_SHORTS = int(os.environ.get("NATIVE_SUBTITLE_MARGIN_V_SHORTS", "520"))
NATIVE_SUBTITLE_MARGIN_V_LONG = int(os.environ.get("NATIVE_SUBTITLE_MARGIN_V_LONG", "90"))
NATIVE_CHARACTER_HEIGHT_SHORTS = int(os.environ.get("NATIVE_CHARACTER_HEIGHT_SHORTS", "874"))
NATIVE_CHARACTER_HEIGHT_LONG = int(os.environ.get("NATIVE_CHARACTER_HEIGHT_LONG", "598"))
ZUNDAMON_PSD_PATH = os.environ.get("ZUNDAMON_PSD_PATH", os.path.join(CHARACTER_PSD_DIR, "zundamon.psd"))
METAN_PSD_PATH = os.environ.get("METAN_PSD_PATH", os.path.join(CHARACTER_PSD_DIR, "metan.psd"))

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
OUTPUT_DATA_DIR = os.environ.get("OUTPUT_DATA_DIR", os.path.join(OUTPUT_DIR, "000_data"))
OUTPUT_ANALYTICS_DIR = os.environ.get("OUTPUT_ANALYTICS_DIR", os.path.join(OUTPUT_DIR, "000_analytics"))
OUTPUT_LEGACY_DIR = os.environ.get("OUTPUT_LEGACY_DIR", os.path.join(OUTPUT_DIR, "000_legacy"))
UPLOAD_RECORDS_FILE = os.environ.get("UPLOAD_RECORDS_FILE", os.path.join(OUTPUT_DATA_DIR, "upload_records.json"))
UPLOADED_TITLES_FILE = os.environ.get("UPLOADED_TITLES_FILE", os.path.join(OUTPUT_DATA_DIR, "uploaded_titles.txt"))
CHARACTER_PNGS = {
    "ずんだもん": os.path.join(CHARACTER_PNG_DIR, "zundamon.png"),
    "四国めたん": os.path.join(CHARACTER_PNG_DIR, "metan.png"),
}

# サムネイル生成用の参照画像。
THUMBNAIL_CHARACTER_PNGS = {
    "ずんだもん": os.path.join(CHARACTER_PNG_DIR, "zundamon.png"),
    "四国めたん": os.path.join(CHARACTER_PNG_DIR, "metan.png"),
}

# Fixed background music. Source: BGMer "のほほん"
BGM_PATH = os.path.join(ASSETS_DIR, "bgm", "nohohon_long_BPM97.mp3")
BGM_VOLUME = 15.0
BGM_LAYER = 2

# Long サムネイル A/B テスト。False にすると variant A のみ生成し thumbnail_ab_test.json を書かない。
LONG_THUMBNAIL_AB_TEST = os.environ.get("LONG_THUMBNAIL_AB_TEST", "0").strip().lower() in ("1", "true", "yes", "on")
LONG_UPLOAD_PLAYLIST_NAME = os.environ.get("LONG_UPLOAD_PLAYLIST_NAME", "ロング動画").strip()

# Cost control: max unique background images generated per video (thumbnail excluded).
# Shorts: ideal visual change every 3-5 seconds.
# Long: ideal visual change every 5-7 seconds; avoid holding the same image for 10+ seconds.
# Long budget mode: limits new image generation to ~16. Use "背景: 前と同じ" in the script to
# explicitly mark scenes that reuse the preceding background (not counted toward the budget).
MAX_BACKGROUNDS_SHORTS = 9
MAX_BACKGROUNDS_LONG = 90
MAX_BACKGROUNDS_LONG_BUDGET = 16
MAX_BACKGROUNDS = MAX_BACKGROUNDS_SHORTS


