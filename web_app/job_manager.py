"""
ジョブ管理モジュール。

Web プロセスはジョブ状態を DB に登録・参照する。生成/レンダーは
workers.runner が queued ジョブを取得して実行する。その他の軽量ジョブは
従来互換のため Web プロセス内スレッドで実行するが、状態は DB を正本にする。
"""
from __future__ import annotations

import atexit
import logging
import threading
import traceback
import uuid
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

_JST = timezone(timedelta(hours=9))

_job_logger = logging.getLogger("yj.job")
_TAG_TO_LEVEL = {
    "error": logging.ERROR,
    "stderr": logging.ERROR,
    "warning": logging.WARNING,
    "success": logging.INFO,
    "info": logging.INFO,
}


def _profile_scope(profile_id: str | None):
    if not profile_id:
        return nullcontext()
    from core.channel_profile import profile_context
    return profile_context(profile_id)


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _now_iso() -> str:
    return datetime.now(_JST).isoformat()


class Job:
    def __init__(self, job_id: str, job_type: str, profile_id: str | None = None, params: dict | None = None):
        self.job_id = job_id
        self.type = job_type
        self.profile_id = profile_id
        self.status = JobStatus.QUEUED
        self.progress_text = ""
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.logs: list[dict[str, str]] = []
        self.result: Any = None
        self.error: str | None = None
        self.params = params or {}
        self.cancel_requested = False
        self.cancel_event = threading.Event()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "type": self.type,
            "profile_id": self.profile_id,
            "status": self.status,
            "progress_text": self.progress_text,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "logs": self.logs,
            "result": self.result,
            "error": self.error,
            "params": self.params,
            "cancel_requested": self.cancel_requested,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        job = cls(d["job_id"], d.get("type") or d.get("job_type") or "unknown", d.get("profile_id"), d.get("params") or {})
        job.status = d.get("status", JobStatus.FAILED)
        job.progress_text = d.get("progress_text", "")
        job.logs = d.get("logs") or []
        job.result = d.get("result")
        job.error = d.get("error")
        job.cancel_requested = bool(d.get("cancel_requested"))
        started = d.get("started_at")
        job.started_at = datetime.fromisoformat(started) if started else None
        finished = d.get("finished_at")
        job.finished_at = datetime.fromisoformat(finished) if finished else None
        return job


