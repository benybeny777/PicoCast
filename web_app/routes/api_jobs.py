from fastapi import APIRouter, HTTPException
from web_app.job_manager import get_job_manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs():
    return get_job_manager().list_jobs()


@router.get("/{job_id}")
def get_job(job_id: str):
    job = get_job_manager().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return job.to_dict()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    ok = get_job_manager().cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"job_id": job_id, "status": "cancelled"}
