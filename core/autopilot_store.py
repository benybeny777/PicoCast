"""チャンネル別自動運用設定と、工程・日次枠・API使用回数のDB正本。"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core import settings_store
from core.channel_profile import require_active_profile
from core.error_codes import AppError
from core.metadata_db import ManagedConnection, initialize_db

_logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_now(now: datetime | None = None) -> datetime:
    from core.channel_schedule import get_schedule
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(get_schedule().timezone_name))


def load_policy() -> dict:
    from config import config as cfg
    policy = {
        "enabled": False, "daily_shorts": cfg.AUTOPILOT_DAILY_SHORTS,
        "daily_longs": cfg.AUTOPILOT_DAILY_LONGS, "start_hour": cfg.AUTOPILOT_START_HOUR,
        "min_score": cfg.AUTOPILOT_MIN_SCORE, "daily_paid_limit": cfg.AUTOPILOT_DAILY_PAID_LIMIT,
        "consent_hash": "",
    }
    key = "AUTOPILOT_POLICY:" + require_active_profile().profile_id
    raw = settings_store.get_all().get(key)
    if raw is not None:
        policy.update(json.loads(raw))
    return policy


def save_policy(values: dict, *, confirmed: bool) -> dict:
    from config import config as cfg
    policy = {k: values[k] for k in ("enabled", "daily_shorts", "daily_longs", "start_hour", "min_score", "daily_paid_limit")}
    if type(policy["enabled"]) is not bool or any(type(policy[k]) is not int for k in policy if k != "enabled"):
        raise AppError("E-AUTO-CONFIG")
    if (not 0 <= policy["daily_shorts"] <= cfg.AUTOPILOT_MAX_DAILY_VIDEOS
            or not 0 <= policy["daily_longs"] <= cfg.AUTOPILOT_MAX_DAILY_VIDEOS
            or policy["daily_shorts"] + policy["daily_longs"] > cfg.AUTOPILOT_MAX_DAILY_VIDEOS
            or not 0 <= policy["start_hour"] <= 23 or not 0 <= policy["min_score"] <= 100
            or policy["daily_paid_limit"] < 0):
        raise AppError("E-AUTO-CONFIG")
    if policy["enabled"]:
        if not confirmed or not policy["daily_paid_limit"] or not (policy["daily_shorts"] + policy["daily_longs"]):
            raise AppError("E-AUTO-CONFIG")
        from core.setup_state import require_setup_completed_for
        from core.secret_store import has_secret
        require_setup_completed_for("自動運用")
        if not has_secret("google_api_key") or not has_secret("youtube_upload_token") or not has_secret("youtube_analytics_token"):
            raise AppError("E-AUTO-CONFIG", "Google AI・YouTube投稿・Analyticsの認証が必要です")
    consent = json.dumps(policy, sort_keys=True)
    policy["consent_hash"] = hashlib.sha256(consent.encode()).hexdigest() if policy["enabled"] else ""
    key = "AUTOPILOT_POLICY:" + require_active_profile().profile_id
    settings_store.set_many({key: json.dumps(policy, ensure_ascii=False)})
    return policy


def initialize() -> None:
    initialize_db()
    with ManagedConnection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS autopilot_runs (
                run_id TEXT PRIMARY KEY, day TEXT NOT NULL, video_type TEXT NOT NULL,
                ordinal INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'ready',
                stage TEXT NOT NULL DEFAULT 'analytics', job_id TEXT,
                policy_json TEXT NOT NULL, topic TEXT, script TEXT, history_name TEXT,
                video_id TEXT, review_json TEXT, error TEXT, updated_at TEXT NOT NULL,
                UNIQUE(day, video_type, ordinal)
            );
            CREATE TABLE IF NOT EXISTS autopilot_usage (
                day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.commit()


def get_run(run_id: str) -> dict:
    with ManagedConnection() as conn:
        row = conn.execute("SELECT * FROM autopilot_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise AppError("E-AUTO-HOLD", "運用記録が見つかりません")
    result = dict(row)
    result["policy"] = json.loads(result.pop("policy_json"))
    return result


def update_run(run_id: str, **updates) -> None:
    allowed = {"state", "stage", "topic", "script", "history_name", "video_id", "review_json", "error"}
    if not updates or not set(updates) <= allowed:
        raise ValueError("自動運用記録の更新フィールドが不正です")
    with ManagedConnection() as conn:
        assignments = ",".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE autopilot_runs SET {assignments},updated_at=? WHERE run_id=?",
                     (*updates.values(), now_iso(), run_id))
        conn.commit()


def assert_authorized(run: dict) -> None:
    policy = load_policy()
    if not policy["enabled"] or not policy["consent_hash"] or policy["consent_hash"] != run["policy"]["consent_hash"]:
        raise AppError("E-AUTO-HOLD", "自動運用が停止されたか、運用設定が変更されています")


def queue_next(now: datetime | None = None) -> str | None:
    """1チャンネル1工程だけを、日次枠とjobsを同じトランザクションで登録する。"""
    policy = load_policy()
    if not policy["enabled"]:
        return None
    initialize()
    clock = local_now(now)
    profile_id = require_active_profile().profile_id
    with ManagedConnection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM jobs WHERE job_type='upload' AND status IN ('queued','running') LIMIT 1").fetchone():
            conn.commit()
            return None
        if conn.execute("SELECT 1 FROM autopilot_runs WHERE state='held' LIMIT 1").fetchone():
            conn.commit()
            return None
        run = conn.execute("SELECT * FROM autopilot_runs WHERE state IN ('ready','working') ORDER BY day,ordinal LIMIT 1").fetchone()
        if run is not None and run["job_id"]:
            job = conn.execute("SELECT status FROM jobs WHERE job_id=?", (run["job_id"],)).fetchone()
            if job and job["status"] in ("queued", "running"):
                conn.commit()
                return None
            if run["state"] == "working":
                conn.execute("UPDATE autopilot_runs SET state='held',error=?,updated_at=? WHERE run_id=?",
                             (AppError("E-AUTO-HOLD", "工程の中断を検出しました。実行結果を確認してください").user_message(), now_iso(), run["run_id"]))
                conn.commit()
                _logger.error("自動運用の中断を検出: profile=%s run=%s", profile_id, run["run_id"])
                return None
        if run is None:
            if clock.hour < policy["start_hour"]:
                conn.commit()
                return None
            for video_type, count in (("shorts", policy["daily_shorts"]), ("long", policy["daily_longs"])):
                for ordinal in range(count):
                    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"autopilot:{profile_id}:{clock.date()}:{video_type}:{ordinal}"))
                    cursor = conn.execute("""INSERT OR IGNORE INTO autopilot_runs
                        (run_id,day,video_type,ordinal,policy_json,updated_at) VALUES(?,?,?,?,?,?)""",
                        (run_id, str(clock.date()), video_type, ordinal, json.dumps(policy), now_iso()))
                    if cursor.rowcount:
                        run = conn.execute("SELECT * FROM autopilot_runs WHERE run_id=?", (run_id,)).fetchone()
                        break
                if run is not None:
                    break
        if run is None:
            conn.commit()
            return None
        job_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO jobs(job_id,job_type,profile_id,status,params_json,created_at)
                        VALUES(?,'autopilot',?,'queued',?,?)""",
                     (job_id, profile_id, json.dumps({"run_id": run["run_id"]}), now_iso()))
        conn.execute("UPDATE autopilot_runs SET job_id=?,updated_at=? WHERE run_id=?", (job_id, now_iso(), run["run_id"]))
        conn.commit()
        return job_id


def status() -> dict:
    initialize()
    day = str(local_now().date())
    with ManagedConnection() as conn:
        runs = [dict(row) for row in conn.execute("""SELECT run_id,day,video_type,ordinal,state,stage,
            topic,history_name,video_id,review_json,error,updated_at FROM autopilot_runs ORDER BY day DESC,ordinal DESC LIMIT 100""")]
        usage = conn.execute("SELECT calls FROM autopilot_usage WHERE day=?", (day,)).fetchone()
    for run in runs:
        raw_review = run.pop("review_json")
        run["review"] = json.loads(raw_review) if raw_review else None
    return {"profile_id": require_active_profile().profile_id, "policy": load_policy(),
            "runs": runs, "paid_calls_today": usage["calls"] if usage else 0, "day": day}


def dismiss(run_id: str) -> None:
    """保留枠を終了扱いにする。成果物を削除・公開・再アップロードしない。"""
    with ManagedConnection() as conn:
        cursor = conn.execute("UPDATE autopilot_runs SET state='skipped',updated_at=? WHERE run_id=? AND state='held'", (now_iso(), run_id))
        if not cursor.rowcount:
            raise AppError("E-AUTO-HOLD", "対象は保留中の運用記録ではありません")
        conn.commit()
