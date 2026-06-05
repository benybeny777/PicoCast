"""ffprobe を使ったメディア情報取得。"""
from __future__ import annotations

import logging
import os
import subprocess

from config import FFMPEG_BIN, NATIVE_FFPROBE_TIMEOUT_SEC

_logger = logging.getLogger(__name__)


def ffprobe_bin() -> str:
    """FFMPEG_BIN に対応する ffprobe コマンド名を返す。"""
    base = os.path.basename(str(FFMPEG_BIN or "ffmpeg")).lower()
    if base in {"ffmpeg", "ffmpeg.exe"}:
        probe_name = "ffprobe.exe" if base.endswith(".exe") else "ffprobe"
        return os.path.join(os.path.dirname(FFMPEG_BIN), probe_name) if os.path.dirname(FFMPEG_BIN) else probe_name
    return "ffprobe"


def media_duration_sec(path: str) -> float | None:
    """メディアファイルの duration 秒を返す。取得できない場合は None。"""
    if not path or not os.path.exists(path):
        return None
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        proc = subprocess.run(
            [
                ffprobe_bin(),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            timeout=NATIVE_FFPROBE_TIMEOUT_SEC,
        )
        if proc.returncode != 0:
            _logger.warning("ffprobeによるメディア尺取得に失敗しました: path=%s returncode=%s", path, proc.returncode)
            return None
        return float((proc.stdout or "").strip())
    except Exception:
        _logger.warning("メディア尺取得に失敗しました: path=%s", path, exc_info=True)
        return None
