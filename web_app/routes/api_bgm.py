import os
import tempfile
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from core.bgm_store import (
    create_bgm_asset,
    disable_bgm_asset,
    list_bgm_assets,
    set_default_bgm,
    update_bgm_asset,
)

router = APIRouter(prefix="/api/bgm", tags=["bgm"])


class BgmUpdateRequest(BaseModel):
    display_name: str | None = None
    default_volume_db: float | None = None
    loop_enabled: bool | None = None
    note: str | None = None


class BgmDeleteRequest(BaseModel):
    confirmed: bool = False


@router.get("")
def api_list_bgm(include_disabled: bool = False):
    return {"items": list_bgm_assets(include_disabled=include_disabled)}


@router.post("")
async def api_create_bgm(
    audio_file: UploadFile = File(...),
    display_name: str = Form(""),
    default_volume_db: float = Form(-20.0),
    loop_enabled: bool = Form(True),
    is_default: bool = Form(False),
    note: str = Form(""),
):
    suffix = os.path.splitext(audio_file.filename or "")[1].lower()
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name
            while True:
                chunk = await audio_file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
        name = display_name.strip() or os.path.splitext(audio_file.filename or "")[0]
        return create_bgm_asset(
            display_name=name,
            source_path=temp_path,
            default_volume_db=default_volume_db,
            loop_enabled=loop_enabled,
            is_default=is_default,
            note=note,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        await audio_file.close()
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.put("/{bgm_id}")
def api_update_bgm(bgm_id: str, req: BgmUpdateRequest):
    try:
        updates: dict[str, Any] = {k: v for k, v in req.model_dump().items() if v is not None}
        return update_bgm_asset(bgm_id, updates)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{bgm_id}/default")
def api_set_default_bgm(bgm_id: str):
    try:
        return set_default_bgm(bgm_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{bgm_id}")
def api_delete_bgm(bgm_id: str, req: BgmDeleteRequest):
    try:
        return disable_bgm_asset(bgm_id, confirmed=req.confirmed)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
