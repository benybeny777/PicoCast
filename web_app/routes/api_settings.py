import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from web_app.services.status_service import get_settings_status
from web_app.services.config_service import get_editable_config, save_config
from web_app.services.secrets_service import save_secrets
from config.config import config as cfg

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
    """設定を .env に書き込み、可能なものは現在プロセスへ反映する。"""
    errors = save_config(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": list(updates.keys()), "note": "保存しました。一部の起動時設定は再起動後に反映されます。"}


@router.post("/secrets")
def api_save_secrets(updates: dict[str, str]):
    """APIキーを .env に書き込む。値はレスポンスに含めない。"""
    errors = save_secrets(updates)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return {"saved": list(updates.keys())}


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
