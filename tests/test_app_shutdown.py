"""
tests/test_app_shutdown.py — app_shutdown モジュールのユニットテスト
"""
import importlib
import threading
import time

import pytest


def _reload_module():
    """テストごとにモジュールの状態をリセットする。"""
    import core.app_shutdown as m
    m._shutdown_requested = False
    m._hooks.clear()
    m._uvicorn_server = None


# ── フック登録・実行 ─────────────────────────────────────────────────────────

def test_hook_called_once_on_shutdown(monkeypatch):
    """shutdown フックが終了処理で1回だけ呼ばれること。"""
    _reload_module()
    import core.app_shutdown as m

    called = []
    m.register_shutdown_hook("test_hook", lambda: called.append(1))

    # _stop_server / 実行中ジョブ判定をモック（実DBの状態に依存させない）
    monkeypatch.setattr(m, "_stop_server", lambda: None)
    monkeypatch.setattr(m, "_get_running_jobs", lambda: [])

    result = m.request_shutdown(force=False)
    assert result["ok"] is True

    # バックグラウンドスレッドが完了するのを待つ
    time.sleep(0.5)
    assert called == [1], "フックが1回だけ呼ばれること"


def test_hook_exception_continues_next(monkeypatch):
    """フックで例外が出ても次のフックが実行されること。"""
    _reload_module()
    import core.app_shutdown as m

    order = []
    m.register_shutdown_hook("fail_hook", lambda: (_ for _ in ()).throw(RuntimeError("意図的エラー")))
    m.register_shutdown_hook("ok_hook", lambda: order.append("ok"))

    monkeypatch.setattr(m, "_stop_server", lambda: None)
    monkeypatch.setattr(m, "_get_running_jobs", lambda: [])
    m.request_shutdown(force=False)
    time.sleep(0.5)

    assert "ok" in order, "例外後のフックも実行されること"


# ── 通常終了の拒否 ───────────────────────────────────────────────────────────

def test_shutdown_rejected_when_worker_running(monkeypatch):
    """worker実行中は force=false で終了が拒否されること。"""
    _reload_module()
    import core.app_shutdown as m

    monkeypatch.setattr(m, "_get_running_jobs", lambda: [{"job_id": "abc", "type": "render"}])

    result = m.request_shutdown(force=False)
    assert result["ok"] is False
    assert result["reason"] == "worker_running"
    assert not m.is_shutdown_requested()


# ── force=true でworker停止要求 ──────────────────────────────────────────────

def test_force_shutdown_calls_stop_workers(monkeypatch):
    """force=true のとき実行中workerへ停止要求が出ること。"""
    _reload_module()
    import core.app_shutdown as m

    stopped = []
    monkeypatch.setattr(m, "_get_running_jobs", lambda: [{"job_id": "xyz", "type": "render"}])
    monkeypatch.setattr(m, "_stop_workers", lambda timeout=10.0: stopped.append(True))
    monkeypatch.setattr(m, "_stop_server", lambda: None)

    result = m.request_shutdown(force=True)
    assert result["ok"] is True
    time.sleep(0.5)
    assert stopped, "force=true で _stop_workers が呼ばれること"


# ── 二重終了 ─────────────────────────────────────────────────────────────────

def test_double_shutdown_returns_ok(monkeypatch):
    """2回目の終了要求は即座に ok を返すこと（二重処理なし）。"""
    _reload_module()
    import core.app_shutdown as m

    monkeypatch.setattr(m, "_stop_server", lambda: None)
    monkeypatch.setattr(m, "_get_running_jobs", lambda: [])

    r1 = m.request_shutdown(force=False)
    time.sleep(0.3)
    r2 = m.request_shutdown(force=False)

    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r2.get("reason") == "already_shutting_down"


# ── is_shutdown_requested ────────────────────────────────────────────────────

def test_is_shutdown_requested_false_initially():
    _reload_module()
    import core.app_shutdown as m
    assert m.is_shutdown_requested() is False


def test_is_shutdown_requested_true_after_shutdown(monkeypatch):
    _reload_module()
    import core.app_shutdown as m
    monkeypatch.setattr(m, "_stop_server", lambda: None)
    monkeypatch.setattr(m, "_get_running_jobs", lambda: [])
    m.request_shutdown(force=False)
    # フラグはリクエスト直後に立つ
    assert m.is_shutdown_requested() is True
