"""
core/secret_migration.py のユニットテスト。

- .env から GOOGLE_API_KEY を移行できる
- client_secrets.json / token.json / token_analytics.json を移行できる
- DB に既存の値がある場合は上書きしない
- 移行ログに秘密値が出ない
- 移行後のファイルは削除しない
外部API実通信なし。
"""
from __future__ import annotations

import json
import logging
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture()
def secret_env(tmp_path, monkeypatch):
    """
    secret_store / secret_migration を一時ディレクトリへリダイレクトし、
    固定マスターキーでモックする。
    """
    import core.secret_store as ss
    import core.secret_migration as sm

    _key = b"\x02" * 32
    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(ss, "_MASTER_KEY_PATH", str(tmp_path / "secret_master.key"))
    monkeypatch.setattr(ss, "_get_master_key", lambda: _key)
    monkeypatch.setattr(sm, "_ROOT", str(tmp_path))
    monkeypatch.setattr(sm, "_ENV_PATH", str(tmp_path / ".env"))

    yield ss, sm, tmp_path


# ── .env からの移行 ───────────────────────────────────────────────────────────

def test_migrate_google_api_key_from_env(secret_env):
    """.env の GOOGLE_API_KEY を DB に移行できる。"""
    ss, sm, tmp = secret_env
    (tmp / ".env").write_text("GOOGLE_API_KEY=AIzaTestMigrate\n", encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["google_api_key"] == "migrated"
    assert ss.has_secret("google_api_key")
    # 値の正確さも確認（平文には触れず、ロードして比較）
    assert ss.load_secret("google_api_key") == "AIzaTestMigrate"


def test_migrate_openai_api_key_from_env(secret_env):
    """.env の OPENAI_API_KEY を DB に移行できる。"""
    ss, sm, tmp = secret_env
    (tmp / ".env").write_text("OPENAI_API_KEY=sk-migrate-test\n", encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["openai_api_key"] == "migrated"
    assert ss.load_secret("openai_api_key") == "sk-migrate-test"


def test_migrate_hf_token_from_env(secret_env):
    """.env の HF_TOKEN を DB に移行できる。"""
    ss, sm, tmp = secret_env
    (tmp / ".env").write_text("HF_TOKEN=hf_MigrateTestToken\n", encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["hf_token"] == "migrated"
    assert ss.load_secret("hf_token") == "hf_MigrateTestToken"


def test_env_key_missing_returns_missing(secret_env):
    """.env に対象キーがない場合は 'missing' を返す。"""
    ss, sm, tmp = secret_env
    (tmp / ".env").write_text("CHANNEL_NAME=TestChannel\n", encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["google_api_key"] == "missing"


def test_existing_db_secret_not_overwritten(secret_env):
    """DB に既存の値がある場合は旧ファイルで上書きしない。"""
    ss, sm, tmp = secret_env
    ss.save_secret("google_api_key", "AIzaOriginal")
    (tmp / ".env").write_text("GOOGLE_API_KEY=AIzaFromEnv\n", encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["google_api_key"] == "already_exists"
    # DB の値は変わらない
    assert ss.load_secret("google_api_key") == "AIzaOriginal"


def test_env_file_not_deleted_after_migration(secret_env):
    """移行後も .env ファイル自体は削除しない（中身の認証キー行が消えるだけ）。"""
    ss, sm, tmp = secret_env
    env_path = tmp / ".env"
    env_path.write_text("GOOGLE_API_KEY=AIzaNoDelete\n", encoding="utf-8")

    sm.migrate_existing_secret_files()

    assert env_path.exists()


def test_migrated_key_removed_from_env(secret_env):
    """移行成功後、.env からその認証キーが削除される。"""
    ss, sm, tmp = secret_env
    env_path = tmp / ".env"
    env_path.write_text(
        "GOOGLE_API_KEY=AIzaMigrated\nCHANNEL_NAME=TestCh\n",
        encoding="utf-8",
    )

    sm.migrate_existing_secret_files()

    content = env_path.read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY" not in content
    assert "CHANNEL_NAME=TestCh" in content  # 非認証設定は残る


def test_already_exists_key_removed_from_env(secret_env):
    """DB に既存の値がある場合も .env から認証キーを削除する。"""
    ss, sm, tmp = secret_env
    ss.save_secret("google_api_key", "AIzaOriginal")
    env_path = tmp / ".env"
    env_path.write_text("GOOGLE_API_KEY=AIzaFromEnv\n", encoding="utf-8")

    sm.migrate_existing_secret_files()

    content = env_path.read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY" not in content
    # DB の値は変わらない
    assert ss.load_secret("google_api_key") == "AIzaOriginal"


def test_failed_migration_key_kept_in_env(secret_env, monkeypatch):
    """移行失敗したキーは .env に残る。"""
    ss, sm, tmp = secret_env
    env_path = tmp / ".env"
    env_path.write_text("GOOGLE_API_KEY=AIzaFail\n", encoding="utf-8")

    def _failing_save(*args, **kwargs):
        raise RuntimeError("テスト用エラー")

    monkeypatch.setattr(ss, "save_secret", _failing_save)

    sm.migrate_existing_secret_files()

    content = env_path.read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY" in content  # 失敗したので残る


# ── OAuth JSON ファイルの移行 ──────────────────────────────────────────────────

def test_migrate_client_secrets_json(secret_env):
    """client_secrets.json を DB に移行できる。"""
    ss, sm, tmp = secret_env
    client_secrets = {
        "installed": {
            "client_id": "test.apps.googleusercontent.com",
            "client_secret": "TEST_SECRET",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    (tmp / "client_secrets.json").write_text(
        json.dumps(client_secrets), encoding="utf-8"
    )

    result = sm.migrate_existing_secret_files()

    assert result["youtube_client_secrets"] == "migrated"
    assert ss.has_secret("youtube_client_secrets")
    # JSON として復元できる
    recovered = json.loads(ss.load_secret("youtube_client_secrets"))
    assert recovered["installed"]["client_id"] == "test.apps.googleusercontent.com"


def test_migrate_token_json(secret_env):
    """token.json を DB に移行できる。"""
    ss, sm, tmp = secret_env
    token = {
        "token": "ya29.TEST_TOKEN",
        "refresh_token": "1//REFRESH",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "TEST_SECRET",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }
    (tmp / "token.json").write_text(json.dumps(token), encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["youtube_upload_token"] == "migrated"


def test_migrate_token_analytics_json(secret_env):
    """token_analytics.json を DB に移行できる。"""
    ss, sm, tmp = secret_env
    token = {"token": "ya29.analytics", "refresh_token": "1//analytics_refresh"}
    (tmp / "token_analytics.json").write_text(json.dumps(token), encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["youtube_analytics_token"] == "migrated"


def test_invalid_json_returns_error(secret_env):
    """不正な JSON ファイルは 'error' を返す。"""
    ss, sm, tmp = secret_env
    (tmp / "client_secrets.json").write_text("not-valid-json", encoding="utf-8")

    result = sm.migrate_existing_secret_files()

    assert result["youtube_client_secrets"] == "error"


def test_json_file_not_deleted_after_migration(secret_env):
    """移行後も token.json は削除しない。"""
    ss, sm, tmp = secret_env
    token_path = tmp / "token.json"
    token_path.write_text(json.dumps({"token": "ya29.x"}), encoding="utf-8")

    sm.migrate_existing_secret_files()

    assert token_path.exists()


# ── ログに秘密値が出ないことを確認 ────────────────────────────────────────────

def test_migration_log_does_not_contain_secret(secret_env, caplog):
    """移行ログに秘密値が含まれない。"""
    ss, sm, tmp = secret_env
    secret_value = "AIzaVerySecretLogTest"
    (tmp / ".env").write_text(f"GOOGLE_API_KEY={secret_value}\n", encoding="utf-8")

    with caplog.at_level(logging.INFO):
        sm.migrate_existing_secret_files()

    for record in caplog.records:
        assert secret_value not in record.getMessage()
