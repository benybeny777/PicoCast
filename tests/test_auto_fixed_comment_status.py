"""固定コメント自動投稿の失敗を画面へ出すためのテスト。"""
import pytest

from core import background_task_status
from core.error_codes import AppError
import web_app.services.auto_fixed_comment_service as auto
import web_app.services.fixed_comment_service as fixed


@pytest.fixture
def status_db(tmp_path, monkeypatch):
    import core.settings_store as ss
    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(auto, "_target_profile_ids", lambda: ["ch_a"])


def _candidates(names):
    return lambda only_unposted, profile_id: [{"name": n} for n in names]


def test_failures_are_recorded_with_user_message(status_db, monkeypatch):
    def post(history_name, **_kwargs):
        if history_name == "ok":
            return {"comment_thread_id": "t1"}
        if history_name == "no_video":
            raise ValueError("video_id がありません（先にアップロードしてください）")
        raise RuntimeError("HttpError 401 https://youtube.googleapis.com/... secret-ish detail")

    monkeypatch.setattr(fixed, "list_fixed_comment_candidates", _candidates(["ok", "no_video", "boom"]))
    monkeypatch.setattr(fixed, "post_fixed_comment_now", post)

    summary = auto.post_all_pending()

    assert summary["posted"] == 1 and summary["failed"] == 2
    run = background_task_status.last_run(auto.TASK_NAME)
    assert run["succeeded"] == 1 and run["failed"] == 2
    messages = {f["target"]: f["message"] for f in run["failures"]}
    assert "video_id がありません" in messages["ch_a / no_video"]
    # 想定外の例外は種類だけを出し、外部APIの生の応答やURLを画面へ出さない
    assert "RuntimeError" in messages["ch_a / boom"]
    assert "googleapis" not in messages["ch_a / boom"]
    assert "対処:" in messages["ch_a / boom"]


def test_successful_run_clears_previous_failures(status_db, monkeypatch):
    monkeypatch.setattr(fixed, "list_fixed_comment_candidates", _candidates(["x"]))
    monkeypatch.setattr(fixed, "post_fixed_comment_now", lambda *_a, **_k: (_ for _ in ()).throw(AppError("E-FIXED-COMMENT-AUTO", "x")))
    auto.post_all_pending()
    assert background_task_status.last_run(auto.TASK_NAME)["failed"] == 1

    monkeypatch.setattr(fixed, "post_fixed_comment_now", lambda *_a, **_k: {"comment_thread_id": "t"})
    auto.post_all_pending()
    run = background_task_status.last_run(auto.TASK_NAME)
    assert run["failed"] == 0 and run["failures"] == []


def test_whole_run_failure_is_recorded_and_raised(status_db, monkeypatch):
    def broken(only_unposted, profile_id):
        raise ValueError("一覧取得に失敗")

    monkeypatch.setattr(fixed, "list_fixed_comment_candidates", broken)
    with pytest.raises(ValueError):
        auto.post_all_pending()
    run = background_task_status.last_run(auto.TASK_NAME)
    assert run["failed"] == 1
    assert run["failures"][0]["target"] == "一括投稿の実行"


def test_auto_status_api_and_page_show_failures(status_db, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("NVF_DISABLE_JOB_RUNNER", "1")
    from web_app.app import app

    background_task_status.record_run(
        auto.TASK_NAME, succeeded=0, failures=[{"target": "ch_a / 動画1", "message": "[E-FIXED-COMMENT-AUTO] 失敗の理由"}],
    )
    monkeypatch.setattr(fixed, "list_fixed_comment_candidates", lambda only_unposted=False, profile_id=None: [])
    with TestClient(app) as client:
        api = client.get("/api/fixed-comment/auto-status").json()
        page = client.get("/fixed-comment").text
    assert api["last_run"]["failed"] == 1
    assert "ch_a / 動画1" in page and "失敗の理由" in page
