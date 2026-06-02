"""
設定画面で使う補助データのプリロード。

Ollama モデル一覧など外部サービスに触れる処理は起動時に先読みし、
画面表示時はキャッシュ済みデータか暫定値を即返す。
"""
import os
import logging
import threading
from typing import Any

import httpx

from config import config as cfg

_logger = logging.getLogger(__name__)
_ollama_models_cache: dict[str, Any] | None = None
_bgm_files_cache: dict[str, Any] | None = None
_cache_lock = threading.Lock()
_ollama_refreshing = False
_bgm_refreshing = False


def preload_settings_screen_cache() -> None:
    """Web UI 起動時に設定画面用の補助データを先読みする。"""
    refresh_ollama_models_cache()
    refresh_bgm_files_cache()


def get_cached_ollama_models() -> dict[str, Any]:
    """Ollama モデル一覧を返す。未キャッシュなら裏で取得を開始して即返す。"""
    with _cache_lock:
        cached = _ollama_models_cache
    if cached is not None:
        return cached
    _start_ollama_refresh()
    return {"models": [], "available": False, "cached": False, "refreshing": True}


def refresh_ollama_models_cache() -> dict[str, Any]:
    """Ollama モデル一覧を取得してキャッシュする。"""
    global _ollama_models_cache, _ollama_refreshing
    with _cache_lock:
        _ollama_refreshing = True
    try:
        data = _fetch_ollama_models()
        with _cache_lock:
            _ollama_models_cache = data
        return data
    finally:
        with _cache_lock:
            _ollama_refreshing = False


def invalidate_ollama_models_cache() -> None:
    """Ollama モデル一覧キャッシュを破棄する。"""
    global _ollama_models_cache
    with _cache_lock:
        _ollama_models_cache = None


def get_cached_bgm_files() -> dict[str, Any]:
    """assets/bgm のファイル一覧を返す。未キャッシュなら裏で取得を開始して即返す。"""
    with _cache_lock:
        cached = _bgm_files_cache
    if cached is not None:
        return cached
    _start_bgm_refresh()
    return {"files": [], "available": True, "cached": False, "refreshing": True}


def refresh_bgm_files_cache() -> dict[str, Any]:
    """assets/bgm のファイル一覧を取得してキャッシュする。"""
    global _bgm_files_cache, _bgm_refreshing
    with _cache_lock:
        _bgm_refreshing = True
    try:
        data = _fetch_bgm_files()
        with _cache_lock:
            _bgm_files_cache = data
        return data
    finally:
        with _cache_lock:
            _bgm_refreshing = False


def invalidate_bgm_files_cache() -> None:
    """BGM ファイル一覧キャッシュを破棄する。"""
    global _bgm_files_cache
    with _cache_lock:
        _bgm_files_cache = None


def _start_ollama_refresh() -> None:
    global _ollama_refreshing
    with _cache_lock:
        if _ollama_refreshing:
            return
        _ollama_refreshing = True
    thread = threading.Thread(target=_refresh_ollama_worker, daemon=True, name="settings-ollama-preload")
    thread.start()


def _refresh_ollama_worker() -> None:
    try:
        data = _fetch_ollama_models()
        with _cache_lock:
            global _ollama_models_cache
            _ollama_models_cache = data
    finally:
        with _cache_lock:
            global _ollama_refreshing
            _ollama_refreshing = False


def _start_bgm_refresh() -> None:
    global _bgm_refreshing
    with _cache_lock:
        if _bgm_refreshing:
            return
        _bgm_refreshing = True
    thread = threading.Thread(target=_refresh_bgm_worker, daemon=True, name="settings-bgm-preload")
    thread.start()


def _refresh_bgm_worker() -> None:
    try:
        data = _fetch_bgm_files()
        with _cache_lock:
            global _bgm_files_cache
            _bgm_files_cache = data
    finally:
        with _cache_lock:
            global _bgm_refreshing
            _bgm_refreshing = False


def _fetch_ollama_models() -> dict[str, Any]:
    base = getattr(cfg, "OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=cfg.WEB_VOICEVOX_CHECK_TIMEOUT_SEC)
        models = [m["name"] for m in r.json().get("models", [])]
        return {"models": sorted(models), "available": True, "cached": True, "refreshing": False}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        _logger.debug("[SettingsPreload] Ollama モデル一覧を取得できません: %s", e)
        return {"models": [], "available": False, "cached": True, "refreshing": False}


def _fetch_bgm_files() -> dict[str, Any]:
    bgm_dir = os.path.join(cfg.ASSETS_DIR, "bgm")
    try:
        files = sorted(
            f for f in os.listdir(bgm_dir)
            if os.path.splitext(f)[1].lower() in (".mp3", ".wav", ".ogg", ".aac", ".flac", ".m4a")
        )
        return {"files": files, "available": True, "cached": True, "refreshing": False}
    except OSError as e:
        _logger.debug("[SettingsPreload] BGMファイル一覧を取得できません: %s", e)
        return {"files": [], "available": False, "cached": True, "refreshing": False}
