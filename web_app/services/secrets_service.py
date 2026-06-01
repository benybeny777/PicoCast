"""
認証情報管理サービス。

APIキー・OAuthトークン・client_secrets を DB（encrypted_secrets テーブル）へ
暗号化保存する。値はレスポンス・ログに一切含めない。
"""
import json
import logging
import os

_logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_ALLOWED_API_KEY_TYPES = {"google_api_key", "openai_api_key", "hf_token"}
_ALLOWED_YOUTUBE_TYPES = {
    "youtube_client_secrets",
    "youtube_upload_token",
    "youtube_analytics_token",
}


def _resolve_profile_id(profile_id: str | None = None) -> str:
    if profile_id:
        return profile_id
    try:
        from core.channel_profile import get_active_profile
        profile = get_active_profile()
        if profile is not None:
            return profile.profile_id
    except Exception as e:
        _logger.warning("[SecretsService] active profile 取得失敗: %s", e)
    return "default"


def save_api_key(secret_type: str, value: str, profile_id: str | None = None) -> list[str]:
    """
    APIキー（google_api_key / openai_api_key / hf_token）を DB へ保存する。
    値をレスポンスやログに含めない。
    """
    errors: list[str] = []
    if secret_type not in _ALLOWED_API_KEY_TYPES:
        errors.append(f"不正なキー種別: {secret_type}")
    value = value.strip()
    if not value:
        errors.append("値が空です")
    if "\n" in value or "\r" in value:
        errors.append("改行は使用できません")
    if errors:
        return errors

    pid = _resolve_profile_id(profile_id)
    from core.secret_store import save_secret
    save_secret(secret_type, value, profile_id=pid)
    _logger.info("[SecretsService] %s を DB に保存しました (profile=%s)", secret_type, pid)
    return []


def save_secrets(updates: dict[str, str], profile_id: str | None = None) -> list[str]:
    """
    複数の APIキーをまとめて保存する。
    空文字は「変更なし」として無視する。
    """
    errors: list[str] = []
    _env_to_secret = {
        "GOOGLE_API_KEY": "google_api_key",
        "OPENAI_API_KEY": "openai_api_key",
        "HF_TOKEN": "hf_token",
    }
    for raw_key, value in updates.items():
        # ENV_KEY 形式でも secret_type 形式でも受け付ける
        secret_type = _env_to_secret.get(raw_key, raw_key)
        if not value.strip():
            continue
        errs = save_api_key(secret_type, value, profile_id=profile_id)
        errors.extend(errs)
    return errors


def save_client_secrets(json_text: str, profile_id: str | None = None) -> list[str]:
    """
    YouTube client_secrets の JSON テキストを DB へ保存する。
    JSON 妥当性チェックしてから保存する。値をログに出さない。
    """
    errors: list[str] = []
    json_text = json_text.strip()
    if not json_text:
        errors.append("JSON が空です")
        return errors
    try:
        json.loads(json_text)
    except json.JSONDecodeError as e:
        errors.append(f"JSON 解析エラー: {e.msg}")
        return errors

    pid = _resolve_profile_id(profile_id)
    from core.secret_store import save_secret
    save_secret("youtube_client_secrets", json_text, profile_id=pid)
    _logger.info("[SecretsService] youtube_client_secrets を DB に保存しました (profile=%s)", pid)
    return []


def delete_api_key(secret_type: str, profile_id: str | None = None) -> list[str]:
    """APIキーを DB から削除する。"""
    errors: list[str] = []
    if secret_type not in _ALLOWED_API_KEY_TYPES:
        errors.append(f"不正なキー種別: {secret_type}")
        return errors
    pid = _resolve_profile_id(profile_id)
    from core.secret_store import delete_secret
    delete_secret(secret_type, profile_id=pid)
    _logger.info("[SecretsService] %s を DB から削除しました (profile=%s)", secret_type, pid)
    return []


def delete_youtube_secret(secret_type: str, profile_id: str | None = None) -> list[str]:
    """YouTube 関連シークレットを DB から削除する。"""
    errors: list[str] = []
    if secret_type not in _ALLOWED_YOUTUBE_TYPES:
        errors.append(f"不正なキー種別: {secret_type}")
        return errors
    pid = _resolve_profile_id(profile_id)
    from core.secret_store import delete_secret
    delete_secret(secret_type, profile_id=pid)
    _logger.info("[SecretsService] %s を DB から削除しました (profile=%s)", secret_type, pid)
    return []


def get_secret_status(profile_id: str | None = None) -> dict[str, bool]:
    """
    各シークレットの登録状態を返す（値は返さない）。
    """
    from core.secret_store import list_secret_status
    return list_secret_status(profile_id=_resolve_profile_id(profile_id))


def get_legacy_file_status() -> dict[str, bool]:
    """
    旧認証ファイルの存在状態を返す（DB 移行状態の参考情報）。
    ファイルの中身は返さない。
    """
    files = [
        (".env",                 "env"),
        ("client_secrets.json",  "client_secrets_json"),
        ("token.json",           "token_json"),
        ("token_analytics.json", "token_analytics_json"),
    ]
    return {
        key: os.path.isfile(os.path.join(_ROOT, filename))
        for filename, key in files
    }


def delete_legacy_file(filename: str, confirmed: bool = False) -> dict:
    """
    旧認証ファイルを削除する。
    条件:
    - confirmed=True 必須
    - DB への移行済みであること（未移行値がある場合は拒否）
    """
    _allowed = {".env", "client_secrets.json", "token.json", "token_analytics.json"}
    if filename not in _allowed:
        return {"ok": False, "error": f"削除対象外のファイルです: {filename}"}
    if not confirmed:
        return {"ok": False, "error": "confirmed=true が必要です"}

    # 未移行チェック
    path = os.path.join(_ROOT, filename)
    if not os.path.isfile(path):
        return {"ok": False, "error": "ファイルが存在しません"}

    _check_result = _check_migration_before_delete(filename)
    if not _check_result["ok"]:
        return _check_result

    try:
        os.remove(path)
        _logger.info("[SecretsService] 旧認証ファイルを削除しました: %s", filename)
        return {"ok": True, "deleted": filename}
    except OSError as e:
        return {"ok": False, "error": f"削除失敗: {type(e).__name__}"}


def _check_migration_before_delete(filename: str) -> dict:
    """
    削除前に DB への移行状態を確認する。
    未移行の値がある場合は削除を拒否する。
    """
    from core.secret_store import has_secret
    profile_id = _resolve_profile_id()

    if filename == ".env":
        pass  # .env への auth キー書き込みは廃止済み

    elif filename == "client_secrets.json":
        if not has_secret("youtube_client_secrets", profile_id=profile_id):
            return {"ok": False, "error": "youtube_client_secrets が DB 未移行です"}

    elif filename == "token.json":
        if not has_secret("youtube_upload_token", profile_id=profile_id):
            return {"ok": False, "error": "youtube_upload_token が DB 未移行です"}

    elif filename == "token_analytics.json":
        if not has_secret("youtube_analytics_token", profile_id=profile_id):
            return {"ok": False, "error": "youtube_analytics_token が DB 未移行です"}

    return {"ok": True}


