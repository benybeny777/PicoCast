import os
from typing import Any

from config import config


def recent_debug_log(max_lines: int | None = None) -> dict[str, Any]:
    """直近のデバッグログ末尾をWeb UI表示用に返す。"""
    max_lines = max_lines or config.DEBUG_LOG_VIEW_LINES
    paths = [
        os.path.join(config.DEBUG_LOG_DIR, "app_debug_web.log"),
        os.path.join(config.DEBUG_LOG_DIR, "app_debug_runner.log"),
    ]
    existing = [p for p in paths if os.path.isfile(p)]
    if not existing:
        return {
            "enabled": config.DEBUG_LOG_ENABLED,
            "path": " / ".join(paths),
            "lines": [],
            "message": "デバッグログはまだ出力されていません。",
        }
    lines: list[str] = []
    per_file = max(1, max_lines // max(1, len(existing)))
    for path in existing:
        name = os.path.basename(path)
        lines.append(f"===== {name} =====")
        lines.extend(_tail_lines(path, per_file))
    return {
        "enabled": config.DEBUG_LOG_ENABLED,
        "path": " / ".join(existing),
        "lines": lines[-max_lines:],
        "message": "",
    }


def _tail_lines(path: str, max_lines: int) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-max(1, max_lines):]]
