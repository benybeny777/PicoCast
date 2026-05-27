"""
SD WebUI Forge モデル管理 API ルート。

GET  /api/sd-models            — マニフェスト内全モデルのステータス
GET  /api/sd-models/webui      — SD WebUI API からインストール済みモデル一覧
GET  /api/sd-models/current    — SD WebUI の現在ロード済みモデル名
GET  /api/sd-models/progress   — ダウンロード進捗確認（ポーリング用）
POST /api/sd-models/download        — マニフェスト内モデルをダウンロード（バックグラウンド）
POST /api/sd-models/delete          — モデルファイルを削除（confirmed=true 必須）
POST /api/sd-models/delete-redownload — 削除して再ダウンロード（confirmed=true 必須）
POST /api/sd-models/use        — SD WebUI のアクティブモデルを切り替える
POST /api/sd-models/rescan     — SD WebUI に再スキャンを依頼する
"""
import logging
import threading

from fastapi import APIRouter
from pydantic import BaseModel

from web_app.services import sd_model_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sd-models", tags=["sd_models"])

# {model_id: {status, downloaded, total, percent, message}}
# status: "downloading" | "verifying" | "done" | "error"
_progress: dict[str, dict] = {}
_download_lock = threading.Lock()


class ModelIdRequest(BaseModel):
    model_id: str


class ModelIdConfirmedRequest(BaseModel):
    model_id: str
    confirmed: bool = False


class ModelNameRequest(BaseModel):
    model_name: str


def _make_progress(
    status: str,
    downloaded: int = 0,
    total: int = 0,
    message: str = "",
) -> dict:
    percent = int(downloaded * 100 / total) if total > 0 else (100 if status == "done" else 0)
    return {
        "status": status,
        "downloaded": downloaded,
        "total": total,
        "percent": percent,
        "message": message,
    }


def _run_download(model_id: str) -> None:
    """バックグラウンドダウンロードスレッド。"""
    try:
        def cb(filename: str, downloaded: int, total: int) -> None:
            _progress[model_id] = _make_progress("downloading", downloaded, total)

        _progress[model_id] = _make_progress("downloading")
        sd_model_service.download_model(model_id, progress_callback=cb)

        # ダウンロード成功後に SD WebUI に再スキャンを依頼（API が起動していれば）
        try:
            sd_model_service.rescan_models()
        except Exception:
            pass  # フォールバック許可: rescan は補助的操作。ダウンロード完了後の通知のみ

        _progress[model_id] = _make_progress("done")
    except Exception as e:
        logger.exception("SDモデルのダウンロードに失敗しました: %s", model_id)
        _progress[model_id] = _make_progress("error", message=str(e))


def _run_delete_redownload(model_id: str) -> None:
    """削除して再ダウンロードするバックグラウンドスレッド。"""
    try:
        _progress[model_id] = _make_progress("downloading", message="削除中...")
        sd_model_service.delete_model(model_id, confirmed=True)

        def cb(filename: str, downloaded: int, total: int) -> None:
            _progress[model_id] = _make_progress("downloading", downloaded, total)

        _progress[model_id] = _make_progress("downloading")
        sd_model_service.download_model(model_id, progress_callback=cb)

        try:
            sd_model_service.rescan_models()
        except Exception:
            pass

        _progress[model_id] = _make_progress("done")
    except Exception as e:
        logger.exception("SDモデルの削除・再ダウンロードに失敗しました: %s", model_id)
        _progress[model_id] = _make_progress("error", message=str(e))


# ─────────────────────────────────────────────
# GET エンドポイント
# ─────────────────────────────────────────────

@router.get("")
def list_models():
    """マニフェスト内全モデルのステータスを返す。"""
    try:
        models = sd_model_service.get_model_list()
        return {"status": "ok", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/webui")
def list_webui_models():
    """SD WebUI API からインストール済みモデル一覧を返す。"""
    try:
        models = sd_model_service.get_installed_models_from_webui()
        return {"status": "ok", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/current")
def get_current_model():
    """SD WebUI の現在ロード済みモデル名を返す。"""
    try:
        model = sd_model_service.get_current_model_from_webui()
        return {"status": "ok", "model": model}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/progress")
def get_progress():
    """ダウンロード進捗を返す（ポーリング用）。"""
    return {"progress": _progress}


# ─────────────────────────────────────────────
# POST エンドポイント
# ─────────────────────────────────────────────

@router.post("/download")
def download_model(req: ModelIdRequest):
    """指定モデルをバックグラウンドでダウンロード開始する。"""
    model_id = req.model_id
    with _download_lock:
        if _progress.get(model_id, {}).get("status") == "downloading":
            return {"status": "error", "message": "すでにダウンロード中です"}
    threading.Thread(target=_run_download, args=(model_id,), daemon=True).start()
    return {"status": "started", "model_id": model_id}


@router.post("/delete")
def delete_model(req: ModelIdConfirmedRequest):
    """指定モデルのファイルを削除する。confirmed=true 必須。"""
    if not req.confirmed:
        return {"status": "error", "message": "confirmed=true が必要です"}
    try:
        path = sd_model_service.delete_model(req.model_id, confirmed=True)
        return {"status": "ok", "deleted": path}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/delete-redownload")
def delete_and_redownload(req: ModelIdConfirmedRequest):
    """指定モデルを削除して再ダウンロードする（バックグラウンド）。confirmed=true 必須。"""
    if not req.confirmed:
        return {"status": "error", "message": "confirmed=true が必要です"}
    model_id = req.model_id
    with _download_lock:
        if _progress.get(model_id, {}).get("status") == "downloading":
            return {"status": "error", "message": "すでにダウンロード中です"}
    threading.Thread(target=_run_delete_redownload, args=(model_id,), daemon=True).start()
    return {"status": "started", "model_id": model_id}


@router.post("/use")
def use_model(req: ModelNameRequest):
    """SD WebUI のアクティブモデルを切り替える。"""
    try:
        sd_model_service.set_active_model(req.model_name)
        return {"status": "ok", "model_name": req.model_name}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/rescan")
def rescan():
    """SD WebUI に再スキャンを依頼する。"""
    try:
        sd_model_service.rescan_models()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
