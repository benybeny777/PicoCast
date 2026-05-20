"""
YouTube upload schedule manager.

Shorts slots: 07:00 / 12:00 / 19:00 JST every day.
Long slots: 21:00 JST on weekdays, 12:00 / 21:00 JST on weekends.
Shorts and Long are tracked separately, so they may share the same time.
"""
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
SLOTS = [7, 12, 19]
LONG_SLOTS_WEEKDAY = [21]
LONG_SLOTS_WEEKEND = [12, 21]

VIDEO_TYPES = ("shorts", "long")


def _as_jst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def _parse_slot(iso: str) -> datetime:
    return _as_jst(datetime.fromisoformat(iso))


def _slot_hours(video_type: str, candidate) -> list[int]:
    if video_type == "long":
        return LONG_SLOTS_WEEKEND if candidate.weekday() in (5, 6) else LONG_SLOTS_WEEKDAY
    return SLOTS


def _assign_slots_from_used(
    count: int,
    video_type: str,
    used: set[str],
    now: datetime | None = None,
) -> list[datetime]:
    now = _as_jst(now or datetime.now(JST))
    result = []
    candidate = now.date()

    for _ in range(90):
        for hour in _slot_hours(video_type, candidate):
            slot_dt = datetime(
                candidate.year,
                candidate.month,
                candidate.day,
                hour,
                0,
                0,
                tzinfo=JST,
            )
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


def assign_slots(count: int, video_type: str) -> list[datetime]:
    """Return empty slots for video_type ('shorts'|'long')."""
    schedule = schedule_from_records().get(video_type, {})
    return _assign_slots_from_used(count, video_type, set(schedule.keys()))


def mark_slot_used(slot_dt: datetime, title: str, video_type: str):
    """Compatibility no-op. upload_records.json is the schedule source."""
    return None


def schedule_from_records(records: list[dict] | None = None) -> dict[str, dict]:
    """Build the derived schedule cache from upload_records data."""
    if records is None:
        from core.upload_records import load_upload_records

        records = load_upload_records()

    import logging

    schedules = {vt: {} for vt in VIDEO_TYPES}
    for record in records:
        vt = str(record.get("video_type") or "").lower()
        if vt not in schedules:
            continue
        if str(record.get("publish_status") or "").lower() != "scheduled":
            continue
        publish_at = str(record.get("publish_at") or "").strip()
        if not publish_at:
            continue
        try:
            iso = _parse_slot(publish_at.replace("Z", "+00:00")).isoformat()
        except Exception:
            continue
        title = str(record.get("title") or "").split("\n")[0].strip()
        if not title:
            continue
        if iso in schedules[vt]:
            logging.warning(
                "schedule_from_records: duplicate slot %s for %s (keeping %r, ignoring %r)",
                iso, vt, schedules[vt][iso], title,
            )
        else:
            schedules[vt][iso] = title
    return schedules


def build_rebalanced_schedule(
    schedule: dict,
    video_type: str,
    now: datetime | None = None,
) -> tuple[dict, list[tuple[str, str, str]]]:
    """Build a rebalanced schedule without saving it."""
    now = _as_jst(now or datetime.now(JST))
    cutoff = now + timedelta(minutes=5)

    fixed = {}
    future = []
    for iso, title in schedule.items():
        try:
            slot_dt = _parse_slot(iso)
        except Exception:
            fixed[iso] = title
            continue

        if slot_dt <= cutoff:
            fixed[iso] = title
        else:
            future.append((iso, title, slot_dt))

    future_sorted = [(iso, title) for iso, title, _dt in sorted(future, key=lambda item: item[2])]
    if not future_sorted:
        return dict(schedule), []

    new_slots = _assign_slots_from_used(len(future_sorted), video_type, set(fixed.keys()), now)
    if len(new_slots) != len(future_sorted):
        raise RuntimeError("Not enough available upload slots within 90 days.")

    new_schedule = dict(fixed)
    changes = []
    for (old_iso, title), new_dt in zip(future_sorted, new_slots):
        new_iso = new_dt.isoformat()
        new_schedule[new_iso] = title
        if old_iso != new_iso:
            changes.append((old_iso, new_iso, title))

    return new_schedule, changes


