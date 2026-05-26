from fastapi import APIRouter
from web_app.services.analytics_service import (
    load_latest_analytics,
    list_analytics_files,
    submit_refresh_job,
    get_tsv_text,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def api_analytics():
    return {
        "files": list_analytics_files(),
        "data": load_latest_analytics(),
    }


@router.get("/tsv")
def api_analytics_tsv():
    return {"tsv": get_tsv_text()}


@router.post("/refresh")
def api_analytics_refresh():
    job_id = submit_refresh_job()
    return {"job_id": job_id, "status": "queued"}
