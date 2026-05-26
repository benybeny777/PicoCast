from fastapi import APIRouter
from web_app.schemas import CheckRequest
from web_app.services.script_check_service import submit_check_job

router = APIRouter(prefix="/api/check", tags=["check"])


@router.post("")
def api_check(req: CheckRequest):
    job_id = submit_check_job(req.script)
    return {"job_id": job_id, "status": "queued"}
