"""製品版ライセンスとエディション制限の管理。

edition は保存せず、`data/settings.db:settings.LICENSE_KEY` に保存した署名付きキーを
参照のたびに検証して決める（DB を書き換えても上位版にならない）。キーの形式は core/license_key.py。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import config
from core.error_codes import AppError
from core.license_key import LicensePayload, verify_license_key
from core.settings_store import get_all, set_many

_logger = logging.getLogger(__name__)

LICENSE_KEY_KEY = "LICENSE_KEY"
# 失効確認（任意）の結果。オンライン確認できたときだけ更新する。
LICENSE_REVOKED_KEY = "LICENSE_REVOKED"
LICENSE_REVOCATION_CHECKED_AT_KEY = "LICENSE_REVOCATION_CHECKED_AT"
LICENSE_REVOCATION_ERROR_KEY = "LICENSE_REVOCATION_ERROR"


def purchase_url() -> str:
    """購入ページURL（未設定なら空文字）。"""
    return (config.PRODUCT_PURCHASE_URL or "").strip()


def _purchase_cta() -> str:
    """上限到達エラーへ付ける購入導線の文言。URL未設定時は誘導文のみ。"""
    base = "製品版（Standard / Pro）の購入で上限を解放できます"
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
    autopilot: bool


_LIMITS: dict[str, LicenseLimits] = {
    "trial": LicenseLimits("trial", True, 3, 1, True, False, False),
    "standard": LicenseLimits("standard", False, None, 1, True, True, True),
    "pro": LicenseLimits("pro", False, None, None, True, True, True),
}


@dataclass(frozen=True)
class _ResolvedLicense:
    edition: str
    status: str            # unregistered / active / invalid / revoked
    payload: LicensePayload | None
    reason: str


def _resolve(settings: dict[str, str]) -> _ResolvedLicense:
    key = (settings.get(LICENSE_KEY_KEY) or "").strip()
    if not key:
        return _ResolvedLicense("trial", "unregistered", None, "")
    try:
        payload = verify_license_key(key)
    except AppError as exc:
        # フォールバック許可: 保存済みキーが検証できない場合は体験版として動かし、理由を画面に表示する
        _logger.warning("保存済みライセンスキーの検証に失敗したため trial として扱います: %s", exc.detail)
        return _ResolvedLicense("trial", "invalid", None, exc.user_message())
    if settings.get(LICENSE_REVOKED_KEY) == "1":
        return _ResolvedLicense("trial", "revoked", payload, "このライセンスは無効化されています。サポートへ連絡してください。")
    return _ResolvedLicense(payload.edition, "active", payload, "")


def get_license_info() -> dict:
    settings = get_all()
    resolved = _resolve(settings)
    limits = _LIMITS[resolved.edition]
    payload = resolved.payload
    return {
        "edition": resolved.edition,
        "status": resolved.status,
        "reason": resolved.reason,
        "registered": resolved.status != "unregistered",
        "buyer": payload.buyer if payload else "",
        "license_id": payload.license_id if payload else "",
        "issued_at": payload.issued_at if payload else "",
        "updates_until": payload.updates_until if payload else "",
        "packs": list(payload.packs) if payload else [],
        "purchase_url": purchase_url(),
        "upgrade_available": resolved.edition != "pro",
        "revocation": {
            "enabled": bool(_revocation_url()),
            "checked_at": settings.get(LICENSE_REVOCATION_CHECKED_AT_KEY, ""),
            "error": settings.get(LICENSE_REVOCATION_ERROR_KEY, ""),
        },
        "limits": {
            "watermark": limits.watermark,
            "daily_generations": limits.daily_generations,
            "max_profiles": limits.max_profiles,
            "youtube_upload": limits.youtube_upload,
            "analytics": limits.analytics,
            "autopilot": limits.autopilot,
        },
    }


def save_license(license_key: str) -> dict:
    """キーを検証して保存する。不正なキーは保存せず AppError(E-LICENSE-INVALID)。"""
    key = "".join((license_key or "").split())
    verify_license_key(key)
    set_many({
        LICENSE_KEY_KEY: key,
        LICENSE_REVOKED_KEY: "",
        LICENSE_REVOCATION_CHECKED_AT_KEY: "",
        LICENSE_REVOCATION_ERROR_KEY: "",
    })
    if _revocation_url():
        check_revocation()
    return get_license_info()


def _revocation_url() -> str:
    return (config.LICENSE_REVOCATION_CHECK_URL or "").strip()


def check_revocation(timeout: float = 10.0) -> dict:
    """失効確認APIへ問い合わせて結果を保存する。

    API は ``?lid=<license_id>`` に ``{"status": "active" | "revoked" | "unknown"}`` を返す（tools/license/gas）。
    通信できない場合は前回の判定を維持し、エラーと最終確認日時を画面に表示する。
    """
    url = _revocation_url()
    if not url:
        return get_license_info()
    resolved = _resolve(get_all())
    if resolved.payload is None:
        return get_license_info()
    lid = resolved.payload.license_id
    query = urllib.parse.urlencode({"lid": lid})
    request_url = f"{url}{'&' if '?' in url else '?'}{query}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        req = urllib.request.Request(request_url, headers={"User-Agent": "NVF-license-check"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        status = str(data.get("status") or "") if isinstance(data, dict) else ""
        if status not in ("active", "revoked", "unknown"):
            raise ValueError(f"想定外の応答です: status={status!r}")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        # フォールバック許可: オフラインでも製品を使えるよう前回判定を維持し、確認失敗を画面に表示する
        _logger.warning("ライセンス失効確認に失敗しました: license_id=%s", lid, exc_info=True)
        set_many({LICENSE_REVOCATION_ERROR_KEY: f"{now} 失効確認に失敗しました（{type(exc).__name__}）"})
        return get_license_info()
    updates = {LICENSE_REVOCATION_CHECKED_AT_KEY: now, LICENSE_REVOKED_KEY: "1" if status == "revoked" else ""}
    if status == "unknown":
        _logger.warning("失効確認APIに未登録の license_id です: %s", lid)
        updates[LICENSE_REVOCATION_ERROR_KEY] = f"{now} 発行台帳に未登録のキーです。サポートへ連絡してください。"
    else:
        updates[LICENSE_REVOCATION_ERROR_KEY] = ""
    set_many(updates)
    return get_license_info()


def check_revocation_if_due() -> None:
    """起動時用。最終確認から LICENSE_REVOCATION_CHECK_INTERVAL_DAYS 日以上経っていれば確認する。"""
    if not _revocation_url():
        return
    settings = get_all()
    if not (settings.get(LICENSE_KEY_KEY) or "").strip():
        return
    checked_at = _parse_dt(settings.get(LICENSE_REVOCATION_CHECKED_AT_KEY, ""))
    interval = timedelta(days=float(config.LICENSE_REVOCATION_CHECK_INTERVAL_DAYS))
    if checked_at and datetime.now(timezone.utc) - checked_at < interval:
        return
    check_revocation()


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


def assert_can_use_autopilot() -> None:
    limits = current_limits()
    if not limits.autopilot:
        raise RuntimeError(f"{limits.edition} では自動運用は利用できません。{_purchase_cta()}")
