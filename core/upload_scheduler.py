"""
YouTube アップロードスケジュール管理。
スロット: 毎日 0:00 / 7:00 / 12:00 / 19:00 (JST)
Shorts / Long は別管理 — 同一スロットに両方の投稿が可能。
永続化: output/upload_schedule_shorts.json / upload_schedule_long.json
"""
import json
import os
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
SLOTS = [0, 7, 12, 19]  # JST 時刻 (ソート済み)

_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
_SCHEDULE_FILES = {
    "shorts": os.path.join(_BASE, "upload_schedule_shorts.json"),
    "long":   os.path.join(_BASE, "upload_schedule_long.json"),
}


def _load(video_type: str) -> dict:
    path = _SCHEDULE_FILES[video_type]
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(data: dict, video_type: str):
    path = _SCHEDULE_FILES[video_type]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def assign_slots(count: int, video_type: str) -> list:
    """video_type ('shorts'|'long') の空きスロットを count 個返す。"""
    schedule = _load(video_type)
    used = set(schedule.keys())
    now = datetime.now(JST)
    result = []
    candidate = now.date()

    for _ in range(90):
        for hour in SLOTS:
            slot_dt = datetime(candidate.year, candidate.month, candidate.day,
                               hour, 0, 0, tzinfo=JST)
            if slot_dt <= now + timedelta(minutes=5):
                continue
            key = slot_dt.isoformat()
            if key not in used:
                result.append(slot_dt)
                used.add(key)
                if len(result) == count:
                    return result
        candidate += timedelta(days=1)

    return result


def mark_slot_used(slot_dt: datetime, title: str, video_type: str):
    """スロットを使用済みとして永続保存する。"""
    schedule = _load(video_type)
    schedule[slot_dt.isoformat()] = title
    _save(schedule, video_type)


def list_schedule() -> dict:
    """{"shorts": {...}, "long": {...}} で返す。"""
    return {vt: _load(vt) for vt in _SCHEDULE_FILES}


def format_slot(slot_dt: datetime) -> str:
    """表示用文字列 'YYYY/MM/DD HH:MM (JST)' を返す。"""
    return slot_dt.strftime("%Y/%m/%d %H:%M") + " (JST)"
