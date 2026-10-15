"""端末固定の署名証明書とライセンス制限を管理する。"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import config
from core.error_codes import AppError
from core.license_key import LicensePayload, ActivationPayload, verify_license_key, verify_activation
from core.machine_id import machine_code
from core.secret_store import protect_local_data, unprotect_local_data
from core.settings_store import get_all, set_many

_logger = logging.getLogger(__name__)
_operation_lock = threading.RLock()
LICENSE_KEY_KEY = "LICENSE_KEY"
LICENSE_ACTIVATION_KEY = "LICENSE_ACTIVATION"
LICENSE_REVOKED_KEY = "LICENSE_REVOKED"
LICENSE_ACTIVATION_ERROR_KEY = "LICENSE_ACTIVATION_ERROR"


def purchase_url() -> str:
    return (config.PRODUCT_PURCHASE_URL or "").strip()


def _purchase_cta() -> str:
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


_LIMITS = {
    "trial": LicenseLimits("trial", True, 3, 1, True, False, False),
    "standard": LicenseLimits("standard", False, None, 1, True, True, True),
    "pro": LicenseLimits("pro", False, None, None, True, True, True),
}


@dataclass(frozen=True)
class _ResolvedLicense:
    edition: str
    status: str
    payload: LicensePayload | None
    reason: str
    activation: ActivationPayload | None = None


def _activation_text(settings: dict[str, str]) -> str:
    stored = settings.get(LICENSE_ACTIVATION_KEY, "")
    if not stored:
        return ""
    try:
        blob = base64.b64decode(stored, validate=True)
    except (ValueError, binascii.Error):
        raise AppError("E-LICENSE-INVALID", "保存された証明書を読み取れません") from None
    # DPAPI復号失敗は黙って体験版に降格せず上位へ伝播する。
    try:
        decoded = unprotect_local_data(blob)
    except Exception:
        _logger.error("証明書の端末保護を解除できませんでした", exc_info=True)
        raise
    try:
        return decoded.decode("utf-8")
    except UnicodeError:
        raise AppError("E-LICENSE-INVALID", "保存された証明書の文字形式が不正です") from None


def _checked_activation(text: str, payload: LicensePayload) -> ActivationPayload:
    cert = verify_activation(text)
    if (cert.license_id, cert.edition, cert.buyer, cert.updates_until, cert.packs) != (
        payload.license_id, payload.edition, payload.buyer, payload.updates_until, payload.packs
    ):
        raise AppError("E-LICENSE-INVALID", "キーと証明書のライセンス内容が一致しません")
    return cert


def _resolve(settings: dict[str, str]) -> _ResolvedLicense:
    key = (settings.get(LICENSE_KEY_KEY) or "").strip()
    if not key:
        return _ResolvedLicense("trial", "unregistered", None, "")
    try:
        payload = verify_license_key(key)
    except AppError as exc:
        # フォールバック許可: 検証不成立の保存キーは体験版とし、理由を画面へ出す（設計T2）。
        _logger.warning("保存キーの検証失敗 code=E-LICENSE-INVALID")
        return _ResolvedLicense("trial", "invalid", None, exc.user_message())
    if settings.get(LICENSE_REVOKED_KEY) == "1":
        return _ResolvedLicense("trial", "revoked", payload, "ライセンスが失効しています。サポートへ連絡してください。")
    try:
        text = _activation_text(settings)
        if not text:
            return _ResolvedLicense("trial", "not_activated", payload, "このPCは未登録です。手動証明書を貼り付けるか、オンラインで登録してください。")
        cert = _checked_activation(text, payload)
    except AppError as exc:
        # フォールバック許可: 検証不成立の保存証明書は体験版とし、理由を画面へ出す（設計T2）。
        _logger.warning("保存証明書の検証失敗 code=E-LICENSE-INVALID")
        return _ResolvedLicense("trial", "invalid", payload, exc.user_message())
    if cert.machine_code != machine_code():
        _logger.warning("証明書の端末が不一致 code=E-LICENSE-MACHINE")
        return _ResolvedLicense("trial", "machine_mismatch", payload, "別のPCの証明書です。このPC用の証明書を登録してください。", cert)
    if cert.expires_at and datetime.fromisoformat(cert.expires_at) <= datetime.now(timezone.utc):
        _logger.warning("証明書が期限切れ code=E-LICENSE-EXPIRED")
        return _ResolvedLicense("trial", "expired", payload, AppError("E-LICENSE-EXPIRED").user_message(), cert)
    return _ResolvedLicense(payload.edition, "active", payload, "", cert)


def _stored_error(settings: dict[str, str]) -> dict:
    text = settings.get(LICENSE_ACTIVATION_ERROR_KEY, "")
    if not text:
        return {}
    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError("保存形式")
        return result
    except ValueError:
        _logger.error("ライセンス処理エラーの保存形式が不正です", exc_info=True)
        raise AppError("E-LICENSE-API", "設定データの保存形式が不正です") from None


def get_license_info() -> dict:
    settings = get_all()
    resolved = _resolve(settings)
    limits = _LIMITS[resolved.edition]
    payload = resolved.payload
    error = _stored_error(settings)
    return {
        "edition": resolved.edition, "status": resolved.status,
        "activation_status": resolved.status, "reason": resolved.reason,
        "registered": resolved.status != "unregistered",
        "buyer": payload.buyer if payload else "",
        "license_id": payload.license_id if payload else "",
        "issued_at": payload.issued_at if payload else "",
        "updates_until": payload.updates_until if payload else "",
        "packs": list(payload.packs) if payload and resolved.status == "active" else [],
        "machine_code": machine_code(),
        "activation_expires_at": resolved.activation.expires_at if resolved.activation else "",
        "activation_error": error, "devices": error.get("devices", []),
        "api_enabled": bool(_api_url()),
        "purchase_url": purchase_url(), "upgrade_available": resolved.edition != "pro",
        "limits": {name: getattr(limits, name) for name in (
            "watermark", "daily_generations", "max_profiles", "youtube_upload", "analytics", "autopilot"
        )},
    }


def verify_activation_now() -> LicenseLimits:
    """キャッシュを使わず署名・端末・期限を再検証する。"""
    return _LIMITS[_resolve(get_all()).edition]


def current_limits() -> LicenseLimits:
    return verify_activation_now()


def _api_url() -> str:
    return (config.LICENSE_API_URL or "").strip()


def _response_devices(value) -> list[dict[str, str]]:
    """端末エラーは表示用IDと日時だけ受け取り、応答の任意本文を保存しない。"""
    try:
        if not isinstance(value, list):
            raise ValueError("一覧形式")
        devices = []
        for row in value:
            if not isinstance(row, dict):
                raise ValueError("行形式")
            mid, updated = row.get("mid"), row.get("last_updated")
            if not isinstance(mid, str) or re.fullmatch(r"(?:[0-9a-f]{6}|[0-9a-f]{32})", mid) is None:
                raise ValueError("端末形式")
            if not isinstance(updated, str):
                raise ValueError("日時形式")
            stamp = datetime.fromisoformat(updated)
            devices.append({"mid": mid[-6:], "last_updated": stamp.isoformat()})
        return devices
    except (TypeError, ValueError):
        _logger.warning("ライセンスAPI端末一覧の形式が不正 code=E-LICENSE-API")
        raise AppError("E-LICENSE-API", "端末一覧の応答形式が不正です") from None


def _api_call(action: str, **fields) -> dict:
    url = _api_url()
    try:
        parsed = urllib.parse.urlsplit(url)
        valid_url = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        valid_url = False
    if not valid_url:
        _logger.warning("ライセンスAPI URLが未設定または不正 code=E-LICENSE-API")
        raise AppError("E-LICENSE-API", "ライセンスAPIのHTTPS URLが未設定または不正です")
    request = urllib.request.Request(
        url, data=json.dumps({"action": action, **fields}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "NVF-license-v2"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.LICENSE_API_TIMEOUT_SEC) as response:
            body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("応答サイズ上限")
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("応答形式")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, UnicodeError) as exc:
        # HTTP応答・URLに秘密値が含まれ得るため例外本文を記録しない。
        _logger.warning("ライセンスAPI通信失敗 action=%s type=%s code=E-LICENSE-API", action, type(exc).__name__)
        raise AppError("E-LICENSE-API", "通信に失敗しました") from None
    error = data.get("error")
    if error is not None and (not isinstance(error, str) or not error):
        _logger.warning("ライセンスAPI応答のerror形式が不正 action=%s code=E-LICENSE-API", action)
        raise AppError("E-LICENSE-API", "応答形式が不正です")
    if error:
        code = {"limit": "E-LICENSE-LIMIT-DEVICES", "invalid": "E-LICENSE-INVALID",
                "machine": "E-LICENSE-MACHINE", "expired": "E-LICENSE-EXPIRED"}.get(error, "E-LICENSE-API")
        _logger.warning("ライセンスAPI処理失敗 action=%s code=%s", action, code)
        exc = AppError(code)
        exc.remote_error = error if error in ("revoked", "inactive") else ""
        exc.devices = _response_devices(data.get("devices", [])) if error == "limit" else []
        raise exc
    return data


def _record_error(exc: AppError) -> None:
    updates = {LICENSE_ACTIVATION_ERROR_KEY: json.dumps(
        {"code": exc.code, "message": exc.user_message(), "devices": getattr(exc, "devices", [])},
        ensure_ascii=False,
    )}
    if getattr(exc, "remote_error", "") == "revoked":
        updates[LICENSE_REVOKED_KEY] = "1"
    if getattr(exc, "remote_error", "") == "inactive":
        updates[LICENSE_ACTIVATION_KEY] = ""
    _logger.warning("ライセンス処理未完了 code=%s", exc.code)
    set_many(updates)


def save_activation(activation: str) -> dict:
    with _operation_lock:
        settings = get_all()
        payload = verify_license_key(settings.get(LICENSE_KEY_KEY, ""))
        if settings.get(LICENSE_REVOKED_KEY) == "1":
            _logger.warning("失効済みライセンスへの証明書登録を拒否 code=E-LICENSE-INVALID")
            raise AppError("E-LICENSE-INVALID", "このライセンスは失効しています。サポートへ連絡してください")
        text = "".join((activation or "").split())
        cert = _checked_activation(text, payload)
        if cert.machine_code != machine_code():
            raise AppError("E-LICENSE-MACHINE", "このPCの端末コードと一致しません")
        if cert.expires_at and datetime.fromisoformat(cert.expires_at) <= datetime.now(timezone.utc):
            raise AppError("E-LICENSE-EXPIRED")
        stored = base64.b64encode(protect_local_data(text.encode("utf-8"))).decode("ascii")
        set_many({LICENSE_ACTIVATION_KEY: stored, LICENSE_ACTIVATION_ERROR_KEY: "", LICENSE_REVOKED_KEY: ""})
        return get_license_info()


def save_license(license_key: str) -> dict:
    with _operation_lock:
        key = "".join((license_key or "").split())
        payload = verify_license_key(key)
        settings = get_all()
        previous_key = settings.get(LICENSE_KEY_KEY, "")
        changed = previous_key != key
        revoked = settings.get(LICENSE_REVOKED_KEY, "")
        if changed and revoked == "1" and previous_key:
            # 同じ購入の再発行キーでも失効状態を引き継ぐ。
            # 検証できない旧キーの失効も、利用者操作だけでは解除しない。
            try:
                if verify_license_key(previous_key).license_id != payload.license_id:
                    revoked = ""
            except AppError:
                _logger.warning("旧購入キーの検証不成立のため失効状態を維持 code=E-LICENSE-INVALID")
        elif changed:
            revoked = ""
        set_many({LICENSE_KEY_KEY: key, LICENSE_ACTIVATION_ERROR_KEY: "", **(
            {LICENSE_ACTIVATION_KEY: "", LICENSE_REVOKED_KEY: revoked} if changed else {}
        )})
        try:
            from core.gui_support import build_app_version
            result = _api_call("activate", license_key=key, machine_code=machine_code(), app_version=build_app_version())
            if not isinstance(result.get("activation"), str):
                raise AppError("E-LICENSE-API", "証明書が応答にありません")
            return save_activation(result["activation"])
        except AppError as exc:
            # フォールバック許可: API未設定・通信失敗はキーを保存して手動登録を案内する（設計T4）。
            _record_error(exc)
            return get_license_info()


def renew_activation() -> dict:
    with _operation_lock:
        settings = get_all()
        payload = verify_license_key(settings.get(LICENSE_KEY_KEY, ""))
        text = _activation_text(settings)
        if not text:
            raise AppError("E-LICENSE-API", "先にこのPCを登録してください")
        cert = _checked_activation(text, payload)
        if cert.machine_code != machine_code():
            raise AppError("E-LICENSE-MACHINE", "証明書の端末が一致しません")
        try:
            result = _api_call("renew", activation=text)
            if not isinstance(result.get("activation"), str):
                raise AppError("E-LICENSE-API", "証明書が応答にありません")
            return save_activation(result["activation"])
        except AppError as exc:
            # フォールバック許可: 期限内はオフラインでも製品版のまま動かす（利用者決定 2026-10-14）。
            _record_error(exc)
            return get_license_info()


def deactivate_activation(*, confirmed: bool) -> dict:
    if not confirmed:
        raise AppError("E-LICENSE-API", "このPCの登録解除には確認が必要です")
    with _operation_lock:
        settings = get_all()
        payload = verify_license_key(settings.get(LICENSE_KEY_KEY, ""))
        text = _activation_text(settings)
        if not text or _checked_activation(text, payload).machine_code != machine_code():
            raise AppError("E-LICENSE-MACHINE", "このPCの証明書を登録してください")
        try:
            result = _api_call("deactivate", activation=text)
            if result.get("ok") is not True:
                raise AppError("E-LICENSE-API", "解除の完了を確認できませんでした")
        except AppError as exc:
            _record_error(exc)
            raise
        set_many({LICENSE_ACTIVATION_KEY: "", LICENSE_ACTIVATION_ERROR_KEY: ""})
        return get_license_info()


def renew_activation_if_due() -> None:
    with _operation_lock:
        if not _api_url():
            return
        resolved = _resolve(get_all())
        cert = resolved.activation
        if resolved.status not in ("active", "expired") or cert is None or not cert.expires_at:
            return
        remaining = datetime.fromisoformat(cert.expires_at) - datetime.now(timezone.utc)
        if remaining <= timedelta(days=config.LICENSE_LEASE_RENEW_BEFORE_DAYS):
            renew_activation()


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
