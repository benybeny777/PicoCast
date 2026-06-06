"""動画生成パイプラインで共有する副作用の小さい補助処理。"""
from __future__ import annotations

import logging
import os
import re

_logger = logging.getLogger("yj.pipeline")
_PUNCTUATION = frozenset("。！？")
_FORMAT_PATTERN = re.compile(r"^(?:動画形式|Format)[:：]\s*(.+)$", re.IGNORECASE)
_SCREEN_FORMAT_PATTERN = re.compile(
    r"^(?:画面形式|ScreenFormat)[:：]\s*(.+)$",
    re.IGNORECASE,
)


def resolution_label(width: int, height: int) -> str:
    """最終出力解像度の表示文字列を返す。"""
    return f"{width}x{height}"


def background_filename(background_number: int) -> str:
    """背景画像の標準ファイル名を返す。"""
    return f"bg_{background_number:03d}_001.png"


def cleanup_orphan_audio(audio_dir: str, expected_filenames: set[str]) -> int:
    """期待一覧にないWAVを削除し、削除件数を返す。"""
    if not expected_filenames or not os.path.isdir(audio_dir):
        return 0

    removed = 0
    for filename in os.listdir(audio_dir):
        if not filename.lower().endswith(".wav") or filename in expected_filenames:
            continue
        try:
            os.remove(os.path.join(audio_dir, filename))
            removed += 1
        except OSError:
            _logger.warning(
                "余剰WAVの削除に失敗しました: file=%s",
                filename,
                exc_info=True,
            )
            # フォールバック許可: 個別ファイルの削除失敗では生成処理を止めない
    return removed


def split_at_punctuation(text: str) -> list[str]:
    """Shorts用セリフを句読点単位に分割する。"""
    chunks: list[str] = []
    current = ""
    for character in text:
        current += character
        if character in _PUNCTUATION and current.strip():
            chunks.append(current)
            current = ""
    if current.strip():
        chunks.append(current)

    merged: list[str] = []
    punctuation_text = "".join(_PUNCTUATION)
    for chunk in chunks:
        if merged and not chunk.strip(punctuation_text + "　 "):
            merged[-1] += chunk
        else:
            merged.append(chunk)
    return merged or [text]


def _metadata_value(script_content: str, pattern: re.Pattern[str]) -> str:
    for raw_line in script_content.splitlines():
        line = raw_line.strip().replace("**", "")
        match = pattern.match(line)
        if match:
            return match.group(1).strip()
    return ""


def detect_is_shorts(script_content: str) -> bool:
    """動画形式メタ情報からShortsか判定する。"""
    format_value = _metadata_value(script_content, _FORMAT_PATTERN).lower()
    return "shorts" in format_value or "ショート" in format_value


def detect_is_netakaigi(script_content: str) -> bool:
    """動画形式メタ情報からネタ会議か判定する。"""
    return "ネタ会議" in _metadata_value(script_content, _FORMAT_PATTERN)


def detect_netakaigi_variant(script_content: str) -> str:
    """ネタ会議の画面形式を ``Long`` または ``Shorts`` で返す。"""
    format_value = _metadata_value(script_content, _FORMAT_PATTERN)
    screen_format = _metadata_value(script_content, _SCREEN_FORMAT_PATTERN)
    if "Long" in format_value or "ロング" in format_value:
        return "Long"
    if "Shorts" in format_value or "ショート" in format_value:
        return "Shorts"
    if "横" in screen_format or "wide" in screen_format.lower():
        return "Long"
    return "Shorts"


def parse_playlist_categories_meta(raw: str | list[str]) -> list[str]:
    """再生リストカテゴリのメタ値を文字列リストへ統一する。"""
    if isinstance(raw, list):
        return raw
    from core.playlist_resolver import parse_playlist_categories

    return parse_playlist_categories(str(raw or ""))
