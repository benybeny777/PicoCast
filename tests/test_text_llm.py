"""文章生成AIの窓口（core/text_llm.py）のテスト。実際の CLI・API は呼ばない。"""
import sys

import pytest

from config import config as cfg
from core import text_llm
from core.error_codes import AppError


def test_claude_args_block_tools_and_allow_only_web_search(monkeypatch):
    monkeypatch.setattr(cfg, "CLAUDE_CLI_MODEL", "")
    plain = text_llm.cli_args("claude_cli", web_search=False)
    assert plain[0] == "-p"
    assert plain[plain.index("--tools") + 1] == ""
    assert plain[plain.index("--permission-mode") + 1] == "plan"
    assert "--safe-mode" in plain and "--no-session-persistence" in plain
    searching = text_llm.cli_args("claude_cli", web_search=True)
    assert searching[searching.index("--tools") + 1] == "WebSearch"


def test_codex_args_are_read_only_and_read_prompt_from_stdin(monkeypatch):
    monkeypatch.setattr(cfg, "CODEX_CLI_MODEL", "gpt-x")
    args = text_llm.cli_args("codex_cli", web_search=True)
    assert args[0] == "exec"
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert args[args.index("--model") + 1] == "gpt-x"
    assert args[-1] == "-"


def test_model_name_with_shell_characters_is_rejected(monkeypatch):
    monkeypatch.setattr(cfg, "CLAUDE_CLI_MODEL", "opus & del")
    with pytest.raises(AppError) as exc:
        text_llm.cli_args("claude_cli", web_search=False)
    assert exc.value.code == "E-LLM-BACKEND"


def test_codex_default_model_follows_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        "model = 'base'\nprofile = 'work'\n[profiles.work]\nmodel = 'profile-model'\n", encoding="utf-8",
    )
    assert text_llm.codex_default_model() == "profile-model"
    (tmp_path / "config.toml").write_text("model = 'base'\n", encoding="utf-8")
    assert text_llm.codex_default_model() == "base"


def _fake_cli(tmp_path, body: str) -> str:
    """標準入力を読んで決まった応答をする偽の CLI。"""
    script = tmp_path / "fake_cli.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_cli_receives_prompt_via_stdin_and_returns_stdout(tmp_path, monkeypatch):
    script = _fake_cli(tmp_path, "import sys\nprint('受信:' + sys.stdin.read().strip())\n")
    monkeypatch.setattr(text_llm, "resolve_cli", lambda backend: sys.executable)
    monkeypatch.setattr(text_llm, "cli_args", lambda backend, web_search: [str(script)])
    text = text_llm.generate("台本を & | \" 改行\nも含めて", system="指示", backend="claude_cli")
    assert text.startswith("受信:指示")
    assert "& | \" 改行\nも含めて" in text


def test_cli_failure_and_empty_output_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(text_llm, "resolve_cli", lambda backend: sys.executable)
    failing = _fake_cli(tmp_path, "import sys\nsys.stdin.read()\nsys.exit(2)\n")
    monkeypatch.setattr(text_llm, "cli_args", lambda backend, web_search: [str(failing)])
    with pytest.raises(AppError) as exc:
        text_llm.generate("x", backend="codex_cli")
    assert exc.value.code == "E-LLM-FAILED"

    empty = tmp_path / "empty.py"
    empty.write_text("import sys\nsys.stdin.read()\n", encoding="utf-8")
    monkeypatch.setattr(text_llm, "cli_args", lambda backend, web_search: [str(empty)])
    with pytest.raises(AppError) as exc:
        text_llm.generate("x", backend="codex_cli")
    assert exc.value.code == "E-LLM-FAILED"


def test_cli_timeout_kills_process(tmp_path, monkeypatch):
    slow = _fake_cli(tmp_path, "import time\ntime.sleep(30)\n")
    monkeypatch.setattr(text_llm, "resolve_cli", lambda backend: sys.executable)
    monkeypatch.setattr(text_llm, "cli_args", lambda backend, web_search: [str(slow)])
    monkeypatch.setattr(cfg, "TEXT_LLM_TIMEOUT_SEC", 1)
    with pytest.raises(AppError) as exc:
        text_llm.generate("x", backend="claude_cli")
    assert exc.value.code == "E-LLM-TIMEOUT"


def test_missing_cli_and_unknown_backend(monkeypatch):
    monkeypatch.setattr(cfg, "CLAUDE_CLI_PATH", "definitely-not-installed-cli")
    with pytest.raises(AppError) as exc:
        text_llm.generate("x", backend="claude_cli")
    assert exc.value.code == "E-LLM-CLI-MISSING"
    monkeypatch.setattr(cfg, "TEXT_LLM_BACKEND", "unknown")
    with pytest.raises(AppError) as exc:
        text_llm.current_backend()
    assert exc.value.code == "E-LLM-BACKEND"


def test_ai_generator_uses_selected_backend_for_title_variants(monkeypatch):
    from core.ai_generator import AIGenerator

    monkeypatch.setattr(cfg, "TEXT_LLM_BACKEND", "claude_cli")
    seen = {}

    def fake_generate(prompt, **kwargs):
        seen["prompt"] = prompt
        return '```json\n{"title_variants": [{"variant": "A", "title": "ずんだ餅の秘密", "concept": "c"}]}\n```'

    monkeypatch.setattr(text_llm, "generate", fake_generate)
    ai = AIGenerator()
    ai.close()  # パイプラインは台本取得後に close してからタイトル案を作る
    assert ai.generate_title_variants("台本", "既定タイトル") == [
        {"variant": "A", "title": "ずんだ餅の秘密", "concept": "c"}
    ]
    assert "既定タイトル" in seen["prompt"]
