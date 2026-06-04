"""
キャラクター設定管理モジュール。

data/settings.db の character_profiles テーブルで、channel profile 別の
キャラクター設定（役割・口調・禁止台詞・掛け合いルール）を管理する。

台本テンプレート（prompt_templates）からキャラ設定を分離し、台本生成時に
有効なキャラクター設定を合成してプロンプトを作るための土台。

設計方針:
- profile_id（チャンネル）ごとに複数のキャラクター設定を持てる。
- enabled=1 のものだけを sort_order 順に合成する。
- 自動フォールバック禁止: 有効なキャラ設定が無いチャンネルでは合成側がエラーにする。
- 別チャンネルのキャラ設定を勝手に流用しない（profile_id で厳密に分離）。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_ROOT, "data", "settings.db")
_lock = threading.Lock()

_DDL = """
CREATE TABLE IF NOT EXISTS character_profiles (
    character_id      TEXT PRIMARY KEY,
    profile_id        TEXT NOT NULL,
    character_key     TEXT NOT NULL,
    display_name      TEXT NOT NULL,
    character_name    TEXT NOT NULL,
    role              TEXT NOT NULL DEFAULT '',
    tone_style        TEXT NOT NULL DEFAULT '',
    speaking_rules    TEXT NOT NULL DEFAULT '',
    forbidden_phrases TEXT NOT NULL DEFAULT '',
    dialogue_rules    TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 1,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(profile_id, character_key),
    FOREIGN KEY(profile_id) REFERENCES channel_profiles(profile_id)
);
"""


@dataclass(frozen=True)
class CharacterProfile:
    character_id: str
    profile_id: str
    character_key: str
    display_name: str
    character_name: str
    role: str
    tone_style: str
    speaking_rules: str
    forbidden_phrases: str
    dialogue_rules: str
    enabled: bool
    sort_order: int
    created_at: str
    updated_at: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "CharacterProfile":
        return CharacterProfile(
            character_id=row["character_id"],
            profile_id=row["profile_id"],
            character_key=row["character_key"],
            display_name=row["display_name"],
            character_name=row["character_name"],
            role=row["role"],
            tone_style=row["tone_style"],
            speaking_rules=row["speaking_rules"],
            forbidden_phrases=row["forbidden_phrases"],
            dialogue_rules=row["dialogue_rules"],
            enabled=bool(row["enabled"]),
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _open_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    for stmt in _DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def has_characters(profile_id: str) -> bool:
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT 1 FROM character_profiles WHERE profile_id=? LIMIT 1", (profile_id,)
            ).fetchone()
        finally:
            conn.close()
    return row is not None


def list_characters(profile_id: str, *, enabled_only: bool = False) -> list[CharacterProfile]:
    with _lock:
        conn = _open_db()
        try:
            sql = "SELECT * FROM character_profiles WHERE profile_id=?"
            if enabled_only:
                sql += " AND enabled=1"
            sql += " ORDER BY sort_order, character_key"
            rows = conn.execute(sql, (profile_id,)).fetchall()
        finally:
            conn.close()
    return [CharacterProfile.from_row(r) for r in rows]


def create_character(
    *,
    profile_id: str,
    character_key: str,
    display_name: str,
    character_name: str,
    role: str = "",
    tone_style: str = "",
    speaking_rules: str = "",
    forbidden_phrases: str = "",
    dialogue_rules: str = "",
    enabled: bool = True,
    sort_order: int = 0,
) -> str:
    """キャラクター設定を作成する。戻り値は character_id。"""
    character_id = str(uuid.uuid4())
    now = _now()
    with _lock:
        conn = _open_db()
        try:
            if enabled:
                conn.execute(
                    """
                    UPDATE character_profiles
                       SET enabled=0, updated_at=?
                     WHERE profile_id=? AND character_name=? AND character_id<>?
                    """,
                    (now, profile_id, character_name, character_id),
                )
            conn.execute(
                """
                INSERT INTO character_profiles
                    (character_id, profile_id, character_key, display_name, character_name,
                     role, tone_style, speaking_rules, forbidden_phrases, dialogue_rules,
                     enabled, sort_order, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (character_id, profile_id, character_key, display_name, character_name,
                 role, tone_style, speaking_rules, forbidden_phrases, dialogue_rules,
                 1 if enabled else 0, sort_order, now, now),
            )
            conn.commit()
        finally:
            conn.close()
    return character_id


def _update_character_locked(conn: sqlite3.Connection, character_id: str, **fields) -> None:
    """conn と _lock を保持した状態でキャラクター設定を更新する。"""
    allowed = {
        "display_name", "character_name", "role", "tone_style", "speaking_rules",
        "forbidden_phrases", "dialogue_rules", "enabled", "sort_order",
    }
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    if "enabled" in sets:
        sets["enabled"] = 1 if sets["enabled"] else 0
    cols = ", ".join(f"{k}=?" for k in sets)
    vals = list(sets.values()) + [_now(), character_id]
    conn.execute(f"UPDATE character_profiles SET {cols}, updated_at=? WHERE character_id=?", vals)


def update_character(character_id: str, **fields) -> None:
    """指定キャラクター設定のフィールドを更新する。"""
    if fields.get("enabled") is True:
        enable_fields = dict(fields)
        enable_fields.pop("enabled", None)
        enable_character_exclusive(character_id, **enable_fields)
        return
    with _lock:
        conn = _open_db()
        try:
            _update_character_locked(conn, character_id, **fields)
            conn.commit()
        finally:
            conn.close()


def enable_character_exclusive(character_id: str, **fields) -> None:
    """指定キャラクターを有効化し、同一 profile・同一 character_name の他設定を無効化する。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT profile_id, character_name FROM character_profiles WHERE character_id=?",
                (character_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("キャラクター設定が見つかりません")
            update_fields = dict(fields)
            update_fields["enabled"] = True
            _update_character_locked(conn, character_id, **update_fields)
            updated = conn.execute(
                "SELECT profile_id, character_name FROM character_profiles WHERE character_id=?",
                (character_id,),
            ).fetchone()
            profile_id = updated["profile_id"]
            character_name = updated["character_name"]
            now = _now()
            conn.execute(
                """
                UPDATE character_profiles
                   SET enabled=0, updated_at=?
                 WHERE profile_id=? AND character_name=? AND character_id<>?
                """,
                (now, profile_id, character_name, character_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            _logger.error("キャラクター設定の排他有効化に失敗: character_id=%s", character_id, exc_info=True)
            raise
        finally:
            conn.close()


def set_enabled(character_id: str, enabled: bool) -> None:
    if enabled:
        enable_character_exclusive(character_id)
    else:
        update_character(character_id, enabled=False)


def delete_character(character_id: str) -> None:
    with _lock:
        conn = _open_db()
        try:
            conn.execute("DELETE FROM character_profiles WHERE character_id=?", (character_id,))
            conn.commit()
        finally:
            conn.close()
