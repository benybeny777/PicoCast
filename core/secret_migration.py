"""
既存認証ファイルから DB への移行モジュール。

対象:
  .env              → GOOGLE_API_KEY / OPENAI_API_KEY / HF_TOKEN
  client_secrets.json → youtube_client_secrets  (profile_id 単位)
  token.json          → youtube_upload_token    (profile_id 単位)
  token_analytics.json → youtube_analytics_token (profile_id 単位)

ルール:
- 秘密値をログに出さない
- 移行結果は状態文字列のみ返す（値を含まない）
- DBに既存の値がある場合はスキップ（上書きしない）
- .env の認証キーは DB 移行済み（migrated / already_exists）なら行ごと削除する
- JSON ファイルは削除しない（手動削除は設定画面から）
- 移行失敗は例外を伝播させずステータス "error" で返す
"""
from __future__ import annotations

import json
import logging
import os
from typing import TypedDict

_logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")

_STATUS_MIGRATED = "migrated"
_STATUS_ALREADY_EXISTS = "already_exists"
_STATUS_MISSING = "missing"
_STATUS_ERROR = "error"

# .env から読む認証キー名
_ENV_AUTH_MAP: list[tuple[str, str]] = [
    ("google_api_key",  "GOOGLE_API_KEY"),
    ("openai_api_key",  "OPENAI_API_KEY"),
    ("hf_token",        "HF_TOKEN"),
]

# JSONファイルからの移行マップ (secret_type, filename)
_OAUTH_FILE_MAP: list[tuple[str, str]] = [
    ("youtube_client_secrets",  "client_secrets.json"),
    ("youtube_upload_token",    "token.json"),
    ("youtube_analytics_token", "token_analytics.json"),
]


class SecretMigrationResult(TypedDict):
    google_api_key: str
    openai_api_key: str
    hf_token: str
    youtube_client_secrets: str
    youtube_upload_token: str
    youtube_analytics_token: str


def migrate_existing_secret_files(
    profile_id: str = "default",
) -> SecretMigrationResult:
    """
    既存の認証ファイルを DB へ移行する。

    Returns:
        各 secret_type のステータス文字列を持つ dict。
        ステータス値: "migrated" / "already_exists" / "missing" / "error"
        秘密値は一切含まない。
    """
    from core.secret_store import has_secret, save_secret

    result: SecretMigrationResult = {
        "google_api_key":          _STATUS_MISSING,
        "openai_api_key":          _STATUS_MISSING,
        "hf_token":                _STATUS_MISSING,
        "youtube_client_secrets":  _STATUS_MISSING,
        "youtube_upload_token":    _STATUS_MISSING,
        "youtube_analytics_token": _STATUS_MISSING,
    }

    # ── .env からAPIキーを移行 ────────────────────────────────────────────
    env_values = _read_env_auth_keys()
    env_keys_to_remove: set[str] = set()  # .env から削除するキー名を収集

    for secret_type, env_key in _ENV_AUTH_MAP:
        value = env_values.get(env_key, "")
        if not value:
            result[secret_type] = _STATUS_MISSING
            continue
        if has_secret(secret_type):
            result[secret_type] = _STATUS_ALREADY_EXISTS
            env_keys_to_remove.add(env_key)  # DB済みなので .env から消す
            continue
        try:
            save_secret(secret_type, value)
            result[secret_type] = _STATUS_MIGRATED
            env_keys_to_remove.add(env_key)  # 移行成功したので .env から消す
            _logger.info("[SecretMigration] %s を DB に移行しました", secret_type)
        except Exception as e:
            _logger.error(
                "[SecretMigration] %s の移行に失敗: %s",
                secret_type, type(e).__name__,
            )
            result[secret_type] = _STATUS_ERROR

    # 移行済みキーを .env から削除する（失敗したキーは残す）
    if env_keys_to_remove:
        _remove_env_auth_keys(env_keys_to_remove)

    # ── OAuth JSON ファイルを移行 ──────────────────────────────────────────
    for secret_type, filename in _OAUTH_FILE_MAP:
        path = os.path.join(_ROOT, filename)
        if not os.path.isfile(path):
            result[secret_type] = _STATUS_MISSING
            continue
        if has_secret(secret_type, profile_id=profile_id):
            result[secret_type] = _STATUS_ALREADY_EXISTS
            continue
        result[secret_type] = _migrate_json_file(
            path, secret_type, profile_id, save_secret
        )

    _logger.info(
        "[SecretMigration] 移行完了: %s",
        {k: v for k, v in result.items()},
    )
    return result


def _remove_env_auth_keys(keys_to_remove: set[str]) -> None:
    """
    .env から指定されたキーの行を削除する。
    値はログに出さない。削除できない場合は警告のみ（例外を伝播しない）。
    """
    if not os.path.isfile(_ENV_PATH):
        return
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            lines = f.readlines()

        new_lines: list[str] = []
        removed: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.partition("=")[0].strip()
                if k in keys_to_remove:
                    removed.append(k)
                    continue  # この行を除去
            new_lines.append(line)

        if removed:
            with open(_ENV_PATH, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            _logger.info(
                "[SecretMigration] .env から認証キーを削除しました: %s", removed
            )
    except OSError as e:
        _logger.warning(
            "[SecretMigration] .env の認証キー削除に失敗: %s", type(e).__name__
        )


def _read_env_auth_keys() -> dict[str, str]:
    """
    .env から AUTH_KEYS（GOOGLE_API_KEY / OPENAI_API_KEY / HF_TOKEN）のみを読む。
    値をログに出さない。
    """
    _auth_keys = {env_key for _, env_key in _ENV_AUTH_MAP}
    values: dict[str, str] = {}
    if not os.path.isfile(_ENV_PATH):
        return values
    try:
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, _, v = stripped.partition("=")
                k = k.strip()
                v = v.strip()
                if k in _auth_keys and v:
                    values[k] = v
    except OSError as e:
        _logger.warning("[SecretMigration] .env 読み込み失敗: %s", type(e).__name__)
    return values


def _migrate_json_file(
    path: str,
    secret_type: str,
    profile_id: str,
    save_secret,
) -> str:
    """
    JSON ファイルを読み、妥当性チェックしてから DB に保存する。
    ファイル内容をログに出さない。
    """
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        json.loads(raw)  # JSON として妥当かチェックするのみ
    except OSError as e:
        _logger.error(
            "[SecretMigration] %s の読み込み失敗: %s",
            os.path.basename(path), type(e).__name__,
        )
        return _STATUS_ERROR
    except json.JSONDecodeError as e:
        _logger.error(
            "[SecretMigration] %s の JSON 解析失敗: %s",
            os.path.basename(path), type(e).__name__,
        )
        return _STATUS_ERROR

    try:
        save_secret(secret_type, raw, profile_id=profile_id)
        _logger.info(
            "[SecretMigration] %s を DB に移行しました (%s)",
            secret_type, os.path.basename(path),
        )
        return _STATUS_MIGRATED
    except Exception as e:
        _logger.error(
            "[SecretMigration] %s の DB 保存失敗: %s",
            secret_type, type(e).__name__,
        )
        return _STATUS_ERROR
