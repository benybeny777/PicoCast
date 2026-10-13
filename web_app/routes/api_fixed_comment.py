from fastapi import APIRouter, HTTPException, Query
from web_app.schemas import FixedCommentMarkAllPostedRequest, FixedCommentMarkPostedRequest, FixedCommentRequest
from web_app.services.fixed_comment_service import (
    list_fixed_comment_candidates,
    mark_all_fixed_comments_posted,
    mark_fixed_comment_posted,
    submit_fixed_comment_job,
)

router = APIRouter(prefix="/api/fixed-comment", tags=["fixed_comment"])


@router.get("/auto-status")
def api_fixed_comment_auto_status():
    """OSタスクから実行される自動投稿の前回結果（未実行なら last_run は null）。"""
    from core import background_task_status
    from web_app.services.auto_fixed_comment_service import TASK_NAME
    return {"last_run": background_task_status.last_run(TASK_NAME)}


@router.get("/candidates")
def api_fixed_comment_candidates(only_unposted: bool = Query(True)):
    return list_fixed_comment_candidates(only_unposted=only_unposted)


@router.post("")
def api_fixed_comment(req: FixedCommentRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です（確認ダイアログを経てから送信してください）")
    job_id = submit_fixed_comment_job(req.history_name)
    return {"job_id": job_id, "status": "queued"}


@router.post("/mark-posted")
def api_fixed_comment_mark_posted(req: FixedCommentMarkPostedRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です（確認ダイアログを経てから送信してください）")
    return mark_fixed_comment_posted(req.history_name)


@router.post("/mark-all-posted")
def api_fixed_comment_mark_all_posted(req: FixedCommentMarkAllPostedRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です（確認ダイアログを経てから送信してください）")
    return mark_all_fixed_comments_posted()
