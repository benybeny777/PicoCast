"""DB queue から生成/レンダージョブを取得して実行する常駐 runner。"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from config import (  # noqa: E402
    JOB_LOG_FLUSH_INTERVAL_SEC,
    JOB_MAX_CONCURRENT_WORKERS,
    JOB_RUNNER_EXECUTOR_CAPACITY,
    JOB_RUNNER_HEARTBEAT_INTERVAL_SEC,
    JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC,
    JOB_RUNNER_POLL_INTERVAL_SEC,
)
from core.channel_profile import list_profiles, profile_context  # noqa: E402
from core.debug_logging import setup_debug_logging  # noqa: E402

_JST = timezone(timedelta(hours=9))
_logger = logging.getLogger("yj.runner")
_RUNNABLE_TYPES = ("generate", "render")
_worker_limit_cache: tuple[float, int] = (0.0, max(1, JOB_MAX_CONCURRENT_WORKERS))
_TAG_TO_LEVEL = {
    "error": logging.ERROR,
    "stderr": logging.ERROR,
    "warning": logging.WARNING,
    "success": logging.INFO,
    "info": logging.INFO,
}


def _now_iso() -> str:
    return datetime.now(_JST).isoformat()


def _current_worker_limit(capacity: int) -> int:
    """settings.db の runner 並行数を読み、次の claim 判断へ反映する。"""
    global _worker_limit_cache
    now = time.monotonic()
    cached_at, cached_value = _worker_limit_cache
    if now - cached_at < 2.0:
        return min(max(1, cached_value), capacity)

    from core.settings_store import get_all

    raw = get_all().get("JOB_MAX_CONCURRENT_WORKERS", str(JOB_MAX_CONCURRENT_WORKERS))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"JOB_MAX_CONCURRENT_WORKERS が整数ではありません: {raw}") from exc
    if value < 1 or value > capacity:
        raise RuntimeError(f"JOB_MAX_CONCURRENT_WORKERS は 1〜{capacity} の範囲で指定してください: {value}")
    if value != cached_value:
        _logger.info("runner同時実行数を更新しました: %s -> %s", cached_value, value)
    _worker_limit_cache = (now, value)
    return value


class _BufferedJobLog:
    def __init__(self, profile_id: str, job_id: str):
        self.profile_id = profile_id
        self.job_id = job_id
        self._entries: list[dict[str, str]] = []
        self._last_flush = 0.0
        self._last_tag = ""
        self._last_message = ""
        self._lock = threading.Lock()

    def add(self, message: str, tag: str = "info", force: bool = False) -> None:
        normalized_tag = tag or "info"
        normalized_message = str(message)
        entry = {"time": _now_iso(), "tag": normalized_tag, "message": normalized_message}
        with self._lock:
            self._entries.append(entry)
            self._last_tag = normalized_tag
            self._last_message = normalized_message
        try:
            _logger.log(
                _TAG_TO_LEVEL.get(normalized_tag, logging.INFO),
                "[runner job=%s] %s",
                self.job_id[:8],
                normalized_message,
            )
        except Exception:
            logging.getLogger(__name__).warning("ジョブログのデバッグログミラーに失敗しました: job_id=%s", self.job_id, exc_info=True)  # フォールバック許可: ミラー失敗はジョブ進行を妨げない（自己ロガー再帰回避のため別ロガー使用）
        if force or time.monotonic() - self._last_flush >= JOB_LOG_FLUSH_INTERVAL_SEC:
            self.flush()

    def is_last(self, message: str, tag: str = "info") -> bool:
        with self._lock:
            return self._last_tag == (tag or "info") and self._last_message == str(message)

    def flush(self) -> None:
        with self._lock:
            entries = list(self._entries)
            self._entries.clear()
        if not entries:
            return
        from core.metadata_db import append_job_logs
        with profile_context(self.profile_id):
            append_job_logs(self.job_id, entries)
        self._last_flush = time.monotonic()


def _job_topic(script: str) -> str:
    from core.parser import ScriptParser
    items = ScriptParser.parse_string(script)
    meta = {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}
    return (meta.get("video_title") or "").strip() or "unknown"


def _run_generate(job: dict, cancel_event: threading.Event, log: _BufferedJobLog) -> dict[str, Any]:
    params = job.get("params") or {}
    script = params.get("script") or params.get("pregenerated_script") or ""
    topic = _job_topic(script)
    log.add("台本を解析中...")
    log.add(f"動画生成開始: {topic}")

    from workers.main import run_pipeline
    msg, report = run_pipeline(
        topic,
        pregenerated_script=script,
        image_style=params.get("image_style", "通常"),
        background_engine=params.get("background_engine", ""),
        reuse_backgrounds=bool(params.get("reuse_backgrounds", False)),
        reuse_audio=bool(params.get("reuse_audio", False)),
        cancel_event=cancel_event,
        progress_callback=lambda message, tag="info": log.add(message, tag),
        long_thumbnail_ab_test=params.get("long_thumbnail_ab_test"),
        long_budget_mode=params.get("long_budget_mode"),
        bgm_mode=params.get("bgm_mode", "profile_default"),
        bgm_id=params.get("bgm_id"),
        bgm_volume_db=params.get("bgm_volume_db"),
    )
    result = {
        "topic": topic,
        "message": msg,
        "theme_dir": getattr(report, "theme_dir", None),
        "elapsed_sec": getattr(report, "elapsed_sec", None),
    }
    if params.get("with_render") and not cancel_event.is_set() and not str(msg).lstrip().startswith("❌"):
        from web_app.services.render_service import submit_render_job
        history_name = os.path.basename(str(result.get("theme_dir") or "")) or topic
        render_job_id = submit_render_job(
            history_name,
            params.get("bgm_mode", "profile_default"),
            params.get("bgm_id"),
            params.get("bgm_volume_db"),
        )
        result["render_job_id"] = render_job_id
        log.add(f"🎬 レンダージョブを登録しました (job_id={render_job_id[:8]}…)")
    return result


def _run_render(job: dict, cancel_event: threading.Event, log: _BufferedJobLog) -> dict[str, Any]:
    params = job.get("params") or {}
    history_name = params["history_name"]
    theme_dir = params["theme_dir"]
    log.add("audio/ と backgrounds/ から MP4 を再生成します")
    log.add(f"対象フォルダ: {theme_dir}")
    if cancel_event.is_set():
        return {"cancelled": True}
    from core.native_renderer import render_native, RenderCancelled
    try:
        render_result = render_native(
            output_dir=theme_dir,
            progress_callback=lambda message, tag="info": log.add(message, tag),
            bgm_mode=params.get("bgm_mode", "profile_default"),
            bgm_id=params.get("bgm_id"),
            bgm_volume_db=params.get("bgm_volume_db"),
            cancel_event=cancel_event,
        )
    except RenderCancelled:
        _logger.info("レンダーがキャンセルされました: job=%s history=%s", log.job_id[:8], history_name)
        return {"cancelled": True}
    output_path = render_result.output_path if hasattr(render_result, "output_path") else str(render_result)
    done_msg = f"✅ MP4 生成完了: {os.path.basename(output_path)}"
    log.add(done_msg, "success")
    # message が空だと _result_error_message が「原因不明で終了」と誤判定するため、
    # レンダー成功時も必ず結果メッセージを返す（生成ジョブと揃える）。
    return {"output_path": output_path, "history_name": history_name, "message": done_msg}


def _result_error_message(result: dict[str, Any] | None) -> str:
    message = str((result or {}).get("message") or "").strip()
    if not message:
        return "❌ 生成が原因不明で終了しました（結果メッセージが空です）"
    lowered = message.lower()
    if message.lstrip().startswith("❌") or lowered.startswith("error"):
        return message
    return ""


def _watch_cancel_and_heartbeat(profile_id: str, job_id: str, cancel_event: threading.Event, stop_event: threading.Event) -> None:
    from core.metadata_db import is_cancel_requested, update_job_progress

    last_heartbeat = 0.0
    while not stop_event.wait(JOB_RUNNER_POLL_INTERVAL_SEC):
        with profile_context(profile_id):
            if is_cancel_requested(job_id):
                cancel_event.set()
            if time.monotonic() - last_heartbeat >= JOB_RUNNER_HEARTBEAT_INTERVAL_SEC:
                update_job_progress(job_id, None, _now_iso())
                last_heartbeat = time.monotonic()


def _run_job(job: dict) -> None:
    profile_id = job.get("profile_id")
    job_id = job["job_id"]
    job_type = job.get("type")
    cancel_event = threading.Event()
    stop_event = threading.Event()
    log = _BufferedJobLog(profile_id, job_id)
    watcher = threading.Thread(target=_watch_cancel_and_heartbeat, args=(profile_id, job_id, cancel_event, stop_event), daemon=True)
    watcher.start()
    status = "failed"
    result: dict[str, Any] | None = None
    error: str | None = None
    try:
        with profile_context(profile_id):
            if job_type == "generate":
                result = _run_generate(job, cancel_event, log)
            elif job_type == "render":
                result = _run_render(job, cancel_event, log)
            else:
                raise RuntimeError(f"未対応のジョブ種別です: {job_type}")
        if cancel_event.is_set() or (result or {}).get("cancelled"):
            status = "cancelled"
            log.add("キャンセル済み", "warning", force=True)
        elif _result_error_message(result):
            status = "failed"
            error = _result_error_message(result)
            if not log.is_last(error, "error"):
                log.add(error, "error", force=True)
            # ジョブ失敗は job ログだけでなく debug ログにも必ず残す（結果メッセージ異常経路）。
            _logger.error(
                "job失敗(結果メッセージ): job=%s type=%s profile=%s result=%r error=%s",
                job_id[:8], job_type, profile_id, result, error,
            )
        else:
            status = "success"
    except Exception as exc:
        status = "failed"
        error = str(exc)
        log.add(f"エラー: {exc}", "error", force=True)
        log.add(traceback.format_exc(), "error", force=True)
        # ジョブ失敗は job ログだけでなく debug ログにもスタックつきで必ず残す（例外経路）。
        _logger.error(
            "job失敗(例外): job=%s type=%s profile=%s: %s",
            job_id[:8], job_type, profile_id, exc, exc_info=exc,
        )
    finally:
        stop_event.set()
        log.flush()
        from core.metadata_db import set_job_result
        with profile_context(profile_id):
            set_job_result(job_id, status, result, error, _now_iso())
        if status == "failed":
            _logger.error("job完了: job=%s type=%s status=%s profile=%s error=%s",
                          job_id[:8], job_type, status, profile_id, error)
        else:
            _logger.info("job完了: job=%s type=%s status=%s profile=%s", job_id[:8], job_type, status, profile_id)


def _discard_pending_on_startup() -> None:
    """起動時に残っていた前回の未実行(queued)ジョブを破棄し、自動実行しないようにする。"""
    from core.metadata_db import discard_pending_jobs, initialize_db, is_initialized

    total = 0
    for profile in list_profiles():
        with profile_context(profile.profile_id):
            if not is_initialized():
                initialize_db()
            total += discard_pending_jobs(_RUNNABLE_TYPES)
    if total:
        _logger.info("起動時に前回の未実行ジョブを破棄しました: count=%s", total)


def _claim_one(pid: int) -> dict | None:
    from core.metadata_db import claim_queued_job, initialize_db, is_initialized, reap_stale_running_jobs

    for profile in list_profiles():
        with profile_context(profile.profile_id):
            if not is_initialized():
                initialize_db()
            reaped = reap_stale_running_jobs(JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC)
            if reaped:
                _logger.warning("heartbeat切れのrunnerジョブを失敗化しました: profile=%s count=%s", profile.profile_id, reaped)
            job = claim_queued_job(pid, _RUNNABLE_TYPES)
            if job:
                job["profile_id"] = job.get("profile_id") or profile.profile_id
                return job
    return None


def main() -> None:
    setup_debug_logging(role="runner")
    pid = os.getpid()
    executor_capacity = max(1, JOB_RUNNER_EXECUTOR_CAPACITY, JOB_MAX_CONCURRENT_WORKERS)
    _logger.info("runner起動 pid=%s capacity=%s max_workers=%s", pid, executor_capacity, JOB_MAX_CONCURRENT_WORKERS)
    _discard_pending_on_startup()
    futures = set()
    with ThreadPoolExecutor(max_workers=executor_capacity) as executor:
        try:
            while True:
                futures = {f for f in futures if not f.done()}
                worker_limit = _current_worker_limit(executor_capacity)
                while len(futures) < worker_limit:
                    job = _claim_one(pid)
                    if not job:
                        break
                    _logger.info("job取得: job=%s type=%s profile=%s", job["job_id"][:8], job.get("type"), job.get("profile_id"))
                    futures.add(executor.submit(_run_job, job))
                if futures:
                    wait(futures, timeout=JOB_RUNNER_POLL_INTERVAL_SEC, return_when=FIRST_COMPLETED)
                else:
                    time.sleep(JOB_RUNNER_POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            _logger.info("runner停止要求")


if __name__ == "__main__":
    main()
