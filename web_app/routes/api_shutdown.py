"""
アプリ終了 API。

POST /api/shutdown  {"confirmed": true, "force": false}

- confirmed=true が必須（誤操作防止）
- force=false（デフォルト）: 生成中workerがある場合は拒否して理由を返す
- force=true: workerへ停止要求を出してから終了する
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/shutdown", tags=["shutdown"])


class ShutdownRequest(BaseModel):
    confirmed: bool = False
    force: bool = False


@router.post("")
def api_shutdown(req: ShutdownRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="confirmed=true が必要です")
    from core.app_shutdown import request_shutdown
    return request_shutdown(force=req.force)


@router.get("/status")
def api_shutdown_status():
    """終了処理が開始されているかどうかを返す。"""
    from core.app_shutdown import is_shutdown_requested, _get_running_jobs
    return {
        "shutdown_requested": is_shutdown_requested(),
        "running_jobs": [
            {"job_id": j.get("job_id"), "type": j.get("type")}
            for j in _get_running_jobs()
        ],
    }
