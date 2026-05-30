"""
アプリケーション安全終了管理モジュール。

使い方:
    from core.app_shutdown import register_shutdown_hook, request_shutdown, is_shutdown_requested

    # フック登録（起動時）
    register_shutdown_hook("metadata_db", close_all_connections)

    # 終了中チェック（重い処理の入口で確認）
    if is_shutdown_requested():
        raise RuntimeError("アプリ終了中です。新しい処理を受け付けられません。")

    # 終了要求（/api/shutdown から呼ばれる）
    result = request_shutdown(force=False)
"""
import logging
import os
import sys
import threading
import time
from typing import Callable

_logger = logging.getLogger(__name__)

# ── 状態管理 ────────────────────────────────────────────────────────────────
_shutdown_lock = threading.Lock()
_shutdown_requested = False
_hooks: list[tuple[str, Callable]] = []  # (name, callable)

# uvicorn.Server への参照（app.py から設定される）
_uvicorn_server = None


def set_uvicorn_server(server) -> None:
    """app.py 起動時に uvicorn.Server インスタンスを登録する。"""
    global _uvicorn_server
    _uvicorn_server = server


def register_shutdown_hook(name: str, fn: Callable) -> None:
    """終了時に呼ぶフックを登録する。登録順に実行される。例外が出ても次のフックを続ける。"""
    _hooks.append((name, fn))
    _logger.debug("終了フック登録: %s", name)


def is_shutdown_requested() -> bool:
    """終了処理が開始されているかどうかを返す。"""
    return _shutdown_requested


# ── 内部処理 ────────────────────────────────────────────────────────────────
def _get_running_jobs() -> list[dict]:
    try:
        from web_app.job_manager import get_job_manager
        return [j for j in get_job_manager().list_jobs() if j.get("status") == "running"]
    except Exception as e:
        _logger.warning("実行中ジョブ取得失敗: %s", e)
        return []


def _run_hooks() -> None:
    for name, fn in _hooks:
        try:
            fn()
            _logger.info("終了フック完了: %s", name)
        except Exception as e:
            _logger.error("終了フック失敗 (%s): %s", name, e)


def _stop_workers(timeout: float = 10.0) -> None:
    try:
        from web_app.worker_runner import cancel_all_workers
        cancel_all_workers(timeout=timeout)
    except Exception as e:
        _logger.error("worker停止エラー: %s", e)


def _stop_server() -> None:
    """uvicorn を正常停止させる。"""
    if _uvicorn_server is not None:
        _logger.info("uvicorn を正常停止します (should_exit=True)")
        _uvicorn_server.should_exit = True
        return

    # uvicorn.Server 参照がない場合のフォールバック（--reload モード等）
    _logger.warning("uvicorn サーバー参照が未設定 — シグナルで停止を試みます")
    try:
        import signal as _sig
        if sys.platform == "win32":
            os.kill(os.getpid(), _sig.CTRL_C_EVENT)
        else:
            os.kill(os.getpid(), _sig.SIGTERM)
    except Exception as e:
        _logger.error("シグナル送信失敗: %s — 1秒後に os._exit(0) で強制終了します", e)
        time.sleep(1.0)
        os._exit(0)


# ── 公開API ─────────────────────────────────────────────────────────────────
def request_shutdown(force: bool = False) -> dict:
    """
    終了要求を受け付ける。

    - 生成中workerがありforce=Falseの場合は拒否してその旨を返す。
    - force=Trueの場合はworkerに停止要求を出してから終了する。
    - 二重呼び出しは即座にOKを返す（処理は1回のみ）。

    Returns:
        {"ok": True, "message": ...} または {"ok": False, "reason": ..., "message": ..., "running_jobs": [...]}
    """
    global _shutdown_requested

    with _shutdown_lock:
        if _shutdown_requested:
            _logger.info("終了処理中に再度終了要求を受けました — 無視します")
            return {"ok": True, "reason": "already_shutting_down", "message": "終了処理はすでに開始されています"}

        running = _get_running_jobs()
        if running and not force:
            return {
                "ok": False,
                "reason": "worker_running",
                "message": "動画生成中です。停止して終了する場合は force=true を指定してください。",
                "running_jobs": [
                    {"job_id": j.get("job_id"), "type": j.get("type")} for j in running
                ],
            }

        _shutdown_requested = True

    _logger.info("正常終了要求を受け付けました (force=%s)", force)

    def _do() -> None:
        if force:
            running_now = _get_running_jobs()
            if running_now:
                _logger.info("実行中worker %d件に停止要求を送信します", len(running_now))
                _stop_workers(timeout=10.0)
        _run_hooks()
        time.sleep(0.2)
        _stop_server()

    threading.Thread(target=_do, daemon=True, name="shutdown-thread").start()
    return {"ok": True, "message": "終了処理を開始しました"}


def run_lifespan_shutdown() -> None:
    """lifespan の shutdown フェーズから呼ぶ。フックを実行する。"""
    if not _shutdown_requested:
        _logger.info("Ctrl+C / SIGTERM による終了 — フックを実行します")
    _run_hooks()
