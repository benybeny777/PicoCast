import logging
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from core.comfyui_model_manager import ComfyUIModelManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/comfyui", tags=["comfyui"])

class DownloadRequest(BaseModel):
    name: str

@router.get("/models")
def get_models():
    """全モデルの状態を取得する"""
    try:
        manager = ComfyUIModelManager()
        models = manager.get_model_status()
        return {"status": "ok", "models": models}
    except Exception as e:
        logger.exception("ComfyUIモデル状態の取得に失敗しました")
        return {"status": "error", "message": str(e)}

@router.post("/models/install")
def install_model(req: DownloadRequest):
    """特定のモデルをダウンロードする"""
    try:
        manager = ComfyUIModelManager()
        manager.download_model(req.name)
        return {"status": "ok", "message": f"{req.name} のダウンロードと配置が完了しました。"}
    except Exception as e:
        logger.exception(f"モデルのダウンロードに失敗しました: {req.name}")
        return {"status": "error", "message": str(e)}

@router.post("/models/install_all")
def install_all_models():
    """自動ダウンロード可能な不足モデルをすべてダウンロードする"""
    try:
        manager = ComfyUIModelManager()
        models = manager.get_model_status()
        success_list = []
        error_list = []
        
        for model in models:
            if model["status"] == "missing" and not model["manual_download"]:
                try:
                    manager.download_model(model["name"])
                    success_list.append(model["name"])
                except Exception as e:
                    error_list.append(f"{model['name']}: {e}")
                    
        message = ""
        if success_list:
            message += f"{len(success_list)}個のモデルをダウンロードしました。 "
        if error_list:
            message += f"失敗: {', '.join(error_list)}"
            
        if not success_list and not error_list:
            message = "ダウンロード対象のモデルがありませんでした。"
            
        return {"status": "ok" if not error_list else "partial", "message": message}
    except Exception as e:
        logger.exception("一括ダウンロード処理中にエラーが発生しました")
        return {"status": "error", "message": str(e)}
