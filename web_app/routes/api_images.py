import mimetypes
import os
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from web_app.schemas import ImageRegenerateRequest
from web_app.services.image_service import list_images, submit_regenerate_job, save_bg_prompts
from web_app.services.image_replace_service import list_replacements, replace_image, restore_image
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
        sd_size_mode=req.sd_size_mode,
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/{history_name}/save-prompts")
def api_save_prompts(history_name: str, req: SavePromptsRequest):
    saved = save_bg_prompts(history_name, req.prompts)
    return {"saved": saved, "count": len(saved)}


@router.post("/{history_name}/replace")
async def api_replace_image(
    history_name: str,
    target_key: str = Form(...),
    confirmed: bool = Form(False),
    image_file: UploadFile = File(...),
):
    try:
        content = await image_file.read()
        return replace_image(history_name, target_key, content, image_file.filename or "", confirmed)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        await image_file.close()


@router.get("/{history_name}/replacements")
def api_replacements(history_name: str):
    try:
        return list_replacements(history_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class RestoreImageRequest(BaseModel):
    replacement_id: int
    confirmed: bool = False


@router.post("/{history_name}/restore")
def api_restore_image(history_name: str, req: RestoreImageRequest):
    try:
        return restore_image(history_name, req.replacement_id, req.confirmed)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{history_name}/file/{file_path:path}")
def serve_file(history_name: str, file_path: str):
    """output/{history_name}/{file_path} を返す。画像・動画どちらも対応。output配下のみ許可。"""
    rel = f"{history_name}/{file_path}"
    full_path = safe_output_path(rel)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")
    media_type, _ = mimetypes.guess_type(full_path)
    return FileResponse(full_path, media_type=media_type or "application/octet-stream")
