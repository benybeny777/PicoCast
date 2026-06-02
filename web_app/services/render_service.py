"""動画（MP4）のみ再レンダリングサービス。"""

from web_app.job_manager import _log, get_job_manager
from web_app.security import find_history_dir


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
    job = mgr.create_job("render", params={
        "history_name": history_name,
        "theme_dir": theme_dir,
        "bgm_mode": bgm_mode,
        "bgm_id": bgm_id,
        "bgm_volume_db": bgm_volume_db,
    })
    _log(job, f"動画再レンダリングジョブを登録: {history_name}", "info")
    return job.job_id


def _validate_name(name: str) -> None:
    if ".." in name or "/" in name or "\\" in name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
