"""チャンネル別自動運用の設定・状態・保留解除API。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictBool, StrictInt

from core import autopilot_store as store
from core.channel_profile import require_active_profile
from core.error_codes import AppError
from web_app.routes.errors import raise_api_error

router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])


class PolicyRequest(BaseModel):
    profile_id: str
    enabled: StrictBool
    daily_shorts: StrictInt
    daily_longs: StrictInt
    start_hour: StrictInt
    min_score: StrictInt
    daily_paid_limit: StrictInt
    confirmed: StrictBool = False


class DismissRequest(BaseModel):
    profile_id: str
    confirmed: StrictBool = False


def _check_profile(profile_id: str) -> None:
    if profile_id != require_active_profile().profile_id:
        raise HTTPException(409, "チャンネルが切り替わりました。画面を再読み込みしてください")


@router.get("")
def get_status():
    try:
        return store.status()
    except Exception as exc:
        raise_api_error(exc, action="自動運用状態取得", detail=AppError("E-AUTO-HOLD").user_message())


@router.post("/settings")
def save_settings(req: PolicyRequest):
    _check_profile(req.profile_id)
    if req.enabled:
        from core.license_manager import assert_can_use_autopilot
        try:
            assert_can_use_autopilot()
        except RuntimeError as exc:
            raise_api_error(exc, status_code=403, action="自動運用ライセンス確認")
    try:
        return store.save_policy(req.model_dump(exclude={"profile_id", "confirmed"}), confirmed=req.confirmed)
    except Exception as exc:
        detail = exc.user_message() if isinstance(exc, AppError) else AppError("E-AUTO-CONFIG").user_message()
        raise_api_error(exc, action="自動運用設定保存", detail=detail)


@router.post("/{run_id}/dismiss")
def dismiss(run_id: str, req: DismissRequest):
    _check_profile(req.profile_id)
    if not req.confirmed:
        raise HTTPException(400, "confirmed=trueが必要です")
    try:
        store.dismiss(run_id)
        return {"status": "skipped"}
    except Exception as exc:
        raise_api_error(exc, action="保留枠の終了", detail=AppError("E-AUTO-HOLD").user_message())
