"""
台本の「再生リスト」カテゴリ名と動画形式から
YouTube上の実際の再生リスト名を解決するモジュール。

再生リストカテゴリは active channel profile の genre_profile に応じた
config/prompt_profiles/genres/{genre_profile}/playlist_categories.md から読み込む。
profile 未設定・genre 未設定の場合は明示エラーで停止する。
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

_NETA_KAIGI_SHORTS = "ずんだもんとめたんのネタ会議 Shorts"
_NETA_KAIGI_LONG = "ずんだもんとめたんのネタ会議【じっくり版】"


def _get_standard_categories() -> tuple[str, ...]:
    """active profile の genre_profile に応じた再生リストカテゴリを返す。"""
    try:
        from core.channel_profile import require_active_profile
        from core.error_codes import AppError
        from core.prompt_profile_loader import get_playlist_categories

        profile = require_active_profile()
        cats = get_playlist_categories(profile.genre_profile)
    except Exception as exc:
        _logger.error("再生リストカテゴリの取得に失敗しました", exc_info=True)
        raise AppError("E-PLAYLIST-CONFIG", detail="チャンネル設定とジャンル設定を確認してください。", cause=exc) from exc
    if not cats:
        _logger.error("再生リストカテゴリが未設定です: profile_id=%s genre_profile=%s", profile.profile_id, profile.genre_profile)
        raise AppError("E-PLAYLIST-CONFIG", detail=f"{profile.genre_profile}/playlist_categories.md が空です。")
    return cats


def _get_suffix_shorts() -> str:
    try:
        from core.channel_profile import require_active_profile
        from core.error_codes import AppError
        from core.prompt_profile_loader import load_genre_profile_config
        profile = require_active_profile()
        cfg = load_genre_profile_config(profile.genre_profile)
        return cfg.get("playlist_suffix_shorts", " Shorts")
    except Exception as exc:
        _logger.error("Shorts再生リスト接尾辞の取得に失敗しました", exc_info=True)
        raise AppError("E-PLAYLIST-CONFIG", detail="Shorts再生リスト接尾辞を取得できません。", cause=exc) from exc


def _get_suffix_long() -> str:
    try:
        from core.channel_profile import require_active_profile
        from core.error_codes import AppError
        from core.prompt_profile_loader import load_genre_profile_config
        profile = require_active_profile()
        cfg = load_genre_profile_config(profile.genre_profile)
        return cfg.get("playlist_suffix_long", "【じっくり解説】")
    except Exception as exc:
        _logger.error("Long再生リスト接尾辞の取得に失敗しました", exc_info=True)
        raise AppError("E-PLAYLIST-CONFIG", detail="Long再生リスト接尾辞を取得できません。", cause=exc) from exc


def normalize_category(name: str) -> str:
    """前後空白・全角スペースを除去して正規化する。"""
    return str(name or "").strip().replace("　", " ")


def parse_playlist_categories(raw: str) -> list[str]:
    """台本の「再生リスト:」の値をカテゴリリストに変換する。カンマ区切りを許容。"""
    if not raw:
        return []
    return [c for c in (normalize_category(p) for p in raw.split(",")) if c]


def _is_neta_kaigi_long(video_format: str, screen_format: str) -> bool:
    vf = (video_format or "").strip()
    sf = (screen_format or "").strip()
    if "ネタ会議" in vf and ("long" in vf.lower() or "ロング" in vf):
        return True
    if "ネタ会議" in vf and sf in ("横", "landscape"):
        return True
    return False


def resolve_video_type(video_format: str, screen_format: str) -> str:
    """動画形式・画面形式から "shorts" または "long" を返す。"""
    vf = (video_format or "").strip()
    sf = (screen_format or "").strip()
    vf_lower = vf.lower()
    if "short" in vf_lower:
        return "shorts"
    if "ネタ会議" in vf:
        return "long" if ("long" in vf_lower or sf in ("横", "landscape")) else "shorts"
    return "shorts" if not vf_lower or "long" not in vf_lower else "long"


def resolve_playlist_title(
    category: str,
    video_format: str,
    screen_format: str,
) -> str | None:
    """
    カテゴリ名・動画形式・画面形式から YouTube 上の実際の再生リスト名を解決する。

    ネタ会議系は category 引数を無視して固定名を返す。
    判定不能な動画形式の場合は None を返す（自動フォールバック禁止）。
    """
    vf = (video_format or "").strip()
    sf = (screen_format or "").strip()
    vf_lower = vf.lower()

    if "ネタ会議" in vf:
        return _NETA_KAIGI_LONG if _is_neta_kaigi_long(vf, sf) else _NETA_KAIGI_SHORTS

    cat = normalize_category(category)
    is_shorts = "short" in vf_lower or sf in ("縦", "portrait")
    is_long = "long" in vf_lower or sf in ("横", "landscape")

    if is_shorts:
        return f"{cat}{_get_suffix_shorts()}"
    if is_long:
        return f"{cat}{_get_suffix_long()}"
    return None


def get_standard_categories() -> tuple[str, ...]:
    """active profile の genre_profile に応じた標準カテゴリ一覧を返す。"""
    return _get_standard_categories()
