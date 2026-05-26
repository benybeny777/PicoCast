from fastapi import APIRouter, HTTPException
from web_app.services.status_service import get_settings_status
from web_app.services.config_service import get_editable_config, save_config
from web_app.services.secrets_service import save_secrets
import config as cfg

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status")
def api_settings_status():
    """設定診断。秘密値（APIキー本体）は返さない。"""
    return get_settings_status()


@router.get("/config")
def api_get_config():
    """編集可能な設定項目と現在値を返す。"""
    return get_editable_config()


@router.post("/config")
def api_save_config(updates: dict[str, str]):
    """設定を .env に書き込む。変更は再起動後に有効になる。"""
    errors = save_config(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": list(updates.keys()), "note": "変更は再起動後に反映されます"}


@router.post("/secrets")
def api_save_secrets(updates: dict[str, str]):
    """APIキーを .env に書き込む。値はレスポンスに含めない。"""
    errors = save_secrets(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": list(updates.keys())}


@router.get("/ollama-models")
def api_ollama_models():
    """Ollama が起動していれば利用可能なモデル一覧を返す。"""
    import httpx
    base = getattr(cfg, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=3.0)
        models = [m["name"] for m in r.json().get("models", [])]
        return {"models": sorted(models), "available": True}
    except Exception:
        return {"models": [], "available": False}
