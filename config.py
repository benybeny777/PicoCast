import os
from dotenv import load_dotenv
load_dotenv()

VOICEVOX_URL = "http://localhost:50021"
VOICEVOX_PATH = r"C:\Program Files\VOICEVOX\VOICEVOX.exe"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

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

OUTPUT_DIR = "output"
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
CHARACTER_PNG_DIR = os.path.join(ASSETS_DIR, "characters")
CHARACTER_PNGS = {
    "ずんだもん": os.path.join(CHARACTER_PNG_DIR, "zundamon.png"),
    "四国めたん": os.path.join(CHARACTER_PNG_DIR, "metan.png"),
}

# Cost control: max unique background images generated per video (thumbnail excluded)
MAX_BACKGROUNDS = 7


