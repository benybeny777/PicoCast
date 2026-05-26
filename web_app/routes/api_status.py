from fastapi import APIRouter
from web_app.services.status_service import get_settings_status, get_dashboard_summary

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status")
def api_status():
    return get_settings_status()


@router.get("/dashboard")
def api_dashboard():
    return get_dashboard_summary()