class JobManager:
    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running: dict[str, Job] = {}
        self._lock = threading.Lock()
        atexit.register(lambda: self._executor.shutdown(wait=False))

    def _active_profile_id(self) -> str | None:
        # active profile 未設定は None（正常系）。get_active_profile は未設定時のみ
        # None を返し、DB エラー等は例外として上位へ伝播させる（サイレント握り潰し禁止）。
        from core.channel_profile import get_active_profile
        profile = get_active_profile()
        return profile.profile_id if profile else None

    def create_job(self, job_type: str, params: dict | None = None, queued: bool = True) -> Job:
        from core.metadata_db import initialize_db, is_initialized, upsert_job
        if not is_initialized():
            initialize_db()
        job = Job(str(uuid.uuid4()), job_type, self._active_profile_id(), params or {})
        job.status = JobStatus.QUEUED if queued else JobStatus.RUNNING
        upsert_job(job.to_dict())
        if not queued:
            with self._lock:
                self._running[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        from core.metadata_db import load_jobs_from_db
        with self._lock:
            running = self._running.get(job_id)
            if running and running.status != JobStatus.QUEUED:
                return running
        for profile_id in self._lookup_profile_ids():
            with _profile_scope(profile_id):
                for d in load_jobs_from_db(max_n=1000):
                    if d.get("job_id") == job_id:
                        return Job.from_dict(d)
        if not self._lookup_profile_ids():
            for d in load_jobs_from_db(max_n=1000):
                if d.get("job_id") == job_id:
                    return Job.from_dict(d)
        return None

    def list_jobs(self) -> list[dict]:
        from config import JOB_LOG_MAX_JOBS
        from core.metadata_db import load_jobs_from_db, initialize_db, is_initialized
        if not is_initialized():
            initialize_db()
        return [Job.from_dict(d).to_dict() for d in load_jobs_from_db(max_n=JOB_LOG_MAX_JOBS)]

    def cancel_job(self, job_id: str) -> bool:
        from core.metadata_db import request_cancel
        with self._lock:
            job = self._running.get(job_id)
            if job:
                with _profile_scope(job.profile_id):
                    ok = request_cancel(job_id)
                self._mark_cancelled_in_memory(job)
                return ok
        for profile_id in self._lookup_profile_ids():
            with _profile_scope(profile_id):
                if request_cancel(job_id):
                    return True
        if not self._lookup_profile_ids():
            return request_cancel(job_id)
        return False

    def _lookup_profile_ids(self) -> list[str]:
        ids: list[str] = []
        active_id = self._active_profile_id()
        if active_id:
            ids.append(active_id)
        try:
            from core.channel_profile import list_profiles
            for profile in list_profiles():
                if profile.profile_id not in ids:
                    ids.append(profile.profile_id)
        except Exception as exc:
            raise RuntimeError(f"ジョブ検索用のチャンネル一覧取得に失敗しました: {exc}") from exc
        return ids

    def _mark_cancelled_in_memory(self, job: Job) -> None:
        job.cancel_event.set()
        job.cancel_requested = True
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            job.status = JobStatus.CANCELLED
            job.progress_text = "キャンセル要求済み"

    def submit(self, job: Job, fn: Callable, *args, **kwargs) -> None:
        """従来互換: 軽量ジョブを Web プロセス内スレッドで実行する。"""
        from core.metadata_db import set_job_result, update_job_progress, upsert_job

        with self._lock:
            self._running[job.job_id] = job

        def _run():
            stop_heartbeat = threading.Event()

            def _heartbeat_loop() -> None:
                from config import JOB_RUNNER_HEARTBEAT_INTERVAL_SEC
                while not stop_heartbeat.wait(max(0.5, float(JOB_RUNNER_HEARTBEAT_INTERVAL_SEC))):
                    with _profile_scope(job.profile_id):
                        update_job_progress(job.job_id, None, _now_iso())

            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(_JST)
            with _profile_scope(job.profile_id):
                upsert_job(job.to_dict())
                update_job_progress(job.job_id, "実行中", _now_iso())
            heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name=f"job-heartbeat-{job.job_id[:8]}")
            heartbeat_thread.start()
            _job_logger.info("[%s job=%s] ▶ 開始", job.type, job.job_id[:8])
            try:
                result = fn(job, *args, **kwargs)
                if job.cancel_event.is_set():
                    job.status = JobStatus.CANCELLED
                    job.progress_text = "キャンセル済み"
                else:
                    job.status = JobStatus.SUCCESS
                    job.result = result
            except Exception as e:
                _job_logger.error("[%s job=%s] ジョブ実行に失敗しました", job.type, job.job_id[:8], exc_info=True)
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.progress_text = f"エラー: {e}"
                _log(job, f"エラー: {e}", "error")
                tb = traceback.format_exc()
                if tb and tb.strip() != "NoneType: None":
                    _log(job, tb, "error")
            finally:
                stop_heartbeat.set()
                heartbeat_thread.join(timeout=1.0)
                job.finished_at = datetime.now(_JST)
                with _profile_scope(job.profile_id):
                    set_job_result(job.job_id, job.status, job.result, job.error, job.finished_at.isoformat())
                    upsert_job(job.to_dict())
                with self._lock:
                    self._running.pop(job.job_id, None)
                _job_logger.info("[%s job=%s] ■ 終了 status=%s", job.type, job.job_id[:8], job.status)

        self._executor.submit(_run)


def _log(job: Job, message: str, tag: str = "info") -> None:
    from core.metadata_db import append_job_logs

    tag = tag or "info"
    entry = {"time": _now_iso(), "tag": tag, "message": message}
    job.logs.append(entry)
    job.progress_text = message
    with _profile_scope(job.profile_id):
        append_job_logs(job.job_id, [entry])
    try:
        _job_logger.log(_TAG_TO_LEVEL.get(tag, logging.INFO), "[%s job=%s] %s", job.type, job.job_id[:8], message)
    except Exception:
        logging.getLogger(__name__).warning("ジョブログのデバッグログミラーに失敗しました: job_id=%s", job.job_id, exc_info=True)
        pass  # フォールバック許可: デバッグログへのミラー失敗は本処理を妨げない


_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
