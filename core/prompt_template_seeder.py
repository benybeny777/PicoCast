"""
プロンプトテンプレートの初期データ投入モジュール。

config/prompt_profiles/genres/{genre_profile}/ のファイルと
core/script_prompts.py の共通定数から、
channel profile 別のテンプレートを DB に作成する。

呼び出し:
  from core.prompt_template_seeder import seed_templates_for_profile
  seed_templates_for_profile(profile_id, genre_profile)

すでにテンプレートが存在する profile はスキップする（冪等）。
"""
from __future__ import annotations

import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_GENRES_DIR = _PROJECT_ROOT / "config" / "prompt_profiles" / "genres"


def _read_genre_file(genre_profile: str, filename: str) -> str:
    """genres/{genre_profile}/{filename} を読む。存在しなければ空文字。"""
    path = _GENRES_DIR / genre_profile / filename
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _load_genre_config(genre_profile: str) -> dict[str, str]:
    """profile.yaml をシンプルパースして dict 化する。"""
    path = _GENRES_DIR / genre_profile / "profile.yaml"
    config: dict[str, str] = {}
    if not path.exists():
        return config
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        config[k.strip()] = v.strip().strip('"').strip("'")
    return config


def _load_common_script_rules() -> str:
    """script_prompts.py の共通ルール定数を結合して返す。"""
    try:
        from core.script_prompts import (
            COMMON_SCRIPT_RULES,
            HIGH_TEMPO_RULES,
            SHORTS_QUANTITY_RULES,
            METAN_TSUNDERE_RULES,
            METADATA_FORMAT,
            SCRIPT_BODY_FORMAT,
        )
        return "\n\n".join([
            "## 出力フォーマット（必須）",
            METADATA_FORMAT,
            SCRIPT_BODY_FORMAT,
            "## 共通ルール",
            COMMON_SCRIPT_RULES,
            "## 高テンポルール",
            HIGH_TEMPO_RULES,
            "## Shorts 分量ルール（最優先）",
            SHORTS_QUANTITY_RULES,
            "## めたん毒舌ルール（必須）",
            METAN_TSUNDERE_RULES,
        ])
    except Exception as e:
        _logger.warning("[Seeder] 共通ルール読み込み失敗: %s", e)
        return ""


def _load_common_meeting_rules() -> str:
    """ネタ会議共通ルールを返す。"""
    try:
        from core.script_prompts import METAN_TSUNDERE_RULES, METAN_TSUNDERE_RULES_MEETING
        return METAN_TSUNDERE_RULES + "\n\n" + METAN_TSUNDERE_RULES_MEETING
    except Exception as e:
        _logger.warning("[Seeder] ネタ会議共通ルール読み込み失敗: %s", e)
        return ""


def seed_templates_for_profile(profile_id: str, genre_profile: str) -> int:
    """
    指定 profile_id のテンプレートを genres/{genre_profile}/ から作成する。
    既にテンプレートが存在する profile_id はスキップする（冪等）。

    Returns:
        作成したテンプレート数（スキップ時は 0）
    """
    from core.prompt_template_store import has_templates, create_template

    if has_templates(profile_id):
        _logger.debug("[Seeder] %s は既にテンプレートあり — スキップ", profile_id)
        return 0

    genre_dir = _GENRES_DIR / genre_profile
    if not genre_dir.is_dir():
        from core.prompt_profile_loader import GenreProfileNotFoundError
        raise GenreProfileNotFoundError(
            f"genre_profile '{genre_profile}' のディレクトリが存在しません: {genre_dir}"
        )

    genre_cfg = _load_genre_config(genre_profile)
    display_name = genre_cfg.get("display_name", genre_profile)
    default_hashtags = genre_cfg.get("default_hashtags", "")

    script_context = _read_genre_file(genre_profile, "script_context.md")
    title_context  = _read_genre_file(genre_profile, "title_context.md")
    meeting_context = _read_genre_file(genre_profile, "meeting_context.md")
    playlist_cats_raw = _read_genre_file(genre_profile, "playlist_categories.md")

    # 再生リストカテゴリの先頭行をデフォルトに使う
    default_playlist = ""
    for line in playlist_cats_raw.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            default_playlist = stripped
            break

    common_script_rules = _load_common_script_rules()
    common_meeting_rules = _load_common_meeting_rules()

    created = 0

    # ── script テンプレート ──────────────────────────────────────────────────
    create_template(
        profile_id=profile_id,
        template_name=f"{display_name} Shorts台本",
        template_kind="script",
        genre_profile=genre_profile,
        system_rules=script_context,
        script_rules=common_script_rules,
        description=f"{display_name}チャンネル向けShorts台本生成テンプレート",
        default_hashtags=default_hashtags,
        default_playlist_category=default_playlist,
        is_default=True,
    )
    created += 1

    # ── title テンプレート ───────────────────────────────────────────────────
    create_template(
        profile_id=profile_id,
        template_name=f"{display_name} タイトル案",
        template_kind="title",
        genre_profile=genre_profile,
        system_rules=title_context,
        script_rules="",
        description=f"{display_name}チャンネル向けタイトル案生成テンプレート",
        default_hashtags=default_hashtags,
        default_playlist_category=default_playlist,
        is_default=True,
    )
    created += 1

    # ── meeting テンプレート ─────────────────────────────────────────────────
    if meeting_context:
        create_template(
            profile_id=profile_id,
            template_name=f"{display_name} ネタ会議",
            template_kind="meeting",
            genre_profile=genre_profile,
            system_rules=meeting_context,
            script_rules="",
            meeting_rules=common_meeting_rules,
            description=f"{display_name}チャンネル向けネタ会議テンプレート",
            default_hashtags=default_hashtags,
            default_playlist_category=default_playlist,
            is_default=True,
        )
        created += 1

    _logger.info(
        "[Seeder] %s (%s) にテンプレートを %d 件作成しました",
        profile_id, genre_profile, created,
    )
    return created


def seed_all_profiles() -> dict[str, int]:
    """
    DB に登録されているすべての channel profile にテンプレートを投入する。
    既存テンプレートがある profile はスキップする。

    Returns:
        {profile_id: 作成件数} のマッピング
    """
    from core.channel_profile import list_profiles

    results: dict[str, int] = {}
    profiles = list_profiles()
    if not profiles:
        _logger.info("[Seeder] channel profile が未登録のため seed をスキップ")
        return results

    for profile in profiles:
        try:
            count = seed_templates_for_profile(profile.profile_id, profile.genre_profile)
            results[profile.profile_id] = count
        except Exception as e:
            _logger.error(
                "[Seeder] %s のシード失敗: %s", profile.profile_id, e
            )
            results[profile.profile_id] = -1

    return results
