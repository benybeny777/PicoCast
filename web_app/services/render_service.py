"""
動画（MP4）のみ再レンダリングサービス。
既存の audio/ と backgrounds/ を使って native_renderer で MP4 を再生成する。
台本・音声・画像は変更しない。
"""
import os
from typing import Any

from core.output_paths import OUTPUT_DIR
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import safe_output_path


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
    from core.native_renderer import render_native_test

    theme_dir = safe_output_path(history_name)

    _log(job, "audio/ と backgrounds/ から MP4 を再生成します", "info")
    _log(job, f"対象フォルダ: {theme_dir}", "info")

    if job.cancel_event.is_set():
        return {"cancelled": True}

    try:
        result = render_native_test(
            output_dir=theme_dir,
            progress_callback=lambda msg: _log(job, msg, "info"),
        )
    except Exception as e:
        _log(job, f"レンダリングエラー: {e}", "error")
        raise

    output_path = result.output_path if hasattr(result, "output_path") else str(result)
    _log(job, f"MP4 生成完了: {os.path.basename(output_path)}", "success")
    return {"output_path": output_path, "history_name": history_name}


def _validate_name(name: str) -> None:
    if ".." in name or "/" in name or "\\" in name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
