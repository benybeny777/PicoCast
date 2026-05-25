import glob as _glob
import json
import os
from datetime import datetime
from typing import Any

from core.output_paths import UPLOAD_RECORDS_FILE

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))


def load_upload_records() -> list[dict[str, Any]]:
    """出力ツリー内の各動画 _meta/upload_record.json を走査して返す。
    中央集約ファイルは廃止済み。各レコードに '_local_path' キーを付与する。
    """
    output_dir = os.path.join(ROOT_DIR, "output")
    seen: dict[str, dict] = {}
    for path in sorted(_glob.glob(
        os.path.join(output_dir, "**", "_meta", "upload_record.json"), recursive=True
    )):
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            continue
        vid = str(record.get("video_id") or "").strip()
        if vid and vid not in seen:
            record["_local_path"] = path
            seen[vid] = record
    return list(seen.values())


def save_upload_records(records: list[dict[str, Any]]) -> str:
    """No-op: 中央集約ファイルは廃止済み。"""
    return UPLOAD_RECORDS_FILE


def upsert_upload_record(record: dict[str, Any]) -> str:
    """No-op: レコードは各動画の _meta/upload_record.json で管理。"""
    return UPLOAD_RECORDS_FILE


def _norm_title(value: str) -> str:
    value = str(value or "").strip()
    for prefix in ("[Shorts]", "[Long]", "[SHORT]", "[LONG]"):
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value


def _to_timestamp(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value.timestamp())
    except Exception:
        pass
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def find_upload_record(title: str | None = None, video_type: str | None = None, publish_at=None, tolerance_sec: int = 60):
    target_title = _norm_title(title or "")
    target_type = str(video_type or "").lower()
    target_ts = _to_timestamp(publish_at)

    records = load_upload_records()
    if target_ts is not None:
        best_match = None
        best_delta = None
        for record in records:
            if target_type:
                rec_type = str(record.get("video_type") or "").lower()
                if rec_type and rec_type != target_type:
                    continue
            if target_title and _norm_title(record.get("title") or "") != target_title:
                continue
            rec_ts = _to_timestamp(record.get("publish_at"))
            if rec_ts is None:
                continue
            delta = abs(rec_ts - target_ts)
            if delta <= tolerance_sec and (best_delta is None or delta < best_delta):
                best_match = record
                best_delta = delta
        if best_match is not None:
            return dict(best_match)

    for record in records:
        if target_type:
            rec_type = str(record.get("video_type") or "").lower()
            if rec_type and rec_type != target_type:
                continue
        if target_title and _norm_title(record.get("title") or "") == target_title:
            return dict(record)
    return None


def migrate_from_uploaded_dir() -> int:
    """No-op: 中央ファイルへの移行は廃止済み。"""
    return 0
