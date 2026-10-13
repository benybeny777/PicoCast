"""生成画面の「AIで台本を作る」（POST /api/prompt/run）のテスト。実際の AI は呼ばない。"""
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NVF_DISABLE_JOB_RUNNER", "1")
    import core.metadata_db as m
    db_path = str(tmp_path / "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()
    from web_app.app import app
    with TestClient(app) as c:
        yield c


def _wait(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("success", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError("ジョブが終わりません")


def test_run_script_prompt_with_selected_backend(client, monkeypatch):
    from config import config as cfg
    from core import text_llm
    import web_app.services.prompt_service as ps

    monkeypatch.setattr(cfg, "TEXT_LLM_BACKEND", "claude_cli")
    monkeypatch.setattr(ps, "get_script_generation_prompt", lambda: {"prompt": "台本を作って"})
    calls = {}

    def fake_generate(prompt, *, system="", web_search=False, backend=None):
        calls.update(prompt=prompt, backend=backend, web_search=web_search)
        return "動画タイトル: テスト\nずんだもん(ノーマル): こんにちはなのだ"

    monkeypatch.setattr(text_llm, "generate", fake_generate)
    res = client.post("/api/prompt/run", json={"kind": "script", "theme": "案3『ずんだ餅の歴史』"})
    assert res.status_code == 200
    assert res.json()["backend_label"] == "Claude Code CLI"
    job = _wait(client, res.json()["job_id"])
    assert job["status"] == "success"
    assert job["result"]["text"].startswith("動画タイトル: テスト")
    assert calls == {
        "prompt": "「案3『ずんだ餅の歴史』」で台本を作ってください。\n\n台本を作って",
        "backend": "claude_cli",
        "web_search": cfg.TEXT_LLM_WEB_SEARCH,
    }


def test_run_failure_is_reported_without_stack_trace(client, monkeypatch):
    from core import text_llm
    from core.error_codes import AppError
    import web_app.services.prompt_service as ps

    monkeypatch.setattr(ps, "get_title_prompt", lambda long_only=False: {"prompt": "タイトル案"})

    def failing(*_a, **_k):
        raise AppError("E-LLM-CLI-MISSING", "Claude Code CLI（claude）")

    monkeypatch.setattr(text_llm, "generate", failing)
    job = _wait(client, client.post("/api/prompt/run", json={"kind": "title-long"}).json()["job_id"])
    assert job["status"] == "failed"
    assert "E-LLM-CLI-MISSING" in job["error"]
    assert "Traceback" not in job["error"]


def test_unknown_kind_is_rejected(client):
    assert client.post("/api/prompt/run", json={"kind": "unknown"}).status_code == 400


def test_backends_endpoint_lists_all_choices(client):
    data = client.get("/api/prompt/backends").json()
    assert [b["backend"] for b in data["backends"]] == ["gemini", "claude_cli", "codex_cli", "ollama"]
