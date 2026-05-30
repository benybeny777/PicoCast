"""
チャンネルプロファイル管理モジュール。

data/settings.db の channel_profiles テーブルで複数チャンネルを管理する。
active profile (is_active=1) が1件のみ存在し、
すべての出力パス / プロンプト / metadata.db はこの profile を基準に解決する。

将来の複数チャンネルUI対応を見据え、内部は複数 profile 対応で設計する。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_ROOT, "data", "settings.db")
_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# データクラス
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChannelProfile:
    profile_id: str
    channel_name: str
    channel_handle: str
    genre_profile: str
    output_root: str                       # 例: "output/food_trivia"
    default_hashtags: str = ""
    channel_theme: str = ""
    channel_accent_color: str = ""
    is_active: bool = False
    created_at: str = ""
    updated_at: str = ""

    @property
    def output_root_abs(self) -> str:
        """output_root の絶対パスを返す。"""
        if os.path.isabs(self.output_root):
            return self.output_root
        return os.path.join(_ROOT, self.output_root)

    @property
    def handle_normalized(self) -> str:
        h = self.channel_handle.strip()
        return h if h.startswith("@") else f"@{h}" if h else ""


# ─────────────────────────────────────────────────────────────────────────────
# 公開例外
# ─────────────────────────────────────────────────────────────────────────────

class ChannelProfileError(Exception):
    """チャンネルプロファイル操作の基底例外。"""


class NoActiveProfileError(ChannelProfileError):
    """アクティブプロファイルが未設定。"""


class ProfileNotFoundError(ChannelProfileError):
    """指定された profile_id が存在しない。"""


class ProfileValidationError(ChannelProfileError):
    """プロファイルのバリデーション失敗。"""


# ─────────────────────────────────────────────────────────────────────────────
# DB 操作
# ─────────────────────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_table(conn)
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_profiles (
            profile_id          TEXT PRIMARY KEY,
            channel_name        TEXT NOT NULL,
            channel_handle      TEXT NOT NULL DEFAULT '',
            genre_profile       TEXT NOT NULL,
            output_root         TEXT NOT NULL,
            default_hashtags    TEXT NOT NULL DEFAULT '',
            channel_theme       TEXT NOT NULL DEFAULT '',
            channel_accent_color TEXT NOT NULL DEFAULT '',
            is_active           INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """)
    conn.commit()


