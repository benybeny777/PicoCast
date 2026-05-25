import os
from dotenv import load_dotenv
load_dotenv()

# ───────────────────────────────────────────────
# VOICEVOX
# ───────────────────────────────────────────────
VOICEVOX_URL = "http://localhost:50021"                          # VOICEVOX エンジン API エンドポイント
VOICEVOX_PATH = r"C:\Users\benyb\AppData\Local\Programs\VOICEVOX\VOICEVOX.exe"  # 自動起動用パス

# ───────────────────────────────────────────────
# 音声速度（VOICEVOX 読み上げ速度）
# ───────────────────────────────────────────────
VOICE_SPEED_SCALE_SHORTS = 1.65       # Shorts 本編速度
VOICE_INTRO_SPEED_SCALE_SHORTS = 2.0  # Shorts 冒頭速度
VOICE_SPEED_SCALE_LONG = 1.35         # Long 本編速度
VOICE_INTRO_SPEED_SCALE_LONG = 1.6    # Long 冒頭速度
VOICE_INTRO_FAST_SECONDS = 5.0        # seconds モード時: 冒頭何秒を高速読みにするか

# Backward-compatible aliases（旧コードとの互換用。新規参照は Shorts/Long 個別定数を使う）
VOICE_SPEED_SCALE       = VOICE_SPEED_SCALE_SHORTS
VOICE_INTRO_SPEED_SCALE = VOICE_INTRO_SPEED_SCALE_SHORTS
VOICE_POST_PHONEME_LENGTH = 0.0  # 各音声 WAV 末尾に追加する無音（秒）。0 = 無効

# ───────────────────────────────────────────────
# 音声速度 — native レンダラー用（字幕追従ズレ対策でやや遅め）
# ───────────────────────────────────────────────
NATIVE_SHORTS_BODY_VOICE_SPEED  = float(os.environ.get("NATIVE_SHORTS_BODY_VOICE_SPEED",  "1.25"))  # Shorts 本編
NATIVE_SHORTS_INTRO_VOICE_SPEED = float(os.environ.get("NATIVE_SHORTS_INTRO_VOICE_SPEED", "1.40"))  # Shorts 冒頭
NATIVE_LONG_BODY_VOICE_SPEED    = float(os.environ.get("NATIVE_LONG_BODY_VOICE_SPEED",    "1.20"))  # Long 本編
NATIVE_LONG_INTRO_VOICE_SPEED   = float(os.environ.get("NATIVE_LONG_INTRO_VOICE_SPEED",   "1.40"))  # Long 冒頭

# 冒頭速度切り替えモード
VOICE_INTRO_FAST_MODE  = os.environ.get("VOICE_INTRO_FAST_MODE", "line_count").strip().lower()  # "line_count" or "seconds"
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
# 立ち絵パラメータ (x座標, y座標, ズーム%) per キャラ per モード
# CHARACTER_UPPER_BODY_MODE が ON の場合、Y と zoom を自動調整した TACHIE_PARAMS を使う
# ───────────────────────────────────────────────
TACHIE_BASE: dict = {
    "ずんだもん": {"long": (-696, 430, 66.9),  "shorts": (-364.5, 850, 60.3)},
    "めたん":     {"long": ( 751, 430, 52.95), "shorts": ( 348.0, 850, 50.1)},
}
if CHARACTER_UPPER_BODY_MODE:
    TACHIE_PARAMS: dict = {
        char: {
            m: (
                x,
                y + (CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET if m == "shorts" else CHARACTER_UPPER_BODY_LONG_Y_OFFSET),
                round(z * (CHARACTER_UPPER_BODY_SHORTS_SCALE if m == "shorts" else CHARACTER_UPPER_BODY_SCALE), 2),
            )
            for m, (x, y, z) in modes.items()
        }
        for char, modes in TACHIE_BASE.items()
    }
else:
    TACHIE_PARAMS = TACHIE_BASE

# ───────────────────────────────────────────────
# native Shorts スクリプト品質チェック閾値
# ───────────────────────────────────────────────
NATIVE_SHORTS_ESTIMATE_BASE_CPS   = float(os.environ.get("NATIVE_SHORTS_ESTIMATE_BASE_CPS",   "5.4"))   # 推定尺計算の基準文字数/秒
NATIVE_SHORTS_CHARS_MUST_FIX_MIN  = int(os.environ.get("NATIVE_SHORTS_CHARS_MUST_FIX_MIN",  "260"))    # これ未満の総文字数は must_fix
NATIVE_SHORTS_TARGET_CHARS_MIN    = int(os.environ.get("NATIVE_SHORTS_TARGET_CHARS_MIN",    "280"))    # 目標文字数の下限
NATIVE_SHORTS_TARGET_CHARS_MAX    = int(os.environ.get("NATIVE_SHORTS_TARGET_CHARS_MAX",    "330"))    # 目標文字数の上限
NATIVE_SHORTS_AVG_CHARS_MIN       = float(os.environ.get("NATIVE_SHORTS_AVG_CHARS_MIN",     "11.5"))   # 1行あたり平均文字数の下限
NATIVE_SHORTS_SHORT_LINE_MAX      = int(os.environ.get("NATIVE_SHORTS_SHORT_LINE_MAX",      "4"))      # 短すぎる行（≤4文字）の最大許容数

