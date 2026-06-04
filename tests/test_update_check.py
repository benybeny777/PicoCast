"""更新確認のテスト（URL未設定時はネットワークアクセスしない）。"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_update_check_disabled_when_url_empty(monkeypatch):
    import core.update_check as uc

    monkeypatch.setattr(uc.config, "PRODUCT_UPDATE_CHECK_URL", "")

    # URL 未設定ならネットワークへ出ない
    def _fail(*a, **k):
        raise AssertionError("URL未設定なのにネットワークアクセスした")

    monkeypatch.setattr(uc.urllib.request, "urlopen", _fail)
    result = uc.check_for_update()
    assert result["enabled"] is False
    assert uc.is_update_check_enabled() is False


def test_update_check_detects_newer(monkeypatch):
    import core.update_check as uc
    import io
    import json

    monkeypatch.setattr(uc.config, "PRODUCT_UPDATE_CHECK_URL", "https://example.com/latest.json")
    monkeypatch.setattr(uc, "build_app_version", lambda: "1.0.0")

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    payload = json.dumps({"latest_version": "1.1.0", "url": "https://example.com/dl"}).encode("utf-8")
    monkeypatch.setattr(uc.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    result = uc.check_for_update()
    assert result["ok"] is True
    assert result["update_available"] is True
    assert result["latest"] == "1.1.0"


def test_update_check_handles_fetch_error(monkeypatch):
    import core.update_check as uc

    monkeypatch.setattr(uc.config, "PRODUCT_UPDATE_CHECK_URL", "https://example.com/latest.json")

    def _boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(uc.urllib.request, "urlopen", _boom)
    result = uc.check_for_update()
    assert result["enabled"] is True
    assert result["ok"] is False
    assert "error" in result
