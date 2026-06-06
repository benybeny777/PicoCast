"""ユーザー向け処理ログからスタックトレースを除去する。"""
from __future__ import annotations

import re

_TRACE_MARKERS = (
    "Traceback (most recent call last):",
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
)
_TRACE_FILE_LINE = re.compile(r'^\s*File "[^"]+", line \d+')


def sanitize_process_log_message(message: object) -> str:
    """処理ログへ保存可能な、スタックトレースを含まない文字列を返す。"""
    text = str(message or "")
    marker_positions = [text.find(marker) for marker in _TRACE_MARKERS if marker in text]
    if marker_positions:
        text = text[:min(marker_positions)]

    safe_lines: list[str] = []
    for line in text.splitlines():
        if _TRACE_FILE_LINE.match(line):
            break
        safe_lines.append(line)

    sanitized = "\n".join(safe_lines).strip()
    if sanitized:
        return sanitized
    return "処理に失敗しました。詳細はデバッグログを確認してください。"


def user_facing_error_message(exc: Exception) -> str:
    """AppErrorは対処付き、それ以外はトレース除去済みの例外文を返す。"""
    user_message = getattr(exc, "user_message", None)
    if callable(user_message):
        return sanitize_process_log_message(user_message())
    return sanitize_process_log_message(exc)
