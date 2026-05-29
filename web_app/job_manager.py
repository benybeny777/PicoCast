"""
ジョブ管理モジュール。
長時間処理をバックグラウンドスレッドで実行し、ステータスを追跡する。
ジョブ情報は JSON ファイルに永続化され、アプリ再起動後も参照できる。
"""
import atexit
import json
import os
import pathlib
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))
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
    _PERSIST_FILE = "jobs.json"

    def __init__(self, max_workers: int = 4, persist_dir: str | None = None):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._persist_path: pathlib.Path | None = None

        if persist_dir:
            p = pathlib.Path(persist_dir)
            p.mkdir(parents=True, exist_ok=True)
            self._persist_path = p / self._PERSIST_FILE
            self._load_jobs()

        atexit.register(lambda: self._executor.shutdown(wait=False))

    # ──────────────────────────────────────────
    # 永続化
    # ──────────────────────────────────────────

    def _load_jobs(self) -> None:
        """起動時にジョブ履歴をファイルから復元する。"""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            raw = self._persist_path.read_text(encoding="utf-8")
            data: list[dict] = json.loads(raw)
            for d in data:
                job = Job.from_dict(d)
                # 実行中・キュー中だったジョブは再起動で中断済みとしてマーク
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                    job.status = JobStatus.FAILED
                    job.error = "アプリ再起動により中断"
                    job.progress_text = "⚠ アプリ再起動により中断されました"
                    if not job.finished_at:
                        job.finished_at = datetime.now(_JST)
                    _log(job, "⚠ アプリ再起動により中断されました", "warning")
                self._jobs[job.job_id] = job
        except Exception as e:
            # フォールバック許可: 永続化ファイルの読み込み失敗はアプリ起動を妨げない
            print(f"[job_manager] ジョブ履歴の読み込みに失敗しました（無視して続行）: {e}")

    def _save_jobs(self, notify_job: "Job | None" = None) -> None:
        """ジョブ一覧をファイルへ書き出す。成功・失敗・キャンセルを問わずジョブ確定時に呼ぶ。"""
        if not self._persist_path:
            return
        try:
            from config import JOB_LOG_MAX_JOBS  # 循環インポート回避のため遅延ロード
            with self._lock:
                jobs_sorted = sorted(
                    self._jobs.values(),
                    key=lambda j: j.started_at or datetime.min.replace(tzinfo=_JST),
                    reverse=True,
                )[:JOB_LOG_MAX_JOBS]
                data = [j.to_dict() for j in jobs_sorted]
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            msg = f"[ジョブログ] 永続化ファイルの書き込みに失敗しました: {e}"
            print(msg, flush=True)
            if notify_job is not None:
                # 保存失敗をジョブ自身のログに記録する
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
                manager_ref._save_jobs(notify_job=job)  # 成功・失敗・キャンセルすべてで保存

        self._executor.submit(_run)


def _log(job: Job, message: str, tag: str = "info") -> None:
    """ジョブのログに追記する。呼び出し側からも使える。"""
    job.logs.append({
        "time": datetime.now(_JST).isoformat(),
        "tag": tag,
        "message": message,
    })
    job.progress_text = message


# アプリケーション全体で共有するシングルトン
_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        from config import JOB_LOG_DIR  # 循環インポート回避のため遅延ロード
        _manager = JobManager(persist_dir=JOB_LOG_DIR)
    return _manager