def _row_to_profile(row: sqlite3.Row) -> ChannelProfile:
    return ChannelProfile(
        profile_id=row["profile_id"],
        channel_name=row["channel_name"],
        channel_handle=row["channel_handle"],
        genre_profile=row["genre_profile"],
        output_root=row["output_root"],
        default_hashtags=row["default_hashtags"] or "",
        channel_theme=row["channel_theme"] or "",
        channel_accent_color=row["channel_accent_color"] or "",
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────────────────────────────────────

def get_active_profile() -> ChannelProfile | None:
    """アクティブプロファイルを返す。未設定なら None。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT * FROM channel_profiles WHERE is_active=1 LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    return _row_to_profile(row) if row else None


def require_active_profile() -> ChannelProfile:
    """
    アクティブプロファイルを返す。
    未設定なら NoActiveProfileError を送出する（fail closed）。
    フォールバックで food_trivia や default を使わない。
    """
    profile = get_active_profile()
    if profile is None:
        raise NoActiveProfileError(
            "アクティブなチャンネルプロファイルが設定されていません。"
            "設定画面の「チャンネル」から profile を作成してください。"
        )
    return profile


def list_profiles() -> list[ChannelProfile]:
    """全プロファイルを返す（is_active=1 が先頭）。"""
    with _lock:
        conn = _open_db()
        try:
            rows = conn.execute(
                "SELECT * FROM channel_profiles ORDER BY is_active DESC, created_at ASC"
            ).fetchall()
        finally:
            conn.close()
    return [_row_to_profile(r) for r in rows]


def get_profile(profile_id: str) -> ChannelProfile | None:
    """profile_id で1件取得する。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT * FROM channel_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
        finally:
            conn.close()
    return _row_to_profile(row) if row else None


def save_profile(profile: ChannelProfile) -> None:
    """プロファイルを保存する（新規 or 上書き）。バリデーション後に保存。"""
    validate_profile(profile)
    now = _now_iso()
    with _lock:
        conn = _open_db()
        try:
            existing = conn.execute(
                "SELECT created_at FROM channel_profiles WHERE profile_id=?",
                (profile.profile_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing else (profile.created_at or now)
            conn.execute(
                """
                INSERT INTO channel_profiles
                    (profile_id, channel_name, channel_handle, genre_profile,
                     output_root, default_hashtags, channel_theme, channel_accent_color,
                     is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    channel_name        = excluded.channel_name,
                    channel_handle      = excluded.channel_handle,
                    genre_profile       = excluded.genre_profile,
                    output_root         = excluded.output_root,
                    default_hashtags    = excluded.default_hashtags,
                    channel_theme       = excluded.channel_theme,
                    channel_accent_color = excluded.channel_accent_color,
                    updated_at          = excluded.updated_at
                """,
                (
                    profile.profile_id, profile.channel_name, profile.channel_handle,
                    profile.genre_profile, profile.output_root,
                    profile.default_hashtags, profile.channel_theme,
                    profile.channel_accent_color, int(profile.is_active),
                    created_at, now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    _logger.info("[ChannelProfile] 保存: %s", profile.profile_id)


def activate_profile(profile_id: str) -> None:
    """
    指定 profile_id をアクティブにし、他はすべて非アクティブにする。
    存在しない profile_id は ProfileNotFoundError。
    """
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT 1 FROM channel_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
            if row is None:
                raise ProfileNotFoundError(f"プロファイルが存在しません: {profile_id}")
            conn.execute("UPDATE channel_profiles SET is_active=0")
            conn.execute(
                "UPDATE channel_profiles SET is_active=1, updated_at=? WHERE profile_id=?",
                (_now_iso(), profile_id),
            )
            conn.commit()
        finally:
            conn.close()
    _logger.info("[ChannelProfile] アクティブ変更: %s", profile_id)


def delete_profile(profile_id: str, confirmed: bool = False) -> None:
    """プロファイルを削除する。confirmed=True 必須。アクティブ profile は削除不可。"""
    if not confirmed:
        raise ChannelProfileError("confirmed=True が必要です")
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT is_active FROM channel_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
            if row is None:
                raise ProfileNotFoundError(f"プロファイルが存在しません: {profile_id}")
            if row["is_active"]:
                raise ChannelProfileError("アクティブなプロファイルは削除できません。先に別のプロファイルをアクティブにしてください。")
            conn.execute("DELETE FROM channel_profiles WHERE profile_id=?", (profile_id,))
            conn.commit()
        finally:
            conn.close()
    _logger.info("[ChannelProfile] 削除: %s", profile_id)


def validate_profile(profile: ChannelProfile) -> None:
    """
    プロファイルの必須フィールドを検証する。
    不正な場合は ProfileValidationError を送出する。
    """
    errors: list[str] = []

    if not profile.profile_id:
        errors.append("profile_id は必須です")
    elif not re.match(r"^[a-z0-9_-]{1,50}$", profile.profile_id):
        errors.append("profile_id は英小文字・数字・アンダースコア・ハイフン 1〜50 文字にしてください")

    if not profile.channel_name:
        errors.append("channel_name は必須です")

    if not profile.genre_profile:
        errors.append("genre_profile は必須です")
    elif not re.match(r"^[a-z0-9_-]{1,50}$", profile.genre_profile):
        errors.append("genre_profile は英小文字・数字・アンダースコア・ハイフン 1〜50 文字にしてください")

    if not profile.output_root:
        errors.append("output_root は必須です")

    if profile.channel_accent_color and not re.match(
        r"^#[0-9a-fA-F]{6}$", profile.channel_accent_color
    ):
        errors.append("channel_accent_color は #RRGGBB 形式にしてください")

    if errors:
        raise ProfileValidationError("プロファイルのバリデーション失敗: " + "; ".join(errors))


# ─────────────────────────────────────────────────────────────────────────────
# 初回起動時の自動作成
# ─────────────────────────────────────────────────────────────────────────────

def ensure_initial_profile_from_env() -> ChannelProfile | None:
    """
    起動時に呼ぶ。既存の channel_profiles が0件の場合のみ、
    環境変数（元 .env 由来）から初期 profile を作成してアクティブにする。
    既存 profile があれば何もしない。

    Returns:
        作成した ChannelProfile、または None（既存 profile がある場合 / 情報不足の場合）
    """
    if list_profiles():
        return None  # 既存プロファイルがあれば skip

    from config import config
    channel_name = config.CHANNEL_NAME
    channel_handle = config.CHANNEL_HANDLE
    channel_theme = config.CHANNEL_THEME
    channel_accent_color = config.CHANNEL_ACCENT_COLOR
    default_hashtags = config.DEFAULT_HASHTAGS

    if not channel_name:
        _logger.info("[ChannelProfile] CHANNEL_NAME 未設定のため初期プロファイルを作成しません")
        return None

    # ハンドルまたはテーマから genre_profile を推定する
    genre_profile = _infer_genre_profile(channel_handle, channel_theme, channel_name)
    profile_id = genre_profile or "default"
    output_root = f"output/{profile_id}"

    profile = ChannelProfile(
        profile_id=profile_id,
        channel_name=channel_name,
        channel_handle=channel_handle or "",
        genre_profile=genre_profile or profile_id,
        output_root=output_root,
        default_hashtags=default_hashtags or "",
        channel_theme=channel_theme or "",
        channel_accent_color=channel_accent_color or "",
        is_active=True,
    )

    try:
        validate_profile(profile)
    except ProfileValidationError as e:
        _logger.warning("[ChannelProfile] 初期プロファイル作成スキップ: %s", e)
        return None

    save_profile(profile)
    activate_profile(profile_id)
    _logger.info(
        "[ChannelProfile] 既存設定から初期プロファイルを作成しました: %s (genre=%s)",
        profile_id, genre_profile,
    )
    return profile


def _infer_genre_profile(handle: str, theme: str, name: str) -> str:
    """
    ハンドル・テーマ・チャンネル名から genre_profile を推定する。
    確定できない場合は "default" を返す。
    """
    text = " ".join(filter(None, [handle, theme, name])).lower()
    if any(kw in text for kw in ("食べ物", "食", "料理", "food", "zunkami")):
        return "food_trivia"
    if any(kw in text for kw in ("都市伝説", "怖い", "ゾッ", "urban", "kowai", "legend")):
        return "urban_legend"
    return "default"
