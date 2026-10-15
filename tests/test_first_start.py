"""未設定環境でも初回セットアップへ到達できることを検証する。"""
import asyncio
from unittest.mock import MagicMock


def test_lifespan_without_channel_does_not_initialize_profile_db(monkeypatch):
    from core import app_shutdown, channel_profile, metadata_db
    from web_app import app
    import threading

    monkeypatch.setattr(channel_profile, "get_active_profile", lambda: None)
    initialize = MagicMock(side_effect=AssertionError("未設定profileのDBを初期化してはいけません"))
    monkeypatch.setattr(metadata_db, "initialize_db", initialize)
    monkeypatch.setattr(app, "_start_job_runner", lambda: None)
    monkeypatch.setattr(app_shutdown, "register_shutdown_hook", lambda *args: None)
    monkeypatch.setattr(app_shutdown, "run_lifespan_shutdown", lambda: None)
    monkeypatch.setattr(threading, "Thread", MagicMock())

    async def startup():
        async with app._lifespan(app.app):
            initialize.assert_not_called()

    asyncio.run(startup())
