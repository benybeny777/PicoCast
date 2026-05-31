import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from web_app.services.status_service import get_settings_status
from web_app.services.config_service import get_editable_config, save_config
from web_app.services.secrets_service import (
    save_secrets,
    save_api_key,
    save_client_secrets,
    delete_api_key,
    delete_youtube_secret,
    get_secret_status,
    get_legacy_file_status,
    delete_legacy_file,
)
from config import config as cfg

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status")
def api_settings_status():
    """設定診断。秘密値（APIキー本体）は返さない。"""
    return get_settings_status()


@router.post("/status/refresh")
def api_refresh_status():
    """サービスチェックを再実行してキャッシュを更新する。"""
    from web_app.services.status_service import refresh_settings_status
    return refresh_settings_status()


@router.get("/config")
def api_get_config():
    """編集可能な設定項目と現在値を返す。"""
    return get_editable_config()


@router.post("/config")
def api_save_config(updates: dict[str, str]):
    """設定を DB に保存し、可能なものは現在プロセスへ反映する。"""
    errors = save_config(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": list(updates.keys()), "note": "保存しました。"}


@router.post("/secrets")
def api_save_secrets(updates: dict[str, str]):
    """APIキーを DB へ暗号化保存する（後方互換エンドポイント）。値はレスポンスに含めない。"""
    errors = save_secrets(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": list(updates.keys())}


# ── 認証情報管理エンドポイント ────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    secret_type: str
    value: str


class ClientSecretsRequest(BaseModel):
    json_text: str
    profile_id: str = "default"


class DeleteSecretRequest(BaseModel):
    secret_type: str
    profile_id: str = "default"
    confirmed: bool = False


class DeleteLegacyFileRequest(BaseModel):
    filename: str
    confirmed: bool = False


@router.get("/secrets/status")
def api_secret_status(profile_id: str = "default"):
    """各シークレットの登録状態を返す（値は一切返さない）。"""
    db_status = get_secret_status(profile_id=profile_id)
    legacy_status = get_legacy_file_status()
    return {
        "secrets": db_status,
        "legacy_files": legacy_status,
    }


@router.post("/secrets/api-key")
def api_save_api_key(req: ApiKeyRequest):
    """APIキー（google_api_key / openai_api_key / hf_token）を DB へ暗号化保存する。"""
    errors = save_api_key(req.secret_type, req.value)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": req.secret_type}


@router.post("/secrets/client-secrets")
def api_save_client_secrets(req: ClientSecretsRequest):
    """YouTube client_secrets JSON を DB へ暗号化保存する。"""
    errors = save_client_secrets(req.json_text, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": "youtube_client_secrets", "profile_id": req.profile_id}


@router.delete("/secrets/api-key")
def api_delete_api_key(req: DeleteSecretRequest):
    """APIキーを DB から削除する。confirmed=true 必須。"""
    if not req.confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    errors = delete_api_key(req.secret_type)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"deleted": req.secret_type}


@router.delete("/secrets/youtube")
def api_delete_youtube_secret(req: DeleteSecretRequest):
    """YouTube シークレットを DB から削除する。confirmed=true 必須。"""
    if not req.confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    errors = delete_youtube_secret(req.secret_type, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"deleted": req.secret_type, "profile_id": req.profile_id}


@router.delete("/secrets/legacy-file")
def api_delete_legacy_file(req: DeleteLegacyFileRequest):
    """
    旧認証ファイルを削除する。
    confirmed=true 必須。DB 未移行の値がある場合は拒否する。
    """
    result = delete_legacy_file(req.filename, confirmed=req.confirmed)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "削除失敗"))
    return result


@router.get("/bgm-files")
def api_bgm_files():
    """assets/bgm/ 内の音声ファイル一覧を返す。"""
    bgm_dir = os.path.join(cfg.ASSETS_DIR, "bgm")
    try:
        files = sorted(
            f for f in os.listdir(bgm_dir)
            if os.path.splitext(f)[1].lower() in (".mp3", ".wav", ".ogg", ".aac", ".flac", ".m4a")
        )
        return {"files": files, "available": True}
    except Exception:
        return {"files": [], "available": False}


class ReadingDictEntry(BaseModel):
    word: str
    reading: str


def _load_reading_dict(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_reading_dict(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("/reading-dict")
def api_get_reading_dict():
    """よみがな辞書（同梱・ユーザー）を返す。"""
    base = _load_reading_dict(cfg.VOICE_READING_BASE_DICT_PATH)
    user = _load_reading_dict(cfg.VOICE_READING_USER_DICT_PATH)
    return {"base": base, "user": user}


@router.post("/reading-dict/base")
def api_add_reading_dict_base(entry: ReadingDictEntry):
    """同梱辞書にエントリを追加/上書きする。"""
    word = entry.word.strip()
    reading = entry.reading.strip()
    if not word or not reading:
        raise HTTPException(status_code=422, detail="word と reading は必須です")
    base = _load_reading_dict(cfg.VOICE_READING_BASE_DICT_PATH)
    base[word] = reading
    _save_reading_dict(cfg.VOICE_READING_BASE_DICT_PATH, base)
    return {"saved": word, "reading": reading}


@router.delete("/reading-dict/base/{word:path}")
def api_delete_reading_dict_base(word: str):
    """同梱辞書からエントリを削除する。"""
    base = _load_reading_dict(cfg.VOICE_READING_BASE_DICT_PATH)
    if word not in base:
        raise HTTPException(status_code=404, detail=f"'{word}' が辞書にありません")
    del base[word]
    _save_reading_dict(cfg.VOICE_READING_BASE_DICT_PATH, base)
    return {"deleted": word}


@router.delete("/reading-dict/user/{word:path}")
def api_delete_reading_dict_user(word: str):
    """ユーザー辞書からエントリを削除する。"""
    user = _load_reading_dict(cfg.VOICE_READING_USER_DICT_PATH)
    if word not in user:
        raise HTTPException(status_code=404, detail=f"'{word}' が辞書にありません")
    del user[word]
    _save_reading_dict(cfg.VOICE_READING_USER_DICT_PATH, user)
    return {"deleted": word}


@router.get("/debug-log")
def api_debug_log():
    """デバッグログの末尾行を返す。"""
    from web_app.services.debug_log_service import recent_debug_log
    return recent_debug_log()


@router.get("/ollama-models")
def api_ollama_models():
    """Ollama が起動していれば利用可能なモデル一覧を返す。"""
    import httpx
    base = getattr(cfg, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=cfg.WEB_VOICEVOX_CHECK_TIMEOUT_SEC)
        models = [m["name"] for m in r.json().get("models", [])]
        return {"models": sorted(models), "available": True}
    except Exception:
        return {"models": [], "available": False}
