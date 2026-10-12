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


def test_windows_action_hides_console(monkeypatch):
    import core.fixed_comment_task as t

    monkeypatch.setattr(
        t,
        "_command",
        lambda: (r"C:\Program Files\Native Video Factory\app.exe", ["--post-fixed-comments"], r"C:\Program Files\Native Video Factory"),
    )
    monkeypatch.setattr(t.shutil, "which", lambda _name: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

    exe, args, workdir = t._windows_action()

    assert exe.endswith("powershell.exe")
    assert "-WindowStyle" in args
    assert "Hidden" in args
    command = args[-1]
    assert "Start-Process" in command
    assert "-WindowStyle Hidden" in command
    assert "--post-fixed-comments" in command
    assert workdir == r"C:\Program Files\Native Video Factory"


def test_register_windows_uses_hidden_action(monkeypatch):
    import core.fixed_comment_task as t

    captured = {}
    monkeypatch.setattr(
        t,
        "_windows_action",
        lambda: (
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            ["-WindowStyle", "Hidden", "-Command", "Start-Process app.exe -WindowStyle Hidden"],
            r"C:\app",
        ),
    )
    monkeypatch.setattr(t, "_run_powershell", lambda script: captured.setdefault("script", script))

    t._register_windows(["07:05"])

    script = captured["script"]
    assert "New-ScheduledTaskAction" in script
    assert "powershell.exe" in script
    assert "WindowStyle" in script
    assert "Hidden" in script


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


# ── inspect / repair（exe移動などの不整合検出・修正） ─────────────────────────

def test_inspect_detects_stale_and_orphans(monkeypatch, tmp_path):
    import core.fixed_comment_task as t
    monkeypatch.setattr(t.platform, "system", lambda: "Windows")
    monkeypatch.setattr(t, "app_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(t, "_windows_exists", lambda: True)  # 現在タスクは登録済み
    # 実行環境に PowerShell が無くても Windows の判定を検証できるようにする
    monkeypatch.setattr(t.shutil, "which", lambda _name: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    monkeypatch.setattr(t, "_command", lambda: (str(tmp_path / "cur.exe"), ["--post-fixed-comments"], str(tmp_path)))

    cur_name = t.task_name()
    existing = tmp_path / "real.exe"
    existing.write_text("x", encoding="utf-8")
    monkeypatch.setattr(t, "_windows_list_prefix", lambda: [
        # 現在タスクだが記録パスが食い違う → stale
        {"name": cur_name, "execute": r"C:\OLD\cur.exe", "arguments": "--post-fixed-comments", "workdir": str(tmp_path)},
        # 別名・実行ファイルが存在しない → 迷子
        {"name": "NativeVideoFactory-FixedComment-old-deadbeef", "execute": r"C:\gone\missing.exe", "arguments": "", "workdir": ""},
        # 別名だが実行ファイルが在る（別インストール）→ 触らない
        {"name": "NativeVideoFactory-FixedComment-keep-cafebabe", "execute": str(existing), "arguments": "", "workdir": ""},
    ])

    info = t.inspect()
    assert info["stale"] is True
    orphan_names = [o["name"] for o in info["orphans"]]
    assert "NativeVideoFactory-FixedComment-old-deadbeef" in orphan_names
    assert "NativeVideoFactory-FixedComment-keep-cafebabe" not in orphan_names


def test_repair_reregisters_and_removes_orphans(monkeypatch):
    import core.fixed_comment_task as t
    monkeypatch.setattr(t.platform, "system", lambda: "Windows")
    calls = {"register": 0, "deleted": []}
    monkeypatch.setattr(t, "register", lambda: calls.__setitem__("register", calls["register"] + 1) or {"task_name": "x"})
    monkeypatch.setattr(t, "_windows_delete", lambda name: calls["deleted"].append(name))
    monkeypatch.setattr(t, "inspect", lambda: {
        "supported": True, "os": "Windows", "registered": True, "stale": True,
        "task_name": "cur", "orphans": [{"name": "orph", "path": "", "exe": r"C:\gone"}],
    })

    res = t.repair()
    assert res["repaired_current"] is True
    assert "orph" in res["removed_orphans"]
    assert calls["register"] >= 1
    assert "orph" in calls["deleted"]


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


# ── 二重投稿防止（投稿権の原子確保） ─────────────────────────────────────────

def test_claim_fixed_comment_is_exclusive(tmp_path):
    import sqlite3
    import web_app.services.fixed_comment_service as fc

    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE youtube_status (local_id TEXT PRIMARY KEY, fixed_comment_posted INTEGER, fixed_comment_id TEXT)"
    )
    conn.execute("INSERT INTO youtube_status(local_id, fixed_comment_posted, fixed_comment_id) VALUES ('vid1', 0, '')")
    conn.commit()
    conn.close()

    ctx = {"profile_id": "p", "db_path": str(db)}

    # 1回目は確保成功、2回目は既に posted=1 のため失敗（＝同時実行で片方だけ投稿）
    assert fc._claim_fixed_comment("vid1", ctx) is True
    assert fc._claim_fixed_comment("vid1", ctx) is False

    # 投稿失敗を模して release すると、再び確保できる（再試行可能）
    fc._release_fixed_comment_claim("vid1", ctx)
    assert fc._claim_fixed_comment("vid1", ctx) is True


def test_claim_not_released_when_already_posted(tmp_path):
    import sqlite3
    import web_app.services.fixed_comment_service as fc

    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE youtube_status (local_id TEXT PRIMARY KEY, fixed_comment_posted INTEGER, fixed_comment_id TEXT)"
    )
    # 既に投稿済み（comment id あり）
    conn.execute("INSERT INTO youtube_status(local_id, fixed_comment_posted, fixed_comment_id) VALUES ('vid1', 1, 'ct_x')")
    conn.commit()
    conn.close()

    ctx = {"profile_id": "p", "db_path": str(db)}
    # 投稿済みの行は release で 0 に戻さない（fixed_comment_id がある間は保護）
    fc._release_fixed_comment_claim("vid1", ctx)
    conn = sqlite3.connect(db)
    posted = conn.execute("SELECT fixed_comment_posted FROM youtube_status WHERE local_id='vid1'").fetchone()[0]
    conn.close()
    assert posted == 1


# ── API ───────────────────────────────────────────────────────────────────────

def test_api_fixed_comment_task_status_and_toggle(monkeypatch):
    from fastapi.testclient import TestClient
    from web_app.app import app
    import core.fixed_comment_task as t

    client = TestClient(app)

    # GET は inspect() を返す。実 schtasks を叩かないようモックする。
    monkeypatch.setattr(t, "inspect", lambda: {
        "supported": True, "os": "Windows", "registered": False, "stale": False,
        "orphans": [], "task_name": "X", "target_dir": "d", "times": ["07:05"],
    })
    r = client.get("/api/settings/fixed-comment-task")
    assert r.status_code == 200
    assert "registered" in r.json()
    assert "orphans" in r.json()

    monkeypatch.setattr(t, "register", lambda: {"registered": True, "task_name": "X", "times": [], "supported": True, "os": "Windows", "target_dir": "d"})
    monkeypatch.setattr(t, "unregister", lambda: {"registered": False, "task_name": "X", "times": [], "supported": True, "os": "Windows", "target_dir": "d"})

    r = client.post("/api/settings/fixed-comment-task", json={"enabled": True})
    assert r.status_code == 200 and r.json()["registered"] is True

    r = client.post("/api/settings/fixed-comment-task", json={"enabled": False})
    assert r.status_code == 200 and r.json()["registered"] is False
