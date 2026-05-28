"""
固定コメント投稿サービス。
既存の二重投稿防止ロジックを維持する。
"""
import json
import os
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from core.output_paths import OUTPUT_DIR
from core.parser import ScriptParser
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import is_video_folder, safe_output_path


def list_fixed_comment_candidates(only_unposted: bool = True) -> list[dict[str, Any]]:
    results = []
    for relative_name, theme_dir in _iter_candidate_dirs():
        name = os.path.basename(theme_dir)
        is_uploaded_archive = relative_name.startswith("000_uploaded" + os.sep)
        try:
            safe_output_path(relative_name, output_base=OUTPUT_DIR)
        except Exception:
            continue
        if not os.path.isdir(theme_dir):
            continue

        render_info = _safe_json(_first_existing(theme_dir, ("_meta/render_info.json", "render_info.json")))
        upload_record_path = _first_existing(theme_dir, ("_meta/upload_record.json", "upload_record.json"))
        upload_record = _safe_json(upload_record_path)
        metadata = _load_metadata(theme_dir)

        fixed_comment = _fixed_comment_text(render_info, upload_record, metadata)
        if not fixed_comment:
            continue

        video_id = upload_record.get("video_id", "")
        if not video_id:
            continue

        publish_status = str(upload_record.get("publish_status") or "").lower()
        if not _is_local_displayable_publish_status(publish_status):
            continue

        comment_thread_id = upload_record.get("fixed_comment_thread_id", "") or upload_record.get("comment_thread_id", "")
        fixed_comment_posted_at = upload_record.get("fixed_comment_posted_at", "")
        fixed_comment_pinned_at = upload_record.get("fixed_comment_pinned_at", "")
        already_posted = bool(comment_thread_id or fixed_comment_posted_at or fixed_comment_pinned_at)

        if only_unposted and already_posted:
            continue

        results.append({
            "name": relative_name,
            "display_name": name,
            "location": "アップロード済み" if is_uploaded_archive else "出力",
            "title": _video_title(render_info, upload_record, metadata, name),
            "video_id": video_id,
            "publish_status": publish_status,
            "published_at": _published_at_text(upload_record),
            "fixed_comment": fixed_comment,
            "comment_thread_id": comment_thread_id,
            "fixed_comment_posted_at": fixed_comment_posted_at,
            "fixed_comment_pinned_at": fixed_comment_pinned_at,
            "already_posted": already_posted,
            "auto_posted": bool(upload_record.get("fixed_comment_auto_posted")),
            "auto_submitted_at": upload_record.get("fixed_comment_auto_submitted_at", ""),
        })
    return _filter_existing_public_videos(results)


def submit_fixed_comment_job(history_name: str, auto_posted: bool = False) -> str:
    if _is_unsafe_history_name(history_name):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
    theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
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

    theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
    if not os.path.isdir(theme_dir) or not _is_fixed_comment_folder(theme_dir):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    render_info = _safe_json(_first_existing(theme_dir, ("_meta/render_info.json", "render_info.json")))
    upload_record_path = _first_existing(theme_dir, ("_meta/upload_record.json", "upload_record.json"))
    upload_record = _safe_json(upload_record_path)
    metadata = _load_metadata(theme_dir)

    video_id = upload_record.get("video_id", "")
    if not video_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="video_id がありません")

    fixed_comment = _fixed_comment_text(render_info, upload_record, metadata)
    if not fixed_comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="固定コメントが設定されていません")

    recorded_at = _now_local_iso()
    upload_record["fixed_comment_posted_at"] = upload_record.get("fixed_comment_posted_at") or recorded_at
    upload_record["fixed_comment_text"] = fixed_comment
    upload_record["fixed_comment_manual_recorded_at"] = recorded_at

    try:
        with open(upload_record_path, "w", encoding="utf-8") as f:
            json.dump(upload_record, f, ensure_ascii=False, indent=2)
    except OSError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"upload_record.json の更新に失敗: {e}") from e

    return {
        "history_name": history_name,
        "video_id": video_id,
        "fixed_comment_posted_at": upload_record["fixed_comment_posted_at"],
    }


