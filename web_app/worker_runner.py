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
import time
from typing import Any

from web_app.job_manager import Job, _log

# worker スクリプトが置いてあるプロジェクトルート（web_app/ の一つ上）
_WORKER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ワーカーsubprocess の同時起動数を制御するキュー用ゲート。
# 複数ジョブを同時実行すると Web プロセスが応答不能（ブロック）になり UI のログ更新が
# 止まる事象を防ぐため、起動数を制限してキューイングする。
# 追加インフラ不要・純Python実装なので配布物にそのまま同梱できる。
#
# Apache MPM 風に下限(min)・上限(max)を config で定義し、待ち行列（負荷）に応じて
# min↔max の範囲で同時実行数を自動増減する。
from config import (  # noqa: E402
    JOB_MIN_CONCURRENT_WORKERS as _MIN_CONCURRENT_WORKERS,
    JOB_MAX_CONCURRENT_WORKERS as _MAX_CONCURRENT_WORKERS,
)
if _MIN_CONCURRENT_WORKERS < 1 or _MAX_CONCURRENT_WORKERS < _MIN_CONCURRENT_WORKERS:
    raise ValueError(
        "JOB_MIN/MAX_CONCURRENT_WORKERS が不正です: "
        f"min={_MIN_CONCURRENT_WORKERS}, max={_MAX_CONCURRENT_WORKERS}（1 <= min <= max が必要）"
    )


class _ConcurrencyGate:
    """同時実行数を min↔max で自動増減するゲート（Apache MPM 風）。

    - 待ち行列（acquire 待ち）が出ると上限 max まで段階的にスケールアップする。
    - 待ちが無くなると下限 min まで段階的にスケールダウンする。
    - `BoundedSemaphore` と異なり実行中に許容数を変えられる。
    - `with gate:` で1枠を確保し、ブロックを抜けると解放する。
    """

    def __init__(self, min_workers: int, max_workers: int):
        self._min = min_workers
        self._max = max_workers
        self._limit = min_workers   # 現在の許容同時実行数
        self._active = 0            # 実行中の枠数
        self._waiting = 0           # acquire 待ちの数（=負荷）
        self._cond = threading.Condition()

    def would_queue(self) -> bool:
        """今 acquire したら（スケールアップしても）順番待ちになるか（ログ表示用・概算）。"""
        with self._cond:
            return self._active >= self._limit and self._limit >= self._max

    def _scale_up_locked(self) -> None:
        if self._waiting > 0 and self._limit < self._max:
            self._limit += 1
            self._cond.notify_all()

    def _scale_down_locked(self) -> None:
        if self._waiting == 0 and self._limit > self._min:
            self._limit -= 1

    def __enter__(self):
        with self._cond:
            self._waiting += 1
            self._scale_up_locked()
            while self._active >= self._limit:
                self._cond.wait()
                self._scale_up_locked()
            self._waiting -= 1
            self._active += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        with self._cond:
            self._active -= 1
            self._scale_down_locked()
            self._cond.notify_all()
        return False


_worker_gate = _ConcurrencyGate(_MIN_CONCURRENT_WORKERS, _MAX_CONCURRENT_WORKERS)

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


def cancel_all_workers(timeout: float = 10.0) -> None:
    """実行中の全workerに停止要求を送り、残れば terminate → kill する。
    shutdown処理から呼ばれる。"""
    with _procs_lock:
        procs = list(_running_procs)
    if not procs:
        return
    print(f"[shutdown] {len(procs)}件のworkerに停止要求を送信します", file=sys.stderr)
    # まずキャンセル要求（stdin "cancel\n"）を試みる
    for proc in procs:
        try:
            proc.stdin.write("cancel\n")
            proc.stdin.flush()
        except OSError:
            pass
    # timeout 秒待って残存プロセスをterminate → kill
    deadline = time.monotonic() + timeout
    for proc in procs:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                proc.wait(timeout=max(0.1, remaining))
                continue
            except subprocess.TimeoutExpired:
                pass
        # terminate
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
            continue
        except subprocess.TimeoutExpired:
            pass
        # 最終手段: kill
        print(f"[shutdown] worker pid={proc.pid} が停止しないため強制終了します", file=sys.stderr)
        try:
            _kill_tree(proc)
        except Exception as e:
            print(f"[shutdown] worker kill失敗 pid={proc.pid}: {e}", file=sys.stderr)

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

    # 同時実行上限(max)に達していれば、この先の `with _worker_gate` で順番待ち（キュー）になる。
    # 待ちになりそうなときだけ待機メッセージをログに出す。
    if _worker_gate.would_queue():
        _log(job, f"⏳ 他のジョブ実行中のため順番待ちです（同時実行 上限{_MAX_CONCURRENT_WORKERS}）", "info")

    # _worker_gate の1枠を保持している間だけ subprocess を起動・実行する（負荷で min↔max に自動増減）
    with _worker_gate, tempfile.TemporaryDirectory(prefix="yjworker_") as tmpdir:
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

        # stderr をリアルタイムで job.logs へ転送（パイプバッファ詰まりを防ぎつつログに残す）
        stderr_lines: list[str] = []

        def _drain_stderr() -> None:
            for line in proc.stderr:
                stripped = line.rstrip()
                if not stripped:
                    continue
                stderr_lines.append(stripped)
                # traceback・ImportError など Python 例外を job.logs に転送する
                _log(job, stripped, "stderr")

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # stdout JSONL を読んで job.logs へ転送
        for raw in proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
                _log(job, entry.get("message", raw), entry.get("tag") or "info")
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
                result = json.load(f)
            # worker が status=failed を返した場合もエラー内容をログに記録
            if result.get("status") == "failed":
                err_msg = result.get("error") or "ワーカーエラー（詳細不明）"
                _log(job, f"❌ ワーカー失敗: {err_msg}", "error")
            return result

        # result ファイルがない＝ worker がクラッシュした
        err_tail = "\n".join(stderr_lines[-30:]) if stderr_lines else "(stderr なし)"
        raise RuntimeError(f"ワーカーが結果ファイルを生成しませんでした\n{err_tail}")
