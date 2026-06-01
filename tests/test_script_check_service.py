import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _sample_script():
    return "\n".join([
        "動画形式: Shorts",
        "動画タイトル: テスト動画",
        "サムネ文字: テスト",
        "ずんだもん: テストなのだ",
        "四国めたん: テストですわ",
    ])


def test_check_service_duration_only_when_llm_disabled(monkeypatch):
    import config.config as cfg
    import core.opening_quality as oq
    import workers.main as wm
    from web_app.job_manager import Job
    from web_app.services.script_check_service import _run_check

    monkeypatch.setattr(cfg, "OPENING_REVIEW_USE_LLM", False)
    monkeypatch.setattr(cfg, "OPENAI_FINAL_REVIEW_ENABLED", False)
    monkeypatch.setattr(wm, "_estimate_script_duration", lambda _items, _is_shorts: (42.0, 2, 6.0))
    monkeypatch.setattr(oq, "local_opening_review", lambda *args, **kwargs: {"score": 80, "checks": {"dialogue_count": 2}})
    monkeypatch.setattr(oq, "llm_opening_review", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ollama should not run")))
    monkeypatch.setattr(oq, "final_chatgpt_review", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chatgpt should not run")))

    result = _run_check(Job("test", "check"), _sample_script())

    assert result[0]["estimated_seconds"] == 42.0
    assert result[0]["ollama_enabled"] is False
    assert result[0]["chatgpt_enabled"] is False
    assert "local_review" not in result[0]
    assert "script" not in result[0]


def test_check_service_includes_enabled_llm_scores(monkeypatch):
    import config.config as cfg
    import core.opening_quality as oq
    import workers.main as wm
    from web_app.job_manager import Job
    from web_app.services.script_check_service import _run_check

    monkeypatch.setattr(cfg, "OPENING_REVIEW_USE_LLM", True)
    monkeypatch.setattr(cfg, "OPENAI_FINAL_REVIEW_ENABLED", True)
    monkeypatch.setattr(wm, "_estimate_script_duration", lambda _items, _is_shorts: (42.0, 2, 6.0))
    monkeypatch.setattr(oq, "local_opening_review", lambda *args, **kwargs: {"score": 80, "checks": {"dialogue_count": 2}})
    monkeypatch.setattr(oq, "llm_opening_review", lambda *args, **kwargs: {"score": 82, "status": "pass", "model": "ollama-test"})
    monkeypatch.setattr(oq, "final_chatgpt_review", lambda **kwargs: {"final_score": 84, "status": "pass", "model": "gpt-test"})

    result = _run_check(Job("test", "check"), _sample_script())

    assert result[0]["ollama_score"] == 82
    assert result[0]["ollama_model"] == "ollama-test"
    assert result[0]["chatgpt_score"] == 84
    assert result[0]["chatgpt_model"] == "gpt-test"