# native Shorts セリフ数ルール（YMM4 とは別基準）
NATIVE_SHORTS_LINES_IDEAL_MIN  = 22   # 理想セリフ数: 下限
NATIVE_SHORTS_LINES_IDEAL_MAX  = 28   # 理想セリフ数: 上限
NATIVE_SHORTS_LINES_TARGET_MIN = int(os.environ.get("NATIVE_SHORTS_LINES_TARGET_MIN", "24"))  # 目標セリフ数: 下限
NATIVE_SHORTS_LINES_TARGET_MAX = int(os.environ.get("NATIVE_SHORTS_LINES_TARGET_MAX", "27"))  # 目標セリフ数: 上限
NATIVE_SHORTS_LINES_WARNING    = 29   # 29〜30行: warning
NATIVE_SHORTS_LINES_MUST_FIX   = 31  # 31行以上: must_fix

# ───────────────────────────────────────────────
# レンダリングエンジン選択
# ───────────────────────────────────────────────
DEFAULT_SHORTS_RENDER_ENGINE = "native"  # deprecated: YMM4出力廃止後は常にnative
GENERATE_YMM4_PROJECT        = False     # deprecated: .ymmp は生成しない
RENDER_WITH_YMM4             = False     # deprecated: YMM4本番レンダリングは行わない

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
OLLAMA_REWRITE_FALLBACK_MODEL = os.environ.get("OLLAMA_REWRITE_FALLBACK_MODEL", "gemma4:e4b")           # リライト失敗時のフォールバックモデル
OPENING_REWRITE_MAX_FALLBACKS = int(os.environ.get("OPENING_REWRITE_MAX_FALLBACKS", "1"))               # フォールバック試行上限

# ChatGPT 生成前レビュー
OPENAI_FINAL_REVIEW_ENABLED  = os.environ.get("OPENAI_FINAL_REVIEW_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")  # レビュー有効/無効
OPENAI_FINAL_REVIEW_MODEL    = os.environ.get("OPENAI_FINAL_REVIEW_MODEL",   "gpt-5.2")                                          # レビューモデル
SHORT_FULL_SCRIPT_REVIEW     = os.environ.get("SHORT_FULL_SCRIPT_REVIEW",    "1").strip().lower() in ("1", "true", "yes", "on")  # Shorts 全文レビュー
LONG_FULL_SCRIPT_REVIEW      = os.environ.get("LONG_FULL_SCRIPT_REVIEW",     "0").strip().lower() in ("1", "true", "yes", "on")  # Long 全文レビュー（重いため OFF）
AUTO_FULL_REWRITE_ENABLED    = os.environ.get("AUTO_FULL_REWRITE_ENABLED",   "0").strip().lower() in ("1", "true", "yes", "on")  # must_fix 時に自動全文リライトするか

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
NATIVE_FFMPEG_ENCODER = os.environ.get("NATIVE_FFMPEG_ENCODER", "h264_nvenc")  # エンコーダ（NVENC / libx264 等）
NATIVE_FFMPEG_PRESET  = os.environ.get("NATIVE_FFMPEG_PRESET",  "p5")          # エンコードプリセット
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
# BGM（固定: BGMer「のほほん」）
# ───────────────────────────────────────────────
BGM_PATH   = os.path.join(ASSETS_DIR, "bgm", "nohohon_long_BPM97.mp3")
BGM_VOLUME = 15.0   # YMM4 BGM 音量 (%)。native は NATIVE_BGM_VOLUME_DB を使う
BGM_LAYER  = 2      # YMM4 プロジェクト内レイヤー番号

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

# ───────────────────────────────────────────────
# 背景画像生成枚数上限
# Shorts: 3〜5 秒ごとに切り替えが理想
# Long: 5〜7 秒ごと。10 秒以上同一背景は避ける
# Long節約モード: 新規生成を最大 16 枚に制限（台本で「背景: 前と同じ」を使うとカウント外）
# ───────────────────────────────────────────────
MAX_BACKGROUNDS_SHORTS      = 9    # Shorts: 最大背景枚数
MAX_BACKGROUNDS_LONG        = 90   # Long: 最大背景枚数（通常モード）
MAX_BACKGROUNDS_LONG_BUDGET = 16   # Long: 最大背景枚数（節約モード）
MAX_BACKGROUNDS             = MAX_BACKGROUNDS_SHORTS  # 後方互換エイリアス
