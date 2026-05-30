"""
メタデータDB 管理 API。
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter(prefix="/api/db", tags=["metadata_db"])


def _ensure_init():
    from core.metadata_db import initialize_db, is_initialized
    if not is_initialized():
        initialize_db()


@router.get("/videos")
def api_db_videos(
    video_type: Optional[str] = Query(None),
    publish_status: Optional[str] = Query(None),
    generation_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    playlist_unregistered: bool = Query(False),
    has_youtube_id: Optional[bool] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    _ensure_init()
    from core.metadata_db import get_videos
    return get_videos(
        video_type=video_type,
        publish_status=publish_status,
        generation_type=generation_type,
        genre=genre,
        playlist_unregistered=playlist_unregistered,
        has_youtube_id=has_youtube_id,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
def api_db_stats():
    _ensure_init()
    from core.metadata_db import get_stats
    return get_stats()


@router.get("/duplicates")
def api_db_duplicates():
    _ensure_init()
    from core.metadata_db import get_duplicate_topics
    return get_duplicate_topics()


@router.post("/sync/{history_name}")
def api_db_sync(history_name: str):
    """指定フォルダを DB に同期する。"""
    if ".." in history_name or "/" in history_name or "\\" in history_name:
        raise HTTPException(status_code=400, detail="無効な履歴名です")
    _ensure_init()
    from core.output_paths import OUTPUT_DIR
    from core.metadata_db import sync_folder_to_db
    import os
    folder = os.path.join(OUTPUT_DIR, history_name)
    if not os.path.isdir(folder):
        folder = os.path.join(OUTPUT_DIR, "000_uploaded", history_name)
    if not os.path.isdir(folder):
        raise HTTPException(status_code=404, detail="フォルダが見つかりません")
    sync_folder_to_db(folder)
    return {"ok": True, "synced": history_name}


@router.post("/import-all")
def api_db_import_all():
    """output/ 配下の全フォルダを DB に取り込む（非同期ジョブ）。"""
    _ensure_init()
    from web_app.job_manager import get_job_manager, _log
    from web_app.job_manager import Job

    def _run(job: Job):
        from core.output_paths import OUTPUT_DIR
        from core.metadata_db import sync_folder_to_db, initialize_db
        import os
        initialize_db()
        ok = fail = 0
        for root, dirs, _ in os.walk(OUTPUT_DIR):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            meta = os.path.join(root, "_meta")
            if os.path.isdir(meta):
                dirs.clear()
                local_id = os.path.basename(root)
                try:
                    sync_folder_to_db(root)
                    ok += 1
                    _log(job, f"✅ {local_id}", "info")
                except Exception as e:
                    fail += 1
                    _log(job, f"❌ {local_id}: {e}", "error")
        _log(job, f"完了: 成功={ok} / 失敗={fail}", "success")
        return {"ok": ok, "fail": fail}

    mgr = get_job_manager()
    job = mgr.create_job("db_import")
    mgr.submit(job, _run)
    return {"job_id": job.job_id}
