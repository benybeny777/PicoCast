"""端末コードの安定性、OS別取得、失敗時の生ID保護を検証する。"""
import hashlib
import logging
import re
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import machine_id
from core.error_codes import AppError


def test_machine_code_is_stable_and_product_scoped(monkeypatch):
    monkeypatch.setattr(machine_id, "_raw_machine_id", lambda: "device-one")
    monkeypatch.setattr(machine_id.cfg, "PRODUCT_ID", "nvf")
    code = machine_id.machine_code()
    assert code == hashlib.sha256(b"nvf:device-one").hexdigest()[:32]
    assert machine_id.machine_code() == code
    assert re.fullmatch(r"[0-9a-f]{32}", code)
    monkeypatch.setattr(machine_id, "_raw_machine_id", lambda: "device-two")
    assert machine_id.machine_code() != code
    monkeypatch.setattr(machine_id, "_raw_machine_id", lambda: "device-one")
    monkeypatch.setattr(machine_id.cfg, "PRODUCT_ID", "picocast")
    assert machine_id.machine_code() != code


@pytest.mark.parametrize("raw_id", ["", "  ", None, 123])
def test_machine_code_rejects_missing_id(monkeypatch, raw_id):
    monkeypatch.setattr(machine_id, "_raw_machine_id", lambda: raw_id)
    with pytest.raises(AppError, match="E-LICENSE-MACHINE"):
        machine_id.machine_code()


def test_failure_does_not_leak_raw_id(monkeypatch, caplog):
    secret = "private-device-identifier"

    def fail():
        raise OSError(secret)

    monkeypatch.setattr(machine_id, "_raw_machine_id", fail)
    with caplog.at_level(logging.ERROR), pytest.raises(AppError) as error:
        machine_id.machine_code()
    assert error.value.code == "E-LICENSE-MACHINE"
    assert secret not in str(error.value)
    assert secret not in caplog.text
    assert "E-LICENSE-MACHINE" in caplog.text
    assert "Traceback" in caplog.text


def test_windows_reads_64_bit_registry_and_closes_key(monkeypatch):
    registry = MagicMock()
    registry.QueryValueEx.return_value = (" machine-guid ", 1)
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(machine_id.sys, "platform", "win32")
    assert machine_id._raw_machine_id() == "machine-guid"
    registry.OpenKey.assert_called_once_with(
        registry.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
        registry.KEY_READ | registry.KEY_WOW64_64KEY,
    )
    registry.QueryValueEx.assert_called_once_with(
        registry.OpenKey.return_value.__enter__.return_value, "MachineGuid",
    )
    registry.OpenKey.return_value.__exit__.assert_called_once()


def test_macos_reads_uuid_with_bounded_subprocess(monkeypatch):
    run = MagicMock(return_value=SimpleNamespace(stdout='  "IOPlatformUUID" = "platform-uuid"'))
    monkeypatch.setattr(machine_id.sys, "platform", "darwin")
    monkeypatch.setattr(machine_id.subprocess, "run", run)
    assert machine_id._raw_machine_id() == "platform-uuid"
    run.assert_called_once_with(
        ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
        capture_output=True, text=True, timeout=5, check=True,
    )


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_unsupported_os_or_missing_macos_uuid_stops(monkeypatch, platform):
    monkeypatch.setattr(machine_id.sys, "platform", platform)
    monkeypatch.setattr(machine_id.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=""))
    with pytest.raises(AppError, match="E-LICENSE-MACHINE"):
        machine_id.machine_code()


def test_machine_code_api_success_and_failure(monkeypatch):
    from web_app.routes.api_settings import router

    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(machine_id, "_raw_machine_id", lambda: "api-private-id")
    with TestClient(app) as client:
        response = client.get("/api/settings/license/machine-code")
        assert response.status_code == 200
        assert response.json() == {"machine_code": machine_id.machine_code()}
        assert "api-private-id" not in response.text
        monkeypatch.setattr(machine_id, "_raw_machine_id", lambda: "")
        response = client.get("/api/settings/license/machine-code")
        assert response.status_code == 422
        assert "E-LICENSE-MACHINE" in response.text
        assert "Traceback" not in response.text
