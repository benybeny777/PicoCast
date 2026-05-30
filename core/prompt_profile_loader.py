"""
プロンプトプロファイルローダー。

config/prompt_profiles/ の以下の順でファイルを読み込み、プロンプト文字列を組み立てる。

  1. config/prompt_profiles/genres/{genre_profile}/  (必須)
  2. config/prompt_profiles/local/{genre_profile}/   (任意・git管理外)

common/ の共通ルールは core/script_prompts.py の定数として持つ（COMMON_SCRIPT_RULES 等）。
genre_profile が存在しない場合はエラー停止。別ジャンルへのフォールバック禁止。

使い方:
  from core.prompt_profile_loader import load_prompt_profile, build_script_prompt_context
  from core.channel_profile import require_active_profile

  profile = require_active_profile()
  prompt = build_script_prompt_context(profile)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_PROFILES_DIR = _PROJECT_ROOT / "config" / "prompt_profiles"
_GENRES_DIR = _PROFILES_DIR / "genres"
_LOCAL_DIR = _PROFILES_DIR / "local"


# ─────────────────────────────────────────────────────────────────────────────
# 公開例外
# ─────────────────────────────────────────────────────────────────────────────

class GenreProfileNotFoundError(Exception):
    """genres/{genre_profile}/ ディレクトリが存在しない。"""


# ─────────────────────────────────────────────────────────────────────────────
# genre profile 存在チェック
# ─────────────────────────────────────────────────────────────────────────────

def validate_genre_profile_exists(genre_profile: str) -> None:
    """
    genres/{genre_profile}/ が存在するか確認する。
    存在しない場合は GenreProfileNotFoundError。別ジャンルへのフォールバック禁止。
    """
    genre_dir = _GENRES_DIR / genre_profile
    if not genre_dir.is_dir():
        available = [d.name for d in _GENRES_DIR.iterdir() if d.is_dir()] if _GENRES_DIR.is_dir() else []
        raise GenreProfileNotFoundError(
            f"genre_profile '{genre_profile}' が見つかりません。"
            f"config/prompt_profiles/genres/ に '{genre_profile}/' ディレクトリを作成してください。"
            f"利用可能: {available}"
        )


def list_available_genre_profiles() -> list[str]:
    """利用可能な genre_profile 名のリストを返す。"""
    if not _GENRES_DIR.is_dir():
        return []
    return sorted(d.name for d in _GENRES_DIR.iterdir() if d.is_dir())


# ─────────────────────────────────────────────────────────────────────────────
# ファイル読み込み
# ─────────────────────────────────────────────────────────────────────────────

def _get_active_profile_id() -> str | None:
    """active profile の profile_id を返す。取得失敗なら None。"""
    try:
        from core.channel_profile import get_active_profile
        p = get_active_profile()
        return p.profile_id if p else None
    except Exception:
        return None


def _read_genre_file(genre_profile: str, filename: str, required: bool = True) -> str:
    """
    genres/{genre_profile}/{filename} を読む。
    優先順位:
      1. local/{profile_id}/{filename}  (active profile_id 別上書き)
      2. local/{genre_profile}/{filename} (genre 別上書き)
      3. genres/{genre_profile}/{filename} (正規)
    required=True で見つからない場合は FileNotFoundError。
    """
    genre_path = _GENRES_DIR / genre_profile / filename

    # 1. local/{profile_id}/
    profile_id = _get_active_profile_id()
    if profile_id and profile_id != genre_profile:
        local_profile_path = _LOCAL_DIR / profile_id / filename
        if local_profile_path.exists():
            _logger.debug("[PromptLoader] local profile override: %s", local_profile_path)
            return local_profile_path.read_text(encoding="utf-8").strip()

    # 2. local/{genre_profile}/
    local_genre_path = _LOCAL_DIR / genre_profile / filename
    if local_genre_path.exists():
        _logger.debug("[PromptLoader] local genre override: %s", local_genre_path)
        return local_genre_path.read_text(encoding="utf-8").strip()

    # 3. genres/{genre_profile}/
    if genre_path.exists():
        return genre_path.read_text(encoding="utf-8").strip()

    if required:
        raise FileNotFoundError(
            f"プロンプトファイルが見つかりません: genres/{genre_profile}/{filename}"
        )
    return ""


def _read_genre_file_optional(genre_profile: str, filename: str) -> str:
    return _read_genre_file(genre_profile, filename, required=False)


def _read_local_override(genre_profile: str, filename: str = "overrides.md") -> str:
    """local/{genre_profile}/{filename} が存在すれば読む。なければ空文字。"""
    path = _LOCAL_DIR / genre_profile / filename
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


# ─────────────────────────────────────────────────────────────────────────────
# YAML-like な profile.yaml 読み取り（PyYAML 不要・シンプルパース）
# ─────────────────────────────────────────────────────────────────────────────

def load_genre_profile_config(genre_profile: str) -> dict[str, str]:
    """
    genres/{genre_profile}/profile.yaml を読み込み dict で返す。
    存在しない場合は空 dict。PyYAML 依存なしで key: value 形式をパース。
    """
    path = _GENRES_DIR / genre_profile / "profile.yaml"
    if not path.exists():
        return {}
    config: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            config[k.strip()] = v.strip().strip('"').strip("'")
    return config


def get_playlist_categories(genre_profile: str) -> tuple[str, ...]:
    """
    genres/{genre_profile}/playlist_categories.md からカテゴリ名のタプルを返す。
    「## 」で始まるヘッダーと空行・コメントを除いた行を返す。
    """
    raw = _read_genre_file_optional(genre_profile, "playlist_categories.md")
    if not raw:
        return ()
    categories = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        categories.append(stripped)
    return tuple(categories)


def get_default_hashtags(genre_profile: str, fallback: str = "") -> str:
    """genre profile の default_hashtags を返す。なければ fallback。"""
    config = load_genre_profile_config(genre_profile)
    return config.get("default_hashtags", fallback)


# ─────────────────────────────────────────────────────────────────────────────
# プロンプト組み立て
# ─────────────────────────────────────────────────────────────────────────────

def build_script_prompt_context(genre_profile: str) -> str:
    """
    台本生成プロンプトのジャンル固有部分を返す。
    genres/{genre_profile}/script_context.md を読む。
    local オーバーライドがあれば優先する。
    """
    validate_genre_profile_exists(genre_profile)
    return _read_genre_file(genre_profile, "script_context.md")


def build_title_prompt_context(genre_profile: str) -> str:
    """
    タイトル案プロンプトのジャンル固有部分を返す。
    genres/{genre_profile}/title_context.md を読む。
    """
    validate_genre_profile_exists(genre_profile)
    return _read_genre_file(genre_profile, "title_context.md")


def build_meeting_prompt_context(genre_profile: str) -> str:
    """
    ネタ会議プロンプトのジャンル固有部分を返す。
    genres/{genre_profile}/meeting_context.md を読む。
    """
    validate_genre_profile_exists(genre_profile)
    return _read_genre_file_optional(genre_profile, "meeting_context.md")


def get_local_override_text(genre_profile: str) -> str:
    """local/{genre_profile}/overrides.md の内容を返す（任意）。"""
    return _read_local_override(genre_profile)


def get_used_topics_text(genre_profile: str) -> str:
    """genres/{genre_profile}/used_topics.txt の内容を返す（ない場合は空文字）。"""
    return _read_genre_file_optional(genre_profile, "used_topics.txt")
