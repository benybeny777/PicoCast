"""Web UI 多重起動防止ロックのテスト。"""
import os
import subprocess
import sys

import pytest

import core.instance_lock as instance_lock


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(instance_lock, "app_base_dir", lambda: str(tmp_path))
    return tmp_path


def test_second_acquire_fails_while_first_is_held(lock_dir):
    first = instance_lock.acquire()
    assert first is not None
    try:
        assert instance_lock.acquire() is None
    finally:
        first.release()
    again = instance_lock.acquire()
    assert again is not None
    again.release()


def test_lock_held_by_other_process_blocks_acquire(lock_dir):
    """別プロセスが保持している間は取れず、そのプロセスが終われば取れる（異常終了でも OS が解放する）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import sys, core.instance_lock as l\n"
        f"l.app_base_dir = lambda: {str(lock_dir)!r}\n"
        "lock = l.acquire()\n"
        "print('locked' if lock else 'busy', flush=True)\n"
        "sys.stdin.readline()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        assert instance_lock.acquire() is None
    finally:
        proc.kill()
        proc.wait(timeout=10)
        proc.stdin.close()
        proc.stdout.close()
    lock = instance_lock.acquire()
    assert lock is not None
    lock.release()


def test_running_instance_url_round_trip(lock_dir):
    assert instance_lock.running_instance_url() is None
    lock = instance_lock.acquire()
    try:
        lock.record_url("http://127.0.0.1:8001")
        assert instance_lock.running_instance_url() == "http://127.0.0.1:8001"
    finally:
        lock.release()


def test_running_instance_url_unreadable_returns_none(lock_dir):
    (lock_dir / "data").mkdir(exist_ok=True)
    (lock_dir / "data" / "web_ui_instance.json").write_text("{壊れた", encoding="utf-8")
    assert instance_lock.running_instance_url() is None


def test_second_launch_opens_existing_instance_instead_of_starting(lock_dir, monkeypatch):
    """既定ポートが別アプリ使用中で退避起動した既存インスタンスがあっても、2つ目は起動しない。"""
    import web_app.app as app_mod

    held = instance_lock.acquire()
    held.record_url("http://127.0.0.1:8001")
    opened = []
    monkeypatch.setattr(sys, "argv", ["app.py", "--open-browser"])
    monkeypatch.setattr(app_mod, "_probe_existing_url", lambda url: url == "http://127.0.0.1:8001")
    monkeypatch.setattr(app_mod, "_open_browser_to", opened.append)
    monkeypatch.setattr(app_mod, "_is_port_free", lambda host, port: pytest.fail("ポート確認まで進んではいけない"))
    try:
        app_mod.main()
    finally:
        held.release()
    assert opened == ["http://127.0.0.1:8001"]


def test_second_launch_without_reachable_instance_exits_with_error(lock_dir, monkeypatch, capsys):
    import web_app.app as app_mod

    held = instance_lock.acquire()
    monkeypatch.setattr(sys, "argv", ["app.py", "--no-open-browser"])
    monkeypatch.setattr(app_mod, "_is_port_free", lambda host, port: pytest.fail("ポート確認まで進んではいけない"))
    try:
        with pytest.raises(SystemExit) as exc:
            app_mod.main()
    finally:
        held.release()
    assert exc.value.code == 1
    assert "起動処理中または終了処理中" in capsys.readouterr().out