def _run_fixed_comment(job: Job, history_name: str, auto_posted: bool = False) -> dict[str, Any]:
    theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
    if not os.path.isdir(theme_dir):
        raise FileNotFoundError(f"履歴フォルダが見つかりません: {history_name}")

    render_info = _safe_json(_first_existing(theme_dir, ("_meta/render_info.json", "render_info.json")))
    upload_record_path = _first_existing(theme_dir, ("_meta/upload_record.json", "upload_record.json"))
    upload_record = _safe_json(upload_record_path)
    metadata = _load_metadata(theme_dir)

    video_id = upload_record.get("video_id", "")
    if not video_id:
        raise ValueError("video_id がありません（先にアップロードしてください）")

    fixed_comment = _fixed_comment_text(render_info, upload_record, metadata)
    if not fixed_comment:
        raise ValueError("固定コメントが設定されていません")

    already_posted_id = (
        upload_record.get("fixed_comment_thread_id")
        or upload_record.get("comment_thread_id")
        or upload_record.get("fixed_comment_posted_at")
        or upload_record.get("fixed_comment_pinned_at")
    )
    if already_posted_id:
        raise ValueError(f"既に投稿済みです (comment_thread_id={already_posted_id})")

    publish_status = str(upload_record.get("publish_status") or "").lower()
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

    # upload_record.json に固定コメント投稿済みIDを記録
    upload_record["fixed_comment_thread_id"] = comment_thread_id
    if auto_posted:
        upload_record["fixed_comment_auto_posted"] = True
    try:
        with open(upload_record_path, "w", encoding="utf-8") as f:
            json.dump(upload_record, f, ensure_ascii=False, indent=2)
    except OSError as e:
        _log(job, f"upload_record.json の更新に失敗: {e}", "warning")

    return {"comment_thread_id": comment_thread_id, "video_id": video_id, "auto_posted": auto_posted}


def _safe_json(path: str) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _iter_candidate_dirs() -> Iterable[tuple[str, str]]:
    try:
        names = sorted(os.listdir(OUTPUT_DIR), reverse=True)
    except OSError:
        return

    for name in names:
        if is_video_folder(name):
            path = os.path.join(OUTPUT_DIR, name)
            if os.path.isdir(path):
                yield name, path

    uploaded_dir = os.path.join(OUTPUT_DIR, "000_uploaded")
    try:
        uploaded_names = sorted(os.listdir(uploaded_dir), reverse=True)
    except OSError:
        return

    for name in uploaded_names:
        path = os.path.join(uploaded_dir, name)
        if os.path.isdir(path):
            yield os.path.join("000_uploaded", name), path


def _first_existing(theme_dir: str, relative_paths: tuple[str, ...]) -> str:
    for rel_path in relative_paths:
        path = os.path.join(theme_dir, rel_path)
        if os.path.exists(path):
            return path
    return os.path.join(theme_dir, relative_paths[0])


def _load_metadata(theme_dir: str) -> dict[str, str]:
    path = _first_existing(theme_dir, ("_meta/metadata.txt", "metadata.txt"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}

    metadata: dict[str, str] = {}
    for item in ScriptParser.parse_string(text):
        item_type = item.get("type")
        if item_type in ScriptParser.META_TYPES:
            metadata[item_type] = item.get("text", "")
    return metadata


def _fixed_comment_text(render_info: dict, upload_record: dict, metadata: dict[str, str]) -> str:
    return str(
        render_info.get("fixed_comment")
        or upload_record.get("fixed_comment_text")
        or metadata.get("fixed_comment")
        or ""
    ).strip()


def _video_title(render_info: dict, upload_record: dict, metadata: dict[str, str], fallback: str) -> str:
    return str(
        render_info.get("video_title")
        or upload_record.get("title")
        or metadata.get("video_title")
        or fallback
    ).strip()


def _is_local_displayable_publish_status(publish_status: str) -> bool:
    # YouTube API による実公開確認 (_filter_existing_public_videos) が最終フィルター。
    # ローカルステータスはアップロード直後に "private" のまま残ることがあるため除外しない。
    return True


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
    try:
        from core.youtube_uploader import get_video_statuses
        return get_video_statuses(video_ids)
    except Exception:
        return None


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


def _is_fixed_comment_folder(theme_dir: str) -> bool:
    basename = os.path.basename(theme_dir)
    if is_video_folder(basename):
        return True
    upload_record_path = _first_existing(theme_dir, ("_meta/upload_record.json", "upload_record.json"))
    metadata_path = _first_existing(theme_dir, ("_meta/metadata.txt", "metadata.txt"))
    return os.path.exists(upload_record_path) and os.path.exists(metadata_path)


def _now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
