"""製品版初回セットアップ状態の管理。"""
from __future__ import annotations

from core.settings_store import get_all, set_many

SETUP_COMPLETED_KEY = "PRODUCT_SETUP_COMPLETED"


def is_setup_completed() -> bool:
    return get_all().get(SETUP_COMPLETED_KEY, "0").strip().lower() in ("1", "true", "yes", "on")


def set_setup_completed(completed: bool) -> None:
    set_many({SETUP_COMPLETED_KEY: "1" if completed else "0"})


def setup_gate_status() -> dict:
    from core.channel_profile import get_active_profile
    profile = get_active_profile()
    completed = is_setup_completed()
    return {
        "completed": completed,
        "active_profile": profile.profile_id if profile else "",
        "generation_allowed": completed and profile is not None,
        "upload_allowed": completed and profile is not None,
        "message": "" if completed and profile else "初回セットアップを完了してください。",
    }


def require_setup_completed_for(operation: str) -> None:
    status = setup_gate_status()
    if not status["generation_allowed"]:
        raise RuntimeError(f"{operation} は初回セットアップ完了後に実行できます。/setup で設定を完了してください。")
