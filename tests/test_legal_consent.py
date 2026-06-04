"""法務同意ゲートのテスト（/setup 完了は同意必須）。"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_consent_accept_roundtrip(monkeypatch):
    import core.legal_consent as lc
    state: dict[str, str] = {}
    monkeypatch.setattr(lc, "get_all", lambda: state)
    monkeypatch.setattr(lc, "set_many", lambda d: state.update(d))

    assert lc.is_consent_accepted() is False
    result = lc.accept_consent()
    assert result["accepted"] is True
    assert lc.is_consent_accepted() is True
    assert any(d["file"] == "EULA.md" for d in result["documents"])


def test_setup_completion_blocked_without_consent(monkeypatch):
    import core.setup_state as ss
    import core.legal_consent as lc
    from web_app.routes.api_settings import api_setup_complete, SetupCompleteRequest
    from fastapi import HTTPException

    monkeypatch.setattr(lc, "is_consent_accepted", lambda: False)
    try:
        api_setup_complete(SetupCompleteRequest(completed=True))
        assert False, "未同意なのに完了できてしまった"
    except HTTPException as e:
        assert e.status_code == 422


def test_setup_completion_allowed_with_consent(monkeypatch):
    import core.setup_state as ss
    import core.legal_consent as lc
    import web_app.services.status_service as status
    from web_app.routes.api_settings import api_setup_complete, SetupCompleteRequest

    monkeypatch.setattr(lc, "is_consent_accepted", lambda: True)
    monkeypatch.setattr(status, "setup_readiness", lambda: {"ready": True, "missing": []})
    completed = {}
    monkeypatch.setattr(ss, "set_setup_completed", lambda v: completed.__setitem__("v", v))
    monkeypatch.setattr(ss, "setup_gate_status", lambda: {"completed": True})
    out = api_setup_complete(SetupCompleteRequest(completed=True))
    assert completed["v"] is True
    assert out["completed"] is True


def test_setup_completion_blocked_when_not_ready(monkeypatch):
    import core.legal_consent as lc
    import web_app.services.status_service as status
    from web_app.routes.api_settings import api_setup_complete, SetupCompleteRequest
    from fastapi import HTTPException

    monkeypatch.setattr(lc, "is_consent_accepted", lambda: True)
    monkeypatch.setattr(status, "setup_readiness", lambda: {"ready": False, "missing": ["VOICEVOX に接続できません"]})
    try:
        api_setup_complete(SetupCompleteRequest(completed=True))
        assert False, "必須未充足なのに完了できてしまった"
    except HTTPException as e:
        assert e.status_code == 422
        assert "VOICEVOX" in str(e.detail)


def test_setup_readiness_lists_missing(monkeypatch):
    import web_app.services.status_service as status
    import core.channel_profile as cp
    monkeypatch.setattr(cp, "get_active_profile", lambda: None)
    monkeypatch.setattr(status, "check_voicevox", lambda: {"ok": False})
    monkeypatch.setattr(status, "check_ffmpeg", lambda: {"ok": True})
    r = status.setup_readiness()
    assert r["ready"] is False
    assert any("チャンネル" in m for m in r["missing"])
    assert any("VOICEVOX" in m for m in r["missing"])
    assert not any("ffmpeg" in m for m in r["missing"])
