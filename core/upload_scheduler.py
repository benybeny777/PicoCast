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
SCHEDULED_STATUSES = {"", "scheduled", "unlisted", "private"}
NOT_SCHEDULED_STATUSES = {"published", "public", "manual_published", "deleted", "failed"}


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


def _is_scheduled_record(record: dict) -> bool:
    status = str(record.get("publish_status") or "").lower()
    privacy = str(record.get("privacy_status") or record.get("privacyStatus") or "").lower()
    if status in NOT_SCHEDULED_STATUSES or privacy in {"public"}:
        return False
    if not str(record.get("publish_at") or "").strip():
        return False
    return status in SCHEDULED_STATUSES or privacy == "unlisted"


def _has_generation_kind(value) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() not in {"none", "null", "n/a", "na", "-"} and text not in {"なし", "未設定"}


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


def assign_slots_from_youtube(count: int, video_type: str) -> list[datetime]:
    """Return empty slots using YouTube scheduled videos as the source of truth.

    Queries the channel's upload list and treats any private/unlisted video
    with a future publishAt of matching video_type as an occupied slot.
    Falls back to local records if the YouTube API call fails.
    """
    from core.youtube_uploader import get_channel_upload_video_statuses

    now = _as_jst(datetime.now(JST))
    used: set[str] = set()
    try:
        statuses = get_channel_upload_video_statuses()
        for _vid_id, status in statuses.items():
            privacy = str(status.get("privacyStatus") or "").lower()
            pub_at_raw = str(status.get("publishAt") or "").strip()
            vt = str(status.get("video_type") or "").lower()
            if vt != video_type:
                continue
            if privacy not in ("private", "unlisted") or not pub_at_raw:
                continue
            try:
                dt = _as_jst(datetime.fromisoformat(pub_at_raw.replace("Z", "+00:00")))
                if dt > now + timedelta(minutes=5):
                    used.add(dt.isoformat())
            except Exception:
                continue
    except Exception:
        schedule = schedule_from_records().get(video_type, {})
        used = set(schedule.keys())

    return _assign_slots_from_used(count, video_type, used, now)


def mark_slot_used(slot_dt: datetime, title: str, video_type: str):
    """Compatibility no-op. upload_records.json is the schedule source."""
    return None


def schedule_from_records(records: list[dict] | None = None) -> dict[str, dict]:
    """Build the derived schedule cache from upload_records data."""
    if records is None:
        from core.upload_records import load_upload_records

        records = load_upload_records()

    schedules = {vt: {} for vt in VIDEO_TYPES}
    for record in records:
        vt = str(record.get("video_type") or "").lower()
        if vt not in schedules:
            continue
        if not _is_scheduled_record(record):
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
        if iso not in schedules[vt]:
            schedules[vt][iso] = title
    return schedules


