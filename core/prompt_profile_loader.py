"""
プロンプトプロファイルローダー。

config/prompt_profiles/genres/{genre_profile}/ のファイルを読む。
ローカル上書き (local/) は廃止済み。テンプレートの編集は DB (prompt_templates) で行う。

主な用途: 起動時の seed（prompt_template_seeder.py から呼ばれる）。
実行時のプロンプト組み立ては core/script_prompts.py が DB から直接行う。

genre_profile が存在しない場合はエラー停止。別ジャンルへのフォールバック禁止。
"""
from __future__ import annotations

import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_PROFILES_DIR = _PROJECT_ROOT / "config" / "prompt_profiles"
_GENRES_DIR = _PROFILES_DIR / "genres"


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
# ファイル読み込み（genres/ のみ）
# ─────────────────────────────────────────────────────────────────────────────

def _read_genre_file(genre_profile: str, filename: str, required: bool = True) -> str:
    """genres/{genre_profile}/{filename} を読む。required=True で存在しなければ FileNotFoundError。"""
    path = _GENRES_DIR / genre_profile / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    if required:
        raise FileNotFoundError(
            f"プロンプトファイルが見つかりません: genres/{genre_profile}/{filename}"
        )
    return ""


def _read_genre_file_optional(genre_profile: str, filename: str) -> str:
    return _read_genre_file(genre_profile, filename, required=False)


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


def get_used_topics_text(genre_profile: str) -> str:
    """genres/{genre_profile}/used_topics.txt の内容を返す（ない場合は空文字）。"""
    return _read_genre_file_optional(genre_profile, "used_topics.txt")


# ─────────────────────────────────────────────────────────────────────────────
# seed 用ファイル読み込み（prompt_template_seeder.py から呼ばれる）
# ─────────────────────────────────────────────────────────────────────────────

def build_script_prompt_context(genre_profile: str) -> str:
    """genres/{genre_profile}/script_context.md を返す（seed 用）。"""
    validate_genre_profile_exists(genre_profile)
    return _read_genre_file(genre_profile, "script_context.md")


def build_title_prompt_context(genre_profile: str) -> str:
    """genres/{genre_profile}/title_context.md を返す（seed 用）。"""
    validate_genre_profile_exists(genre_profile)
    return _read_genre_file(genre_profile, "title_context.md")


def build_meeting_prompt_context(genre_profile: str) -> str:
    """genres/{genre_profile}/meeting_context.md を返す（seed 用）。"""
    validate_genre_profile_exists(genre_profile)
    return _read_genre_file_optional(genre_profile, "meeting_context.md")
