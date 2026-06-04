"""VOICEVOX 接続エラーが対処手順つきの AppError に包まれることを確認する。"""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest
import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_audio_query_connection_error_becomes_voicevox_down():
    from core.voicevox import VoicevoxAPI
    from core.error_codes import AppError
    vv = VoicevoxAPI(base_url="http://localhost:50021")
    with mock.patch("core.voicevox.requests.post", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(AppError) as exc:
            vv.audio_query_only("テスト", 1)
    assert exc.value.code == "E-VOICEVOX-DOWN"
    assert "対処:" in exc.value.user_message()


def test_synthesis_timeout_becomes_voicevox_down():
    from core.voicevox import VoicevoxAPI
    from core.error_codes import AppError
    vv = VoicevoxAPI(base_url="http://localhost:50021")
    with mock.patch("core.voicevox.requests.post", side_effect=requests.Timeout("slow")):
        with pytest.raises(AppError) as exc:
            vv.synthesis_only({"k": "v"}, 1, os.devnull)
    assert exc.value.code == "E-VOICEVOX-DOWN"
