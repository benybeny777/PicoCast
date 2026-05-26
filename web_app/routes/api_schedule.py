from fastapi import APIRouter, HTTPException, Query
from web_app.schemas import ScheduleUpdateRequest, ScheduleDeleteRequest
from web_app.services.schedule_service import (
    list_schedule,
    submit_sync_job,
    submit_rebalance_job,
    update_schedule,
    delete_schedule,
)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def api_schedule(
    video_type: str = Query("all"),
    include_published: bool = Query(False),
):
    return list_schedule(video_type_filter=video_type, include_published=include_published)


@router.post("/sync")
def api_schedule_sync():
    job_id = submit_sync_job()
    return {"job_id": job_id, "status": "queued"}


@router.post("/rebalance")
def api_schedule_rebalance():
    """スロット詰め直し変更案を計算する（YouTube APIへの書き込みなし）。"""
    job_id = submit_rebalance_job()
    return {"job_id": job_id, "status": "queued"}


@router.post("/update")
def api_schedule_update(req: ScheduleUpdateRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です")
    return update_schedule(req.video_id, req.publish_at)


@router.post("/delete")
def api_schedule_delete(req: ScheduleDeleteRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です")
    return delete_schedule(req.video_id)
