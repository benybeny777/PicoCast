"""手動のOllama再生リスト振り分けAPI。"""
from fastapi import APIRouter, HTTPException

from web_app.schemas import PlaylistClassifierRequest
from web_app.services.playlist_classifier_service import (
    list_classifier_candidates,
    submit_playlist_classifier_job,
)

router = APIRouter(prefix="/api/playlist-classifier", tags=["playlist-classifier"])


@router.get("/candidates")
def api_playlist_classifier_candidates():
    return list_classifier_candidates()


@router.post("")
def api_playlist_classifier(req: PlaylistClassifierRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=trueが必要です")
    if not req.history_names:
        raise HTTPException(status_code=400, detail="history_namesが空です")
    job_id = submit_playlist_classifier_job(
        req.history_names,
        only_unregistered=req.only_unregistered,
    )
    return {"job_id": job_id, "status": "queued"}
