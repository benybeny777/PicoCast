"""自動運用の永続化、投稿停止、日次上限を実APIなしで検証する。"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import config as cfg
from core import autopilot_budget as budgets
from core import autopilot_store as store
from core import channel_profile as profiles
from core import metadata_db as metadata
from core import settings_store
from core.error_codes import AppError
from web_app.services import autopilot_service as service


NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(profiles, "get_profile", lambda name: SimpleNamespace(profile_id=name))
    monkeypatch.setattr(profiles, "get_active_profile", lambda: profiles.get_profile(
        getattr(profiles._profile_context, "profile_id", "alpha")))
    monkeypatch.setattr(metadata, "get_db_path", lambda: str(
        tmp_path / profiles.require_active_profile().profile_id / "metadata.db"))
    monkeypatch.setattr(store, "local_now", lambda now=None: now or NOW)
    monkeypatch.setattr(budgets, "local_now", lambda now=None: now or NOW)
    monkeypatch.setattr(cfg, "AUTOPILOT_MAX_DAILY_VIDEOS", 10)
    from core import setup_state, secret_store
    monkeypatch.setattr(setup_state, "require_setup_completed_for", lambda action: None)
    monkeypatch.setattr(secret_store, "has_secret", lambda name: True)
    from core import license_manager
    monkeypatch.setattr(license_manager, "assert_can_use_autopilot", lambda: None)
    store.initialize()
    return tmp_path


def policy(**changes):
    return {"enabled": True, "daily_shorts": 1, "daily_longs": 0,
            "start_hour": 6, "min_score": 80, "daily_paid_limit": 4, **changes}


def enable(**changes):
    return store.save_policy(policy(**changes), confirmed=True)


def queued_run():
    job_id = store.queue_next(NOW)
    with metadata.ManagedConnection() as conn:
        row = conn.execute("SELECT run_id FROM autopilot_runs WHERE job_id=?", (job_id,)).fetchone()
    return job_id, store.get_run(row["run_id"])


def finish_job(job_id):
    with metadata.ManagedConnection() as conn:
        conn.execute("UPDATE jobs SET status='success' WHERE job_id=?", (job_id,))
        conn.commit()


def test_default_policy_is_off_without_spending(isolated):
    current = store.load_policy()
    assert current["enabled"] is False
    assert current["daily_shorts"] == 1
    assert current["daily_longs"] == 0
    assert current["daily_paid_limit"] == 0
    assert store.queue_next(NOW) is None


@pytest.mark.parametrize("changes,confirmed", [
    ({}, False), ({"daily_paid_limit": 0}, True),
    ({"daily_shorts": 0}, True), ({"daily_shorts": True}, True),
    ({"daily_shorts": -1}, True), ({"daily_shorts": 7, "daily_longs": 4}, True),
    ({"start_hour": 24}, True), ({"min_score": 101}, True),
])
def test_enabled_policy_requires_valid_budget_counts_and_consent(isolated, changes, confirmed):
    with pytest.raises(AppError):
        store.save_policy(policy(**changes), confirmed=confirmed)
    assert store.load_policy()["enabled"] is False


def test_enabled_policy_requires_all_credentials(isolated, monkeypatch):
    from core import secret_store
    monkeypatch.setattr(secret_store, "has_secret", lambda name: name != "youtube_analytics_token")
    with pytest.raises(AppError):
        enable()


def test_disabled_policy_can_be_saved_without_consent(isolated):
    saved = store.save_policy(policy(enabled=False, daily_paid_limit=0), confirmed=False)
    assert saved["consent_hash"] == ""
    assert store.load_policy() == saved


def test_daily_counts_and_duplicate_queue_are_persistent(isolated):
    enable(daily_shorts=2, daily_longs=1)
    seen = []
    for _ in range(3):
        job_id, run = queued_run()
        seen.append((run["video_type"], run["ordinal"]))
        assert store.queue_next(NOW) is None
        store.update_run(run["run_id"], state="complete", stage="complete")
        finish_job(job_id)
    assert seen == [("shorts", 0), ("shorts", 1), ("long", 0)]
    assert store.queue_next(NOW) is None
    store.initialize()
    assert store.queue_next(NOW) is None
    assert store.queue_next(NOW.replace(day=14)) is not None


def test_no_daily_run_before_start_hour(isolated):
    enable(start_hour=6)
    assert store.queue_next(NOW.replace(hour=5)) is None
    assert store.queue_next(NOW.replace(hour=6)) is not None


def test_profiles_have_independent_policy_runs_and_budget(isolated):
    enable(daily_shorts=2)
    _, alpha = queued_run()
    with profiles.profile_context("beta"):
        store.initialize()
        assert store.load_policy()["enabled"] is False
        enable(daily_shorts=0, daily_longs=1)
        _, beta = queued_run()
        assert beta["video_type"] == "long"
        with pytest.raises(AppError):
            store.get_run(alpha["run_id"])
        budgets.Budget("beta", beta).reserve()
    assert store.load_policy()["daily_shorts"] == 2
    assert store.status()["paid_calls_today"] == 0
    assert alpha["run_id"] != beta["run_id"]


def test_queue_claim_is_atomic_across_threads(isolated):
    enable()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: store.queue_next(NOW), range(8)))
    assert sum(value is not None for value in results) == 1
    with metadata.ManagedConnection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE job_type='autopilot'").fetchone()[0] == 1


def test_next_stage_is_persisted_before_queueing(isolated, monkeypatch):
    enable()
    job_id, run = queued_run()
    store.update_run(run["run_id"], stage="topic")
    monkeypatch.setattr(service, "_choose_topic", lambda run: {"topic": "新しいテーマ"})
    result = service.execute_step({"job_id": job_id, "params": {"run_id": run["run_id"]}}, threading.Event(), Mock())
    saved = store.get_run(run["run_id"])
    assert result["next_stage"] == "script"
    assert (saved["state"], saved["stage"], saved["topic"]) == ("ready", "script", "新しいテーマ")
    assert store.queue_next(NOW) is None
    finish_job(job_id)
    next_job = store.queue_next(NOW)
    assert next_job != job_id
    assert store.get_run(run["run_id"])["job_id"] == next_job


def test_interrupted_working_upload_is_held_not_reposted(isolated):
    enable()
    job_id, run = queued_run()
    store.update_run(run["run_id"], state="working", stage="upload", video_id="already-created")
    finish_job(job_id)
    assert store.queue_next(NOW) is None
    saved = store.get_run(run["run_id"])
    assert saved["state"] == "held"
    assert saved["video_id"] == "already-created"
    assert store.queue_next(NOW.replace(day=14)) is None


def test_policy_change_invalidates_existing_consent(isolated):
    enable()
    _, run = queued_run()
    enable(daily_shorts=2)
    with pytest.raises(AppError):
        store.assert_authorized(run)


def test_paid_budget_is_atomic_and_denials_do_not_increment(isolated):
    enable(daily_paid_limit=3)
    _, run = queued_run()
    budget = budgets.Budget("alpha", run)

    def attempt(_):
        try:
            budget.reserve()
            return True
        except AppError:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(12))) == 3
    assert budget.denied.is_set()
    assert store.status()["paid_calls_today"] == 3


def test_guarded_image_client_keeps_budget_in_child_threads(isolated):
    enable(daily_paid_limit=2)
    _, run = queued_run()
    client = SimpleNamespace(models=SimpleNamespace(generate_content=Mock(return_value="image")), close=Mock())
    with budgets.budget_scope("alpha", run) as budget:
        guarded = budgets.guard_paid_client(client)

    def image_in_other_profile():
        with profiles.profile_context("beta"):
            return guarded.models.generate_content(contents="one")

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(image_in_other_profile).result() == "image"
        assert executor.submit(guarded.models.generate_content, contents="two").result() == "image"
        with pytest.raises(AppError):
            executor.submit(guarded.models.generate_content, contents="three").result()
    assert client.models.generate_content.call_count == 2
    assert budget.denied.is_set()
    assert store.status()["paid_calls_today"] == 2
    guarded.close()
    client.close.assert_called_once()


@pytest.mark.parametrize("review", [
    {"score": 90, "publish_ok": False, "must_fix": []},
    {"score": 79, "publish_ok": True, "must_fix": []},
    {"score": 90, "publish_ok": True, "must_fix": ["根拠不足"]},
])
def test_failed_quality_review_is_saved_and_held(isolated, monkeypatch, review):
    from core import opening_quality
    from web_app import security
    from web_app.services import upload_service
    enable()
    job_id, run = queued_run()
    store.update_run(run["run_id"], stage="review", history_name="video")
    mp4 = isolated / "video.mp4"
    mp4.write_bytes(b"mock-media")
    monkeypatch.setattr(metadata, "get_render_info", lambda name: {"video_title": "テーマ"})
    monkeypatch.setattr(metadata, "get_script_content", lambda name: "ずんだもん: 説明")
    monkeypatch.setattr(security, "find_history_dir", lambda name: str(isolated))
    monkeypatch.setattr(upload_service, "_find_mp4", lambda path: str(mp4))
    monkeypatch.setattr(service.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps({
        "streams": [{"codec_type": "video"}, {"codec_type": "audio"}], "format": {"duration": "50"}})))
    monkeypatch.setattr(opening_quality, "duration_review", lambda *a, **k: {"status": "ok"})
    monkeypatch.setattr(opening_quality, "local_opening_review", lambda *a, **k: {})
    monkeypatch.setattr(opening_quality, "_post_ollama", lambda *a, **k: json.dumps(review))
    with pytest.raises(AppError):
        service.execute_step({"job_id": job_id, "params": {"run_id": run["run_id"]}}, threading.Event(), Mock())
    saved = store.get_run(run["run_id"])
    assert saved["state"] == "held"
    assert saved["stage"] == "review"
    assert json.loads(saved["review_json"]) == review


@pytest.mark.parametrize("id_source", ["run", "youtube_status"])
def test_upload_refuses_existing_video_id(isolated, monkeypatch, id_source):
    from core import channel_info, license_manager, youtube_uploader
    enable()
    _, run = queued_run()
    store.update_run(run["run_id"], history_name="known")
    if id_source == "run":
        store.update_run(run["run_id"], video_id="existing")
    else:
        with metadata.ManagedConnection() as conn:
            conn.execute("INSERT INTO videos(local_id,output_dir) VALUES('known',?)", (str(isolated),))
            metadata.upsert_youtube_status(conn, "known", {"video_id": "existing"})
            conn.commit()
    upload = Mock(side_effect=AssertionError("既存動画を再投稿してはいけない"))
    monkeypatch.setattr(youtube_uploader, "upload_video", upload)
    monkeypatch.setattr(channel_info, "get_channel_info", lambda: {"upload_allowed": True})
    monkeypatch.setattr(license_manager, "assert_can_upload", lambda: None)
    with pytest.raises(AppError):
        service._upload(store.get_run(run["run_id"]), Mock())
    upload.assert_not_called()


@pytest.fixture
def upload_ready(isolated, monkeypatch):
    from core import channel_info, license_manager, upload_scheduler, youtube_uploader
    from web_app import security
    from web_app.services import upload_service
    enable()
    job_id, run = queued_run()
    store.update_run(run["run_id"], stage="upload", history_name="fresh")
    with metadata.ManagedConnection() as conn:
        conn.execute("INSERT INTO videos(local_id,output_dir) VALUES('fresh',?)", (str(isolated),))
        conn.commit()
    monkeypatch.setattr(channel_info, "get_channel_info", lambda: {"upload_allowed": True})
    monkeypatch.setattr(license_manager, "assert_can_upload", lambda: None)
    monkeypatch.setattr(license_manager, "verify_activation_now", lambda: SimpleNamespace(edition="pro", autopilot=True))
    monkeypatch.setattr(metadata, "get_render_info", lambda name: {"video_title": "新テーマ"})
    monkeypatch.setattr(security, "find_history_dir", lambda name: str(isolated))
    monkeypatch.setattr(upload_service, "_find_mp4", lambda path: str(isolated / "video.mp4"))
    monkeypatch.setattr(upload_scheduler, "assign_slots_from_youtube", lambda *args: [NOW])
    return job_id, run


@pytest.mark.parametrize("outcome", ["thumbnail_failure", "wrong_schedule", "verified"])
def test_upload_saves_id_before_postprocessing_and_checks_schedule(upload_ready, monkeypatch, outcome):
    from core import youtube_uploader
    job_id, run = upload_ready

    def uploaded(*args, **kwargs):
        kwargs["on_uploaded"]("created-video")
        saved = store.get_run(run["run_id"])
        assert saved["video_id"] == "created-video"
        with metadata.ManagedConnection() as conn:
            assert conn.execute("SELECT youtube_video_id FROM youtube_status WHERE local_id='fresh'").fetchone()[0] == "created-video"
        if outcome == "thumbnail_failure":
            raise RuntimeError("サムネイル設定失敗")
        return "created-video"

    upload = Mock(side_effect=uploaded)
    monkeypatch.setattr(youtube_uploader, "upload_video", upload)
    monkeypatch.setattr(youtube_uploader, "get_video_statuses", lambda ids: {"created-video": {
        "privacyStatus": "private", "publishAt": NOW.replace(hour=13).isoformat() if outcome == "wrong_schedule" else NOW.isoformat()}})
    job = {"job_id": job_id, "params": {"run_id": run["run_id"]}}
    if outcome == "verified":
        service.execute_step(job, threading.Event(), Mock())
        saved = store.get_run(run["run_id"])
        assert (saved["state"], saved["stage"]) == ("ready", "analysis")
        with metadata.ManagedConnection() as conn:
            row = conn.execute("SELECT publish_status,publish_at FROM youtube_status WHERE local_id='fresh'").fetchone()
        assert (row["publish_status"], row["publish_at"]) == ("scheduled", NOW.isoformat())
    else:
        with pytest.raises(AppError):
            service.execute_step(job, threading.Event(), Mock())
        saved = store.get_run(run["run_id"])
        assert (saved["state"], saved["video_id"]) == ("held", "created-video")
        finish_job(job_id)
        assert store.queue_next(NOW) is None
    upload.assert_called_once()


def test_upload_is_held_when_license_becomes_trial_before_posting(upload_ready, monkeypatch):
    from core import license_manager, youtube_uploader
    job_id, run = upload_ready
    verify = Mock(return_value=SimpleNamespace(edition="trial", autopilot=False))
    upload = Mock(side_effect=AssertionError("投稿直前に体験版へ戻った場合は投稿してはいけない"))
    monkeypatch.setattr(license_manager, "verify_activation_now", verify)
    monkeypatch.setattr(youtube_uploader, "upload_video", upload)
    with pytest.raises(AppError):
        service.execute_step({"job_id": job_id, "params": {"run_id": run["run_id"]}}, threading.Event(), Mock())
    verify.assert_called_once()
    upload.assert_not_called()
    saved = store.get_run(run["run_id"])
    assert (saved["state"], saved["stage"]) == ("held", "upload")
    assert not saved["video_id"]
    assert "E-LICENSE-LIMIT" in saved["error"]
    with metadata.ManagedConnection() as conn:
        assert conn.execute("SELECT youtube_video_id FROM youtube_status WHERE local_id='fresh'").fetchone() is None
