"""
固定コメント投稿サービス。
metadata.db の youtube_status / video_metadata を正本として扱う。
"""
import os
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from core.output_paths import get_output_videos_dir, get_uploaded_dir, get_output_root
from core.metadata_db import ManagedConnection, initialize_db, is_initialized
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import is_video_folder, safe_output_path


def list_fixed_comment_candidates(only_unposted: bool = True) -> list[dict[str, Any]]:
    results = []
    for relative_name, theme_dir in _iter_candidate_dirs():
        name = os.path.basename(theme_dir)
        is_uploaded_archive = relative_name.startswith("000_uploaded" + os.sep)
        try:
            _safe_fixed_comment_theme_dir(relative_name)
        except Exception:
            continue
        if not os.path.isdir(theme_dir):
            continue

        record = _fixed_comment_record(name)
        if not record:
            continue
        fixed_comment = str(record.get("fixed_comment") or "").strip()
        if not fixed_comment:
            continue

        video_id = str(record.get("video_id") or "").strip()
        if not video_id:
            continue

        publish_status = str(record.get("publish_status") or "").lower()
        if not _is_local_displayable_publish_status(publish_status):
            continue

        comment_thread_id = str(record.get("comment_thread_id") or "").strip()
        already_posted = bool(record.get("fixed_comment_posted") or comment_thread_id)

        if only_unposted and already_posted:
            continue

        results.append({
            "name": relative_name,
            "display_name": name,
            "location": "アップロード済み" if is_uploaded_archive else "出力",
            "title": str(record.get("title") or name),
            "video_id": video_id,
            "publish_status": publish_status,
            "published_at": _published_at_text(record),
            "fixed_comment": fixed_comment,
            "comment_thread_id": comment_thread_id,
            "fixed_comment_posted_at": "DB" if record.get("fixed_comment_posted") else "",
            "fixed_comment_pinned_at": "",
            "already_posted": already_posted,
            "auto_posted": False,
            "auto_submitted_at": "",
        })
    results.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    return _filter_existing_public_videos(results)


def submit_fixed_comment_job(history_name: str, auto_posted: bool = False) -> str:
    if _is_unsafe_history_name(history_name):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
    theme_dir = _safe_fixed_comment_theme_dir(history_name)
    if not os.path.isdir(theme_dir) or not _is_fixed_comment_folder(theme_dir):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    mgr = get_job_manager()
    job = mgr.create_job("fixed_comment")
    _log(job, f"固定コメントジョブを登録: {history_name}", "info")
    mgr.submit(job, _run_fixed_comment, history_name, auto_posted)
    return job.job_id


def mark_fixed_comment_posted(history_name: str) -> dict[str, Any]:
    if _is_unsafe_history_name(history_name):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")

    theme_dir = _safe_fixed_comment_theme_dir(history_name)
    if not os.path.isdir(theme_dir) or not _is_fixed_comment_folder(theme_dir):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    local_id = os.path.basename(theme_dir)
    record = _fixed_comment_record(local_id)
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="DBに固定コメント対象がありません")

    video_id = str(record.get("video_id") or "")
    if not video_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="video_id がありません")

    fixed_comment = str(record.get("fixed_comment") or "").strip()
    if not fixed_comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="固定コメントが設定されていません")

    recorded_at = _now_local_iso()
    _mark_fixed_comment_db(local_id, comment_thread_id=record.get("comment_thread_id") or None)

    return {
        "history_name": history_name,
        "video_id": video_id,
        "fixed_comment_posted_at": recorded_at,
    }


def _run_fixed_comment(job: Job, history_name: str, auto_posted: bool = False) -> dict[str, Any]:
    theme_dir = _safe_fixed_comment_theme_dir(history_name)
    if not os.path.isdir(theme_dir):
        raise FileNotFoundError(f"履歴フォルダが見つかりません: {history_name}")

    local_id = os.path.basename(theme_dir)
    record = _fixed_comment_record(local_id)
    if not record:
        raise ValueError("DBに固定コメント対象がありません")

    video_id = str(record.get("video_id") or "")
    if not video_id:
        raise ValueError("video_id がありません（先にアップロードしてください）")

    fixed_comment = str(record.get("fixed_comment") or "").strip()
    if not fixed_comment:
        raise ValueError("固定コメントが設定されていません")

    already_posted_id = record.get("comment_thread_id") or record.get("fixed_comment_posted")
    if already_posted_id:
        raise ValueError(f"既に投稿済みです (comment_thread_id={already_posted_id})")

    publish_status = str(record.get("publish_status") or "").lower()
    if publish_status not in ("published", "public", "manual_published"):
        _log(job, f"注意: 動画が非公開または予約状態です (status={publish_status})", "warning")

    _log(job, f"固定コメント投稿中: video_id={video_id}", "info")
    if job.cancel_event.is_set():
        return {"cancelled": True}

    try:
        from core.youtube_uploader import post_comment
        comment_thread_id = post_comment(
            video_id=video_id,
            comment_text=fixed_comment,
            progress_callback=lambda msg: _log(job, msg, "info"),
        )
    except Exception as e:
        _log(job, f"投稿エラー: {e}", "error")
        raise

    if not comment_thread_id:
        raise Exception("コメント投稿が失敗しました（YouTube API がIDを返しませんでした）")

    _log(job, f"固定コメント投稿完了: comment_thread_id={comment_thread_id}", "success")

    _mark_fixed_comment_db(local_id, comment_thread_id=comment_thread_id)

    return {"comment_thread_id": comment_thread_id, "video_id": video_id, "auto_posted": auto_posted}


