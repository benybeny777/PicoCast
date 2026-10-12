"""裏で動く処理（OSタスクから定期実行される固定コメント自動投稿など）の前回結果を記録する。

裏で動く処理の失敗をデバッグログだけに残すと、利用者は「まだ実行されていない」のか
「毎回失敗している」のかを区別できない。前回の実行結果を settings.db に保存し、
画面（ヘッダーと各機能の画面）に失敗の理由と対処を表示する。次に成功した実行で表示は消える。
複数 profile をまたいで実行するため、profile 別の metadata.db ではなく settings.db に置く。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

from core import settings_store

_lock = threading.Lock()

# 画面へ出す失敗の最大件数（それ以上は件数だけ表示する）
MAX_FAILURE_DETAILS = 20


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(settings_store._DB_PATH, check_same_thread=False, timeout=5)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS background_task_runs (
            task          TEXT PRIMARY KEY,
            finished_at   TEXT NOT NULL,
            succeeded     INTEGER NOT NULL,
            failed        INTEGER NOT NULL,
            failures_json TEXT NOT NULL DEFAULT '[]'
        )
    """)
    return conn


def record_run(task: str, *, succeeded: int, failures: list[dict[str, str]]) -> None:
    """前回結果を上書き保存する。failures は {"target", "message"} の一覧（利用者向けの文言だけを入れる）。"""
    with _lock:
        conn = _open()
        try:
            conn.execute(
                """
                INSERT INTO background_task_runs(task, finished_at, succeeded, failed, failures_json)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(task) DO UPDATE SET
                    finished_at=excluded.finished_at, succeeded=excluded.succeeded,
                    failed=excluded.failed, failures_json=excluded.failures_json
                """,
                (
                    task,
                    datetime.now().isoformat(timespec="seconds"),
                    succeeded,
                    len(failures),
                    json.dumps(failures[:MAX_FAILURE_DETAILS], ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def last_run(task: str) -> dict | None:
    """前回結果。まだ一度も実行されていなければ None。"""
    with _lock:
        conn = _open()
        try:
            row = conn.execute(
                "SELECT finished_at, succeeded, failed, failures_json FROM background_task_runs WHERE task=?",
                (task,),
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    return {
        "task": task,
        "finished_at": row[0],
        "succeeded": row[1],
        "failed": row[2],
        "failures": json.loads(row[3]),
    }
