import logging
import threading
from fastapi import APIRouter
from pydantic import BaseModel
from core.comfyui_model_manager import ComfyUIModelManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/comfyui", tags=["comfyui"])

# {model_name: {status, downloaded, total, percent, message}}
# status: "downloading" | "verifying" | "done" | "error"
_progress: dict[str, dict] = {}
_install_all_lock = threading.Lock()
_install_all_running = False


class DownloadRequest(BaseModel):
    name: str


def _make_progress(status: str, downloaded: int = 0, total: int = 0, message: str = "") -> dict:
    percent = int(downloaded * 100 / total) if total > 0 else (100 if status == "done" else 0)
    return {"status": status, "downloaded": downloaded, "total": total, "percent": percent, "message": message}


def _run_download(name: str) -> None:
    try:
        manager = ComfyUIModelManager()

        def cb(dl: int, total: int) -> None:
            _progress[name] = _make_progress("downloading", dl, total)

        _progress[name] = _make_progress("downloading")
        manager.download_model(name, progress_callback=cb)
        _progress[name] = _make_progress("done")
    except Exception as e:
        logger.exception("モデルのダウンロードに失敗しました: %s", name)
        _progress[name] = _make_progress("error", message=str(e))


@router.get("/models")
def get_models():
    """全モデルの状態を取得する"""
    manager = ComfyUIModelManager()
    models = manager.get_model_status()
    return {"status": "ok", "models": models}


@router.get("/models/progress")
def get_progress():
    """ダウンロード進捗を返す。ポーリング用。"""
    return {"progress": _progress, "install_all_running": _install_all_running}


@router.post("/models/install")
def install_model(req: DownloadRequest):
    """特定のモデルをバックグラウンドでダウンロードする"""
    name = req.name
    if _progress.get(name, {}).get("status") == "downloading":
        return {"status": "error", "message": "すでにダウンロード中です"}
    threading.Thread(target=_run_download, args=(name,), daemon=True).start()
    return {"status": "started"}


@router.post("/models/install_all")
def install_all_models():
    """自動ダウンロード可能な不足モデルをすべてバックグラウンドでダウンロードする"""
    global _install_all_running
    with _install_all_lock:
        if _install_all_running:
            return {"status": "error", "message": "すでに一括ダウンロード中です"}
        _install_all_running = True

    manager = ComfyUIModelManager()
    targets = [m for m in manager.get_model_status() if m["status"] == "missing" and not m["manual_download"]]
    names = [m["name"] for m in targets]

    def run_all() -> None:
        global _install_all_running
        try:
            for name in names:
                if _progress.get(name, {}).get("status") == "downloading":
                    continue
                _run_download(name)
        finally:
            _install_all_running = False

    threading.Thread(target=run_all, daemon=True).start()
    return {"status": "started", "names": names}
