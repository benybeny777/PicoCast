"""pytest 共通設定。"""

from tools.oracle_environment import deny_network, isolate
import pytest

# collection中のimportにもDB初期化があるため、fixtureより先に隔離する。
_isolated_environment, _isolated_root = isolate()
_network_guard = deny_network()


@pytest.fixture(scope="session", autouse=True)
def isolate_web_startup_side_effects():
    """画面テストの起動時にOSタスク・runner・実サービス調査を動かさない。"""
    from importlib import import_module
    from unittest.mock import Mock
    app_module = import_module("web_app.app")
    with pytest.MonkeyPatch.context() as monkeypatch:
        import threading
        original_start = threading.Thread.start

        def start_isolated_thread(thread, *args, **kwargs):
            # 関数そのものは差し替えず、起動時の自動更新スレッドだけを止める。
            if thread.name == "license-activation-renew":
                return None
            return original_start(thread, *args, **kwargs)

        monkeypatch.setattr(threading.Thread, "start", start_isolated_thread)
        status_service = import_module("web_app.services.status_service")
        for name in ["check_voicevox", "check_ffmpeg", "check_ollama", "check_sd_webui", "check_aquestalk"]:
            monkeypatch.setattr(status_service, name, Mock(return_value={"ok": False, "error": "隔離テストでは調査しません"}))
        monkeypatch.setattr(status_service, "refresh_settings_status", Mock(side_effect=status_service.get_settings_status))
        preload_service = import_module("web_app.services.settings_preload_service")
        monkeypatch.setattr(preload_service, "_fetch_ollama_models", Mock(return_value={"models": [], "available": False}))
        targets = [
            (app_module, "_start_job_runner"),
            (app_module, "_self_heal_fixed_comment_task"),
            (import_module("web_app.services.settings_preload_service"), "preload_settings_screen_cache"),
            (import_module("core.external_service_check"), "log_external_services"),
        ]
        for module, name in targets:
            monkeypatch.setattr(module, name, Mock(name="isolated_" + name))
        yield


@pytest.fixture
def configured_test_channel(monkeypatch, tmp_path):
    """設定済みチャンネルが前提のテストだけが明示利用する架空の設定。"""
    from core import channel_profile, prompt_profile_loader
    genre_dir = tmp_path / "genres" / "test_oracle"
    genre_dir.mkdir(parents=True)
    (genre_dir / "profile.yaml").write_text("", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    profile = channel_profile.ChannelProfile(
        profile_id="test_oracle", channel_name="架空の検証用", channel_handle="@test_oracle",
        genre_profile="test_oracle", output_root=str(output), is_active=True,
    )
    monkeypatch.setattr(channel_profile, "get_active_profile", lambda: profile)
    monkeypatch.setattr(prompt_profile_loader, "_GENRES_DIR", genre_dir.parent)
    return profile


def local_api_client(app, **kwargs):
    """通常の画面と同じ宛先・Origin・トークンを持つテストクライアント。"""
    from fastapi.testclient import TestClient
    origin = "http://127.0.0.1"
    headers = {"Origin": origin}
    if hasattr(app.state, "local_api_token"):
        headers["X-PicoCast-Token"] = app.state.local_api_token
    headers.update(kwargs.pop("headers", {}))
    return TestClient(app, base_url=origin, headers=headers, **kwargs)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_active_profile: active profile を用意せず未設定状態の挙動を検証する",
    )
