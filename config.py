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
OPENING_REVIEW_MAX_LLM_RETRIES = int(os.environ.get("OPENING_REVIEW_MAX_LLM_RETRIES", "1"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_REVIEW_MODEL = os.environ.get("OLLAMA_REVIEW_MODEL", "qwen3:8b")
OLLAMA_REWRITE_MODEL = os.environ.get("OLLAMA_REWRITE_MODEL", "qwen3:8b")
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

OUTPUT_DIR = "output"
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
CHARACTER_PNG_DIR = os.path.join(ASSETS_DIR, "characters")
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

# Cost control: max unique background images generated per video (thumbnail excluded).
# Shorts: ideal visual change every 3-5 seconds.
# Long: ideal visual change every 5-7 seconds; avoid holding the same image for 10+ seconds.
MAX_BACKGROUNDS_SHORTS = 9
MAX_BACKGROUNDS_LONG = 90
MAX_BACKGROUNDS = MAX_BACKGROUNDS_SHORTS


