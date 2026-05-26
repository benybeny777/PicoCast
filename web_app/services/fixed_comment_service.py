"""
固定コメント投稿サービス。
既存の二重投稿防止ロジックを維持する。
"""
import json
import os
from typing import Any

from core.output_paths import OUTPUT_DIR
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import is_video_folder, safe_output_path


def list_fixed_comment_candidates(only_unposted: bool = True) -> list[dict[str, Any]]:
    results = []
    try:
        names = sorted(os.listdir(OUTPUT_DIR), reverse=True)
    except OSError:
        return results

    for name in names:
        if not is_video_folder(name):
            continue
        try:
            theme_dir = safe_output_path(name, output_base=OUTPUT_DIR)
        except Exception:
            continue
        if not os.path.isdir(theme_dir):
            continue

        render_info = _safe_json(os.path.join(theme_dir, "_meta", "render_info.json"))
        upload_record = _safe_json(os.path.join(theme_dir, "_meta", "upload_record.json"))

        fixed_comment = render_info.get("fixed_comment", "")
        if not fixed_comment:
            continue

        video_id = upload_record.get("video_id", "")
        if not video_id:
            continue

        publish_status = str(upload_record.get("publish_status") or "").lower()
        comment_thread_id = upload_record.get("fixed_comment_thread_id", "") or upload_record.get("comment_thread_id", "")
        already_posted = bool(comment_thread_id)

        if only_unposted and already_posted:
            continue

        results.append({
            "name": name,
            "title": render_info.get("video_title") or name,
            "video_id": video_id,
            "publish_status": publish_status,
            "fixed_comment": fixed_comment,
            "comment_thread_id": comment_thread_id,
            "already_posted": already_posted,
        })
    return results


def submit_fixed_comment_job(history_name: str) -> str:
    if ".." in history_name or "/" in history_name or "\\" in history_name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
    theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
    if not os.path.isdir(theme_dir) or not is_video_folder(os.path.basename(theme_dir)):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    mgr = get_job_manager()
    job = mgr.create_job("fixed_comment")
    _log(job, f"固定コメントジョブを登録: {history_name}", "info")
    mgr.submit(job, _run_fixed_comment, history_name)
    return job.job_id


def _run_fixed_comment(job: Job, history_name: str) -> dict[str, Any]:
    theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
    if not os.path.isdir(theme_dir):
        raise FileNotFoundError(f"履歴フォルダが見つかりません: {history_name}")

    render_info = _safe_json(os.path.join(theme_dir, "_meta", "render_info.json"))
    upload_record = _safe_json(os.path.join(theme_dir, "_meta", "upload_record.json"))

    video_id = upload_record.get("video_id", "")
    if not video_id:
        raise ValueError("video_id がありません（先にアップロードしてください）")

    fixed_comment = render_info.get("fixed_comment", "")
    if not fixed_comment:
        raise ValueError("固定コメントが設定されていません")

    already_posted_id = upload_record.get("fixed_comment_thread_id") or upload_record.get("comment_thread_id")
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

    # upload_record.json に記録（gui.py と同じキー名）
    upload_record["fixed_comment_thread_id"] = comment_thread_id
    upload_record_path = os.path.join(theme_dir, "_meta", "upload_record.json")
    try:
        with open(upload_record_path, "w", encoding="utf-8") as f:
            json.dump(upload_record, f, ensure_ascii=False, indent=2)
    except OSError as e:
        _log(job, f"upload_record.json の更新に失敗: {e}", "warning")

    return {"comment_thread_id": comment_thread_id, "video_id": video_id}


def _safe_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
