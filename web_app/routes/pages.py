"""
Jinja2テンプレートを使ったページルート。
将来のReact化を考慮してAPI層とページ層を分離する。
Starlette 1.1.0以降: TemplateResponse(request, name, context) の順で呼ぶ。
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

from config import (
    WEB_APP_NAME,
    WEB_DEFAULT_IMAGE_STYLE,
    WEB_DEFAULT_LONG_BUDGET_MODE,
    WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST,
    WEB_DEFAULT_REUSE_BACKGROUNDS,
    WEB_DEFAULT_SD_SIZE_MODE,
    WEB_IMAGE_STYLE_CHOICES,
    WEB_JOB_POLL_INTERVAL_MS,
    WEB_SUCCESS_RELOAD_DELAY_MS,
    WEB_TOAST_HIDE_DELAY_MS,
    WEB_TOAST_VISIBLE_MS,
)
from web_app.services import (
    status_service,
    history_service,
    analytics_service,
    schedule_service,
    upload_service,
    fixed_comment_service,
    image_service,
)
from web_app.job_manager import get_job_manager

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter(tags=["pages"])


def _render(request: Request, name: str, ctx: dict):
    """Starlette 1.x の TemplateResponse API を吸収するラッパー。"""
    ctx["request"] = request
    ctx["web_app_name"] = WEB_APP_NAME
    ctx["web_job_poll_interval_ms"] = WEB_JOB_POLL_INTERVAL_MS
    ctx["web_success_reload_delay_ms"] = WEB_SUCCESS_RELOAD_DELAY_MS
    ctx["web_toast_visible_ms"] = WEB_TOAST_VISIBLE_MS
    ctx["web_toast_hide_delay_ms"] = WEB_TOAST_HIDE_DELAY_MS
    ctx["static_asset_version"] = _static_asset_version()
    return templates.TemplateResponse(request, name, ctx)


def _static_asset_version() -> int:
    try:
        paths = [
            os.path.join(_STATIC_DIR, "app.css"),
            os.path.join(_STATIC_DIR, "app.js"),
            os.path.join(_STATIC_DIR, "job_poll.js"),
        ]
        return int(max(os.path.getmtime(path) for path in paths if os.path.exists(path)))
    except Exception:
        return 0


@router.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request):
    summary = status_service.get_dashboard_summary()
    histories = history_service.list_histories()[:10]
    jobs = get_job_manager().list_jobs()[:5]
    return _render(request, "dashboard.html", {
        "summary": summary,
        "histories": histories,
        "recent_jobs": jobs,
    })


@router.get("/generate", response_class=HTMLResponse)
def page_generate(request: Request):
    jobs = get_job_manager().list_jobs()
    gen_jobs = [j for j in jobs if j["type"] == "generate"][:10]
    return _render(request, "generate.html", {
        "recent_jobs": gen_jobs,
        "image_style_choices": WEB_IMAGE_STYLE_CHOICES,
        "default_image_style": WEB_DEFAULT_IMAGE_STYLE,
        "default_reuse_backgrounds": WEB_DEFAULT_REUSE_BACKGROUNDS,
        "default_long_thumbnail_ab_test": WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST,
        "default_long_budget_mode": WEB_DEFAULT_LONG_BUDGET_MODE,
        "default_sd_size_mode": WEB_DEFAULT_SD_SIZE_MODE,
    })


@router.get("/check", response_class=HTMLResponse)
def page_check(request: Request):
    jobs = get_job_manager().list_jobs()
    check_jobs = [j for j in jobs if j["type"] == "check"][:10]
    return _render(request, "check.html", {"recent_jobs": check_jobs})


@router.get("/history", response_class=HTMLResponse)
def page_history(request: Request):
    histories = history_service.list_histories()
    return _render(request, "history.html", {"histories": histories})


@router.get("/history/{history_name}", response_class=HTMLResponse)
def page_history_detail(request: Request, history_name: str):
    detail = history_service.get_history_detail(history_name)
    if detail is None:
        raise HTTPException(status_code=404, detail="履歴が見つかりません")
    return _render(request, "history_detail.html", {
        "detail": detail,
        "image_style_choices": WEB_IMAGE_STYLE_CHOICES,
        "default_image_style": WEB_DEFAULT_IMAGE_STYLE,
        "default_reuse_backgrounds": WEB_DEFAULT_REUSE_BACKGROUNDS,
        "default_long_thumbnail_ab_test": WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST,
        "default_long_budget_mode": WEB_DEFAULT_LONG_BUDGET_MODE,
        "default_sd_size_mode": WEB_DEFAULT_SD_SIZE_MODE,
    })


@router.get("/images", response_class=HTMLResponse)
def page_images(request: Request, history: str = ""):
    histories = history_service.list_histories()
    selected = None
    if history:
        try:
            selected = image_service.list_images(history)
        except Exception:
            selected = None
    return _render(request, "images.html", {
        "histories": histories,
        "selected_history": history,
        "image_data": selected,
    })


@router.get("/analytics", response_class=HTMLResponse)
def page_analytics(request: Request):
    data = analytics_service.load_latest_analytics()
    files = analytics_service.list_analytics_files()
    return _render(request, "analytics.html", {
        "analytics_data": data,
        "analytics_files": files,
    })


@router.get("/schedule", response_class=HTMLResponse)
def page_schedule(request: Request):
    scheduled = schedule_service.list_schedule(include_published=False)
    return _render(request, "schedule.html", {"schedule_items": scheduled})


@router.get("/upload", response_class=HTMLResponse)
def page_upload(request: Request):
    candidates = upload_service.list_upload_candidates()
    return _render(request, "upload.html", {"candidates": candidates})


@router.get("/fixed-comment", response_class=HTMLResponse)
def page_fixed_comment(request: Request):
    candidates = fixed_comment_service.list_fixed_comment_candidates(only_unposted=False)
    return _render(request, "fixed_comment.html", {"candidates": candidates})


@router.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    status = status_service.get_settings_status()
    return _render(request, "settings.html", {"status": status})


@router.get("/logs", response_class=HTMLResponse)
def page_logs(request: Request):
    jobs = get_job_manager().list_jobs()
    return _render(request, "logs.html", {"jobs": jobs})
