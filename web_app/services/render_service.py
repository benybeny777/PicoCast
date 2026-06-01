"""
動画（MP4）のみ再レンダリングサービス。
native_renderer をサブプロセス（worker_render.py）で実行してメモリを解放する。
"""
import os
from typing import Any

from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import find_history_dir
from web_app.worker_runner import run_in_worker


def submit_render_job(
    history_name: str,
    bgm_mode: str = "profile_default",
    bgm_id: str | None = None,
    bgm_volume_db: float | None = None,
) -> str:
    """動画再レンダリングジョブを登録してjob_idを返す。"""
    _validate_name(history_name)
    theme_dir = find_history_dir(history_name)
    if theme_dir is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    mgr = get_job_manager()
    job = mgr.create_job("render")
    _log(job, f"動画再レンダリングジョブを登録: {history_name}", "info")
    mgr.submit(job, _run_render, history_name, bgm_mode, bgm_id, bgm_volume_db)
    return job.job_id


def _run_render(
    job: Job,
    history_name: str,
    bgm_mode: str,
    bgm_id: str | None,
    bgm_volume_db: float | None,
) -> dict[str, Any]:
    theme_dir = find_history_dir(history_name)
    if theme_dir is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")
    _log(job, "audio/ と backgrounds/ から MP4 を再生成します", "info")
    _log(job, f"対象フォルダ: {theme_dir}", "info")

    worker_result = run_in_worker(
        "workers/worker_render.py",
        {
            "history_name": history_name,
            "theme_dir": theme_dir,
            "bgm_mode": bgm_mode,
            "bgm_id": bgm_id,
            "bgm_volume_db": bgm_volume_db,
        },
        job,
    )

    status = worker_result.get("status")
    if status == "cancelled":
        return {"cancelled": True}
    if status == "failed":
        raise RuntimeError(worker_result.get("error", "レンダリングエラー"))

    output_path = worker_result.get("output_path", "")
    _log(job, f"MP4 生成完了: {os.path.basename(output_path)}", "success")
    return {"output_path": output_path, "history_name": history_name}


def _validate_name(name: str) -> None:
    if ".." in name or "/" in name or "\\" in name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
