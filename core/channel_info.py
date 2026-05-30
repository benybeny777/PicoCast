"""チャンネル識別情報の読み込みと検証。"""
import logging
import re

_logger = logging.getLogger(__name__)
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
_DEFAULT_ACCENT = "#4a5568"  # 未設定時の安全なデフォルト色（グレー）


def get_channel_info() -> dict:
    """
    .env / 環境変数からチャンネル識別情報を読み込む。

    upload_allowed=False のとき、アップロード系処理は中止すること。
    warnings の level="error" が1件でもあれば upload_allowed=False になる。
    """
    from config import config
    name = config.CHANNEL_NAME
    handle = config.CHANNEL_HANDLE
    theme = config.CHANNEL_THEME
    accent_raw = config.CHANNEL_ACCENT_COLOR
    hashtags = config.DEFAULT_HASHTAGS

    warnings: list[dict] = []

    if not name:
        warnings.append({"level": "error", "message": "CHANNEL_NAME が未設定です"})
    if not handle:
        warnings.append({"level": "error", "message": "CHANNEL_HANDLE が未設定です"})

    accent_color = _DEFAULT_ACCENT
    accent_color_set = False
    if accent_raw:
        if _HEX_COLOR_RE.match(accent_raw):
            accent_color = accent_raw
            accent_color_set = True
        else:
            warnings.append({
                "level": "warn",
                "message": f"CHANNEL_ACCENT_COLOR の値が不正です（{accent_raw}）。デフォルト色を使用します",
            })

    return {
        "name": name or None,
        "handle": handle or None,
        "theme": theme or None,
        "accent_color": accent_color,
        "accent_color_set": accent_color_set,
        "hashtags": hashtags or None,
        "warnings": warnings,
        "upload_allowed": bool(name and handle),
    }


def log_channel_info() -> None:
    """アップロード直前ログ用。[CHANNEL] プレフィックスで標準ログに出力する。"""
    info = get_channel_info()
    _logger.info("[CHANNEL] name=%s", info["name"] or "")
    _logger.info("[CHANNEL] handle=%s", info["handle"] or "")
    _logger.info("[CHANNEL] theme=%s", info["theme"] or "")