def build_rebalanced_schedule(
    schedule: dict,
    video_type: str,
    now: datetime | None = None,
    used_slots: set[str] | None = None,
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

    used = set(used_slots or set())
    used.update(fixed.keys())
    new_slots = _assign_slots_from_used(len(future_sorted), video_type, used, now)
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


def _scheduled_entries_from_records(records: list[dict], video_type: str) -> list[dict]:
    now = datetime.now(JST)
    entries = []
    for idx, record in enumerate(records):
        vt = str(record.get("video_type") or "").lower()
        if vt != video_type:
            continue
        if not _is_scheduled_record(record):
            continue
        publish_at = str(record.get("publish_at") or "").strip()
        if publish_at:
            try:
                iso = _parse_slot(publish_at.replace("Z", "+00:00")).isoformat()
                slot_dt = _parse_slot(iso)
            except Exception:
                continue
            if slot_dt <= now and str(record.get("publish_status") or "").lower() != "scheduled":
                continue
        else:
            continue
        title = str(record.get("title") or "").split("\n")[0].strip()
        if not title:
            title = str(record.get("video_id") or f"record-{idx}").strip()
        entries.append({
            "index": idx,
            "iso": iso,
            "slot_dt": slot_dt,
            "title": title,
            "video_id": str(record.get("video_id") or "").strip(),
            "generation_kind": str(record.get("generation_kind") or "").strip(),
        })
    return entries


def build_rebalanced_entries(
    entries: list[dict],
    video_type: str,
    now: datetime | None = None,
    include_video_id: bool = False,
    used_slots: set[str] | None = None,
    include_record_index: bool = False,
) -> list[tuple]:
    """Build rebalance changes from record entries, preserving duplicate slots."""
    now = _as_jst(now or datetime.now(JST))
    cutoff = now + timedelta(minutes=5)

    used = set(used_slots or set())
    future = []
    for entry in entries:
        slot_dt = entry["slot_dt"]
        iso = entry["iso"]
        if iso and slot_dt <= cutoff:
            used.add(iso)
        else:
            future.append(entry)

    future.sort(key=lambda item: (0 if _has_generation_kind(item.get("generation_kind")) else 1, item["slot_dt"], item["index"]))
    if not future:
        return []

    new_slots = _assign_slots_from_used(len(future), video_type, used, now)
    if len(new_slots) != len(future):
        raise RuntimeError("Not enough available upload slots within 90 days.")

    changes = []
    for entry, new_dt in zip(future, new_slots):
        old_iso = entry["iso"]
        new_iso = new_dt.isoformat()
        if old_iso != new_iso:
            if include_video_id:
                change = (old_iso, new_iso, entry["title"], entry.get("video_id") or "")
                if include_record_index:
                    change = (*change, entry.get("index"))
                changes.append(change)
            else:
                changes.append((old_iso, new_iso, entry["title"]))
    return changes


def rebalance_slots(video_type: str) -> list[tuple[str, str, str]]:
    """Compute changes needed to repack future slots. Does not write anything.
    The caller is responsible for applying each change to YouTube and upload_records."""
    from core.upload_records import load_upload_records

    records = load_upload_records()
    entries = _scheduled_entries_from_records(records, video_type)
    return build_rebalanced_entries(entries, video_type)


def rebalance_slots_detailed(video_type: str) -> list[tuple[str, str, str, str, int | None]]:
    """Like rebalance_slots(), with video_id and record index for unambiguous callers."""
    from core.upload_records import load_upload_records

    records = load_upload_records()
    entries = _scheduled_entries_from_records(records, video_type)
    return build_rebalanced_entries(
        entries,
        video_type,
        include_video_id=True,
        include_record_index=True,
    )


def count_rebalance_candidates(video_type: str) -> int:
    from core.upload_records import load_upload_records

    return len(_scheduled_entries_from_records(load_upload_records(), video_type))


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
    seen_video_ids = set()

    for video_id, status in statuses.items():
        seen_video_ids.add(video_id)
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
        elif privacy in ("private", "unlisted") and yt_publish_at:
            yt_dt = _parse_slot(str(yt_publish_at).replace("Z", "+00:00"))
            new_iso = yt_dt.isoformat()
            record["publish_at"] = new_iso
            record["publish_status"] = "scheduled" if yt_dt > now else "private"
            record["privacy_status"] = privacy
            scheduled += 1
        elif privacy == "unlisted":
            record["publish_status"] = "unlisted"
            record["privacy_status"] = "unlisted"
            record["publish_at"] = None
        else:
            record["publish_status"] = privacy or "unknown"
            record["publish_at"] = None

        if record != before:
            changed_records += 1

    for record in records:
        before = dict(record)
        video_id = str(record.get("video_id") or "").strip()
        publish_at = str(record.get("publish_at") or "").strip()
        status = str(record.get("publish_status") or "").lower()
        if publish_at and (not video_id or video_id not in seen_video_ids):
            record["publish_at"] = None
            record["publish_status"] = "private"
        elif publish_at and status in ("", "private", "unlisted"):
            try:
                if _parse_slot(publish_at.replace("Z", "+00:00")) <= now:
                    record["publish_at"] = None
                    record["publish_status"] = "private"
            except Exception:
                pass
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
