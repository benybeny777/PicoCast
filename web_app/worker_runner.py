"""
バックグラウンドジョブ用 subprocess 実行ヘルパー。
worker_pipeline.py / worker_render.py を subprocess で起動し、
stdout JSONL を Job.logs へ転送する。
キャンセルは stdin へ "cancel\n" を送り、タイムアウト後に terminate する。
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import tempfile
import threading
from typing import Any

from web_app.job_manager import Job, _log

# worker スクリプトが置いてあるプロジェクトルート（web_app/ の一つ上）
_WORKER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# subprocess に渡す環境変数（PYTHONIOENCODING を強制して文字化けを防ぐ）
_WORKER_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}

# 起動中ワーカープロセスを追跡して atexit で強制終了する
_running_procs: set[subprocess.Popen] = set()
_procs_lock = threading.Lock()


def _kill_all_workers() -> None:
    with _procs_lock:
        procs = list(_running_procs)
    for proc in procs:
        try:
            _kill_tree(proc)
        except Exception as e:
            print(f"Failed to kill worker {proc.pid}: {e}", file=sys.stderr)
            pass  # フォールバック許可: atexit時はエラーを無視して後続のkillを継続する


atexit.register(_kill_all_workers)

# Windows ではプロセスグループを新規作成して子プロセスツリーをまとめて kill できるようにする
_POPEN_EXTRA: dict[str, Any] = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    if sys.platform == "win32"
    else {}
)


def _kill_tree(proc: subprocess.Popen) -> None:
    """プロセスとその子プロセスをすべて強制終了する。"""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            check=False,
            capture_output=True,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_in_worker(worker_name: str, params: dict[str, Any], job: Job) -> dict[str, Any]:
    """
    worker_name（例: "worker_pipeline.py"）をサブプロセスで実行する。
    進捗 JSONL を job.logs へ転送し、result dict を返す。
    ワーカー失敗時は RuntimeError を raise する。
    """
    worker_script = os.path.join(_WORKER_DIR, worker_name)
    if not os.path.isfile(worker_script):
        raise FileNotFoundError(f"ワーカースクリプトが見つかりません: {worker_script}")

    with tempfile.TemporaryDirectory(prefix="yjworker_") as tmpdir:
        input_path = os.path.join(tmpdir, "input.json")
        result_path = os.path.join(tmpdir, "result.json")

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False)

        proc = subprocess.Popen(
            [sys.executable, worker_script, "--input", input_path, "--result", result_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=_WORKER_DIR,
            env=_WORKER_ENV,
            **_POPEN_EXTRA,
        )

        with _procs_lock:
            _running_procs.add(proc)

        def _cancel_monitor() -> None:
            """cancel_event を監視して stdin に cancel を送り、タイムアウト後にツリーごと kill する。
            プロセスが正常終了した場合は何もせずに抜ける（①スレッドリーク対策）。"""
            while not job.cancel_event.wait(timeout=0.5):
                if proc.poll() is not None:
                    return
            try:
                proc.stdin.write("cancel\n")
                proc.stdin.flush()
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)  # ③ ffmpeg 孤立防止: ツリーごと強制終了

        cancel_thread = threading.Thread(target=_cancel_monitor, daemon=True)
        cancel_thread.start()

        # stderr をバックグラウンドで読み捨て（パイプバッファ詰まり防止）
        stderr_lines: list[str] = []

        def _drain_stderr() -> None:
            for line in proc.stderr:
                stderr_lines.append(line.rstrip())

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # stdout JSONL を読んで job.logs へ転送
        for raw in proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
                _log(job, entry.get("message", raw), entry.get("tag", "info"))
            except json.JSONDecodeError:
                _log(job, raw, "info")

        # ② stdout 閉鎖後のハングに備えてタイムアウトを設ける
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
        finally:
            with _procs_lock:
                _running_procs.discard(proc)
        stderr_thread.join(timeout=2)

        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                return json.load(f)

        # result ファイルがない＝ worker がクラッシュした
        err_tail = "\n".join(stderr_lines[-20:]) if stderr_lines else "(stderr なし)"
        raise RuntimeError(f"ワーカーが結果ファイルを生成しませんでした\n{err_tail}")
