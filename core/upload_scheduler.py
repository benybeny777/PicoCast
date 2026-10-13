"""
YouTubeアップロードスケジュール管理。

Shorts枠: 毎日 12:00 / 21:00 JST。
Long枠: 毎日 22:00 JST。
Shorts と Long は別枠として扱うため、同時刻をそれぞれ使用できる。
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import config as _cfg
from core.error_codes import AppError

_logger = logging.getLogger(__name__)

def _timezone_from_name(name: str):
    if name == "Asia/Tokyo":
        return timezone(timedelta(hours=9))
    return ZoneInfo(name)


JST = _timezone_from_name(_cfg.UPLOAD_TIMEZONE)
SLOTS = list(_cfg.SHORTS_UPLOAD_SLOT_HOURS)
LONG_SLOTS_WEEKDAY = list(_cfg.LONG_UPLOAD_SLOT_HOURS)
LONG_SLOTS_WEEKEND = list(_cfg.LONG_UPLOAD_SLOT_HOURS)

VIDEO_TYPES = ("shorts", "long")
SCHEDULED_STATUSES = {"", "scheduled", "unlisted", "private"}
NOT_SCHEDULED_STATUSES = {"published", "public", "manual_published", "deleted", "failed"}


def _as_jst(dt: datetime) -> datetime:
    tz = _active_timezone()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _active_schedule():
    from core.channel_schedule import get_schedule
    return get_schedule()


def _active_timezone():
    schedule = _active_schedule()
    if schedule is None:
        return JST
    return _timezone_from_name(schedule.timezone_name)


def _parse_slot(iso: str) -> datetime:
    return _as_jst(datetime.fromisoformat(iso))


def _slot_hours(video_type: str, candidate, schedule=None) -> list[int]:
    schedule = schedule or _active_schedule()
    if schedule is None:
        return LONG_SLOTS_WEEKDAY if video_type == "long" else SLOTS
    if video_type == "long":
        return list(schedule.long_slot_hours)
    return list(schedule.shorts_slot_hours)


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
    now = _as_jst(now or datetime.now(_active_timezone()))
    schedule = _active_schedule()
    result = []
    candidate = now.date()

    for _ in range(90):
        for hour in _slot_hours(video_type, candidate, schedule):
            slot_dt = datetime(
                candidate.year,
                candidate.month,
                candidate.day,
                hour,
                0,
                0,
                tzinfo=now.tzinfo,
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
    """video_type ('shorts'|'long') の空きスロットを返す。"""
    schedule = schedule_from_records().get(video_type, {})
    return _assign_slots_from_used(count, video_type, set(schedule.keys()))


def assign_slots_from_youtube(count: int, video_type: str) -> list[datetime]:
    """YouTube予約動画を正として空きスロットを返す。

    チャンネルのアップロードリストを取得し、該当 video_type の
    private/unlisted かつ将来の publishAt を使用済みスロットとして扱う。
    YouTube から取得できないときは割り当てずに止める（ローカル記録だけで推定すると、
    記録に無い予約と同じ枠へ重ねて予約してしまうため）。
    """
    from core.youtube_uploader import get_channel_upload_video_statuses

    now = _as_jst(datetime.now(_active_timezone()))
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
                _logger.warning("YouTube予約枠publishAtの解析に失敗しました: publishAt=%s", pub_at_raw, exc_info=True)
                continue
    except Exception as exc:
        _logger.error("YouTube予約状況の取得に失敗したため予約枠を割り当てません", exc_info=True)
        raise AppError("E-YOUTUBE-SCHEDULE", "予約枠の割り当て", cause=exc) from exc

    return _assign_slots_from_used(count, video_type, used, now)


def mark_slot_used(slot_dt: datetime, title: str, video_type: str):
    """後方互換用 No-op。"""
    return None


def schedule_from_youtube() -> dict[str, dict]:
    """YouTube APIを正としてスケジュールを構築する。
    {"shorts": {iso: title, ...}, "long": {...}} を返す。
    """
    from core.youtube_uploader import get_channel_upload_video_statuses

    now = _as_jst(datetime.now(_active_timezone()))
    schedules: dict[str, dict] = {vt: {} for vt in VIDEO_TYPES}
    try:
        statuses = get_channel_upload_video_statuses()
    except Exception as exc:
        # 空の一覧を返すと「予約なし」と区別できず、空き枠と誤解されるため止める
        _logger.error("YouTube予約一覧の取得に失敗しました", exc_info=True)
        raise AppError("E-YOUTUBE-SCHEDULE", "予約一覧の取得", cause=exc) from exc
    for _vid_id, status in statuses.items():
        vt = str(status.get("video_type") or "").lower()
        if vt not in schedules:
            continue
        privacy = str(status.get("privacyStatus") or "").lower()
        pub_at_raw = str(status.get("publishAt") or "").strip()
        if privacy not in ("private", "unlisted") or not pub_at_raw:
            continue
        try:
            dt = _as_jst(datetime.fromisoformat(pub_at_raw.replace("Z", "+00:00")))
            if dt <= now:
                continue
            iso = dt.isoformat()
        except Exception:
            _logger.warning("YouTube予約一覧publishAtの解析に失敗しました: video_id=%s publishAt=%s", _vid_id, pub_at_raw, exc_info=True)
            continue
        title = str(status.get("title") or "").strip()
        if not title:
            continue
        if iso not in schedules[vt]:
            schedules[vt][iso] = title
    return schedules


def _scheduled_entries_from_youtube(video_type: str) -> list[dict]:
    """リバランス用にYouTubeから予約済みエントリを取得する。"""
    from core.youtube_uploader import get_channel_upload_video_statuses

    now = datetime.now(_active_timezone())
    entries = []
    try:
        statuses = get_channel_upload_video_statuses()
    except Exception:
        _logger.warning("YouTube予約済みエントリの取得に失敗しました", exc_info=True)
        return entries
    for video_id, status in statuses.items():
        vt = str(status.get("video_type") or "").lower()
        if vt != video_type:
            continue
        privacy = str(status.get("privacyStatus") or "").lower()
        pub_at_raw = str(status.get("publishAt") or "").strip()
        if privacy not in ("private", "unlisted") or not pub_at_raw:
            continue
        try:
            iso = _as_jst(datetime.fromisoformat(pub_at_raw.replace("Z", "+00:00"))).isoformat()
            slot_dt = _parse_slot(iso)
        except Exception:
            _logger.warning("YouTube予約済みエントリpublishAtの解析に失敗しました: video_id=%s publishAt=%s", video_id, pub_at_raw, exc_info=True)
            continue
        if slot_dt <= now:
            continue
        title = str(status.get("title") or "").strip()
        entries.append({
            "index": None,
            "iso": iso,
            "slot_dt": slot_dt,
            "title": title or video_id,
            "video_id": video_id,
            "generation_kind": "",
        })
    return entries


def schedule_from_records(records: list[dict] | None = None) -> dict[str, dict]:
    """アップロードレコードからスケジュールキャッシュを構築する。"""
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
            _logger.warning("ローカルアップロード記録のpublish_at解析に失敗しました: publish_at=%s", publish_at, exc_info=True)
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
    """保存せずにリバランス後のスケジュールを構築する。"""
    now = _as_jst(now or datetime.now(_active_timezone()))
    cutoff = now + timedelta(minutes=5)

    fixed = {}
    future = []
    for iso, title in schedule.items():
        try:
            slot_dt = _parse_slot(iso)
        except Exception:
            _logger.warning("リバランス対象スロットの解析に失敗しました: iso=%s", iso, exc_info=True)
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
    now = datetime.now(_active_timezone())
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
                _logger.warning("publish_at の解析に失敗したため対象外とします: publish_at=%r", publish_at, exc_info=True)
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
    """レコードエントリからリバランス変更リストを構築する（重複スロット保持）。"""
    now = _as_jst(now or datetime.now(_active_timezone()))
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
    """YouTubeを正として将来スロットを詰め直す変更リストを計算する。
    書き込みは行わず、呼び出し元がYouTubeへ適用する。"""
    entries = _scheduled_entries_from_youtube(video_type)
    return build_rebalanced_entries(entries, video_type)


def rebalance_slots_detailed(video_type: str) -> list[tuple[str, str, str, str, int | None]]:
    """rebalance_slots() の video_id 付き版。YouTubeを正として動作。"""
    entries = _scheduled_entries_from_youtube(video_type)
    return build_rebalanced_entries(
        entries,
        video_type,
        include_video_id=True,
        include_record_index=True,
    )


def count_rebalance_candidates(video_type: str) -> int:
    return len(_scheduled_entries_from_youtube(video_type))


def list_schedule() -> dict:
    """YouTubeから {"shorts": {...}, "long": {...}} を返す。"""
    return schedule_from_youtube()


def _title_key(value: str) -> str:
    value = str(value or "").split("\n")[0].strip()
    lower_value = value.lower()
    from config import config as _cfg
    for prefix in _cfg._LEGACY_FOLDER_PREFIXES:
        if lower_value.startswith(str(prefix).lower()):
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
    """YouTubeのステータスを正としてローカルレコード・スケジュールを更新する。"""
    from core.metadata_db import sync_youtube_statuses
    from core.upload_records import load_upload_records
    from core.youtube_uploader import get_channel_upload_video_statuses

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
    except Exception as exc:
        # 既知の動画だけで同期すると、記録に無い予約を見落としたまま「同期済み」になるため止める
        _logger.error("YouTubeチャンネルの動画一覧を取得できないため同期を中止します", exc_info=True)
        raise AppError("E-YOUTUBE-SCHEDULE", "予約の同期", cause=exc) from exc
    db_result = sync_youtube_statuses(statuses, delete_missing=False)
    now = datetime.now(_active_timezone())
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
                    _logger.warning("published_atの解析に失敗したため受領値をそのまま保存します: published_at=%r", published_at, exc_info=True)
                    record["published_at"] = published_at  # フォールバック許可: 正規化失敗時はYouTube受領値を保持
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
            except Exception as _e:
                raise RuntimeError(f"Error: {_e}") from _e
        if record != before:
            changed_records += 1

    if changed_records:
        _log(f"YouTube sync: records={changed_records}")
    return {
        "checked": len(statuses),
        "scheduled": scheduled,
        "published": published,
        "changed": max(changed_records, db_result.get("updated", 0)),
        "db_updated": db_result.get("updated", 0),
        "db_missing": db_result.get("missing", 0),
    }


def format_slot(slot_dt: datetime) -> str:
    """'YYYY/MM/DD HH:MM (JST)' 形式の表示文字列を返す。"""
    return _as_jst(slot_dt).strftime("%Y/%m/%d %H:%M") + " (JST)"
