"""固定コメント自動投稿タスク（OSスケジューラ登録）と一括投稿のテスト。

実際の schtasks / launchctl / YouTube API は呼ばず、すべてモックする。
"""
from __future__ import annotations

import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── タスク識別子・時刻 ────────────────────────────────────────────────────────

def test_task_name_includes_dir_identifier():
    import core.fixed_comment_task as t
    name = t.task_name()
    assert name.startswith("NativeVideoFactory-FixedComment-")
    # 末尾はパスのハッシュ8桁（同一PCの別ディレクトリと区別するため）
    assert re.search(r"-[0-9a-f]{8}$", name)


def test_task_name_differs_by_directory(monkeypatch):
    import core.fixed_comment_task as t
    monkeypatch.setattr(t, "app_base_dir", lambda: r"C:\apps\alpha")
    name_a = t.task_name()
    monkeypatch.setattr(t, "app_base_dir", lambda: r"C:\apps\beta")
    name_b = t.task_name()
    assert name_a != name_b


def test_slot_times_format():
    import core.fixed_comment_task as t
    times = t.slot_times()
    assert times, "スロット時刻が空"
    for s in times:
        assert re.fullmatch(r"\d{2}:\d{2}", s)
        assert s.endswith(f":{t._BUFFER_MINUTE:02d}")


# ── status / register / unregister のOS分岐 ───────────────────────────────────

def test_status_windows_registered(monkeypatch):
    import core.fixed_comment_task as t
    monkeypatch.setattr(t.platform, "system", lambda: "Windows")
    monkeypatch.setattr(t, "_windows_exists", lambda: True)
    s = t.status()
    assert s["supported"] is True
    assert s["os"] == "Windows"
    assert s["registered"] is True
    assert s["target_dir"]
    assert s["times"]


def test_status_unsupported_os(monkeypatch):
    import core.fixed_comment_task as t
    monkeypatch.setattr(t.platform, "system", lambda: "Linux")
    s = t.status()
    assert s["supported"] is False
    assert s["registered"] is False


def test_register_dispatches_windows(monkeypatch):
    import core.fixed_comment_task as t
    called = {}
    monkeypatch.setattr(t.platform, "system", lambda: "Windows")
    monkeypatch.setattr(t, "_register_windows", lambda times: called.setdefault("times", times))
    monkeypatch.setattr(t, "_windows_exists", lambda: True)
    result = t.register()
    assert called["times"] == t.slot_times()
    assert result["registered"] is True


def test_register_dispatches_mac(monkeypatch):
    import core.fixed_comment_task as t
    called = {}
    monkeypatch.setattr(t.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(t, "_register_mac", lambda times: called.setdefault("times", times))
    monkeypatch.setattr(t, "_mac_plist_path", lambda: os.devnull)  # 存在しない扱い
    t.register()
    assert called["times"] == t.slot_times()


def test_register_unsupported_raises(monkeypatch):
    import core.fixed_comment_task as t
    monkeypatch.setattr(t.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError):
        t.register()


# ── post_all_pending（直接投稿の一括パス） ───────────────────────────────────

def test_post_all_pending_counts(monkeypatch):
    import web_app.services.auto_fixed_comment_service as svc

    monkeypatch.setattr(svc, "_target_profile_ids", lambda: ["alpha", "beta"])

    import web_app.services.fixed_comment_service as fc
    monkeypatch.setattr(
        fc, "list_fixed_comment_candidates",
        lambda only_unposted=True, profile_id=None: [{"name": f"{profile_id}_v1"}],
    )
    posted_calls = []

    def fake_post(history_name, profile_id=None, auto_posted=False, log=None, is_cancelled=None):
        posted_calls.append((history_name, profile_id))
        return {"comment_thread_id": "ct_" + history_name, "video_id": "v", "auto_posted": auto_posted}

    monkeypatch.setattr(fc, "post_fixed_comment_now", fake_post)

    result = svc.post_all_pending()
    assert result == {"posted": 2, "failed": 2 - 2, "profiles": 2}
    assert ("alpha_v1", "alpha") in posted_calls
    assert ("beta_v1", "beta") in posted_calls


def test_post_all_pending_counts_failures(monkeypatch):
    import web_app.services.auto_fixed_comment_service as svc
    import web_app.services.fixed_comment_service as fc

    monkeypatch.setattr(svc, "_target_profile_ids", lambda: ["only"])
    monkeypatch.setattr(
        fc, "list_fixed_comment_candidates",
        lambda only_unposted=True, profile_id=None: [{"name": "x"}, {"name": "y"}],
    )

    def fake_post(history_name, profile_id=None, auto_posted=False, log=None, is_cancelled=None):
        if history_name == "y":
            raise RuntimeError("boom")
        return {"comment_thread_id": "ct", "video_id": "v", "auto_posted": auto_posted}

    monkeypatch.setattr(fc, "post_fixed_comment_now", fake_post)
    result = svc.post_all_pending()
    assert result["posted"] == 1
    assert result["failed"] == 1
    assert result["profiles"] == 1


# ── API ───────────────────────────────────────────────────────────────────────

def test_api_fixed_comment_task_status_and_toggle(monkeypatch):
    from fastapi.testclient import TestClient
    from web_app.app import app
    import core.fixed_comment_task as t

    client = TestClient(app)

    r = client.get("/api/settings/fixed-comment-task")
    assert r.status_code == 200
    assert "registered" in r.json()

    monkeypatch.setattr(t, "register", lambda: {"registered": True, "task_name": "X", "times": [], "supported": True, "os": "Windows", "target_dir": "d"})
    monkeypatch.setattr(t, "unregister", lambda: {"registered": False, "task_name": "X", "times": [], "supported": True, "os": "Windows", "target_dir": "d"})

    r = client.post("/api/settings/fixed-comment-task", json={"enabled": True})
    assert r.status_code == 200 and r.json()["registered"] is True

    r = client.post("/api/settings/fixed-comment-task", json={"enabled": False})
    assert r.status_code == 200 and r.json()["registered"] is False
