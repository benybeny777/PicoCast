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
    JOB_RUNNER_HEARTBEAT_INTERVAL_SEC,
    JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC,
    JOB_RUNNER_POLL_INTERVAL_SEC,
)
from core.channel_profile import list_profiles, profile_context  # noqa: E402
from core.debug_logging import setup_debug_logging  # noqa: E402

_JST = timezone(timedelta(hours=9))
_logger = logging.getLogger("yj.runner")
_RUNNABLE_TYPES = ("generate", "render")


def _now_iso() -> str:
    return datetime.now(_JST).isoformat()


class _BufferedJobLog:
    def __init__(self, profile_id: str, job_id: str):
        self.profile_id = profile_id
        self.job_id = job_id
        self._entries: list[dict[str, str]] = []
        self._last_flush = 0.0
        self._lock = threading.Lock()

    def add(self, message: str, tag: str = "info", force: bool = False) -> None:
        entry = {"time": _now_iso(), "tag": tag or "info", "message": str(message)}
        with self._lock:
            self._entries.append(entry)
        if force or time.monotonic() - self._last_flush >= JOB_LOG_FLUSH_INTERVAL_SEC:
            self.flush()

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
        sd_size_mode=bool(params.get("sd_size_mode", False)),
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
    from core.native_renderer import render_native_test
    render_result = render_native_test(
        output_dir=theme_dir,
        progress_callback=lambda message, tag="info": log.add(message, tag),
        bgm_mode=params.get("bgm_mode", "profile_default"),
        bgm_id=params.get("bgm_id"),
        bgm_volume_db=params.get("bgm_volume_db"),
    )
    output_path = render_result.output_path if hasattr(render_result, "output_path") else str(render_result)
    log.add(f"MP4 生成完了: {os.path.basename(output_path)}", "success")
    return {"output_path": output_path, "history_name": history_name}


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
        elif str((result or {}).get("message", "")).lstrip().startswith("❌"):
            status = "failed"
            error = str((result or {}).get("message", "生成エラー"))
            log.add(error, "error", force=True)
        else:
            status = "success"
    except Exception as exc:
        status = "failed"
        error = str(exc)
        log.add(f"エラー: {exc}", "error", force=True)
        log.add(traceback.format_exc(), "error", force=True)
    finally:
        stop_event.set()
        log.flush()
        from core.metadata_db import set_job_result
        with profile_context(profile_id):
            set_job_result(job_id, status, result, error, _now_iso())
        _logger.info("job完了: job=%s type=%s status=%s profile=%s", job_id[:8], job_type, status, profile_id)


def _claim_one(pid: int) -> dict | None:
    from core.metadata_db import claim_queued_job, initialize_db, is_initialized, reap_stale_running_jobs

    for profile in list_profiles():
        with profile_context(profile.profile_id):
            if not is_initialized():
                initialize_db()
            reap_stale_running_jobs(JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC)
            job = claim_queued_job(pid, _RUNNABLE_TYPES)
            if job:
                job["profile_id"] = job.get("profile_id") or profile.profile_id
                return job
    return None


def main() -> None:
    setup_debug_logging(role="runner")
    pid = os.getpid()
    _logger.info("runner起動 pid=%s max_workers=%s", pid, JOB_MAX_CONCURRENT_WORKERS)
    futures = set()
    with ThreadPoolExecutor(max_workers=max(1, JOB_MAX_CONCURRENT_WORKERS)) as executor:
        try:
            while True:
                futures = {f for f in futures if not f.done()}
                while len(futures) < max(1, JOB_MAX_CONCURRENT_WORKERS):
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
