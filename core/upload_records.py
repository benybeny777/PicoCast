import json
import os
from datetime import datetime
from typing import Any


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
UPLOAD_RECORDS_FILE = os.path.join(ROOT_DIR, "output", "upload_records.json")


def load_upload_records() -> list[dict[str, Any]]:
    if not os.path.exists(UPLOAD_RECORDS_FILE):
        return []
    try:
        with open(UPLOAD_RECORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            records = data.get("records", [])
        else:
            records = data
        return records if isinstance(records, list) else []
    except Exception:
        return []


def save_upload_records(records: list[dict[str, Any]]) -> str:
    os.makedirs(os.path.dirname(UPLOAD_RECORDS_FILE), exist_ok=True)
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "records": records,
    }
    with open(UPLOAD_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return UPLOAD_RECORDS_FILE


def upsert_upload_record(record: dict[str, Any]) -> str:
    if not record:
        return UPLOAD_RECORDS_FILE
    records = load_upload_records()
    video_id = str(record.get("video_id") or "").strip()
    title = str(record.get("title") or "").strip()
    publish_at = str(record.get("publish_at") or "").strip()

    match_index = None
    for idx, current in enumerate(records):
        current_video_id = str(current.get("video_id") or "").strip()
        if video_id and current_video_id == video_id:
            match_index = idx
            break
        if not video_id and title and publish_at:
            if str(current.get("title") or "").strip() == title and str(current.get("publish_at") or "").strip() == publish_at:
                match_index = idx
                break

    merged = dict(records[match_index]) if match_index is not None else {}
    merged.update(record)
    if match_index is None:
        records.append(merged)
    else:
        records[match_index] = merged
    return save_upload_records(records)


def _norm_title(value: str) -> str:
    value = str(value or "").strip()
    for prefix in ("[Shorts]", "[Long]", "[SHORT]", "[LONG]"):
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value


def find_upload_record(title: str | None = None, video_type: str | None = None, publish_at=None, tolerance_sec: int = 60):
    target_title = _norm_title(title or "")
    target_type = str(video_type or "").lower()
    target_ts = None
    if publish_at is not None:
        try:
            target_ts = int(publish_at.timestamp())
        except Exception:
            target_ts = None

    for record in load_upload_records():
        if target_type:
            rec_type = str(record.get("video_type") or "").lower()
            if rec_type and rec_type != target_type:
                continue
        if target_ts is not None:
            rec_publish = record.get("publish_at")
            if rec_publish:
                try:
                    rec_dt = datetime.fromisoformat(str(rec_publish))
                    if abs(int(rec_dt.timestamp()) - target_ts) <= tolerance_sec:
                        return dict(record)
                except Exception:
                    pass
        if target_title and _norm_title(record.get("title") or "") == target_title:
            return dict(record)
    return None


def migrate_from_uploaded_dir() -> int:
    uploaded_dir = os.path.join(ROOT_DIR, "output", "000_uploaded")
    if not os.path.isdir(uploaded_dir):
        return 0
    migrated = 0
    for root, _dirs, files in os.walk(uploaded_dir):
        if "upload_record.json" not in files:
            continue
        path = os.path.join(root, "upload_record.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            continue
        if not record.get("video_id"):
            continue
        script_path = os.path.join(os.path.dirname(root), "script.txt") if os.path.basename(root) == "_meta" else os.path.join(root, "script.txt")
        if os.path.exists(script_path):
            try:
                from core.parser import ScriptParser
                script_meta = {
                    it["type"]: it["text"]
                    for it in ScriptParser.parse(script_path)
                    if it["type"] in ScriptParser.META_TYPES
                }
                record.setdefault("generation_kind", script_meta.get("generation_kind", ""))
                record.setdefault("source_video_title", script_meta.get("source_video_title", ""))
                record.setdefault("generation_purpose", script_meta.get("generation_purpose", ""))
                record.setdefault("fixed_comment_text", script_meta.get("fixed_comment", ""))
            except Exception:
                pass
        upsert_upload_record(record)
        migrated += 1
    return migrated
