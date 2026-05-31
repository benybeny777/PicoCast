import os
import subprocess
import sys

from fastapi import APIRouter, Body, HTTPException, Query
from web_app.schemas import HistoryRegenerateRequest
from web_app.services.history_service import list_histories, get_history_detail
from web_app.services.generation_service import submit_history_regenerate_jobs
from web_app.services.render_service import submit_render_job
from web_app.security import safe_output_path

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def api_list_history(
    include_management: bool = Query(False),
    include_uploaded: bool = Query(False),
):
    return list_histories(
        include_management=include_management,
        include_uploaded=include_uploaded,
    )


@router.get("/{history_name}")
def api_get_history(history_name: str):
    detail = get_history_detail(history_name)
    if detail is None:
        raise HTTPException(status_code=404, detail="履歴が見つかりません")
    return detail


@router.post("/{history_name}/render")
def api_render(history_name: str, confirmed: bool = Body(False, embed=True)):
    """既存の audio/ + backgrounds/ から MP4 を再生成する。confirmed=true 必須。"""
    if not confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です")
    job_id = submit_render_job(history_name)
    return {"job_id": job_id, "status": "queued"}


@router.post("/{history_name}/open-folder")
def api_open_folder(history_name: str):
    """出力フォルダをOSのファイルマネージャーで開く（127.0.0.1専用ローカル操作）。"""
    path = safe_output_path(history_name)
    if not os.path.isdir(path):
        raise HTTPException(status_code=404, detail="フォルダが見つかりません")
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return {"opened": path}


@router.get("/{history_name}/fixed-comment-copy")
def api_fixed_comment_copy(history_name: str):
    """metadata.db の固定コメント本文を返す。"""
    local_id = os.path.basename(history_name.replace("\\", "/"))
    from core.metadata_db import ManagedConnection, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        row = conn.execute(
            "SELECT fixed_comment FROM video_metadata WHERE local_id=?",
            (local_id,),
        ).fetchone()
    if row and row["fixed_comment"]:
        return {"exists": True, "text": row["fixed_comment"]}
    return {"exists": False, "text": ""}


@router.get("/{history_name}/poll-copy")
def api_poll_copy(history_name: str):
    """アンケート用コピーテキストはローカルファイル正本を廃止済みのため返さない。"""
    return {"exists": False, "text": ""}


@router.post("/regenerate")
def api_regenerate_histories(req: HistoryRegenerateRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です")
    if not req.history_names:
        raise HTTPException(status_code=400, detail="history_namesが空です")
    job_ids = submit_history_regenerate_jobs(
        req.history_names,
        req.image_style,
        req.background_engine,
        req.reuse_backgrounds,
        req.long_thumbnail_ab_test,
        req.long_budget_mode,
        req.sd_size_mode,
        req.with_render,
    )
    if not job_ids:
        raise HTTPException(status_code=404, detail="再生成可能なscript.txtが見つかりません")
    return {"job_ids": job_ids, "count": len(job_ids)}
