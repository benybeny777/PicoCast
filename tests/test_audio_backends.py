"""音声バックエンド抽象化のテスト。"""
from __future__ import annotations

import os
import sys
import textwrap
import wave

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _write_fake_wav_script(path):
    path.write_text(
        textwrap.dedent(
            """
            import sys
            import wave

            out = sys.argv[1]
            with wave.open(out, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b"\\x00\\x00" * 240)
            """
        ).strip(),
        encoding="utf-8",
    )


def test_aquestalk_check_disabled(monkeypatch):
    from core import audio_backends
    from config import config

    monkeypatch.setattr(config, "AQUESTALK_ENABLED", False)
    assert audio_backends.check_aquestalk()["enabled"] is False


def test_aquestalk_requires_engine_path(monkeypatch):
    from core.audio_backends import AudioSpeaker, generate_aquestalk_audio
    from config import config

    monkeypatch.setattr(config, "AQUESTALK_ENABLED", True)
    monkeypatch.setattr(config, "AQUESTALK_ENGINE_PATH", "")
    monkeypatch.setattr(config, "AQUESTALK_LICENSE_CONFIRMED", True)

    with pytest.raises(RuntimeError, match="エンジンパス"):
        generate_aquestalk_audio(
            text="テスト",
            speaker=AudioSpeaker(backend="aquestalk", speaker="yukkuri_reimu"),
            output_path="dummy.wav",
        )


def test_aquestalk_requires_license_key_or_confirmed_flag(tmp_path, monkeypatch):
    from core.audio_backends import AudioSpeaker, generate_aquestalk_audio
    from config import config

    monkeypatch.setattr(config, "AQUESTALK_ENABLED", True)
    monkeypatch.setattr(config, "AQUESTALK_ENGINE_PATH", sys.executable)
    monkeypatch.setattr(config, "AQUESTALK_LICENSE_CONFIRMED", False)
    monkeypatch.setattr(config, "AQUESTALK_COMMAND_TEMPLATE", '"{engine}" --version')

    with pytest.raises(RuntimeError, match="ライセンス"):
        generate_aquestalk_audio(
            text="テスト",
            speaker=AudioSpeaker(backend="aquestalk", speaker="yukkuri_reimu"),
            output_path=str(tmp_path / "dummy.wav"),
        )


def test_aquestalk_generate_with_command_template(tmp_path, monkeypatch):
    from core.audio_backends import AudioSpeaker, generate_aquestalk_audio
    from config import config

    fake = tmp_path / "fake_aquestalk.py"
    out = tmp_path / "out.wav"
    _write_fake_wav_script(fake)

    monkeypatch.setattr(config, "AQUESTALK_ENABLED", True)
    monkeypatch.setattr(config, "AQUESTALK_ENGINE_PATH", sys.executable)
    monkeypatch.setattr(config, "AQUESTALK_LICENSE_CONFIRMED", True)
    monkeypatch.setattr(config, "AQUESTALK_COMMAND_TEMPLATE", f'"{{engine}}" "{fake}" "{{output}}"')
    monkeypatch.setattr(config, "AQUESTALK_TIMEOUT_SEC", 10)

    generate_aquestalk_audio(
        text="ゆっくりしていってね",
        speaker=AudioSpeaker(
            backend="aquestalk",
            speaker="yukkuri_reimu",
            voice_type="reimu",
            speed=100,
            pitch=100,
            volume=100,
        ),
        output_path=str(out),
    )

    with wave.open(str(out), "rb") as w:
        assert w.getnframes() > 0
