"""
.env ファイルの読み書きによる設定変更サービス。
APIキー・トークンなど秘密値は対象外。変更後はアプリ再起動が必要。
"""
import os
from typing import Any
import config as cfg

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")

# 編集可能な設定項目の定義（秘密値は含めない）
EDITABLE_CONFIG: list[dict[str, Any]] = [
    {"key": "WEB_APP_NAME",                    "type": "str",   "label": "Web UI 表示名",             "default": str(cfg.WEB_APP_NAME)},
    {"key": "NATIVE_SHORTS_BODY_VOICE_SPEED",  "type": "float", "label": "Shorts 本編音声速度",       "default": str(cfg.NATIVE_SHORTS_BODY_VOICE_SPEED), "min": 0.5, "max": 3.0},
    {"key": "NATIVE_SHORTS_INTRO_VOICE_SPEED", "type": "float", "label": "Shorts 冒頭音声速度",       "default": str(cfg.NATIVE_SHORTS_INTRO_VOICE_SPEED), "min": 0.5, "max": 3.0},
    {"key": "NATIVE_LONG_BODY_VOICE_SPEED",    "type": "float", "label": "Long 本編音声速度",          "default": str(cfg.NATIVE_LONG_BODY_VOICE_SPEED), "min": 0.5, "max": 3.0},
    {"key": "NATIVE_LONG_INTRO_VOICE_SPEED",   "type": "float", "label": "Long 冒頭音声速度",          "default": str(cfg.NATIVE_LONG_INTRO_VOICE_SPEED), "min": 0.5, "max": 3.0},
    {"key": "BGM_FILE",                         "type": "bgm_file", "label": "BGMファイル",             "default": str(cfg.BGM_FILE)},
    {"key": "NATIVE_BGM_VOLUME_DB",            "type": "float", "label": "native BGM音量(dB)",         "default": str(cfg.NATIVE_BGM_VOLUME_DB), "min": -60, "max": 0},
    {"key": "NATIVE_ENABLE_MOTION_EFFECTS",    "type": "bool",  "label": "Shorts軽量エフェクト全体",   "default": "1" if cfg.NATIVE_ENABLE_MOTION_EFFECTS else "0"},
    {"key": "NATIVE_ENABLE_BG_KEN_BURNS",      "type": "bool",  "label": "背景ズーム/パン",            "default": "1" if cfg.NATIVE_ENABLE_BG_KEN_BURNS else "0"},
    {"key": "NATIVE_ENABLE_CHARACTER_BOUNCE",  "type": "bool",  "label": "キャラバウンス",             "default": "1" if cfg.NATIVE_ENABLE_CHARACTER_BOUNCE else "0"},
    {"key": "NATIVE_ENABLE_POP_TELOP",         "type": "bool",  "label": "テロップポップ",             "default": "1" if cfg.NATIVE_ENABLE_POP_TELOP else "0"},
    {"key": "NATIVE_ENABLE_SHAKE",             "type": "bool",  "label": "ツッコミ/驚きシェイク",      "default": "1" if cfg.NATIVE_ENABLE_SHAKE else "0"},
    {"key": "NATIVE_MAX_SHAKE_COUNT_SHORTS",   "type": "int",   "label": "シェイク上限 (Shorts)",      "default": str(cfg.NATIVE_MAX_SHAKE_COUNT_SHORTS), "min": 0, "max": 10},
    {"key": "NATIVE_MAX_ICON_COUNT_SHORTS",    "type": "int",   "label": "疑問/驚きアイコン上限",      "default": str(cfg.NATIVE_MAX_ICON_COUNT_SHORTS), "min": 0, "max": 10},
    {"key": "NATIVE_BG_ZOOM_MAX",              "type": "float", "label": "背景ズーム最大倍率",          "default": str(cfg.NATIVE_BG_ZOOM_MAX), "min": 1.0, "max": 1.2},
    {"key": "MAX_BACKGROUNDS_SHORTS",          "type": "int",   "label": "最大背景枚数 (Shorts)",      "default": str(cfg.MAX_BACKGROUNDS_SHORTS),    "min": 1,   "max": 30},
    {"key": "MAX_BACKGROUNDS_LONG",            "type": "int",   "label": "最大背景枚数 (Long)",         "default": str(cfg.MAX_BACKGROUNDS_LONG),   "min": 1,   "max": 200},
    {"key": "MAX_BACKGROUNDS_LONG_BUDGET",     "type": "int",   "label": "最大背景枚数 (Long節約)",     "default": str(cfg.MAX_BACKGROUNDS_LONG_BUDGET),   "min": 1,   "max": 50},
    {"key": "LONG_UPLOAD_PLAYLIST_NAME",       "type": "str",   "label": "Long追加先再生リスト名",      "default": str(cfg.LONG_UPLOAD_PLAYLIST_NAME), "allow_empty": True},
    {"key": "GEMINI_MODEL",                    "type": "str",   "label": "Gemini 台本生成モデル",       "default": str(cfg.GEMINI_MODEL)},
    {"key": "NANOBANANA_PRO_MODEL",            "type": "str",   "label": "画像生成モデル(高品質)",      "default": str(cfg.NANOBANANA_PRO_MODEL)},
    {"key": "NANOBANANA_FLASH_MODEL",          "type": "str",   "label": "画像生成モデル(高速)",        "default": str(cfg.NANOBANANA_FLASH_MODEL)},
    {"key": "OPENING_REVIEW_USE_LLM",          "type": "bool",         "label": "Ollama レビュー有効",           "default": "1" if cfg.OPENING_REVIEW_USE_LLM else "0"},
    {"key": "OLLAMA_REVIEW_MODEL",             "type": "ollama_model", "label": "Ollama レビューモデル",         "default": str(cfg.OLLAMA_REVIEW_MODEL)},
    {"key": "OLLAMA_REWRITE_MODEL",            "type": "ollama_model", "label": "Ollama リライトモデル",         "default": str(cfg.OLLAMA_REWRITE_MODEL)},
    {"key": "OLLAMA_REWRITE_FALLBACK_MODEL",   "type": "ollama_model", "label": "Ollama リライト fallback モデル", "default": str(cfg.OLLAMA_REWRITE_FALLBACK_MODEL)},
    {"key": "VOICE_READING_NORMALIZE_ENABLED",    "type": "bool",         "label": "よみがな正規化 有効",          "default": "1" if cfg.VOICE_READING_NORMALIZE_ENABLED else "0"},
    {"key": "VOICE_READING_NORMALIZE_MODEL",      "type": "ollama_model", "label": "よみがな正規化 モデル",         "default": str(cfg.VOICE_READING_NORMALIZE_MODEL)},
    {"key": "VOICE_READING_NORMALIZE_OLLAMA_URL", "type": "str",          "label": "よみがな正規化 Ollama URL",     "default": str(cfg.VOICE_READING_NORMALIZE_OLLAMA_URL)},
    {"key": "OPENAI_FINAL_REVIEW_ENABLED",     "type": "bool",  "label": "ChatGPT 最終レビュー有効",   "default": "1" if cfg.OPENAI_FINAL_REVIEW_ENABLED else "0"},
    {"key": "OPENAI_FINAL_REVIEW_MODEL",       "type": "str",   "label": "ChatGPT 最終レビューモデル", "default": str(cfg.OPENAI_FINAL_REVIEW_MODEL)},
    {"key": "WEB_UI_PORT",                     "type": "int",   "label": "Web UI ポート番号",          "default": str(cfg.WEB_UI_PORT), "min": 1024, "max": 65535},
    {"key": "WEB_DEFAULT_IMAGE_STYLE",         "type": "str",   "label": "Web既定画像スタイル",        "default": str(cfg.WEB_DEFAULT_IMAGE_STYLE)},
    {"key": "WEB_IMAGE_STYLE_CHOICES",         "type": "str",   "label": "Web画像スタイル選択肢",      "default": ",".join(cfg.WEB_IMAGE_STYLE_CHOICES)},
    {"key": "WEB_DEFAULT_REUSE_BACKGROUNDS",   "type": "bool",  "label": "Web既定: 背景再利用",        "default": "1" if cfg.WEB_DEFAULT_REUSE_BACKGROUNDS else "0"},
    {"key": "WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST", "type": "bool", "label": "Web既定: LongサムネAB",     "default": "1" if cfg.WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST else "0"},
    {"key": "WEB_DEFAULT_LONG_BUDGET_MODE",    "type": "bool",  "label": "Web既定: Long節約",          "default": "1" if cfg.WEB_DEFAULT_LONG_BUDGET_MODE else "0"},
    {"key": "WEB_DEFAULT_SD_SIZE_MODE",        "type": "bool",  "label": "Web既定: SD生成",            "default": "1" if cfg.WEB_DEFAULT_SD_SIZE_MODE else "0"},
    {"key": "WEB_JOB_POLL_INTERVAL_MS",        "type": "int",   "label": "Webジョブ更新間隔(ms)",      "default": str(cfg.WEB_JOB_POLL_INTERVAL_MS), "min": 500, "max": 30000},
    {"key": "WEB_SUCCESS_RELOAD_DELAY_MS",     "type": "int",   "label": "Web成功後再読み込み待ち(ms)", "default": str(cfg.WEB_SUCCESS_RELOAD_DELAY_MS), "min": 0, "max": 10000},
    {"key": "WEB_TOAST_VISIBLE_MS",            "type": "int",   "label": "Webトースト表示時間(ms)",    "default": str(cfg.WEB_TOAST_VISIBLE_MS), "min": 500, "max": 10000},
    {"key": "WEB_TOAST_HIDE_DELAY_MS",         "type": "int",   "label": "Webトースト非表示待ち(ms)",  "default": str(cfg.WEB_TOAST_HIDE_DELAY_MS), "min": 0, "max": 3000},
    {"key": "WEB_VOICEVOX_CHECK_TIMEOUT_SEC",  "type": "float", "label": "VOICEVOX確認タイムアウト(秒)", "default": str(cfg.WEB_VOICEVOX_CHECK_TIMEOUT_SEC), "min": 0.2, "max": 30},
    {"key": "WEB_FFMPEG_CHECK_TIMEOUT_SEC",    "type": "float", "label": "ffmpeg確認タイムアウト(秒)",   "default": str(cfg.WEB_FFMPEG_CHECK_TIMEOUT_SEC), "min": 0.2, "max": 30},
    {"key": "FFMPEG_BIN",                      "type": "str",   "label": "ffmpeg バイナリパス",        "default": str(cfg.FFMPEG_BIN)},
]

