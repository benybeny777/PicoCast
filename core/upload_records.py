from datetime import datetime
import logging
from typing import Any

_logger = logging.getLogger(__name__)


def load_upload_records() -> list[dict[str, Any]]:
    """youtube_status + render_info テーブルから upload records を返す。"""
    from core.metadata_db import ManagedConnection, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        rows = conn.execute("""
            SELECT ys.youtube_video_id AS video_id,
                   ys.publish_status,
                   ys.publish_at,
                   ys.uploaded_at,
                   ys.local_id,
                   ri.video_title   AS title,
                   ri.video_format  AS video_type
            FROM youtube_status ys
            LEFT JOIN render_info ri ON ri.local_id = ys.local_id
            WHERE ys.youtube_video_id IS NOT NULL
        """).fetchall()
    return [dict(r) for r in rows]


def save_upload_records(records: list[dict[str, Any]]) -> str:
    """No-op: upload records は DB（youtube_status）で管理。"""
    return ""


def upsert_upload_record(record: dict[str, Any]) -> str:
    """No-op: youtube_status に直接書き込むため不要。"""
    return ""


def _norm_title(value: str) -> str:
    value = str(value or "").strip()
    lower_value = value.lower()
    from config import config as _cfg
    for prefix in _cfg._LEGACY_FOLDER_PREFIXES:
        if lower_value.startswith(str(prefix).lower()):
            return value[len(prefix):].strip()
    return value


def _to_timestamp(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value.timestamp())
    except AttributeError:
        _logger.debug("timestamp() を持たない値のため文字列日時として解析します: value=%r", value, exc_info=True)
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except Exception:
        _logger.warning("アップロード記録の日時解析に失敗しました: value=%r", value, exc_info=True)
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
    """No-op: DB 管理に移行済み。"""
    return 0
