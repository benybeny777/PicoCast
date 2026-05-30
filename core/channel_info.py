"""チャンネル識別情報の読み込みと検証。

active channel profile があればそこから読む。
なければ .env / 環境変数にフォールバック（後方互換）。
"""
import logging
import re

_logger = logging.getLogger(__name__)
_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
_DEFAULT_ACCENT = "#4a5568"  # 未設定時の安全なデフォルト色（グレー）


def get_channel_info() -> dict:
    """
    active channel profile からチャンネル識別情報を取得する。
    profile 未設定なら .env / 環境変数にフォールバック（後方互換）。

    upload_allowed=False のとき、アップロード系処理は中止すること。
    warnings の level="error" が1件でもあれば upload_allowed=False になる。
    """
    # active profile から読む
    try:
        from core.channel_profile import get_active_profile
        profile = get_active_profile()
        if profile:
            return _build_from_profile(profile)
    except Exception as e:
        _logger.debug("[ChannelInfo] profile 読み込みエラー（フォールバック）: %s", e)

    # フォールバック: .env / 環境変数
    return _build_from_env()


def _build_from_profile(profile) -> dict:
    """active ChannelProfile から channel_info dict を組み立てる。"""
    handle = profile.handle_normalized
    accent_raw = profile.channel_accent_color
    warnings: list[dict] = []

    if not profile.channel_name:
        warnings.append({"level": "error", "message": "channel_name が未設定です"})
    if not handle:
        warnings.append({"level": "error", "message": "channel_handle が未設定です"})

    accent_color = _DEFAULT_ACCENT
    accent_color_set = False
    if accent_raw:
        if _HEX_COLOR_RE.match(accent_raw):
            accent_color = accent_raw
            accent_color_set = True
        else:
            warnings.append({
                "level": "warn",
                "message": f"channel_accent_color の値が不正です（{accent_raw}）。デフォルト色を使用します",
            })

    return {
        "name": profile.channel_name or None,
        "handle": handle or None,
        "theme": profile.channel_theme or None,
        "accent_color": accent_color,
        "accent_color_set": accent_color_set,
        "hashtags": profile.default_hashtags or None,
        "genre_profile": profile.genre_profile,
        "profile_id": profile.profile_id,
        "warnings": warnings,
        "upload_allowed": bool(profile.channel_name and handle),
    }


def _build_from_env() -> dict:
    """環境変数からチャンネル情報を組み立てる（後方互換）。"""
    from config import config
    name = config.CHANNEL_NAME
    handle = config.CHANNEL_HANDLE
    if handle and not handle.startswith("@"):
        handle = "@" + handle
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
        "genre_profile": None,
        "profile_id": None,
        "warnings": warnings,
        "upload_allowed": bool(name and handle),
    }


def log_channel_info() -> None:
    """アップロード直前ログ用。[CHANNEL] プレフィックスで標準ログに出力する。"""
    info = get_channel_info()
    _logger.info("[CHANNEL] name=%s", info["name"] or "")
    _logger.info("[CHANNEL] handle=%s", info["handle"] or "")
    _logger.info("[CHANNEL] theme=%s", info["theme"] or "")
    _logger.info("[CHANNEL] genre_profile=%s", info.get("genre_profile") or "")
