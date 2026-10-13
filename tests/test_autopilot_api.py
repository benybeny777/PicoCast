"""自動運用APIの確認・チャンネル隔離・入力制約を実通信なしで検証する。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.error_codes import AppError
from web_app.routes import api_autopilot as api


@pytest.fixture
def client(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(api, "require_active_profile", lambda: SimpleNamespace(profile_id="channel-a"))
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def policy(**updates):
    return {"profile_id": "channel-a", "enabled": True, "daily_shorts": 2, "daily_longs": 0,
            "start_hour": 6, "min_score": 80, "daily_paid_limit": 20, "confirmed": True, **updates}


def test_channel_switch_does_not_write_another_channel(client, monkeypatch):
    monkeypatch.setattr(api.store, "save_policy", lambda *a, **k: pytest.fail("別チャンネルを書き込んだ"))
    assert client.post("/api/autopilot/settings", json=policy(profile_id="channel-b")).status_code == 409


@pytest.mark.parametrize("update", [{"daily_shorts": 1.5}, {"daily_shorts": True}, {"enabled": "true"}, {"confirmed": "true"}])
def test_strict_types_reject_ambiguous_values(client, update):
    assert client.post("/api/autopilot/settings", json=policy(**update)).status_code == 422


def test_confirmed_setting_is_passed_to_store(client, monkeypatch):
    saved = []
    monkeypatch.setattr(api.store, "save_policy", lambda value, **kw: saved.append((value, kw)) or value)
    assert client.post("/api/autopilot/settings", json=policy()).status_code == 200
    assert saved[0][0]["daily_shorts"] == 2
    assert saved[0][1] == {"confirmed": True}


def test_dismiss_requires_confirmation_and_current_channel(client, monkeypatch):
    dismissed = []
    monkeypatch.setattr(api.store, "dismiss", dismissed.append)
    assert client.post("/api/autopilot/run/dismiss", json={"profile_id": "channel-a"}).status_code == 400
    assert client.post("/api/autopilot/run/dismiss", json={"profile_id": "channel-b", "confirmed": True}).status_code == 409
    assert client.post("/api/autopilot/run/dismiss", json={"profile_id": "channel-a", "confirmed": True}).status_code == 200
    assert dismissed == ["run"]


def test_error_has_code_and_fix_without_stack(client, monkeypatch):
    def fail(*args, **kwargs):
        raise AppError("E-AUTO-BUDGET")
    monkeypatch.setattr(api.store, "save_policy", fail)
    response = client.post("/api/autopilot/settings", json=policy())
    assert response.status_code == 400
    assert "E-AUTO-BUDGET" in response.json()["detail"]
    assert "Traceback" not in response.text
