"""
ジョブ管理モジュール。
長時間処理をバックグラウンドスレッドで実行し、ステータスを追跡する。
初期実装はメモリ内管理。将来DB/JSON保存へ移行しやすい構造にする。
"""
import threading
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


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


class JobManager:
    def __init__(self, max_workers: int = 4):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

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
                key=lambda j: j.started_at or datetime.min.replace(tzinfo=timezone.utc),
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
            job.finished_at = datetime.now(timezone.utc)
        return True

    def submit(self, job: Job, fn: Callable, *args, **kwargs) -> None:
        """ジョブをバックグラウンドスレッドで実行する。"""
        def _run():
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
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
            finally:
                job.finished_at = datetime.now(timezone.utc)

        self._executor.submit(_run)


def _log(job: Job, message: str, tag: str = "info") -> None:
    """ジョブのログに追記する。呼び出し側からも使える。"""
    job.logs.append({
        "time": datetime.now(timezone.utc).isoformat(),
        "tag": tag,
        "message": message,
    })
    job.progress_text = message


# アプリケーション全体で共有するシングルトン
_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
