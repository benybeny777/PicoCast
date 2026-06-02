from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from web_app.services.status_service import get_settings_status
from web_app.services.config_service import get_editable_config, save_config
from web_app.services.status_service import invalidate_settings_status_cache
from web_app.services.settings_preload_service import (
    get_cached_ollama_models,
    get_cached_bgm_files,
    invalidate_bgm_files_cache,
)
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
    invalidate_bgm_files_cache()
    return {"saved": list(updates.keys()), "note": "保存しました。"}


@router.post("/secrets")
def api_save_secrets(updates: dict[str, str]):
    """APIキーを DB へ暗号化保存する（後方互換エンドポイント）。値はレスポンスに含めない。"""
    errors = save_secrets(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"saved": list(updates.keys())}


# ── 認証情報管理エンドポイント ────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    secret_type: str
    value: str
    profile_id: str | None = None


class ClientSecretsRequest(BaseModel):
    json_text: str
    profile_id: str | None = None


class DeleteSecretRequest(BaseModel):
    secret_type: str
    profile_id: str | None = None
    confirmed: bool = False


class DeleteLegacyFileRequest(BaseModel):
    filename: str
    confirmed: bool = False


@router.get("/secrets/status")
def api_secret_status(profile_id: str | None = None):
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
    errors = save_api_key(req.secret_type, req.value, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"saved": req.secret_type, "profile_id": req.profile_id}


@router.post("/secrets/client-secrets")
def api_save_client_secrets(req: ClientSecretsRequest):
    """YouTube client_secrets JSON を DB へ暗号化保存する。"""
    errors = save_client_secrets(req.json_text, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"saved": "youtube_client_secrets", "profile_id": req.profile_id}


@router.delete("/secrets/api-key")
def api_delete_api_key(req: DeleteSecretRequest):
    """APIキーを DB から削除する。confirmed=true 必須。"""
    if not req.confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    errors = delete_api_key(req.secret_type, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
    return {"deleted": req.secret_type}


@router.delete("/secrets/youtube")
def api_delete_youtube_secret(req: DeleteSecretRequest):
    """YouTube シークレットを DB から削除する。confirmed=true 必須。"""
    if not req.confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    errors = delete_youtube_secret(req.secret_type, profile_id=req.profile_id)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    invalidate_settings_status_cache()
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
    return get_cached_bgm_files()


class ReadingDictEntry(BaseModel):
    word: str
    reading: str


@router.get("/reading-dict")
def api_get_reading_dict():
    """よみがな辞書（同梱・ユーザー）を返す。"""
    from core import reading_dictionary_store
    data = reading_dictionary_store.load_all()
    entries = []
    for dict_type, values in data.items():
        for word, reading in values.items():
            entries.append({"dict_type": dict_type, "word": word, "reading": reading})
    entries.sort(key=lambda x: (x["dict_type"], x["word"]))
    return {"base": data["base"], "user": data["user"], "entries": entries}


@router.post("/reading-dict/base")
def api_add_reading_dict_base(entry: ReadingDictEntry):
    """同梱辞書にエントリを追加/上書きする。"""
    from core import reading_dictionary_store
    word = entry.word.strip()
    reading = entry.reading.strip()
    if not word or not reading:
        raise HTTPException(status_code=422, detail="word と reading は必須です")
    reading_dictionary_store.upsert_entry("base", word, reading)
    return {"saved": word, "reading": reading}


@router.delete("/reading-dict/base/{word:path}")
def api_delete_reading_dict_base(word: str):
    """同梱辞書からエントリを削除する。"""
    from core import reading_dictionary_store
    if not reading_dictionary_store.delete_entry("base", word):
        raise HTTPException(status_code=404, detail=f"'{word}' が辞書にありません")
    return {"deleted": word}


@router.delete("/reading-dict/user/{word:path}")
def api_delete_reading_dict_user(word: str):
    """ユーザー辞書からエントリを削除する。"""
    from core import reading_dictionary_store
    if not reading_dictionary_store.delete_entry("user", word):
        raise HTTPException(status_code=404, detail=f"'{word}' が辞書にありません")
    return {"deleted": word}


@router.get("/debug-log")
def api_debug_log():
    """デバッグログの末尾行を返す。"""
    from web_app.services.debug_log_service import recent_debug_log
    return recent_debug_log()


@router.get("/ollama-models")
def api_ollama_models():
    """Ollama が起動していれば利用可能なモデル一覧を返す。"""
    return get_cached_ollama_models()
