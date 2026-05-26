"""
Web UI の最低限テスト。
外部API (VOICEVOX / YouTube / OpenAI) への実通信なしで動くことを確認する。
"""
import sys
import os
import pytest

# プロジェクトルートをパスに追加
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── FastAPI テストクライアント ───────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from web_app.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# 1. /health が成功する
def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# 2. /api/health も成功する
def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200


# 3. ダッシュボード (/) が 200 を返す
def test_dashboard_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "ダッシュボード" in res.text or "Web UI" in res.text


# 4. /generate ページが 200 を返す
def test_generate_page(client):
    res = client.get("/generate")
    assert res.status_code == 200
    assert "LongサムネAB" in res.text
    assert "Long節約" in res.text
    assert "SD生成" in res.text


# 5. /history ページが 200 を返す
def test_history_page(client):
    res = client.get("/history")
    assert res.status_code == 200


# 6. /settings ページが 200 を返す
def test_settings_page(client):
    res = client.get("/settings")
    assert res.status_code == 200


def test_dashboard_scheduled_count_only_future_scheduled(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import core.upload_records as upload_records
    from web_app.services.status_service import _count_scheduled

    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    monkeypatch.setattr(upload_records, "load_upload_records", lambda: [
        {"publish_status": "scheduled", "publish_at": future},
        {"publish_status": "scheduled", "publish_at": past},
        {"publish_status": "private", "publish_at": future},
        {"publish_status": "unlisted", "publish_at": future},
        {"publish_status": "", "publish_at": future},
        {"publish_status": "published", "publish_at": past},
    ])

    assert _count_scheduled() == 1


# 7. /logs ページが 200 を返す
def test_logs_page(client):
    res = client.get("/logs")
    assert res.status_code == 200


# ── job_manager の状態遷移 ───────────────────────────────────────────────────
def test_job_manager_state_transitions():
    from web_app.job_manager import get_job_manager, JobStatus

    mgr = get_job_manager()
    job = mgr.create_job("test")
    assert job.status == JobStatus.QUEUED

    # cancel_job
    ok = mgr.cancel_job(job.job_id)
    assert ok
    assert job.status == JobStatus.CANCELLED


def test_job_manager_get_missing():
    from web_app.job_manager import get_job_manager
    mgr = get_job_manager()
    result = mgr.get_job("nonexistent-id")
    assert result is None


def test_job_manager_cancel_missing():
    from web_app.job_manager import get_job_manager
    mgr = get_job_manager()
    ok = mgr.cancel_job("nonexistent-id")
    assert not ok


# ── パストラバーサル対策 ────────────────────────────────────────────────────
def test_path_traversal_rejected():
    from web_app.security import is_safe_output_path
    assert not is_safe_output_path("../../etc/passwd")
    assert not is_safe_output_path("../../../Windows/System32/cmd.exe")
    assert not is_safe_output_path("/etc/passwd")


def test_secret_files_rejected():
    from web_app.security import is_safe_output_path
    from core.output_paths import OUTPUT_DIR
    # output/ 配下であっても秘密ファイル名は拒否
    assert not is_safe_output_path(os.path.join(OUTPUT_DIR, ".env"))
    assert not is_safe_output_path(os.path.join(OUTPUT_DIR, "token.json"))
    assert not is_safe_output_path(os.path.join(OUTPUT_DIR, "client_secrets.json"))


def test_safe_path_accepted():
    from web_app.security import is_safe_output_path
    from core.output_paths import OUTPUT_DIR
    # output/ 自体はOK
    assert is_safe_output_path(OUTPUT_DIR)


# ── 履歴一覧が管理フォルダを適切に扱う ────────────────────────────────────
def test_history_excludes_management_dirs(tmp_path, monkeypatch):
    """[Shorts]/[Long] プレフィックスがないフォルダは管理フォルダとして除外される。"""
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    (fake_output / "000_analytics").mkdir(parents=True)
    (fake_output / "000_data").mkdir(parents=True)
    (fake_output / "random_folder").mkdir(parents=True)
    (fake_output / "[Shorts]テスト動画").mkdir(parents=True)
    (fake_output / "[Long]テスト動画").mkdir(parents=True)

    monkeypatch.setattr(hs, "OUTPUT_DIR", str(fake_output))

    result = hs.list_histories(include_management=False)
    names = [r["name"] for r in result]
    assert "000_analytics" not in names
    assert "000_data" not in names
    assert "random_folder" not in names
    assert "[Shorts]テスト動画" in names
    assert "[Long]テスト動画" in names


def test_history_includes_management_when_requested(tmp_path, monkeypatch):
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    (fake_output / "000_analytics").mkdir(parents=True)
    (fake_output / "[Shorts]テスト動画").mkdir(parents=True)

    monkeypatch.setattr(hs, "OUTPUT_DIR", str(fake_output))

    result = hs.list_histories(include_management=True)
    names = [r["name"] for r in result]
    assert "000_analytics" in names
    assert "[Shorts]テスト動画" in names


# ── 設定診断APIが秘密値を返さない ─────────────────────────────────────────
def test_settings_api_no_secrets(client):
    res = client.get("/api/settings/status")
    assert res.status_code == 200
    data = res.json()

    # APIキーの値そのものが含まれていないことを確認
    # (bool または None が返るべきで、文字列のキー値が含まれてはならない)
    assert isinstance(data.get("google_api_key"), bool)
    assert isinstance(data.get("openai_api_key"), bool)

    # レスポンスのテキストにキーの値がないことを大まかにチェック
    raw = res.text
    assert "sk-" not in raw  # OpenAI APIキーパターン
    assert "AIza" not in raw  # Google APIキーパターン


def test_config_rejects_newline_injection():
    from web_app.services.config_service import save_config
    errors = save_config({"FFMPEG_BIN": "ffmpeg\nOPENAI_API_KEY=leak"})
    assert errors
    assert "改行" in errors[0]


def test_secrets_reject_newline_injection():
    from web_app.services.secrets_service import save_secrets
    errors = save_secrets({"OPENAI_API_KEY": "sk-test\nGOOGLE_API_KEY=leak"})
    assert errors
    assert "改行" in errors[0]


# ── /api/jobs API ──────────────────────────────────────────────────────────
def test_api_jobs_list(client):
    res = client.get("/api/jobs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_jobs_cancel_missing(client):
    res = client.post("/api/jobs/nonexistent-id/cancel")
    assert res.status_code == 404


# ── /api/history API ───────────────────────────────────────────────────────
def test_api_history_list(client):
    res = client.get("/api/history")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_history_missing(client):
    res = client.get("/api/history/nonexistent-theme-xyz123")
    assert res.status_code == 404


def test_api_history_regenerate_requires_confirmation(client):
    res = client.post("/api/history/regenerate", json={"history_names": ["x"], "confirmed": False})
    assert res.status_code == 400


# ── 外部APIなしでもWebアプリが起動できる ──────────────────────────────────
def test_app_starts_without_external_apis(client):
    """VOICEVOX/YouTube未接続でも /health と / が返ることを確認。"""
    h = client.get("/health")
    assert h.status_code == 200
    d = client.get("/")
    assert d.status_code == 200


# ── /api/generate: 空台本はエラー ─────────────────────────────────────────
def test_generate_empty_script_rejected(client):
    res = client.post("/api/generate", json={"script": ""})
    assert res.status_code == 422  # Pydantic validation error


# ── /api/upload: confirmed=false はエラー ─────────────────────────────────
def test_upload_requires_confirmation(client):
    res = client.post("/api/upload", json={"history_name": "test", "confirmed": False})
    assert res.status_code == 400
