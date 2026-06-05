"""製品版ライセンスとエディション制限の管理。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import config
from core.settings_store import get_all, set_many

_logger = logging.getLogger(__name__)

LICENSE_EDITION_KEY = "LICENSE_EDITION"
LICENSE_ID_KEY = "LICENSE_ID"

# trial / 上限到達時に購入を促す対象（最上位 studio は購入訴求しない）
_PAID_EDITIONS = ("personal", "pro", "studio")


def purchase_url() -> str:
    """購入ページURL（未設定なら空文字）。"""
    return (config.PRODUCT_PURCHASE_URL or "").strip()


def _purchase_cta() -> str:
    """上限到達エラーへ付ける購入導線の文言。URL未設定時は誘導文のみ。"""
    base = "上位エディションへのアップグレードで上限を解放できます"
    url = purchase_url()
    return f"{base}（購入: {url}）。" if url else f"{base}。"


@dataclass(frozen=True)
class LicenseLimits:
    edition: str
    watermark: bool
    daily_generations: int | None
    max_profiles: int | None
    youtube_upload: bool
    analytics: bool
    template_limit: int | None


_LIMITS: dict[str, LicenseLimits] = {
    "trial": LicenseLimits("trial", True, 3, 1, False, False, 3),
    "personal": LicenseLimits("personal", False, 10, 2, True, False, 10),
    "pro": LicenseLimits("pro", False, 50, 5, True, True, 50),
    "studio": LicenseLimits("studio", False, None, None, True, True, None),
}


def _normalize_edition(value: str | None) -> str:
    edition = (value or "trial").strip().lower()
    if edition not in _LIMITS:
        raise RuntimeError(f"未知のライセンス edition です: {edition}")
    return edition


def get_license_info() -> dict:
    settings = get_all()
    edition = _normalize_edition(settings.get(LICENSE_EDITION_KEY))
    limits = _LIMITS[edition]
    return {
        "edition": edition,
        "registered": bool(settings.get(LICENSE_ID_KEY, "").strip()),
        "purchase_url": purchase_url(),
        "upgrade_available": edition != "studio",
        "limits": {
            "watermark": limits.watermark,
            "daily_generations": limits.daily_generations,
            "max_profiles": limits.max_profiles,
            "youtube_upload": limits.youtube_upload,
            "analytics": limits.analytics,
            "template_limit": limits.template_limit,
        },
    }


def save_license(edition: str, license_id: str = "") -> dict:
    normalized = _normalize_edition(edition)
    updates = {LICENSE_EDITION_KEY: normalized}
    if license_id:
        updates[LICENSE_ID_KEY] = license_id.strip()
    set_many(updates)
    return get_license_info()


def current_limits() -> LicenseLimits:
    return _LIMITS[get_license_info()["edition"]]


def should_watermark() -> bool:
    return current_limits().watermark


def assert_profile_limit_for_create() -> None:
    limits = current_limits()
    if limits.max_profiles is None:
        return
    from core.channel_profile import list_profiles
    if len(list_profiles()) >= limits.max_profiles:
        raise RuntimeError(f"{limits.edition} では channel profile は最大 {limits.max_profiles} 件です。{_purchase_cta()}")


def _today_window_jst() -> tuple[datetime, datetime]:
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        _logger.debug("ライセンス日時の解析に失敗しました: value=%r", value, exc_info=True)
        return None


def daily_generation_count(profile_id: str | None = None) -> int:
    from core.channel_profile import list_profiles, profile_context, get_active_profile
    from core.metadata_db import load_jobs_from_db

    profiles = [profile_id] if profile_id else [p.profile_id for p in list_profiles()]
    if not profiles:
        active = get_active_profile()
        profiles = [active.profile_id] if active else []
    start, end = _today_window_jst()
    count = 0
    for pid in profiles:
        with profile_context(pid):
            for job in load_jobs_from_db(max_n=1000):
                if job.get("type") != "generate" and job.get("job_type") != "generate":
                    continue
                if job.get("status") not in ("queued", "running", "success"):
                    continue
                created = _parse_dt(job.get("created_at") or job.get("started_at") or "")
                if created and start <= created.astimezone(start.tzinfo) < end:
                    count += 1
    return count


def assert_can_generate(batch_count: int = 1) -> None:
    limits = current_limits()
    if limits.daily_generations is None:
        return
    current = daily_generation_count()
    if current + batch_count > limits.daily_generations:
        raise RuntimeError(
            f"{limits.edition} の1日生成上限は {limits.daily_generations} 本です。"
            f"本日登録済み: {current} 本。{_purchase_cta()}"
        )


def assert_can_upload() -> None:
    limits = current_limits()
    if not limits.youtube_upload:
        raise RuntimeError(f"{limits.edition} では YouTube アップロードは利用できません。{_purchase_cta()}")


def assert_can_use_analytics() -> None:
    limits = current_limits()
    if not limits.analytics:
        raise RuntimeError(f"{limits.edition} では Analytics は利用できません。{_purchase_cta()}")


def assert_template_limit(profile_id: str, adding: int = 1) -> None:
    limits = current_limits()
    if limits.template_limit is None:
        return
    from core.prompt_template_store import list_templates
    current = len(list_templates(profile_id))
    if current + adding > limits.template_limit:
        raise RuntimeError(f"{limits.edition} ではテンプレートは最大 {limits.template_limit} 件です。{_purchase_cta()}")
