"""
Jinja2テンプレートを使ったページルート。
将来のReact化を考慮してAPI層とページ層を分離する。
Starlette 1.1.0以降: TemplateResponse(request, name, context) の順で呼ぶ。
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import logging

from config import config as _cfg
from config import (
    WEB_APP_NAME,
    WEB_DEFAULT_IMAGE_STYLE,
    WEB_DEFAULT_LONG_BUDGET_MODE,
    WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST,
    WEB_DEFAULT_REUSE_BACKGROUNDS,
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

# onefile(exe)では __file__ の階層が展開先で平坦化されうるため、同梱リソースは
# resource_base_dir()（<展開先> または開発時はリポジトリルート）基準で解決する。
from core.runtime_env import resource_base_dir as _resource_base_dir
_WEB_APP_DIR = os.path.join(_resource_base_dir(), "web_app")
_TEMPLATES_DIR = os.path.join(_WEB_APP_DIR, "templates")
_STATIC_DIR = os.path.join(_WEB_APP_DIR, "static")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

router = APIRouter(tags=["pages"])
_logger = logging.getLogger(__name__)

# 表示用アプリバージョン（起動時に一度だけ算出。実行中は変わらない）
from core.gui_support import build_app_version as _build_app_version
_APP_VERSION = _build_app_version()


def _render(request: Request, name: str, ctx: dict):
    """Starlette 1.x の TemplateResponse API を吸収するラッパー。"""
    ctx["request"] = request
    ctx["web_app_name"] = WEB_APP_NAME
    ctx["app_version"] = _APP_VERSION
    ctx["web_job_poll_interval_ms"] = WEB_JOB_POLL_INTERVAL_MS
    ctx["web_log_poll_interval_ms"] = _cfg.WEB_LOG_POLL_INTERVAL_MS
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
        _logger.warning("静的アセットバージョンの算出に失敗しました", exc_info=True)
        return 0


@router.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request):
    summary = status_service.get_dashboard_summary()
    status = status_service.get_cached_settings_status()
    histories = history_service.list_histories()[:10]
    jobs = get_job_manager().list_jobs()[:5]
    return _render(request, "dashboard.html", {
        "summary": summary,
        "status": status,
        "histories": histories,
        "recent_jobs": jobs,
    })


@router.get("/generate", response_class=HTMLResponse)
def page_generate(request: Request):
    jobs = get_job_manager().list_jobs()
    gen_jobs = [j for j in jobs if j["type"] == "generate"][:10]
    from core.bgm_store import list_bgm_assets
    return _render(request, "generate.html", {
        "recent_jobs": gen_jobs,
        "image_style_choices": WEB_IMAGE_STYLE_CHOICES,
        "default_image_style": WEB_DEFAULT_IMAGE_STYLE,
        "default_reuse_backgrounds": WEB_DEFAULT_REUSE_BACKGROUNDS,
        "default_long_thumbnail_ab_test": WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST,
        "default_long_budget_mode": WEB_DEFAULT_LONG_BUDGET_MODE,
        "image_backend": _cfg.IMAGE_BACKEND,
        "bgm_assets": list_bgm_assets(),
    })


@router.get("/check", response_class=HTMLResponse)
def page_check(request: Request):
    jobs = get_job_manager().list_jobs()
    check_jobs = [j for j in jobs if j["type"] == "check"][:10]
    return _render(request, "check.html", {"recent_jobs": check_jobs})


@router.get("/history", response_class=HTMLResponse)
def page_history(request: Request, include_uploaded: bool = False):
    histories = history_service.list_histories(include_uploaded=include_uploaded)
    return _render(request, "history.html", {
        "histories": histories,
        "include_uploaded": include_uploaded,
    })


@router.get("/history/{history_name}", response_class=HTMLResponse)
def page_history_detail(request: Request, history_name: str):
    detail = history_service.get_history_detail(history_name)
    if detail is None:
        raise HTTPException(status_code=404, detail="履歴が見つかりません")
    from core.bgm_store import list_bgm_assets
    return _render(request, "history_detail.html", {
        "detail": detail,
        "image_style_choices": WEB_IMAGE_STYLE_CHOICES,
        "default_image_style": WEB_DEFAULT_IMAGE_STYLE,
        "default_reuse_backgrounds": WEB_DEFAULT_REUSE_BACKGROUNDS,
        "default_long_thumbnail_ab_test": WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST,
        "default_long_budget_mode": WEB_DEFAULT_LONG_BUDGET_MODE,
        "image_backend": _cfg.IMAGE_BACKEND,
        "bgm_assets": list_bgm_assets(),
    })


@router.get("/images", response_class=HTMLResponse)
def page_images(request: Request, history: str = ""):
    histories = history_service.list_histories()
    selected = None
    if history:
        selected = image_service.list_images(history)
    return _render(request, "images.html", {
        "histories": histories,
        "selected_history": history,
        "image_data": selected,
        "image_backend": _cfg.IMAGE_BACKEND,
    })


@router.get("/analytics", response_class=HTMLResponse)
def page_analytics(request: Request):
    data = analytics_service.load_latest_analytics()
    from core.metadata_db import get_latest_analytics_meta
    meta = get_latest_analytics_meta()
    return _render(request, "analytics.html", {
        "analytics_data": data,
        "analytics_collected_at": meta.get("generated_at", ""),
    })


@router.get("/schedule", response_class=HTMLResponse)
def page_schedule(request: Request):
    try:
        scheduled = schedule_service.list_schedule(include_published=False)
        schedule_error = None
    except Exception as e:
        _logger.error("スケジュールページ用データ取得に失敗しました", exc_info=True)
        scheduled = []
        schedule_error = str(e)
    from core.channel_schedule import get_schedule, schedule_to_dict
    active_schedule = schedule_to_dict(get_schedule())
    schedule_times_unique = []
    for t in active_schedule.get("shorts_times", []) + active_schedule.get("long_times", []):
        if t not in schedule_times_unique:
            schedule_times_unique.append(t)
    return _render(request, "schedule.html", {
        "schedule_items": scheduled,
        "schedule_error": schedule_error,
        "active_schedule": active_schedule,
        "schedule_times_unique": schedule_times_unique,
    })


@router.get("/upload", response_class=HTMLResponse)
def page_upload(request: Request):
    candidates = upload_service.list_upload_candidates()
    return _render(request, "upload.html", {"candidates": candidates})


@router.get("/playlist-classifier", response_class=HTMLResponse)
def page_playlist_classifier(request: Request):
    from web_app.services.playlist_classifier_service import list_classifier_candidates
    return _render(request, "playlist_classifier.html", {
        "candidates": list_classifier_candidates(),
    })


@router.get("/fixed-comment", response_class=HTMLResponse)
def page_fixed_comment(request: Request):
    from core import background_task_status
    from web_app.services.auto_fixed_comment_service import TASK_NAME
    candidates = fixed_comment_service.list_fixed_comment_candidates(only_unposted=False)
    auto_last_run = background_task_status.last_run(TASK_NAME)
    return _render(request, "fixed_comment.html", {"candidates": candidates, "auto_last_run": auto_last_run})


@router.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    from web_app.services.secrets_service import get_secret_status
    from web_app.services.config_service import developer_tools_enabled
    status = get_secret_status()
    return _render(request, "settings.html", {
        "status": status,
        "developer_tools_enabled": developer_tools_enabled(),
    })


@router.get("/setup", response_class=HTMLResponse)
def page_setup(request: Request):
    from core.setup_state import setup_gate_status
    from web_app.services.status_service import get_cached_settings_status
    from core.service_detector import get_installation_guides
    from core.legal_consent import consent_status
    return _render(request, "setup.html", {
        "setup": setup_gate_status(),
        "status": get_cached_settings_status(),
        "install_guides": get_installation_guides(),
        "legal": consent_status(),
    })


@router.get("/legal/{doc}", response_class=HTMLResponse)
def page_legal(request: Request, doc: str):
    """法務文書（利用規約・EULA・プライバシーポリシー等）を表示する。

    表示対象は LEGAL_DOCUMENTS のホワイトリストに限定し、任意パス読み取りを防ぐ。
    """
    from core.legal_consent import LEGAL_DOCUMENTS
    if doc not in LEGAL_DOCUMENTS:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    legal_path = os.path.abspath(os.path.join(_resource_base_dir(), "legal", doc))
    if not os.path.isfile(legal_path):
        raise HTTPException(status_code=404, detail="文書ファイルが見つかりません")
    with open(legal_path, "r", encoding="utf-8") as f:
        content = f.read()
    return _render(request, "legal.html", {
        "doc_label": LEGAL_DOCUMENTS[doc],
        "doc_content": content,
    })


@router.get("/logs", response_class=HTMLResponse)
def page_logs(request: Request):
    jobs = get_job_manager().list_jobs()
    return _render(request, "logs.html", {"jobs": jobs})


@router.get("/sd-models", response_class=HTMLResponse)
def page_sd_models(request: Request):
    from config import config as _cfg
    from core.secret_store import active_profile_id, has_secret
    profile_id = active_profile_id()
    return _render(request, "sd_models.html", {
        "sd_webui_root": _cfg.SD_WEBUI_ROOT,
        "sd_webui_model": _cfg.SD_WEBUI_MODEL,
        "auto_download_sd_models": _cfg.AUTO_DOWNLOAD_SD_MODELS,
        "sd_webui_base_url": _cfg.SD_WEBUI_BASE_URL,
        "hf_token_set": has_secret("hf_token", profile_id=profile_id) if profile_id else False,
    })


@router.get("/db", response_class=HTMLResponse)
def page_db(request: Request):
    return _render(request, "db.html", {})
