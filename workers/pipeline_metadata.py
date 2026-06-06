"""生成動画の説明文・タグ・クレジットを整形する処理。"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from typing import Any

from core.ng_words import apply_ng_word_replacements
from core.youtube_metadata import optimize_description, optimize_tags

_logger = logging.getLogger("yj.pipeline")


def strip_voicevox_credit(text: str) -> tuple[str, bool]:
    """手書きされたVOICEVOXクレジット行を除去する。"""
    lines = text.splitlines()
    cleaned = [
        line
        for line in lines
        if "VOICEVOX:" not in line and "使用音声合成" not in line
    ]
    return "\n".join(cleaned).strip(), len(cleaned) != len(lines)


def character_names_for_credits(
    script_items: Sequence[dict[str, Any]] | None = None,
) -> list[str]:
    """台本の登場順を保った重複なしのキャラクター名一覧を返す。"""
    names: list[str] = []
    seen: set[str] = set()
    for item in script_items or []:
        if item.get("type") != "dialogue":
            continue
        name = str(item.get("character") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def build_audio_credit_block(
    script_items: Sequence[dict[str, Any]] | None = None,
) -> str:
    """active profileと台本話者から音声クレジットを構築する。"""
    try:
        from core.channel_profile import get_active_profile
        from core.character_profile_store import build_character_credit_block

        profile = get_active_profile()
        return build_character_credit_block(
            profile.profile_id if profile else None,
            character_names_for_credits(script_items),
        )
    except Exception:
        _logger.error("音声クレジット表記の生成に失敗しました", exc_info=True)
        raise


def build_channel_footer() -> str:
    """active profileのチャンネル情報から説明文フッターを返す。"""
    from core.channel_info import get_channel_info

    info = get_channel_info()
    channel_url = f"https://www.youtube.com/{info['handle']}"
    hashtags = (info.get("hashtags") or "").strip()
    footer = (
        "\n\n"
        "👍 いいね＆チャンネル登録お願いします！\n"
        "💬 感想はコメントで！\n"
        "🔔 通知オンで見逃しなし！\n"
        f"\n▶ チャンネル登録はこちら → {channel_url}\n"
    )
    if hashtags:
        footer += f"\n{hashtags}"
    return footer


def normalize_metadata(
    meta: dict[str, Any],
    is_shorts: bool,
    topic: str,
    update_status: Callable[..., None],
    script_items: Sequence[dict[str, Any]] | None = None,
) -> None:
    """説明文とタグを正規化し、辞書をインプレース更新する。"""
    if "description" in meta:
        description, stripped = strip_voicevox_credit(
            str(meta["description"]).rstrip()
        )
        if stripped:
            update_status("  説明文の手書きVOICEVOXクレジットを自動除去しました")
        description = re.sub(r"#\S+", "", description).strip()
        description = optimize_description(
            apply_ng_word_replacements(description),
            is_shorts=is_shorts,
            keep_hashtags=False,
        )
        meta["description"] = (
            description
            + build_audio_credit_block(script_items)
            + build_channel_footer()
        )
    if "tags" in meta:
        meta["tags"] = optimize_tags(
            meta["tags"],
            title=meta.get("video_title", topic),
            description=meta.get("description", ""),
        )
