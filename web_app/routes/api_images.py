import mimetypes
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from web_app.schemas import ImageRegenerateRequest
from web_app.services.image_service import list_images, submit_regenerate_job, save_bg_prompts
from web_app.security import safe_output_path


class SavePromptsRequest(BaseModel):
    prompts: dict[str, str]  # key → prompt_text

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/{history_name}")
def api_list_images(history_name: str):
    return list_images(history_name)


@router.post("/{history_name}/regenerate")
def api_regenerate(history_name: str, req: ImageRegenerateRequest):
    job_id = submit_regenerate_job(
        history_name, req.image_keys, req.prompts,
        background_engine=req.background_engine,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/{history_name}/save-prompts")
def api_save_prompts(history_name: str, req: SavePromptsRequest):
    saved = save_bg_prompts(history_name, req.prompts)
    return {"saved": saved, "count": len(saved)}


@router.get("/{history_name}/file/{file_path:path}")
def serve_file(history_name: str, file_path: str):
    """output/{history_name}/{file_path} を返す。画像・動画どちらも対応。output配下のみ許可。"""
    rel = f"{history_name}/{file_path}"
    full_path = safe_output_path(rel)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")
    media_type, _ = mimetypes.guess_type(full_path)
    return FileResponse(full_path, media_type=media_type or "application/octet-stream")
