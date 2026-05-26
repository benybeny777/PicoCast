"""
.env ファイルの読み書きによる設定変更サービス。
APIキー・トークンなど秘密値は対象外。変更後はアプリ再起動が必要。
"""
import os
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")

# 編集可能な設定項目の定義（秘密値は含めない）
EDITABLE_CONFIG: list[dict[str, Any]] = [
    {"key": "NATIVE_SHORTS_BODY_VOICE_SPEED",  "type": "float", "label": "Shorts 本編音声速度",       "default": "1.25", "min": 0.5, "max": 3.0},
    {"key": "NATIVE_SHORTS_INTRO_VOICE_SPEED", "type": "float", "label": "Shorts 冒頭音声速度",       "default": "1.40", "min": 0.5, "max": 3.0},
    {"key": "NATIVE_LONG_BODY_VOICE_SPEED",    "type": "float", "label": "Long 本編音声速度",          "default": "1.20", "min": 0.5, "max": 3.0},
    {"key": "NATIVE_LONG_INTRO_VOICE_SPEED",   "type": "float", "label": "Long 冒頭音声速度",          "default": "1.40", "min": 0.5, "max": 3.0},
    {"key": "MAX_BACKGROUNDS_SHORTS",          "type": "int",   "label": "最大背景枚数 (Shorts)",      "default": "9",    "min": 1,   "max": 30},
    {"key": "MAX_BACKGROUNDS_LONG",            "type": "int",   "label": "最大背景枚数 (Long)",         "default": "90",   "min": 1,   "max": 200},
    {"key": "MAX_BACKGROUNDS_LONG_BUDGET",     "type": "int",   "label": "最大背景枚数 (Long節約)",     "default": "16",   "min": 1,   "max": 50},
    {"key": "OPENING_REVIEW_USE_LLM",          "type": "bool",         "label": "Ollama レビュー有効",           "default": "1"},
    {"key": "OLLAMA_REVIEW_MODEL",             "type": "ollama_model", "label": "Ollama レビューモデル",         "default": "qwen3:8b"},
    {"key": "OLLAMA_REWRITE_MODEL",            "type": "ollama_model", "label": "Ollama リライトモデル",         "default": "qwen3:8b"},
    {"key": "OLLAMA_REWRITE_FALLBACK_MODEL",   "type": "ollama_model", "label": "Ollama リライト fallback モデル", "default": "gemma4:e4b"},
    {"key": "VOICE_READING_NORMALIZE_ENABLED",    "type": "bool",         "label": "よみがな正規化 有効",          "default": "1"},
    {"key": "VOICE_READING_NORMALIZE_MODEL",      "type": "ollama_model", "label": "よみがな正規化 モデル",         "default": "qwen2.5:7b"},
    {"key": "VOICE_READING_NORMALIZE_OLLAMA_URL", "type": "str",          "label": "よみがな正規化 Ollama URL",     "default": "http://localhost:11434"},
    {"key": "OPENAI_FINAL_REVIEW_ENABLED",     "type": "bool",  "label": "ChatGPT 最終レビュー有効",   "default": "1"},
    {"key": "OPENAI_FINAL_REVIEW_MODEL",       "type": "str",   "label": "ChatGPT 最終レビューモデル", "default": "gpt-4o"},
    {"key": "WEB_UI_PORT",                     "type": "int",   "label": "Web UI ポート番号",          "default": "58080", "min": 1024, "max": 65535},
    {"key": "FFMPEG_BIN",                      "type": "str",   "label": "ffmpeg バイナリパス",        "default": "ffmpeg"},
]

_ALLOWED_KEYS = {item["key"] for item in EDITABLE_CONFIG}


def get_editable_config() -> list[dict[str, Any]]:
    """現在値付きの設定項目リストを返す。"""
    import config as cfg
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
        if key not in _ALLOWED_KEYS:
            errors.append(f"不正なキー: {key}")
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
            elif spec["type"] in ("str", "ollama_model"):
                if not raw_val.strip():
                    errors.append(f"{key}: 空文字は不正です")
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
