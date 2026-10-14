"""
/api/settings/secrets/status など認証情報 API エンドポイントのテスト。

- status API は値ではなく登録状態だけ返す
- save/delete が正常に動作する
- client_secrets 登録が動作する
- 旧ファイル削除は confirmed=true 必須
外部API実通信なし。
"""
from __future__ import annotations

import json
import os
import sys

import pytest
from conftest import local_api_client as TestClient

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_secret_store(tmp_path, monkeypatch):
    """全テストで secret_store を一時ディレクトリ + 固定キーでモックする。"""
    import core.secret_store as ss
    import core.channel_profile as cp

    _key = b"\x04" * 32
    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(ss, "_MASTER_KEY_PATH", str(tmp_path / "key"))
    monkeypatch.setattr(ss, "_get_master_key", lambda: _key)
    monkeypatch.setattr(cp, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(cp, "_ROOT", str(tmp_path))
    monkeypatch.setattr(cp, "_RES_ROOT", str(tmp_path))


@pytest.fixture()
def client():
    from web_app.app import app
    return TestClient(app, raise_server_exceptions=True)


# ── /api/settings/secrets/status ─────────────────────────────────────────────

def test_status_returns_bool_not_value(client):
    """status API は値ではなく bool（登録状態）だけを返す。"""
    resp = client.get("/api/settings/secrets/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "secrets" in body
    for v in body["secrets"].values():
        assert isinstance(v, bool)


def test_status_shows_registered_after_save(client):
    """APIキー登録後に status が True になる。"""
    client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "google_api_key", "value": "AIzaStatusTest"},
    )
    resp = client.get("/api/settings/secrets/status")
    assert resp.json()["secrets"]["google_api_key"] is True


def test_status_shows_aquestalk_license_after_save(client):
    """AquesTalkライセンスキーは値ではなく登録状態だけ返す。"""
    client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "aquestalk_license_key", "value": "AQUESTALK-LICENSE-TEST"},
    )
    body = client.get("/api/settings/secrets/status").json()
    assert body["secrets"]["aquestalk_license_key"] is True


def test_api_key_status_is_profile_scoped(client):
    """APIキーは profile_id ごとに登録状態が分離される。"""
    client.post(
        "/api/settings/secrets/api-key",
        json={
            "secret_type": "google_api_key",
            "value": "AIzaProfileA",
            "profile_id": "profile_a",
        },
    )

    profile_a = client.get("/api/settings/secrets/status?profile_id=profile_a").json()
    profile_b = client.get("/api/settings/secrets/status?profile_id=profile_b").json()

    assert profile_a["secrets"]["google_api_key"] is True
    assert profile_b["secrets"]["google_api_key"] is False


def test_channel_list_includes_profile_scoped_api_key_status(client):
    from core.channel_profile import ChannelProfile, save_profile

    save_profile(ChannelProfile(
        profile_id="profile_auth",
        channel_name="認証状態テスト",
        channel_handle="@profile_auth",
        genre_profile="food_trivia",
        output_root="output/profile_auth",
    ))
    client.post(
        "/api/settings/secrets/api-key",
        json={
            "secret_type": "google_api_key",
            "value": "AIzaProfileAuth",
            "profile_id": "profile_auth",
        },
    )

    resp = client.get("/api/channels")
    profile = next(p for p in resp.json()["profiles"] if p["profile_id"] == "profile_auth")

    assert profile["auth"]["google_api_key"] is True
    assert profile["auth"]["openai_api_key"] is False


def test_status_does_not_contain_key_value(client):
    """status レスポンスに APIキーの値が含まれない。"""
    client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "openai_api_key", "value": "sk-should-not-appear"},
    )
    resp = client.get("/api/settings/secrets/status")
    body_str = resp.text
    assert "sk-should-not-appear" not in body_str


# ── /api/settings/secrets/api-key ────────────────────────────────────────────

def test_save_api_key(client):
    """APIキーを保存できる。"""
    resp = client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "hf_token", "value": "hf_SaveTest"},
    )
    assert resp.status_code == 200


def test_save_api_key_invalid_type(client):
    """不正な secret_type は 422 エラー。"""
    resp = client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "bad_type", "value": "test"},
    )
    assert resp.status_code == 422


def test_save_api_key_empty_value(client):
    """空の値は 422 エラー。"""
    resp = client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "google_api_key", "value": ""},
    )
    assert resp.status_code == 422


def test_save_api_key_with_newline(client):
    """改行を含む値は 422 エラー。"""
    resp = client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "google_api_key", "value": "AIza\nleaked=value"},
    )
    assert resp.status_code == 422


# ── /api/settings/secrets/client-secrets ──────────────────────────────────────

def test_save_client_secrets_valid_json(client):
    """有効な JSON の client_secrets を保存できる。"""
    cs = {"installed": {"client_id": "test", "client_secret": "sec"}}
    resp = client.post(
        "/api/settings/secrets/client-secrets",
        json={"json_text": json.dumps(cs)},
    )
    assert resp.status_code == 200


def test_save_client_secrets_invalid_json(client):
    """不正な JSON は 422 エラー。"""
    resp = client.post(
        "/api/settings/secrets/client-secrets",
        json={"json_text": "not-valid-json"},
    )
    assert resp.status_code == 422


# ── /api/settings/secrets/delete (API key) ───────────────────────────────────

def test_delete_api_key_requires_confirmed(client):
    """confirmed=true なしの削除は 422 エラー。"""
    client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "hf_token", "value": "hf_del"},
    )
    resp = client.request(
        "DELETE",
        "/api/settings/secrets/api-key",
        json={"secret_type": "hf_token", "confirmed": False},
    )
    assert resp.status_code == 422


def test_delete_api_key_with_confirmed(client):
    """confirmed=true で削除できる。"""
    client.post(
        "/api/settings/secrets/api-key",
        json={"secret_type": "hf_token", "value": "hf_del_ok"},
    )
    resp = client.request(
        "DELETE",
        "/api/settings/secrets/api-key",
        json={"secret_type": "hf_token", "confirmed": True},
    )
    assert resp.status_code == 200
    # 削除後は False
    status = client.get("/api/settings/secrets/status").json()
    assert status["secrets"]["hf_token"] is False


# ── /api/settings/secrets/legacy-file ────────────────────────────────────────

def test_delete_legacy_file_requires_confirmed(client):
    """confirmed=true なしの旧ファイル削除は 422 エラー。"""
    resp = client.request(
        "DELETE",
        "/api/settings/secrets/legacy-file",
        json={"filename": "token.json", "confirmed": False},
    )
    assert resp.status_code == 422


def test_delete_legacy_file_disallows_unknown_file(client):
    """対象外ファイル名は 422 エラー。"""
    resp = client.request(
        "DELETE",
        "/api/settings/secrets/legacy-file",
        json={"filename": "../../etc/passwd", "confirmed": True},
    )
    assert resp.status_code == 422