def _iter_candidate_dirs() -> Iterable[tuple[str, str]]:
    try:
        names = sorted(os.listdir(get_output_videos_dir()), reverse=True)
    except OSError:
        names = []

    for name in names:
        if is_video_folder(name):
            path = os.path.join(get_output_videos_dir(), name)
            if os.path.isdir(path):
                yield name, path

    uploaded_dir = get_uploaded_dir()
    try:
        uploaded_names = sorted(os.listdir(uploaded_dir), reverse=True)
    except OSError:
        return

    for name in uploaded_names:
        path = os.path.join(uploaded_dir, name)
        if os.path.isdir(path):
            yield os.path.join("000_uploaded", name), path


def _fixed_comment_record(local_id: str) -> dict[str, Any]:
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        row = conn.execute(
            """
            SELECT v.local_id,
                   COALESCE(ri.video_title, v.title, v.local_id) AS title,
                   vm.fixed_comment,
                   ys.youtube_video_id AS video_id,
                   ys.publish_status,
                   ys.publish_at,
                   ys.uploaded_at,
                   ys.published_at,
                   ys.fixed_comment_posted,
                   ys.fixed_comment_id AS comment_thread_id
            FROM videos v
            LEFT JOIN render_info ri ON ri.local_id = v.local_id
            LEFT JOIN video_metadata vm ON vm.local_id = v.local_id
            LEFT JOIN youtube_status ys ON ys.local_id = v.local_id
            WHERE v.local_id=?
            """,
            (local_id,),
        ).fetchone()
    return dict(row) if row else {}


def _mark_fixed_comment_db(local_id: str, comment_thread_id: str | None = None) -> None:
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        conn.execute(
            """
            UPDATE youtube_status
            SET fixed_comment_posted=1,
                fixed_comment_id=COALESCE(?, fixed_comment_id)
            WHERE local_id=?
            """,
            (comment_thread_id, local_id),
        )
        conn.commit()


def _is_local_displayable_publish_status(publish_status: str) -> bool:
    # YouTube API による実公開確認 (_filter_existing_public_videos) が最終フィルター。
    # ローカル "private" はアップロード直後に残ることがあるため許容し、予約中は候補から除外する。
    return publish_status not in ("scheduled", "reserved")


def _published_at_text(upload_record: dict) -> str:
    return str(
        upload_record.get("published_at")
        or upload_record.get("uploaded_at")
        or upload_record.get("publish_at")
        or ""
    ).strip()


def _filter_existing_public_videos(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    video_ids = sorted({str(item.get("video_id") or "").strip() for item in candidates if item.get("video_id")})
    statuses = _fetch_youtube_statuses(video_ids)
    if statuses is None:
        return candidates

    filtered = []
    for item in candidates:
        video_id = str(item.get("video_id") or "").strip()
        status = statuses.get(video_id)
        if not status:
            continue

        privacy = str(status.get("privacyStatus") or "").lower()
        if privacy != "public":
            continue

        item = dict(item)
        item["publish_status"] = "public"
        item["published_at"] = status.get("publishedAt") or item.get("published_at", "")
        item["title"] = status.get("title") or item.get("title", "")
        filtered.append(item)
    return filtered


def _fetch_youtube_statuses(video_ids: list[str]) -> dict[str, dict] | None:
    if not video_ids:
        return {}
    from core.youtube_uploader import get_video_statuses
    return get_video_statuses(video_ids)


def _is_unsafe_history_name(history_name: str) -> bool:
    normalized = history_name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    return (
        not history_name
        or os.path.isabs(history_name)
        or ".." in parts
        or normalized.startswith("/")
        or (len(parts) > 2)
        or (len(parts) == 2 and parts[0] != "000_uploaded")
    )


def _safe_fixed_comment_theme_dir(history_name: str) -> str:
    normalized = history_name.replace("\\", "/")
    if normalized.startswith("000_uploaded/"):
        return safe_output_path(normalized, output_base=get_output_root())
    return safe_output_path(normalized, output_base=get_output_videos_dir())


def _is_fixed_comment_folder(theme_dir: str) -> bool:
    basename = os.path.basename(theme_dir)
    record = _fixed_comment_record(basename)
    return bool(record.get("video_id") and record.get("fixed_comment"))


def _now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
