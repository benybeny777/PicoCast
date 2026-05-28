import os
from typing import Any

from config.config import config


def recent_debug_log(max_lines: int | None = None) -> dict[str, Any]:
    """直近のデバッグログ末尾をWeb UI表示用に返す。"""
    max_lines = max_lines or config.DEBUG_LOG_VIEW_LINES
    log_path = os.path.join(config.DEBUG_LOG_DIR, "app_debug.log")
    if not os.path.isfile(log_path):
        return {
            "enabled": config.DEBUG_LOG_ENABLED,
            "path": log_path,
            "lines": [],
            "message": "デバッグログはまだ出力されていません。",
        }
    lines = _tail_lines(log_path, max_lines)
    return {
        "enabled": config.DEBUG_LOG_ENABLED,
        "path": log_path,
        "lines": lines,
        "message": "",
    }


def _tail_lines(path: str, max_lines: int) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-max(1, max_lines):]]
