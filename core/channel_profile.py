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
import shutil
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

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
    output_root: str                       # profile_id と同じ値を保存する
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
        if self.output_root == self.profile_id:
            return os.path.join(_ROOT, "output", self.profile_id)
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
    _migrate_profile_ids_to_handles(conn)
    conn.execute("UPDATE channel_profiles SET output_root = profile_id WHERE output_root != profile_id")
    _copy_legacy_default_secrets(conn)
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


def profile_id_from_handle(channel_handle: str) -> str:
    """チャンネルハンドルから profile_id を作る（@なし・小文字）。"""
    handle = channel_handle.strip()
    if handle.startswith("@"):
        handle = handle[1:]
    return handle.strip().lower()


def _migrate_profile_ids_to_handles(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT profile_id, channel_handle FROM channel_profiles").fetchall()
    for row in rows:
        old_id = row["profile_id"]
        new_id = profile_id_from_handle(row["channel_handle"] or "")
        if not new_id:
            continue
        if not re.match(r"^[a-z0-9_-]{1,50}$", new_id):
            _logger.warning("[ChannelProfile] profile_id移行スキップ: handle=%s", row["channel_handle"])
            continue

        old_row = conn.execute(
            "SELECT genre_profile FROM channel_profiles WHERE profile_id=?", (old_id,)
        ).fetchone()
        source_genre = old_row["genre_profile"] if old_row else ""
        _ensure_handle_genre_profile(source_genre, new_id)

        if new_id != old_id:
            conflict = conn.execute(
                "SELECT 1 FROM channel_profiles WHERE profile_id=?", (new_id,)
            ).fetchone()
            if conflict:
                _logger.warning("[ChannelProfile] profile_id移行スキップ: %s -> %s は既存です", old_id, new_id)
                continue

            conn.execute(
                "UPDATE channel_profiles SET profile_id=?, output_root=?, genre_profile=? WHERE profile_id=?",
                (new_id, new_id, new_id, old_id),
            )
            for table in ("encrypted_secrets", "bgm_assets", "channel_schedule_settings"):
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if exists:
                    conn.execute(f"UPDATE {table} SET profile_id=? WHERE profile_id=?", (new_id, old_id))
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prompt_templates'"
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE prompt_templates SET profile_id=?, genre_profile=? WHERE profile_id=?",
                    (new_id, new_id, old_id),
                )
            _migrate_output_dir(old_id, new_id)
            _logger.info("[ChannelProfile] profile_id移行: %s -> %s", old_id, new_id)
        elif source_genre != new_id:
            conn.execute(
                "UPDATE channel_profiles SET output_root=?, genre_profile=? WHERE profile_id=?",
                (new_id, new_id, old_id),
            )
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prompt_templates'"
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE prompt_templates SET genre_profile=? WHERE profile_id=?",
                    (new_id, old_id),
                )
            _logger.info("[ChannelProfile] genre_profile移行: %s -> %s", source_genre, new_id)


def _ensure_handle_genre_profile(source_genre: str, target_genre: str) -> None:
    """handle 名の genre_profile フォルダがなければ既存 genre からコピーする。"""
    if not target_genre:
        return
    genres_dir = os.path.join(_ROOT, "config", "prompt_profiles", "genres")
    target_dir = os.path.join(genres_dir, target_genre)
    if os.path.isdir(target_dir):
        return
    source_dir = os.path.join(genres_dir, source_genre)
    if not source_genre or not os.path.isdir(source_dir):
        return
    shutil.copytree(source_dir, target_dir)
    _logger.info("[ChannelProfile] genre_profileフォルダ作成: %s <- %s", target_genre, source_genre)


def _migrate_output_dir(old_id: str, new_id: str) -> None:
    old_path = os.path.join(_ROOT, "output", old_id)
    new_path = os.path.join(_ROOT, "output", new_id)
    if not os.path.isdir(old_path) or os.path.exists(new_path):
        return
    os.replace(old_path, new_path)


def _copy_legacy_default_secrets(conn: sqlite3.Connection) -> None:
    """
    旧仕様で default に保存されていた共通認証情報を各 profile へコピーする。
    値は復号せず、暗号化済み blob をそのまま複製する。
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='encrypted_secrets'"
    ).fetchone()
    if not exists:
        return
    profiles = [r["profile_id"] for r in conn.execute("SELECT profile_id FROM channel_profiles").fetchall()]
    if not profiles:
        return
    legacy_types = ("google_api_key", "openai_api_key", "hf_token", "youtube_client_secrets")
    placeholders = ",".join("?" * len(legacy_types))
    rows = conn.execute(
        f"""
        SELECT secret_type, encrypted_value, nonce, salt, key_version, created_at, updated_at
        FROM encrypted_secrets
        WHERE profile_id='default' AND secret_type IN ({placeholders})
        """,
        legacy_types,
    ).fetchall()
    now = _now_iso()
    for profile_id in profiles:
        for row in rows:
            found = conn.execute(
                "SELECT 1 FROM encrypted_secrets WHERE profile_id=? AND secret_type=?",
                (profile_id, row["secret_type"]),
            ).fetchone()
            if found:
                continue
            secret_id = hashlib.sha256(f"{profile_id}:{row['secret_type']}".encode()).hexdigest()[:32]
            conn.execute(
                """
                INSERT INTO encrypted_secrets(
                    secret_id, profile_id, secret_type, encrypted_value, nonce,
                    salt, key_version, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    secret_id,
                    profile_id,
                    row["secret_type"],
                    row["encrypted_value"],
                    row["nonce"],
                    row["salt"],
                    row["key_version"],
                    row["created_at"] or now,
                    now,
                ),
            )


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
    source_genre = profile.genre_profile
    profile.profile_id = profile_id_from_handle(profile.channel_handle)
    profile.output_root = profile.profile_id
    profile.genre_profile = profile.profile_id
    _ensure_handle_genre_profile(source_genre, profile.genre_profile)
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
    try:
        from core.channel_schedule import ensure_profile_schedule
        ensure_profile_schedule(profile.profile_id)
    except Exception:
        _logger.exception("[ChannelProfile] 投稿予約スロット初期化失敗: %s", profile.profile_id)
        raise


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
    try:
        from core.channel_schedule import delete_schedule
        delete_schedule(profile_id)
    except Exception:
        _logger.exception("[ChannelProfile] 投稿予約スロット削除失敗: %s", profile_id)
        raise


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

    if not profile.channel_handle:
        errors.append("channel_handle は必須です")

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


