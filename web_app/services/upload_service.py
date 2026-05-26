"""
YouTubeアップロードサービス。
二重アップロード防止チェックを行い、ジョブとして実行する。
"""
import json
import os
from typing import Any

from core.output_paths import OUTPUT_DIR
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import is_video_folder, safe_output_path


def list_upload_candidates() -> list[dict[str, Any]]:
    """MP4がある未アップロード履歴を返す。"""
    candidates = []
    try:
        names = sorted(os.listdir(OUTPUT_DIR), reverse=True)
    except OSError:
        return candidates

    for name in names:
        if not is_video_folder(name):
            continue
        try:
            theme_dir = safe_output_path(name, output_base=OUTPUT_DIR)
        except Exception:
            continue
        if not os.path.isdir(theme_dir):
            continue

        mp4_path = _find_mp4(theme_dir)
        if not mp4_path:
            continue

        upload_record = _safe_json(os.path.join(theme_dir, "_meta", "upload_record.json"))
        render_info = _safe_json(os.path.join(theme_dir, "_meta", "render_info.json"))

        # 二重アップロード防止チェック
        video_id = upload_record.get("video_id", "")
        publish_status = upload_record.get("publish_status", "")
        already_uploaded = bool(video_id) and publish_status not in ("", None)

        candidates.append({
            "name": name,
            "mp4_path": mp4_path,
            "mp4_filename": os.path.basename(mp4_path),
            "title": render_info.get("video_title") or name,
            "video_format": render_info.get("video_format", ""),
            "video_id": video_id,
            "publish_status": publish_status,
            "publish_at": upload_record.get("publish_at", ""),
            "already_uploaded": already_uploaded,
        })
    return candidates


def submit_upload_job(history_name: str) -> str:
    if ".." in history_name or "/" in history_name or "\\" in history_name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
    theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
    if not os.path.isdir(theme_dir) or not is_video_folder(os.path.basename(theme_dir)):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    mgr = get_job_manager()
    job = mgr.create_job("upload")
    _log(job, f"アップロードジョブを登録: {history_name}", "info")
    mgr.submit(job, _run_upload, history_name)
    return job.job_id


def _run_upload(job: Job, history_name: str) -> dict[str, Any]:
    from core.youtube_uploader import upload_video
    theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
    if not os.path.isdir(theme_dir):
        raise FileNotFoundError(f"履歴フォルダが見つかりません: {history_name}")

    mp4_path = _find_mp4(theme_dir)
    if not mp4_path:
        raise FileNotFoundError(f"MP4ファイルが見つかりません: {history_name}")

    upload_record = _safe_json(os.path.join(theme_dir, "_meta", "upload_record.json"))
    if upload_record.get("video_id"):
        raise ValueError(f"既にアップロード済みです (video_id={upload_record['video_id']})")

    render_info = _safe_json(os.path.join(theme_dir, "_meta", "render_info.json"))
    _log(job, f"アップロード開始: {mp4_path}", "info")

    if job.cancel_event.is_set():
        return {"cancelled": True}

    # サムネイルパスを探す
    thumbnail_path = os.path.join(theme_dir, "thumbnails", "thumbnail.png")
    if not os.path.exists(thumbnail_path):
        thumbnail_path = None

    try:
        result = upload_video(
            mp4_path=mp4_path,
            title=render_info.get("video_title", history_name),
            description=render_info.get("description", ""),
            tags=render_info.get("tags", []),
            thumbnail_path=thumbnail_path,
            progress_callback=lambda msg, tag="info": _log(job, msg, tag),
        )
    except Exception as e:
        _log(job, f"アップロードエラー: {e}", "error")
        raise

    _log(job, f"アップロード完了: video_id={result.get('video_id')}", "success")
    return result


def _find_mp4(theme_dir: str) -> str | None:
    try:
        for fname in sorted(os.listdir(theme_dir)):
            if fname.endswith("_native.mp4") or fname == "video_native.mp4":
                return os.path.join(theme_dir, fname)
    except OSError:
        pass
    return None


def _safe_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
