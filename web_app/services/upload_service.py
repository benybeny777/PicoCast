"""
YouTubeアップロードサービス。
二重アップロード防止チェックを行い、ジョブとして実行する。
"""
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from typing import Any

from core.output_paths import OUTPUT_DIR
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import is_video_folder, safe_output_path

_JST = timezone(timedelta(hours=9))


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
        video_id = upload_video(
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

    _log(job, f"アップロード完了: video_id={video_id}", "success")

    # スロットを取得して YouTube でスケジュール設定
    video_format = str(render_info.get("video_format") or "").strip().lower()
    video_type = "shorts" if "short" in video_format else "long"
    publish_at_iso: str | None = None
    try:
        from core.upload_scheduler import assign_slots_from_youtube
        from core.youtube_uploader import update_video_publish_time
        slots = assign_slots_from_youtube(1, video_type)
        if slots:
            slot_dt = slots[0]
            _log(job, f"スロット割り当て: {slot_dt.isoformat()}", "info")
            ok = update_video_publish_time(
                video_id, slot_dt,
                progress_callback=lambda msg: _log(job, msg, "info"),
            )
            if ok:
                publish_at_iso = slot_dt.isoformat()
                _log(job, f"公開予定を設定しました: {publish_at_iso}", "success")
            else:
                _log(job, "公開予定の設定に失敗しました。非公開のままです。", "warning")
        else:
            _log(job, "空きスロットが見つかりませんでした。非公開のままです。", "warning")
    except Exception as e:
        _log(job, f"スロット設定エラー（非公開のまま続行）: {e}", "warning")

    # upload_record.json を書く
    record: dict = {
        "video_id": video_id,
        "title": render_info.get("video_title", history_name),
        "video_type": video_type,
        "uploaded_at": datetime.now(_JST).isoformat(),
        "publish_status": "scheduled" if publish_at_iso else "private",
    }
    if publish_at_iso:
        record["publish_at"] = publish_at_iso
    meta_dir = os.path.join(theme_dir, "_meta")
    os.makedirs(meta_dir, exist_ok=True)
    with open(os.path.join(meta_dir, "upload_record.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    _log(job, "upload_record.json を保存しました", "info")

    # 000_uploaded/ へフォルダ移動
    folder_name = os.path.basename(theme_dir)
    uploaded_dir = os.path.join(OUTPUT_DIR, "000_uploaded")
    os.makedirs(uploaded_dir, exist_ok=True)
    shutil.move(theme_dir, os.path.join(uploaded_dir, folder_name))
    _log(job, f"フォルダを移動しました → 000_uploaded/{folder_name}", "info")

    # 000_backups/ から同テーマのバックアップを削除
    backups_dir = os.path.join(OUTPUT_DIR, "000_backups")
    prefix = f"{folder_name}_"
    removed = 0
    if os.path.isdir(backups_dir):
        for entry in os.listdir(backups_dir):
            entry_path = os.path.join(backups_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry == folder_name or entry.startswith(prefix):
                shutil.rmtree(entry_path)
                removed += 1
    if removed:
        _log(job, f"バックアップを削除しました: {removed}件", "info")

    return {"video_id": video_id, "message": f"video_id={video_id}"}


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
