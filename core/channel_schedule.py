"""
チャンネル別の投稿予約スロット設定。

data/settings.db の channel_schedule_settings テーブルで、profile_id ごとに
Shorts / Long の投稿予約時刻とタイムゾーンを管理する。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import config as _cfg

from core.runtime_env import settings_db_path as _settings_db_path
_DB_PATH = _settings_db_path()
_lock = threading.Lock()

_MIGRATION_KEY = "upload_slots_20260606_1221_22"
# Shorts 既定を 21:00 1枠へ集約（config.SHORTS_UPLOAD_SLOT_HOURS の変更を既存チャンネルへ反映）
_SHORTS_SLOT_MIGRATION_KEY = "upload_slots_20260623_shorts_21"


@dataclass
class ChannelSchedule:
    profile_id: str
    timezone_name: str
    shorts_slot_hours: tuple[int, ...]
    long_slot_hours: tuple[int, ...]
    created_at: str = ""
    updated_at: str = ""

    @property
    def shorts_times(self) -> list[str]:
        return [_hour_to_time(h) for h in self.shorts_slot_hours]

    @property
    def long_times(self) -> list[str]:
        return [_hour_to_time(h) for h in self.long_slot_hours]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_schedule(profile_id: str) -> ChannelSchedule:
    return ChannelSchedule(
        profile_id=profile_id,
        timezone_name=_cfg.UPLOAD_TIMEZONE,
        shorts_slot_hours=tuple(_cfg.SHORTS_UPLOAD_SLOT_HOURS),
        long_slot_hours=tuple(_cfg.LONG_UPLOAD_SLOT_HOURS),
    )


def _hour_to_time(hour: int) -> str:
    return f"{int(hour):02d}:00"


def _hours_to_text(hours: tuple[int, ...]) -> str:
    return ",".join(_hour_to_time(h) for h in hours)


def _parse_hours(value) -> tuple[int, ...]:
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace("、", ",").split(",")]
    else:
        parts = [str(p).strip() for p in value]
    hours: list[int] = []
    for part in parts:
        if not part:
            continue
        hour_text = part.split(":", 1)[0].strip()
        hour = int(hour_text)
        if hour < 0 or hour > 23:
            raise ValueError("投稿予約時刻は 0〜23 時で指定してください")
        if hour not in hours:
            hours.append(hour)
    if not hours:
        raise ValueError("投稿予約スロットは1件以上必要です")
    return tuple(hours)


def _validate_timezone(timezone_name: str) -> str:
    name = str(timezone_name or "").strip() or _cfg.UPLOAD_TIMEZONE
    if name == "Asia/Tokyo":
        return name
    try:
        ZoneInfo(name)
    except Exception as e:
        raise ValueError(f"タイムゾーンが不正です: {name}") from e
    return name


def _open_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_table(conn)
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_schedule_settings (
            profile_id          TEXT PRIMARY KEY,
            timezone_name       TEXT NOT NULL,
            shorts_slot_hours   TEXT NOT NULL,
            long_slot_hours     TEXT NOT NULL,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_schedule_migrations (
            migration_key TEXT PRIMARY KEY,
            applied_at    TEXT NOT NULL
        )
    """)
    _apply_default_slot_migration(conn)
    _apply_shorts_slot_migration(conn)
    conn.commit()


def _apply_default_slot_migration(conn: sqlite3.Connection) -> None:
    has_profiles = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='channel_profiles'"
    ).fetchone()
    if not has_profiles:
        return
    done = conn.execute(
        "SELECT 1 FROM channel_schedule_migrations WHERE migration_key=?",
        (_MIGRATION_KEY,),
    ).fetchone()
    if done:
        return
    rows = conn.execute("SELECT profile_id FROM channel_profiles").fetchall()
    now = _now_iso()
    for row in rows:
        default = _default_schedule(row["profile_id"])
        conn.execute(
            """
            INSERT INTO channel_schedule_settings(
                profile_id, timezone_name, shorts_slot_hours, long_slot_hours,
                created_at, updated_at
            )
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(profile_id) DO UPDATE SET
                timezone_name=excluded.timezone_name,
                shorts_slot_hours=excluded.shorts_slot_hours,
                long_slot_hours=excluded.long_slot_hours,
                updated_at=excluded.updated_at
            """,
            (
                default.profile_id,
                default.timezone_name,
                _hours_to_text(default.shorts_slot_hours),
                _hours_to_text(default.long_slot_hours),
                now,
                now,
            ),
        )
    conn.execute(
        "INSERT INTO channel_schedule_migrations(migration_key, applied_at) VALUES(?,?)",
        (_MIGRATION_KEY, now),
    )


