from fastapi import APIRouter, HTTPException
from web_app.schemas import UploadRequest, BatchUploadRequest
from web_app.services.upload_service import list_upload_candidates, submit_upload_job

router = APIRouter(prefix="/api/upload", tags=["upload"])


def _require_channel() -> None:
    """CHANNEL_NAME / CHANNEL_HANDLE 未設定ならアップロードを禁止する。"""
    from core.channel_info import get_channel_info
    ch = get_channel_info()
    if not ch["upload_allowed"]:
        missing = [w["message"] for w in ch["warnings"] if w["level"] == "error"]
        raise HTTPException(
            status_code=400,
            detail="チャンネル設定不足のためアップロード禁止: " + "、".join(missing),
        )


@router.get("/candidates")
def api_upload_candidates():
    return list_upload_candidates()


@router.post("")
def api_upload(req: UploadRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です")
    _require_channel()
    job_id = submit_upload_job(req.history_name)
    return {"job_id": job_id, "status": "queued"}


@router.post("/batch")
def api_batch_upload(req: BatchUploadRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です")
    if not req.history_names:
        raise HTTPException(status_code=400, detail="history_namesが空です")
    _require_channel()
    job_ids = [submit_upload_job(name) for name in req.history_names]
    return {"job_ids": job_ids, "count": len(job_ids)}
