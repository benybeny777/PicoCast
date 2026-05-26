"""
動画（MP4）のみ再レンダリングサービス。
native_renderer をサブプロセス（worker_render.py）で実行してメモリを解放する。
"""
import os
from typing import Any

from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import safe_output_path
from web_app.worker_runner import run_in_worker


def submit_render_job(history_name: str) -> str:
    """動画再レンダリングジョブを登録してjob_idを返す。"""
    _validate_name(history_name)
    theme_dir = safe_output_path(history_name)
    if not os.path.isdir(theme_dir):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    mgr = get_job_manager()
    job = mgr.create_job("render")
    _log(job, f"動画再レンダリングジョブを登録: {history_name}", "info")
    mgr.submit(job, _run_render, history_name)
    return job.job_id


def _run_render(job: Job, history_name: str) -> dict[str, Any]:
    theme_dir = safe_output_path(history_name)
    _log(job, "audio/ と backgrounds/ から MP4 を再生成します", "info")
    _log(job, f"対象フォルダ: {theme_dir}", "info")

    worker_result = run_in_worker(
        "worker_render.py",
        {
            "history_name": history_name,
            "theme_dir": theme_dir,
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