_ALLOWED_KEYS = {item["key"] for item in EDITABLE_CONFIG}


def get_editable_config() -> list[dict[str, Any]]:
    """現在値付きの設定項目リストを返す。"""
    env_values = _read_env()
    result = []
    for item in EDITABLE_CONFIG:
        key = item["key"]
        raw = getattr(cfg, key, None)
        if raw is None:
            raw = env_values.get(key, item["default"])
        if isinstance(raw, bool):
            current_str = "1" if raw else "0"
        else:
            current_str = str(raw)
        result.append({**item, "current": current_str})
    return result


def save_config(updates: dict[str, str]) -> list[str]:
    """
    更新値を検証して .env に書き込む。
    戻り値: バリデーションエラーのリスト（空なら成功）
    """
    errors = _validate(updates)
    if errors:
        return errors

    safe_updates = {k: v for k, v in updates.items() if k in _ALLOWED_KEYS}
    _write_env(safe_updates)
    return []


def _validate(updates: dict[str, str]) -> list[str]:
    errors = []
    key_map = {item["key"]: item for item in EDITABLE_CONFIG}
    for key, raw_val in updates.items():
        raw_val = str(raw_val)
        if key not in _ALLOWED_KEYS:
            errors.append(f"不正なキー: {key}")
            continue
        if "\n" in raw_val or "\r" in raw_val:
            errors.append(f"{key}: 改行は使用できません")
            continue
        spec = key_map[key]
        try:
            if spec["type"] == "float":
                v = float(raw_val)
                if "min" in spec and v < spec["min"]:
                    errors.append(f"{key}: {v} は最小値 {spec['min']} 未満です")
                if "max" in spec and v > spec["max"]:
                    errors.append(f"{key}: {v} は最大値 {spec['max']} 超です")
            elif spec["type"] == "int":
                v = int(raw_val)
                if "min" in spec and v < spec["min"]:
                    errors.append(f"{key}: {v} は最小値 {spec['min']} 未満です")
                if "max" in spec and v > spec["max"]:
                    errors.append(f"{key}: {v} は最大値 {spec['max']} 超です")
            elif spec["type"] == "bool":
                if raw_val not in ("0", "1"):
                    errors.append(f"{key}: '0' か '1' で指定してください")
            elif spec["type"] in ("str", "ollama_model", "bgm_file"):
                if not raw_val.strip() and not spec.get("allow_empty"):
                    errors.append(f"{key}: 空文字は不正です")
                if spec["type"] == "bgm_file" and raw_val.strip():
                    if os.path.sep in raw_val or "/" in raw_val or "\\" in raw_val:
                        errors.append(f"{key}: ファイル名のみ指定してください（パス区切り文字不可）")
        except (ValueError, TypeError):
            errors.append(f"{key}: '{raw_val}' は {spec['type']} として無効です")
    return errors


def _read_env() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return result


def _write_env(updates: dict[str, str]) -> None:
    """既存の .env を行単位で書き換え、未登録キーは末尾に追記する。"""
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    updated: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.partition("=")[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                updated.add(k)
                continue
        new_lines.append(line)

    for k, v in updates.items():
        if k not in updated:
            new_lines.append(f"{k}={v}\n")

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
