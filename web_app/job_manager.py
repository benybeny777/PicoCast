"""
ジョブ管理モジュール。
長時間処理をバックグラウンドスレッドで実行し、ステータスを追跡する。
ジョブ情報は JSON ファイルに永続化され、アプリ再起動後も参照できる。
"""
import atexit
import json
import logging
import os
import pathlib
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))
from typing import Any, Callable

# ジョブの全ログ（ワーカーの stdout/stderr 転送分を含む）を app_debug.log にも残すための logger。
# 進捗・エラーがメモリ上の job.logs にしか残らず永続デバッグログが薄かったのを補う。
_job_logger = logging.getLogger("yj.job")
_TAG_TO_LEVEL = {
    "error": logging.ERROR,
    "stderr": logging.ERROR,
    "warning": logging.WARNING,
    "success": logging.INFO,
    "info": logging.INFO,
}


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    def __init__(self, job_id: str, job_type: str):
        self.job_id = job_id
        self.type = job_type
        self.status = JobStatus.QUEUED
        self.progress_text = ""
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.logs: list[dict[str, str]] = []
        self.result: Any = None
        self.error: str | None = None
        self.cancel_event = threading.Event()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "type": self.type,
            "status": self.status,
            "progress_text": self.progress_text,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "logs": self.logs,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        """永続化ファイルから Job を復元する。"""
        job = cls(d["job_id"], d.get("type", "unknown"))
        job.status = d.get("status", JobStatus.FAILED)
        job.progress_text = d.get("progress_text", "")
        job.logs = d.get("logs") or []
        job.result = d.get("result")
        job.error = d.get("error")
        started = d.get("started_at")
        job.started_at = datetime.fromisoformat(started) if started else None
        finished = d.get("finished_at")
        job.finished_at = datetime.fromisoformat(finished) if finished else None
        return job


class JobManager:
    def __init__(self, max_workers: int = 4):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._load_jobs()
        atexit.register(lambda: self._executor.shutdown(wait=False))

    # ──────────────────────────────────────────
    # 永続化
    # ──────────────────────────────────────────

    def _load_jobs(self) -> None:
        """起動時にジョブ履歴を DB から復元する。"""
        try:
            from core.metadata_db import load_jobs_from_db, initialize_db, is_initialized
            if not is_initialized():
                initialize_db()
            from config import JOB_LOG_MAX_JOBS
            data = load_jobs_from_db(max_n=JOB_LOG_MAX_JOBS)
            for d in data:
                job = Job.from_dict(d)
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    job.status = JobStatus.FAILED
                    job.error = "アプリ再起動により中断"
                    job.progress_text = "⚠ アプリ再起動により中断されました"
                    if not job.finished_at:
                        job.finished_at = datetime.now(_JST)
                    _log(job, "⚠ アプリ再起動により中断されました", "warning")
                self._jobs[job.job_id] = job
        except Exception as e:
            # フォールバック許可: DB読み込み失敗はアプリ起動を妨げない
            print(f"[job_manager] ジョブ履歴の読み込みに失敗しました（無視して続行）: {e}")

    def _save_jobs(self, notify_job: "Job | None" = None) -> None:
        """ジョブ確定時に DB へ保存する。"""
        try:
            from core.metadata_db import upsert_job, delete_old_jobs, initialize_db, is_initialized
            if not is_initialized():
                initialize_db()
            from config import JOB_LOG_MAX_JOBS
            if notify_job is not None:
                upsert_job(notify_job.to_dict())
            else:
                with self._lock:
                    for job in self._jobs.values():
                        upsert_job(job.to_dict())
            delete_old_jobs(JOB_LOG_MAX_JOBS)
        except Exception as e:
            msg = f"[ジョブログ] DB書き込みに失敗しました: {e}"
            print(msg, flush=True)
            if notify_job is not None:
                try:
                    _log(notify_job, msg, "warning")
                except Exception:
                    pass  # フォールバック許可: ログ追記自体の失敗は無視する

    # ──────────────────────────────────────────
    # CRUD
    # ──────────────────────────────────────────

    def create_job(self, job_type: str) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id, job_type)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in sorted(
                self._jobs.values(),
                key=lambda j: j.started_at or datetime.min.replace(tzinfo=_JST),
                reverse=True,
            )]

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        job.cancel_event.set()
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            job.status = JobStatus.CANCELLED
            job.progress_text = "キャンセル要求済み"
            job.finished_at = datetime.now(_JST)
            self._save_jobs(notify_job=job)
        return True

    def submit(self, job: Job, fn: Callable, *args, **kwargs) -> None:
        """ジョブをバックグラウンドスレッドで実行する。"""
        manager_ref = self  # _save_jobs 呼び出し用に参照保持

        def _run():
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(_JST)
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
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.progress_text = f"エラー: {e}"
                _log(job, f"エラー: {e}", "error")
                # トレースバック全文もログに記録する（1エントリに収める）
                tb = traceback.format_exc()
                if tb and tb.strip() != "NoneType: None":
                    _log(job, tb, "error")
                # except ブロック内でも明示的に保存する（finally と二重になるが失敗時の確実性優先）
                manager_ref._save_jobs(notify_job=job)
            finally:
                job.finished_at = datetime.now(_JST)
                _dur = (job.finished_at - job.started_at).total_seconds() if job.started_at else 0.0
                _job_logger.info(
                    "[%s job=%s] ■ 終了 status=%s 所要=%.1fs", job.type, job.job_id[:8], job.status, _dur,
                )
                manager_ref._save_jobs(notify_job=job)  # 成功・失敗・キャンセルすべてで保存

        self._executor.submit(_run)


def _log(job: Job, message: str, tag: str = "info") -> None:
    """ジョブのログに追記する。呼び出し側からも使える。

    同じ内容を app_debug.log（Python logging）へもジョブ文脈付きでミラーする。
    ワーカー subprocess の stdout/stderr も run_in_worker 経由でこの関数を通るため、
    生成・レンダーの進捗とエラーが永続デバッグログにも残る。
    """
    tag = tag or "info"
    job.logs.append({
        "time": datetime.now(_JST).isoformat(),
        "tag": tag,
        "message": message,
    })
    job.progress_text = message
    try:
        _job_logger.log(
            _TAG_TO_LEVEL.get(tag, logging.INFO),
            "[%s job=%s] %s", job.type, job.job_id[:8], message,
        )
    except Exception:
        pass  # フォールバック許可: デバッグログへのミラー失敗は本処理を妨げない


# アプリケーション全体で共有するシングルトン
_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