def _apply_shorts_slot_migration(conn: sqlite3.Connection) -> None:
    """既存全チャンネルの Shorts スロットを config 既定（21:00）へ更新する。

    config.SHORTS_UPLOAD_SLOT_HOURS の既定変更は新規チャンネルにしか効かないため、
    既存の channel_schedule_settings 全行を新既定で上書きする一度きりの移行。
    """
    done = conn.execute(
        "SELECT 1 FROM channel_schedule_migrations WHERE migration_key=?",
        (_SHORTS_SLOT_MIGRATION_KEY,),
    ).fetchone()
    if done:
        return
    shorts_text = _hours_to_text(tuple(_cfg.SHORTS_UPLOAD_SLOT_HOURS))
    now = _now_iso()
    conn.execute(
        "UPDATE channel_schedule_settings SET shorts_slot_hours=?, updated_at=?",
        (shorts_text, now),
    )
    conn.execute(
        "INSERT INTO channel_schedule_migrations(migration_key, applied_at) VALUES(?,?)",
        (_SHORTS_SLOT_MIGRATION_KEY, now),
    )


def _row_to_schedule(row: sqlite3.Row) -> ChannelSchedule:
    return ChannelSchedule(
        profile_id=row["profile_id"],
        timezone_name=row["timezone_name"],
        shorts_slot_hours=_parse_hours(row["shorts_slot_hours"]),
        long_slot_hours=_parse_hours(row["long_slot_hours"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def initialize() -> None:
    with _lock:
        conn = _open_db()
        try:
            conn.commit()
        finally:
            conn.close()


def ensure_profile_schedule(profile_id: str) -> ChannelSchedule:
    with _lock:
        conn = _open_db()
        try:
            existing = conn.execute(
                "SELECT * FROM channel_schedule_settings WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
            if existing:
                return _row_to_schedule(existing)
            default = _default_schedule(profile_id)
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO channel_schedule_settings(
                    profile_id, timezone_name, shorts_slot_hours, long_slot_hours,
                    created_at, updated_at
                )
                VALUES(?,?,?,?,?,?)
                """,
                (
                    default.profile_id,
                    default.timezone_name,
                    _hours_to_text(default.shorts_slot_hours),
                    _hours_to_text(default.long_slot_hours),
                    now,
                    now,
                ),
            )
            conn.commit()
            return default
        finally:
            conn.close()


def get_schedule(profile_id: str | None = None) -> ChannelSchedule:
    if not profile_id:
        from core.channel_profile import require_active_profile
        profile_id = require_active_profile().profile_id
    return ensure_profile_schedule(profile_id)


def save_schedule(
    profile_id: str,
    *,
    timezone_name: str,
    shorts_slot_hours,
    long_slot_hours,
) -> ChannelSchedule:
    schedule = ChannelSchedule(
        profile_id=profile_id,
        timezone_name=_validate_timezone(timezone_name),
        shorts_slot_hours=_parse_hours(shorts_slot_hours),
        long_slot_hours=_parse_hours(long_slot_hours),
    )
    now = _now_iso()
    with _lock:
        conn = _open_db()
        try:
            conn.execute(
                """
                INSERT INTO channel_schedule_settings(
                    profile_id, timezone_name, shorts_slot_hours, long_slot_hours,
                    created_at, updated_at
                )
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    timezone_name=excluded.timezone_name,
                    shorts_slot_hours=excluded.shorts_slot_hours,
                    long_slot_hours=excluded.long_slot_hours,
                    updated_at=excluded.updated_at
                """,
                (
                    schedule.profile_id,
                    schedule.timezone_name,
                    _hours_to_text(schedule.shorts_slot_hours),
                    _hours_to_text(schedule.long_slot_hours),
                    now,
                    now,
                ),
            )
            conn.commit()
            return schedule
        finally:
            conn.close()


def delete_schedule(profile_id: str) -> None:
    with _lock:
        conn = _open_db()
        try:
            conn.execute("DELETE FROM channel_schedule_settings WHERE profile_id=?", (profile_id,))
            conn.commit()
        finally:
            conn.close()


def schedule_to_dict(schedule: ChannelSchedule) -> dict:
    return {
        "profile_id": schedule.profile_id,
        "timezone": schedule.timezone_name,
        "shorts_slot_hours": list(schedule.shorts_slot_hours),
        "long_slot_hours": list(schedule.long_slot_hours),
        "shorts_times": schedule.shorts_times,
        "long_times": schedule.long_times,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }
