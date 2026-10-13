"""ライセンスv2の状態遷移とAPI・保存・更新失敗を検証する。"""
import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import license_key as lk, license_manager as lm
from core.error_codes import AppError


@pytest.fixture
def license_env(monkeypatch):
    private, public = lk.generate_key_pair()
    payload = lk.LicensePayload("test-lid", "pro", "購入者", "2026-10-14", "", ("pack",))
    key = lk.encode_license_key(payload, private)
    code = "1" * 32
    cert = lk.ActivationPayload(**vars(payload), machine_code=code,
                                expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
    settings = {"LICENSE_KEY": key}
    monkeypatch.setattr(lm, "get_all", lambda: dict(settings))
    monkeypatch.setattr(lm, "set_many", settings.update)
    monkeypatch.setattr(lm, "machine_code", lambda: code)
    monkeypatch.setattr(lm, "verify_license_key", lambda value: lk.verify_license_key(value, public))
    monkeypatch.setattr(lm, "verify_activation", lambda value: lk.verify_activation(value, public))
    monkeypatch.setattr(lm, "protect_local_data", lambda value: b"protected:" + value)
    monkeypatch.setattr(lm, "unprotect_local_data", lambda value: value.removeprefix(b"protected:"))
    monkeypatch.setattr(lm.config, "LICENSE_API_URL", "https://license.example/api")
    return SimpleNamespace(settings=settings, key=key, cert=cert, private=private,
                           encode=lambda value: lk.encode_activation(value, private))


@pytest.fixture
def api_response(monkeypatch):
    def set_response(data):
        response = MagicMock()
        response.read.return_value = json.dumps(data).encode()
        context = MagicMock()
        context.__enter__.return_value = response
        monkeypatch.setattr(lm.urllib.request, "urlopen", lambda *a, **k: context)
    return set_response


def test_license_settings_save_to_db_and_apply_immediately(monkeypatch):
    from core import settings_store
    from web_app.services import config_service
    saved = {}
    monkeypatch.setattr(settings_store, "set_many", saved.update)
    monkeypatch.setattr(config_service, "developer_tools_enabled", lambda: True)
    original = {key: str(getattr(lm.config, key)) for key in (
        "LICENSE_API_URL", "LICENSE_LEASE_RENEW_BEFORE_DAYS", "LICENSE_API_TIMEOUT_SEC")}
    try:
        values = {"LICENSE_API_URL": "https://license.example/api", "LICENSE_LEASE_RENEW_BEFORE_DAYS": "5", "LICENSE_API_TIMEOUT_SEC": "12"}
        assert config_service.save_config(values) == []
        assert saved == values
        assert lm._api_url() == values["LICENSE_API_URL"]
        assert lm.config.LICENSE_LEASE_RENEW_BEFORE_DAYS == 5
        assert lm.config.LICENSE_API_TIMEOUT_SEC == 12
        monkeypatch.setattr(config_service, "developer_tools_enabled", lambda: False)
        assert config_service.save_config({"LICENSE_API_URL": "https://another.example"})
        assert saved == values
    finally:
        monkeypatch.setattr(config_service, "developer_tools_enabled", lambda: True)
        assert config_service.save_config(original) == []


def test_key_requires_activation_and_valid_cert_enables_pro(license_env):
    env = license_env
    assert lm.get_license_info()["status"] == "not_activated"
    info = lm.save_activation(env.encode(env.cert))
    assert info["edition"] == "pro"
    assert info["activation_status"] == "active"
    assert info["packs"] == ["pack"]
    assert base64.b64decode(env.settings["LICENSE_ACTIVATION"]).startswith(b"protected:")
    assert env.key not in json.dumps(info)
    assert "NVA1." not in json.dumps(info)


@pytest.mark.parametrize("changes,status", [
    ({"machine_code": "2" * 32}, "machine_mismatch"),
    ({"expires_at": "2020-01-01T00:00:00+00:00"}, "expired"),
    ({"license_id": "another"}, "invalid"),
    ({"edition": "standard"}, "invalid"),
    ({"packs": ("another",)}, "invalid"),
])
def test_saved_cert_failures_are_trial(license_env, changes, status):
    env = license_env
    token = env.encode(replace(env.cert, **changes))
    env.settings["LICENSE_ACTIVATION"] = base64.b64encode(b"protected:" + token.encode()).decode()
    info = lm.get_license_info()
    assert info["status"] == status
    assert info["edition"] == "trial"
    assert lm.verify_activation_now().watermark
    assert info["packs"] == []


def test_foreign_signing_key_is_invalid(license_env):
    private, _ = lk.generate_key_pair()
    token = lk.encode_activation(license_env.cert, private)
    license_env.settings["LICENSE_ACTIVATION"] = base64.b64encode(token.encode()).decode()
    assert lm.get_license_info()["status"] == "invalid"


def test_activation_calls_api_and_limit_shows_devices(license_env, monkeypatch):
    env = license_env
    monkeypatch.setattr(lm, "_api_call", lambda action, **kw: {"activation": env.encode(env.cert)})
    assert lm.save_license(env.key)["status"] == "active"
    env.settings.pop("LICENSE_ACTIVATION")

    def limit(action, **kwargs):
        error = AppError("E-LICENSE-LIMIT-DEVICES")
        error.devices = [{"mid": "abc123", "last_updated": "2026-10-14"}]
        raise error

    monkeypatch.setattr(lm, "_api_call", limit)
    info = lm.save_license(env.key)
    assert info["status"] == "not_activated"
    assert info["activation_error"]["code"] == "E-LICENSE-LIMIT-DEVICES"
    assert info["devices"][0]["mid"] == "abc123"


def test_failed_renewal_keeps_only_unexpired_entitlement(license_env, monkeypatch):
    env = license_env
    lm.save_activation(env.encode(env.cert))

    def offline(action, **kwargs):
        raise AppError("E-LICENSE-API")

    monkeypatch.setattr(lm, "_api_call", offline)
    assert lm.renew_activation()["edition"] == "pro"
    expired = env.encode(replace(env.cert, expires_at="2020-01-01T00:00:00+00:00"))
    env.settings["LICENSE_ACTIVATION"] = base64.b64encode(expired.encode()).decode()
    assert lm.renew_activation()["status"] == "expired"
    assert lm.current_limits().edition == "trial"


def test_deactivate_requires_confirmation_and_server_success(license_env, monkeypatch):
    lm.save_activation(license_env.encode(license_env.cert))
    call = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(lm, "_api_call", call)
    with pytest.raises(AppError):
        lm.deactivate_activation(confirmed=False)
    call.assert_not_called()
    assert lm.deactivate_activation(confirmed=True)["status"] == "not_activated"
    assert license_env.settings["LICENSE_KEY"] == license_env.key


def test_decryption_failure_propagates(license_env, monkeypatch):
    license_env.settings["LICENSE_ACTIVATION"] = base64.b64encode(b"blob").decode()

    def corrupt(value):
        raise OSError("DPAPI failure")

    monkeypatch.setattr(lm, "unprotect_local_data", corrupt)
    with pytest.raises(OSError):
        lm.current_limits()


def test_due_renewal_and_permanent_cert(license_env, monkeypatch):
    env = license_env
    near = replace(env.cert, expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    lm.save_activation(env.encode(near))
    renew = MagicMock()
    monkeypatch.setattr(lm, "renew_activation", renew)
    lm.renew_activation_if_due()
    renew.assert_called_once()
    renew.reset_mock()
    lm.save_activation(env.encode(replace(env.cert, expires_at="")))
    lm.renew_activation_if_due()
    renew.assert_not_called()


def test_api_routes_manual_renew_deactivate(license_env, monkeypatch):
    from web_app.routes.api_settings import router
    app = FastAPI()
    app.include_router(router)
    env = license_env
    monkeypatch.setattr(lm, "_api_call", lambda action, **kw: (
        {"ok": True} if action == "deactivate" else {"activation": env.encode(env.cert)}))
    with TestClient(app) as client:
        assert client.post("/api/settings/license", json={"license_key": env.key}).json()["status"] == "active"
        assert client.post("/api/settings/license/activation", json={"activation": env.encode(env.cert)}).status_code == 200
        assert client.post("/api/settings/license/renew").json()["status"] == "active"
        assert client.post("/api/settings/license/deactivate", json={}).status_code == 422
        assert client.post("/api/settings/license/deactivate", json={"confirmed": True}).json()["status"] == "not_activated"


def test_api_response_has_bounded_and_redacted_errors(license_env, monkeypatch, caplog, api_response):
    api_response({"error": "limit", "devices": [{"mid": "a" * 32, "last_updated": "2026-10-14"}]})
    with pytest.raises(AppError) as error:
        lm._api_call("activate", license_key=license_env.key)
    assert error.value.devices[0]["mid"] == "aaaaaa"
    assert license_env.key not in caplog.text
    monkeypatch.setattr(lm.config, "LICENSE_API_URL", "http://unsafe.example")
    with pytest.raises(AppError, match="E-LICENSE-API"):
        lm._api_call("activate", license_key=license_env.key)


@pytest.mark.parametrize("error_value", [{"secret": "hidden"}, ["hidden"], 1, True, ""])
def test_malformed_remote_error_fails_with_stable_error(license_env, caplog, error_value, api_response):
    api_response({"error": error_value})
    with pytest.raises(AppError) as error:
        lm._api_call("renew", activation=license_env.encode(license_env.cert))
    assert error.value.code == "E-LICENSE-API"
    assert "hidden" not in caplog.text


def test_manual_certificate_cannot_clear_known_revocation(license_env):
    env = license_env
    lm.save_activation(env.encode(env.cert))
    original = env.settings["LICENSE_ACTIVATION"]
    env.settings["LICENSE_REVOKED"] = "1"
    with pytest.raises(AppError):
        lm.save_activation(env.encode(replace(env.cert, expires_at="")))
    assert env.settings["LICENSE_REVOKED"] == "1"
    assert env.settings["LICENSE_ACTIVATION"] == original
    assert lm.current_limits().edition == "trial"


def test_reissued_purchase_key_does_not_clear_revocation(license_env, monkeypatch):
    env = license_env
    env.settings["LICENSE_REVOKED"] = "1"
    reissued = replace(env.cert, issued_at="2026-10-15")
    key = lk.encode_license_key(lk.LicensePayload(
        reissued.license_id, reissued.edition, reissued.buyer,
        reissued.issued_at, reissued.updates_until, reissued.packs), env.private)
    monkeypatch.setattr(lm, "_api_call", lambda action, **kw: {"activation": env.encode(reissued)})
    assert lm.save_license(key)["status"] == "revoked"
    assert env.settings["LICENSE_REVOKED"] == "1"


def test_different_purchase_can_replace_revoked_license(license_env, monkeypatch):
    env = license_env
    env.settings["LICENSE_REVOKED"] = "1"
    new_cert = replace(env.cert, license_id="another-purchase")
    key = lk.encode_license_key(lk.LicensePayload(
        new_cert.license_id, new_cert.edition, new_cert.buyer,
        new_cert.issued_at, new_cert.updates_until, new_cert.packs), env.private)
    monkeypatch.setattr(lm, "_api_call", lambda action, **kw: {"activation": env.encode(new_cert)})
    assert lm.save_license(key)["status"] == "active"


def test_malformed_config_url_reports_stable_error(license_env, monkeypatch):
    monkeypatch.setattr(lm.config, "LICENSE_API_URL", "https://[invalid")
    with pytest.raises(AppError) as error:
        lm._api_call("renew")
    assert error.value.code == "E-LICENSE-API"


@pytest.mark.parametrize("devices", [
    {"secret": "hidden"}, [None], [{"mid": "hidden", "last_updated": "2026-10-14"}],
    [{"mid": "abc123", "last_updated": "hidden-secret-response"}],
])
def test_remote_device_metadata_cannot_copy_arbitrary_text(license_env, caplog, devices, api_response):
    api_response({"error": "limit", "devices": devices})
    info = lm.save_license(license_env.key)
    assert info["activation_error"]["code"] == "E-LICENSE-API"
    assert "hidden" not in json.dumps(info)
    assert "hidden" not in caplog.text
