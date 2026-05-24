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
# ffmpeg ネイティブレンダラー用の低速設定（YMM4より字幕追従のズレが出やすいため遅め）
NATIVE_SHORTS_BODY_VOICE_SPEED = float(os.environ.get("NATIVE_SHORTS_BODY_VOICE_SPEED", "1.25"))
NATIVE_SHORTS_INTRO_VOICE_SPEED = float(os.environ.get("NATIVE_SHORTS_INTRO_VOICE_SPEED", "1.40"))
NATIVE_LONG_BODY_VOICE_SPEED = float(os.environ.get("NATIVE_LONG_BODY_VOICE_SPEED", "1.20"))
NATIVE_LONG_INTRO_VOICE_SPEED = float(os.environ.get("NATIVE_LONG_INTRO_VOICE_SPEED", "1.40"))
NATIVE_AUDIO_LOUDNORM_ENABLED = os.environ.get("NATIVE_AUDIO_LOUDNORM_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
NATIVE_AUDIO_LOUDNORM_I = float(os.environ.get("NATIVE_AUDIO_LOUDNORM_I", "-15"))
NATIVE_AUDIO_LOUDNORM_TP = float(os.environ.get("NATIVE_AUDIO_LOUDNORM_TP", "-1.5"))
NATIVE_AUDIO_LOUDNORM_LRA = float(os.environ.get("NATIVE_AUDIO_LOUDNORM_LRA", "6"))
NATIVE_BGM_VOLUME_DB = float(os.environ.get("NATIVE_BGM_VOLUME_DB", "-20"))
NATIVE_SHORTS_CHARACTER_SCALE = float(os.environ.get("NATIVE_SHORTS_CHARACTER_SCALE", "1.05"))
CHARACTER_UPPER_BODY_MODE = os.environ.get("CHARACTER_UPPER_BODY_MODE", "1").strip().lower() in ("1", "true", "yes", "on")
CHARACTER_UPPER_BODY_SCALE = float(os.environ.get("CHARACTER_UPPER_BODY_SCALE", "1.55"))
CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET = int(os.environ.get("CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET", "250"))
CHARACTER_UPPER_BODY_LONG_Y_OFFSET = int(os.environ.get("CHARACTER_UPPER_BODY_LONG_Y_OFFSET", "400"))
NATIVE_SHORTS_ESTIMATE_BASE_CPS = float(os.environ.get("NATIVE_SHORTS_ESTIMATE_BASE_CPS", "5.4"))
NATIVE_SHORTS_CHARS_MUST_FIX_MIN = int(os.environ.get("NATIVE_SHORTS_CHARS_MUST_FIX_MIN", "260"))
NATIVE_SHORTS_TARGET_CHARS_MIN = int(os.environ.get("NATIVE_SHORTS_TARGET_CHARS_MIN", "280"))
NATIVE_SHORTS_TARGET_CHARS_MAX = int(os.environ.get("NATIVE_SHORTS_TARGET_CHARS_MAX", "330"))
NATIVE_SHORTS_AVG_CHARS_MIN = float(os.environ.get("NATIVE_SHORTS_AVG_CHARS_MIN", "11.5"))
NATIVE_SHORTS_SHORT_LINE_MAX = int(os.environ.get("NATIVE_SHORTS_SHORT_LINE_MAX", "4"))
# native Shorts セリフ数ルール（YMM4とは別）
NATIVE_SHORTS_LINES_IDEAL_MIN = 22
NATIVE_SHORTS_LINES_IDEAL_MAX = 28
NATIVE_SHORTS_LINES_TARGET_MIN = int(os.environ.get("NATIVE_SHORTS_LINES_TARGET_MIN", "24"))
NATIVE_SHORTS_LINES_TARGET_MAX = int(os.environ.get("NATIVE_SHORTS_LINES_TARGET_MAX", "27"))
NATIVE_SHORTS_LINES_WARNING = 29   # 29〜30行: warning
NATIVE_SHORTS_LINES_MUST_FIX = 31  # 31行以上: must_fix

# native Shorts 速度許容範囲
NATIVE_SHORTS_INTRO_VOICE_SPEED_MIN = 1.35
NATIVE_SHORTS_INTRO_VOICE_SPEED_MAX = 1.45
NATIVE_SHORTS_BODY_VOICE_SPEED_MIN = 1.20
NATIVE_SHORTS_BODY_VOICE_SPEED_MAX = 1.30

# native セリフ間無音（秒）
NATIVE_MIN_SILENCE_BETWEEN_LINES = float(os.environ.get("NATIVE_MIN_SILENCE_BETWEEN_LINES", "0.10"))
NATIVE_DEFAULT_SILENCE_BETWEEN_LINES = float(os.environ.get("NATIVE_DEFAULT_SILENCE_BETWEEN_LINES", "0.12"))
NATIVE_SCENE_CHANGE_SILENCE = float(os.environ.get("NATIVE_SCENE_CHANGE_SILENCE", "0.18"))
NATIVE_MAX_NORMAL_SILENCE = float(os.environ.get("NATIVE_MAX_NORMAL_SILENCE", "0.35"))
NATIVE_WARNING_SILENCE = float(os.environ.get("NATIVE_WARNING_SILENCE", "0.50"))

# Shorts本番レンダリング設定
DEFAULT_SHORTS_RENDER_ENGINE = os.environ.get("DEFAULT_SHORTS_RENDER_ENGINE", "native").strip().lower()
GENERATE_YMM4_PROJECT = os.environ.get("GENERATE_YMM4_PROJECT", "1").strip().lower() in ("1", "true", "yes", "on")
RENDER_WITH_YMM4 = os.environ.get("RENDER_WITH_YMM4", "0").strip().lower() in ("1", "true", "yes", "on")

# YMM4専用速度定数（明示エイリアス）
YMM4_SHORTS_INTRO_VOICE_SPEED = VOICE_INTRO_SPEED_SCALE_SHORTS  # 2.0
YMM4_SHORTS_BODY_VOICE_SPEED = VOICE_SPEED_SCALE_SHORTS          # 1.65
YMM4_LONG_INTRO_VOICE_SPEED = VOICE_INTRO_SPEED_SCALE_LONG       # 1.6
YMM4_LONG_BODY_VOICE_SPEED = VOICE_SPEED_SCALE_LONG              # 1.35

# 冒頭速度切り替えモード
VOICE_INTRO_FAST_MODE = os.environ.get("VOICE_INTRO_FAST_MODE", "line_count").strip().lower()  # "line_count" or "seconds"
VOICE_INTRO_FAST_LINES = int(os.environ.get("VOICE_INTRO_FAST_LINES", "3"))  # native: 冒頭N行がintro速度

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
OPENAI_FINAL_REVIEW_MODEL = os.environ.get("OPENAI_FINAL_REVIEW_MODEL", "gpt-5.2")
SHORT_FULL_SCRIPT_REVIEW = os.environ.get("SHORT_FULL_SCRIPT_REVIEW", "1").strip().lower() in ("1", "true", "yes", "on")
LONG_FULL_SCRIPT_REVIEW = os.environ.get("LONG_FULL_SCRIPT_REVIEW", "0").strip().lower() in ("1", "true", "yes", "on")
AUTO_FULL_REWRITE_ENABLED = os.environ.get("AUTO_FULL_REWRITE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")

# Google AI Models (Nano Banana Suite)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")
NANOBANANA_PRO_MODEL = os.environ.get("NANOBANANA_PRO_MODEL", "gemini-3-pro-image-preview")
NANOBANANA_FLASH_MODEL = os.environ.get("NANOBANANA_FLASH_MODEL", "gemini-3.1-flash-image-preview")
SD_SIZE_IMAGE_SCALE = float(os.environ.get("SD_SIZE_IMAGE_SCALE", "0.5"))

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
NATIVE_SUBTITLE_Y_OFFSET_SHORTS = int(os.environ.get("NATIVE_SUBTITLE_Y_OFFSET_SHORTS", "70"))
NATIVE_SUBTITLE_Y_OFFSET_LONG = int(os.environ.get("NATIVE_SUBTITLE_Y_OFFSET_LONG", "0"))
NATIVE_SUBTITLE_BOX_SHORTS = os.environ.get("NATIVE_SUBTITLE_BOX_SHORTS", "1").strip().lower() in ("1", "true", "yes", "on")
NATIVE_SUBTITLE_BOX_ALPHA = float(os.environ.get("NATIVE_SUBTITLE_BOX_ALPHA", os.environ.get("NATIVE_SUBTITLE_BOX_OPACITY_SHORTS", "0.60")))
NATIVE_SUBTITLE_BOX_OPACITY_SHORTS = NATIVE_SUBTITLE_BOX_ALPHA
NATIVE_SUBTITLE_STROKE_WIDTH = int(os.environ.get("NATIVE_SUBTITLE_STROKE_WIDTH", "9"))
NATIVE_SUBTITLE_OUTER_STROKE_WIDTH = int(os.environ.get("NATIVE_SUBTITLE_OUTER_STROKE_WIDTH", str(NATIVE_SUBTITLE_STROKE_WIDTH + 4)))
NATIVE_SUBTITLE_PADDING_Y = int(os.environ.get("NATIVE_SUBTITLE_PADDING_Y", "8"))
NATIVE_SUBTITLE_FONT_SCALE = float(os.environ.get("NATIVE_SUBTITLE_FONT_SCALE", "1.4"))
NATIVE_SUBTITLE_ALIGNMENT_SHORTS = int(os.environ.get("NATIVE_SUBTITLE_ALIGNMENT_SHORTS", "5"))
NATIVE_SUBTITLE_ALIGNMENT_LONG = int(os.environ.get("NATIVE_SUBTITLE_ALIGNMENT_LONG", "2"))
NATIVE_CHARACTER_HEIGHT_SHORTS = int(os.environ.get("NATIVE_CHARACTER_HEIGHT_SHORTS", "1000"))
NATIVE_CHARACTER_HEIGHT_LONG = int(os.environ.get("NATIVE_CHARACTER_HEIGHT_LONG", "598"))
NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS = int(os.environ.get("NATIVE_CHARACTER_BOTTOM_MARGIN_SHORTS", "-360"))
NATIVE_CHARACTER_SIDE_MARGIN_SHORTS = int(os.environ.get("NATIVE_CHARACTER_SIDE_MARGIN_SHORTS", "-80"))
NATIVE_CHARACTER_BOTTOM_MARGIN_LONG = int(os.environ.get("NATIVE_CHARACTER_BOTTOM_MARGIN_LONG", "40"))
NATIVE_CHARACTER_SIDE_MARGIN_LONG = int(os.environ.get("NATIVE_CHARACTER_SIDE_MARGIN_LONG", "-40"))
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