def rebalance_slots(video_type: str) -> list[tuple[str, str, str]]:
    """Compute changes needed to repack future slots. Does not write anything.
    The caller is responsible for applying each change to YouTube and upload_records."""
    schedule = schedule_from_records().get(video_type, {})
    _new_schedule, changes = build_rebalanced_schedule(schedule, video_type)
    return changes


def list_schedule() -> dict:
    """Return {"shorts": {...}, "long": {...}}."""
    return schedule_from_records()


def _title_key(value: str) -> str:
    value = str(value or "").split("\n")[0].strip()
    for prefix in ("[Shorts]", "[Long]", "[SHORT]", "[LONG]"):
        if value.startswith(prefix):
            return value[len(prefix):].strip().lower()
    return value.lower()


def _remove_schedule_entry(schedule: dict, iso: str | None, title: str):
    if not iso:
        return False
    current = schedule.get(iso)
    if current is None:
        return False
    if _title_key(current) != _title_key(title):
        return False
    schedule.pop(iso, None)
    return True


def sync_schedule_from_youtube(progress_callback=None) -> dict:
    """Use YouTube status as source of truth and update local records/schedules."""
    from core.upload_records import load_upload_records, save_upload_records
    from core.youtube_uploader import get_channel_upload_video_statuses, get_video_statuses

    def _log(message):
        if progress_callback:
            progress_callback(message)

    records = load_upload_records()
    id_to_record = {
        str(record.get("video_id") or "").strip(): record
        for record in records
        if str(record.get("video_id") or "").strip()
    }
    try:
        statuses = get_channel_upload_video_statuses()
    except Exception as _e:
        _log(f"チャンネル全件取得失敗、既知IDのみでフォールバック: {_e}")
        statuses = get_video_statuses(list(id_to_record.keys()))
    now = datetime.now(JST)
    changed_records = 0
    scheduled = 0
    published = 0

    for video_id, status in statuses.items():
        record = id_to_record.get(video_id)
        if record is None:
            record = {
                "video_id": video_id,
                "title": status.get("title") or video_id,
                "video_type": status.get("video_type") or "long",
                "uploaded_at": status.get("publishedAt"),
            }
            records.append(record)
            id_to_record[video_id] = record

        vt = str(record.get("video_type") or "").lower()
        if not vt and status.get("video_type"):
            record["video_type"] = status.get("video_type")
            vt = record["video_type"]
        if vt not in VIDEO_TYPES:
            continue

        privacy = status.get("privacyStatus") or ""
        yt_publish_at = status.get("publishAt")
        before = dict(record)

        if privacy == "public":
            record["publish_status"] = "published"
            record["publish_at"] = None
            published_at = status.get("publishedAt")
            if published_at:
                try:
                    record["published_at"] = _parse_slot(str(published_at).replace("Z", "+00:00")).isoformat()
                except Exception:
                    record["published_at"] = published_at
            published += 1
        elif privacy == "private" and yt_publish_at:
            yt_dt = _parse_slot(str(yt_publish_at).replace("Z", "+00:00"))
            new_iso = yt_dt.isoformat()
            record["publish_at"] = new_iso
            record["publish_status"] = "scheduled" if yt_dt > now else "private"
            scheduled += 1
        else:
            record["publish_status"] = privacy or "unknown"
            record["publish_at"] = None

        if record != before:
            changed_records += 1

    if changed_records:
        save_upload_records(records)
    if changed_records:
        _log(f"YouTube sync: records={changed_records}")
    return {
        "checked": len(statuses),
        "scheduled": scheduled,
        "published": published,
        "changed": changed_records,
    }


def format_slot(slot_dt: datetime) -> str:
    """Return display text like 'YYYY/MM/DD HH:MM (JST)'."""
    return _as_jst(slot_dt).strftime("%Y/%m/%d %H:%M") + " (JST)"
