"""自動運用だけに適用する有料API呼び出しの原子的な日次上限。"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import threading

from core.channel_profile import profile_context
from core.error_codes import AppError
from core.metadata_db import ManagedConnection
from core.autopilot_store import assert_authorized, local_now

_current = ContextVar("autopilot_budget", default=None)


class Budget:
    def __init__(self, profile_id: str, run: dict):
        self.profile_id = profile_id
        self.run = run
        self.denied = threading.Event()

    def reserve(self) -> None:
        with profile_context(self.profile_id):
            assert_authorized(self.run)
            day = str(local_now().date())
            with ManagedConnection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT OR IGNORE INTO autopilot_usage(day,calls) VALUES(?,0)", (day,))
                cursor = conn.execute("UPDATE autopilot_usage SET calls=calls+1 WHERE day=? AND calls<?",
                                      (day, self.run["policy"]["daily_paid_limit"]))
                if not cursor.rowcount:
                    self.denied.set()
                    raise AppError("E-AUTO-BUDGET")
                conn.commit()


@contextmanager
def budget_scope(profile_id: str, run: dict):
    budget = Budget(profile_id, run)
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def reserve_paid_call() -> None:
    budget = _current.get()
    if budget is not None:
        budget.reserve()


class _Models:
    def __init__(self, models, budget):
        self._models = models
        self._budget = budget

    def generate_content(self, *args, **kwargs):
        self._budget.reserve()
        return self._models.generate_content(*args, **kwargs)


class _Client:
    def __init__(self, client, budget):
        self._client = client
        self.models = _Models(client.models, budget)

    def close(self):
        self._client.close()


def guard_paid_client(client):
    """画像生成の子スレッドでも、作成時の運用枠・チャンネルを保持する。"""
    budget = _current.get()
    return _Client(client, budget) if budget is not None else client
