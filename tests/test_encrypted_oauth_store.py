"""
OAuthトークンの DB 保存・復元・refresh後再保存テスト。

- OAuth refresh 後に DB へ再保存される
- token.json / token_analytics.json が新規作成されない
- Credentials.from_authorized_user_info による復元ができる
外部API実通信はすべてモック。
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture()
def oauth_env(tmp_path, monkeypatch):
    """
    secret_store を一時ディレクトリへリダイレクトし、
    youtube_uploader / youtube_analytics の外部依存をモックする。
    """
    import core.secret_store as ss

    _key = b"\x03" * 32
    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(ss, "_MASTER_KEY_PATH", str(tmp_path / "key"))
    monkeypatch.setattr(ss, "_get_master_key", lambda: _key)

    yield ss, tmp_path


# ── Credentials から DB 保存・復元 ────────────────────────────────────────────

def test_save_and_restore_token_json(oauth_env):
    """OAuthトークン JSON を DB に保存して復元できる。"""
    ss, tmp = oauth_env
    token_data = {
        "token": "ya29.UPLOAD_TOKEN",
        "refresh_token": "1//REFRESH_UPLOAD",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "TEST_SECRET",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }
    token_json = json.dumps(token_data)
    ss.save_secret("youtube_upload_token", token_json, profile_id="food_trivia")

    recovered = json.loads(ss.load_secret("youtube_upload_token", profile_id="food_trivia"))
    assert recovered["token"] == "ya29.UPLOAD_TOKEN"
    assert recovered["refresh_token"] == "1//REFRESH_UPLOAD"


def test_token_file_not_created(oauth_env, monkeypatch, tmp_path):
    """
    get_youtube_client() が token.json を新規作成しないことを確認する。
    InstalledAppFlow と build をモックして実際の OAuth フローを発生させない。
    """
    ss, _ = oauth_env

    # 有効な Credentials をモック
    import unittest.mock as mock
    import core.youtube_uploader as uploader

    valid_token = {
        "token": "ya29.VALID",
        "refresh_token": "1//REFRESH",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "TEST_SECRET",
        "scopes": uploader.SCOPES,
    }
    ss.save_secret("youtube_upload_token", json.dumps(valid_token), profile_id="food_trivia")

    # Credentials.from_authorized_user_info でモック Credentials を返す
    fake_creds = mock.MagicMock()
    fake_creds.valid = True
    monkeypatch.setattr(
        "core.youtube_uploader.Credentials.from_authorized_user_info",
        lambda info, scopes: fake_creds,
    )
    mock_build = mock.MagicMock()
    monkeypatch.setattr("core.youtube_uploader.build", mock_build)

    # 既存 token.json の更新日時を記録（移行前の旧ファイルが残っていても更新されないことを確認）
    _token_path = os.path.join(_ROOT, "token.json")
    _pre_mtime = os.path.getmtime(_token_path) if os.path.isfile(_token_path) else None

    uploader.get_youtube_client()

    # tmp_path には token.json が作られていない
    assert not os.path.isfile(os.path.join(str(tmp_path), "token.json"))
    # 既存 token.json が更新されていない（新規作成もしていない）
    if _pre_mtime is None:
        assert not os.path.isfile(_token_path)
    else:
        assert os.path.getmtime(_token_path) == _pre_mtime


def test_token_analytics_file_not_created(oauth_env, monkeypatch, tmp_path):
    """
    _get_credentials() が token_analytics.json を新規作成しないことを確認する。
    """
    ss, _ = oauth_env

    import unittest.mock as mock
    import core.youtube_analytics as analytics

    valid_token = {
        "token": "ya29.ANALYTICS",
        "refresh_token": "1//ANALYTICS_REFRESH",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "TEST_SECRET",
        "scopes": analytics.SCOPES,
    }
    ss.save_secret("youtube_analytics_token", json.dumps(valid_token), profile_id="food_trivia")

    fake_creds = mock.MagicMock()
    fake_creds.valid = True
    monkeypatch.setattr(
        "core.youtube_analytics.Credentials.from_authorized_user_info",
        lambda info, scopes: fake_creds,
    )

    _analytics_path = os.path.join(_ROOT, "token_analytics.json")
    _pre_mtime = os.path.getmtime(_analytics_path) if os.path.isfile(_analytics_path) else None

    analytics._get_credentials()

    assert not os.path.isfile(os.path.join(str(tmp_path), "token_analytics.json"))
    if _pre_mtime is None:
        assert not os.path.isfile(_analytics_path)
    else:
        assert os.path.getmtime(_analytics_path) == _pre_mtime


def test_refresh_saves_updated_token_to_db(oauth_env, monkeypatch):
    """OAuth refresh 後に更新トークンが DB へ再保存される。"""
    ss, _ = oauth_env

    import unittest.mock as mock
    import core.youtube_uploader as uploader

    # 期限切れトークンをセット
    expired_token = {
        "token": "ya29.EXPIRED",
        "refresh_token": "1//REFRESH_OLD",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "TEST_SECRET",
        "scopes": uploader.SCOPES,
    }
    ss.save_secret("youtube_upload_token", json.dumps(expired_token), profile_id="food_trivia")

    # refresh 後の新トークン
    new_token_json = json.dumps({
        "token": "ya29.REFRESHED",
        "refresh_token": "1//REFRESH_NEW",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "TEST_SECRET",
        "scopes": uploader.SCOPES,
    })

    fake_creds = mock.MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "1//REFRESH_OLD"
    fake_creds.to_json.return_value = new_token_json

    def _mock_refresh(request):
        fake_creds.valid = True

    fake_creds.refresh = _mock_refresh

    monkeypatch.setattr(
        "core.youtube_uploader.Credentials.from_authorized_user_info",
        lambda info, scopes: fake_creds,
    )
    mock_build = mock.MagicMock()
    monkeypatch.setattr("core.youtube_uploader.build", mock_build)
    monkeypatch.setattr("core.youtube_uploader.Request", mock.MagicMock)

    uploader.get_youtube_client()

    # DB に新しいトークンが保存されている
    recovered = json.loads(ss.load_secret("youtube_upload_token", profile_id="food_trivia"))
    assert recovered["token"] == "ya29.REFRESHED"
