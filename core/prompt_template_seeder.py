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


def _load_common_script_rules(genre_profile: str | None = None) -> str:
    """script_prompts.py の共通ルール定数（構成・尺・分量・出力形式）を結合して返す。

    キャラクター設定（役割・口調・禁止台詞・掛け合い）は台本テンプレートから分離し、
    character_profiles で管理する。台本生成時に compose_character_section() で合成するため、
    ここには **キャラ設定（めたん毒舌ルール等）を含めない**。
    """
    try:
        from core.script_prompts import (
            COMMON_SCRIPT_RULES,
            EXPLANATION_DENSITY_RULES,
            HIGH_TEMPO_RULES,
            SHORTS_QUANTITY_RULES,
            METADATA_FORMAT,
            SCRIPT_BODY_FORMAT,
        )
        return "\n\n".join([
            "## 出力フォーマット（必須）",
            METADATA_FORMAT,
            SCRIPT_BODY_FORMAT,
            "## 共通ルール",
            COMMON_SCRIPT_RULES,
            "## 説明密度ルール",
            EXPLANATION_DENSITY_RULES,
            "## 高テンポルール",
            HIGH_TEMPO_RULES,
            "## Shorts 分量ルール（最優先）",
            SHORTS_QUANTITY_RULES,
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
    template_pack = genre_cfg.get("template_pack", f"genre/{genre_profile}")
    visibility = genre_cfg.get("visibility", "private")
    product_bundle = genre_cfg.get("product_bundle", "")

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
        template_pack=template_pack,
        visibility=visibility,
        product_bundle=product_bundle,
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
        template_pack=template_pack,
        visibility=visibility,
        product_bundle=product_bundle,
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
            template_pack=template_pack,
            visibility=visibility,
            product_bundle=product_bundle,
            is_default=True,
        )
        created += 1

    # キャラクター設定（役割・口調・禁止台詞・掛け合い）を分離して投入する。
    try:
        from core.character_profiles_seed import seed_character_profiles_for_profile
        char_created = seed_character_profiles_for_profile(profile_id, genre_profile)
        if char_created:
            _logger.info("[Seeder] %s にキャラクター設定を %d 件作成しました", profile_id, char_created)
    except Exception as e:
        _logger.error("[Seeder] %s のキャラクター設定 seed 失敗: %s", profile_id, e)
        raise

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
            if profile.genre_profile in {"zunkami", "food_trivia", "zundamon_kowai", "urban_legend"}:
                sync_quality_rules_for_profile(profile.profile_id, profile.genre_profile)
            results[profile.profile_id] = count
        except Exception as e:
            _logger.error(
                "[Seeder] %s のシード失敗: %s", profile.profile_id, e
            )
            results[profile.profile_id] = -1

    return results


def sync_quality_rules_for_profile(profile_id: str, genre_profile: str) -> int:
    """未移行のデフォルト台本・ネタ会議テンプレートへ現行品質ルールを同期する。"""
    from core.prompt_template_store import get_default_template, update_template

    updated = 0
    script_template = get_default_template(profile_id, "script")
    needs_script_sync = script_template is not None and (
        "説明密度・掛け合い品質ルール" not in script_template.script_rules
        or (
            genre_profile in {"zunkami", "food_trivia"}
            and "食べ物雑学専用の具体性" not in script_template.system_rules
        )
        or (
            genre_profile in {"zundamon_kowai", "urban_legend"}
            and "都市伝説専用の具体性" not in script_template.system_rules
        )
    )
    if needs_script_sync:
        update_template(
            script_template.template_id,
            profile_id,
            system_rules=_read_genre_file(genre_profile, "script_context.md"),
            script_rules=_load_common_script_rules(genre_profile),
        )
        updated += 1

    meeting_template = get_default_template(profile_id, "meeting")
    meeting_context = _read_genre_file(genre_profile, "meeting_context.md")
    if (
        meeting_template is not None
        and meeting_context
        and "説明密度の査定" not in meeting_template.system_rules
    ):
        update_template(
            meeting_template.template_id,
            profile_id,
            system_rules=meeting_context,
            meeting_rules=_load_common_meeting_rules(),
        )
        updated += 1

    if updated:
        _logger.info("[Seeder] %s の説明密度ルールを %d テンプレートへ同期しました", profile_id, updated)
    return updated
