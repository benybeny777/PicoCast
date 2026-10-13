"""Codex CLI の画像生成（core/codex_image.py）のテスト。実際の codex は呼ばず、偽の CLI で確かめる。"""
import io
import os
import sys

import pytest
from PIL import Image

from config import config as cfg
from core import codex_image, text_llm
from core.error_codes import AppError


def test_command_is_sandboxed_to_workdir_and_reads_prompt_from_stdin(monkeypatch):
    monkeypatch.setattr(cfg, "CODEX_CLI_MODEL", "")
    monkeypatch.setattr(text_llm, "codex_default_model", lambda: None)
    args = codex_image.command("codex", "/work", ["/work/reference_1.png", "/work/reference_2.png"])
    assert args[:2] == ["codex", "exec"]
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert args[args.index("--cd") + 1] == "/work"
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert "--image=/work/reference_1.png" in args and "--image=/work/reference_2.png" in args
    assert args[-1] == "-"
    assert "--model" not in args


def test_subscription_env_drops_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-pass")
    assert "OPENAI_API_KEY" not in codex_image.subscription_env()


def _fake_codex(tmp_path, body):
    script = tmp_path / "fake_codex.py"
    script.write_text(body, encoding="utf-8")
    return script


def _use_fake(monkeypatch, script):
    monkeypatch.setattr(text_llm, "resolve_cli", lambda backend: sys.executable)
    monkeypatch.setattr(
        codex_image, "command",
        lambda program, workdir, refs: [program, str(script), *[f"--image={r}" for r in refs]],
    )


def test_generate_png_returns_saved_image_and_cleans_workdir(tmp_path, monkeypatch):
    script = _fake_codex(tmp_path, (
        "import os, sys\n"
        "from PIL import Image\n"
        "prompt = sys.stdin.read()\n"
        "assert 'output.png' in prompt and '夕焼けの屋台' in prompt and '横長' in prompt\n"
        "assert 'OPENAI_API_KEY' not in os.environ\n"
        "refs = [a.split('=', 1)[1] for a in sys.argv[1:]]\n"
        "assert refs and all(os.path.dirname(r) == os.getcwd() for r in refs)\n"
        "Image.new('RGB', (32, 18), (200, 10, 10)).save('output.png')\n"
        "print('保存しました')\n"
    ))
    _use_fake(monkeypatch, script)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ref = tmp_path / "zundamon.png"
    Image.new("RGBA", (4, 4)).save(ref)
    workdirs = []
    real_mkdtemp = codex_image.tempfile.mkdtemp
    monkeypatch.setattr(codex_image.tempfile, "mkdtemp", lambda **k: workdirs.append(real_mkdtemp(**k)) or workdirs[-1])

    png = codex_image.generate_png("夕焼けの屋台", width=1920, height=1080, reference_paths=[str(ref)])

    with Image.open(io.BytesIO(png)) as img:
        assert img.size == (32, 18)
    assert workdirs and not os.path.exists(workdirs[0])


def test_missing_output_is_an_error_not_a_search(tmp_path, monkeypatch):
    script = _fake_codex(tmp_path, "import sys\nsys.stdin.read()\nopen('other.png', 'wb').write(b'x')\n")
    _use_fake(monkeypatch, script)
    with pytest.raises(AppError) as exc:
        codex_image.generate_png("x", width=100, height=100)
    assert exc.value.code == "E-CODEX-IMAGE-MISSING"


def test_cli_failure_raises(tmp_path, monkeypatch):
    script = _fake_codex(tmp_path, "import sys\nsys.stdin.read()\nsys.exit(1)\n")
    _use_fake(monkeypatch, script)
    with pytest.raises(AppError) as exc:
        codex_image.generate_png("x", width=100, height=100)
    assert exc.value.code == "E-LLM-FAILED"


def test_image_generator_codex_backend_resizes_to_final_size(tmp_path, monkeypatch):
    from core.image_generator import ImageGenerator

    monkeypatch.setattr(cfg, "IMAGE_BACKEND", "codex_cli")
    sent = {}

    def fake_generate_png(prompt, *, width, height, reference_paths=None):
        sent.update(prompt=prompt, refs=reference_paths)
        buf = io.BytesIO()
        Image.new("RGB", (64, 36)).save(buf, format="PNG")
        return buf.getvalue()

    monkeypatch.setattr(codex_image, "generate_png", fake_generate_png)
    ref = tmp_path / "metan.png"
    Image.new("RGBA", (4, 4)).save(ref)
    with ImageGenerator(width=1920, height=1080) as gen:
        name = gen.generate_background("台本", target_dir=str(tmp_path), raw=True, is_thumbnail=True,
                                       reference_image_paths=[str(ref), str(tmp_path / "missing.png")])
    with Image.open(tmp_path / name) as img:
        assert img.size == (1920, 1080)
    assert sent["refs"] == [str(ref)]
    assert sent["prompt"].startswith("上記はキャラクターの参照画像です")


@pytest.mark.parametrize(
    ("setting", "background", "expected"),
    [("", "comfyui", "comfyui"), ("codex_cli", "comfyui", "codex_cli"), ("gemini", "sd_webui", "nanobanana")],
)
def test_thumbnail_engine_follows_setting(monkeypatch, setting, background, expected):
    from core.image_generator import thumbnail_engine

    monkeypatch.setattr(cfg, "THUMBNAIL_IMAGE_BACKEND", setting)
    assert thumbnail_engine(background) == expected


def test_unknown_thumbnail_backend_is_rejected(monkeypatch):
    from core.image_generator import thumbnail_engine

    monkeypatch.setattr(cfg, "THUMBNAIL_IMAGE_BACKEND", "dalle")
    with pytest.raises(ValueError):
        thumbnail_engine("comfyui")
