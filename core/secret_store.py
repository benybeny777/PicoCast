"""
暗号化シークレットストア。

認証情報（APIキー・OAuthトークン・client_secrets）を AES-GCM で暗号化して
data/settings.db の encrypted_secrets テーブルに保存する。

マスターキー管理:
  Windows : DPAPI (CryptProtectData) で保護した data/secret_master.key
  macOS/Linux : keyring または NVF_MASTER_KEY 環境変数

ルール:
- load_secret() 以外で復号しない
- 復号した値をログに出さない
- 例外メッセージに秘密値を含めない
- OAuth/API 呼び出し直前にだけ復号する
- master key が取得できない場合は fail closed
"""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

# プロジェクトルートは core/ の1階層上
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_ROOT, "data", "settings.db")
_MASTER_KEY_PATH = os.path.join(_ROOT, "data", "secret_master.key")

_KEY_VERSION = 1
_lock = threading.Lock()

# 管理する secret_type の一覧
KNOWN_SECRET_TYPES: list[str] = [
    "google_api_key",
    "openai_api_key",
    "hf_token",
    "youtube_client_secrets",
    "youtube_upload_token",
    "youtube_analytics_token",
]


# ─────────────────────────────────────────────────────────────────────────────
# 公開例外
# ─────────────────────────────────────────────────────────────────────────────

class SecretError(Exception):
    """シークレット操作の基底例外。"""


class SecretNotFoundError(SecretError):
    """シークレットが DB に存在しない。"""


class SecretDecryptionError(SecretError):
    """復号に失敗した（master key 不一致 / データ破損）。"""


class MasterKeyError(SecretError):
    """master key の取得または生成に失敗した。"""


# ─────────────────────────────────────────────────────────────────────────────
# マスターキー管理
# ─────────────────────────────────────────────────────────────────────────────

def _get_master_key() -> bytes:
    """
    マスターキー（32 byte）を取得する。
    取得できない場合は MasterKeyError を送出する（fail closed）。
    NVF_MASTER_KEY を含む環境変数をログに出さない。
    """
    if sys.platform == "win32":
        return _get_master_key_windows()
    return _get_master_key_unix()


def _get_master_key_windows() -> bytes:
    """
    Windows DPAPI でマスターキーを取得する。
    data/secret_master.key が存在しなければ新規生成して保存する。
    """
    if not os.path.isfile(_MASTER_KEY_PATH):
        _generate_and_save_master_key_windows()
    with open(_MASTER_KEY_PATH, "rb") as f:
        encrypted = f.read()
    return _dpapi_unprotect(encrypted)


def _generate_and_save_master_key_windows() -> None:
    """32 byte ランダムキーを生成し DPAPI で保護して保存する。"""
    key = secrets.token_bytes(32)
    encrypted = _dpapi_protect(key)
    os.makedirs(os.path.dirname(_MASTER_KEY_PATH), exist_ok=True)
    with open(_MASTER_KEY_PATH, "wb") as f:
        f.write(encrypted)
    _logger.info("[SecretStore] マスターキーを新規生成しました: %s", _MASTER_KEY_PATH)


def _dpapi_protect(data: bytes) -> bytes:
    """Windows DPAPI (CryptProtectData) で data を暗号化する。"""
    import ctypes
    import ctypes.wintypes as w

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = _BLOB(
        len(data),
        ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = _BLOB()
    res = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not res:
        raise MasterKeyError(f"CryptProtectData 失敗 (error={ctypes.GetLastError()})")
    protected = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return protected


def _dpapi_unprotect(data: bytes) -> bytes:
    """Windows DPAPI (CryptUnprotectData) で data を復号する。"""
    import ctypes
    import ctypes.wintypes as w

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", w.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = _BLOB(
        len(data),
        ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = _BLOB()
    res = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not res:
        raise MasterKeyError(f"CryptUnprotectData 失敗 (error={ctypes.GetLastError()})")
    decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return decrypted


def _get_master_key_unix() -> bytes:
    """
    macOS/Linux: keyring → NVF_MASTER_KEY 環境変数 の順で試みる。
    NVF_MASTER_KEY の値をログに出さない。
    """
    try:
        import keyring
        key_hex = keyring.get_password("nvf_secret_store", "master_key")
        if key_hex:
            return bytes.fromhex(key_hex)
        new_key = secrets.token_bytes(32)
        keyring.set_password("nvf_secret_store", "master_key", new_key.hex())
        _logger.info("[SecretStore] keyring にマスターキーを新規生成しました")
        return new_key
    except Exception:
        pass

    env_key = os.environ.get("NVF_MASTER_KEY", "")
    if env_key:
        try:
            return bytes.fromhex(env_key)
        except ValueError:
            raise MasterKeyError("NVF_MASTER_KEY が不正な hex 文字列です")

    raise MasterKeyError(
        "マスターキーを取得できません。"
        "keyring をインストールするか、NVF_MASTER_KEY 環境変数（32 byte hex）を設定してください。"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AES-GCM 暗号化 / 復号
# ─────────────────────────────────────────────────────────────────────────────

def _encrypt(plaintext: str, key: bytes) -> tuple[bytes, bytes]:
    """AES-GCM で暗号化。(ciphertext, nonce) を返す。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)  # AES-GCM 推奨 nonce サイズ
    aes = AESGCM(key)
    ciphertext = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return ciphertext, nonce


def _decrypt(ciphertext: bytes, nonce: bytes, key: bytes) -> str:
    """AES-GCM で復号する。秘密値は呼び出し元で適切に扱うこと。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
    try:
        aes = AESGCM(key)
        plaintext_bytes = aes.decrypt(nonce, ciphertext, None)
        return plaintext_bytes.decode("utf-8")
    except InvalidTag:
        raise SecretDecryptionError(
            "復号失敗: データが破損しているかマスターキーが異なります"
        )


# ─────────────────────────────────────────────────────────────────────────────
# DB 操作
# ─────────────────────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_table(conn)
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encrypted_secrets (
            secret_id       TEXT PRIMARY KEY,
            profile_id      TEXT NOT NULL DEFAULT 'default',
            secret_type     TEXT NOT NULL,
            encrypted_value BLOB NOT NULL,
            nonce           BLOB NOT NULL,
            salt            BLOB,
            key_version     INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            UNIQUE(profile_id, secret_type)
        )
    """)
    conn.commit()


def _profile_id(profile_id: str | None) -> str:
    return profile_id or "default"


def current_profile_id_or_default() -> str:
    """active profile があればその profile_id、未設定なら default を返す。"""
    try:
        from core.channel_profile import get_active_profile
        profile = get_active_profile()
        if profile is not None:
            return profile.profile_id
    except Exception as e:
        _logger.warning("[SecretStore] active profile 取得失敗: %s", e)
    return "default"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_secret_id(secret_type: str, profile_id: str) -> str:
    import hashlib
    raw = f"{profile_id}:{secret_type}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────────────────────────────────────

def save_secret(secret_type: str, value: str, profile_id: str | None = None) -> None:
    """
    シークレットを AES-GCM で暗号化して DB に保存する。
    既存の値は上書きする。値をログに出さない。
    """
    pid = _profile_id(profile_id)
    key = _get_master_key()
    encrypted_value, nonce = _encrypt(value, key)
    secret_id = _make_secret_id(secret_type, pid)
    now = _now_iso()

    with _lock:
        conn = _open_db()
        try:
            conn.execute(
                """
                INSERT INTO encrypted_secrets
                    (secret_id, profile_id, secret_type, encrypted_value, nonce,
                     key_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, secret_type) DO UPDATE SET
                    secret_id       = excluded.secret_id,
                    encrypted_value = excluded.encrypted_value,
                    nonce           = excluded.nonce,
                    key_version     = excluded.key_version,
                    updated_at      = excluded.updated_at
                """,
                (secret_id, pid, secret_type, encrypted_value, nonce,
                 _KEY_VERSION, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    _logger.debug("[SecretStore] 保存完了: type=%s profile=%s", secret_type, pid)


def load_secret(secret_type: str, profile_id: str | None = None) -> str:
    """
    シークレットを復号して返す。
    - 未登録: SecretNotFoundError
    - 復号失敗: SecretDecryptionError
    - master key 取得失敗: MasterKeyError
    返値をログに出さないこと。
    """
    pid = _profile_id(profile_id)
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT encrypted_value, nonce FROM encrypted_secrets"
                " WHERE profile_id=? AND secret_type=?",
                (pid, secret_type),
            ).fetchone()
        finally:
            conn.close()

    if row is None:
        raise SecretNotFoundError(
            f"シークレット未登録: type={secret_type} profile={pid}"
        )

    key = _get_master_key()
    return _decrypt(bytes(row["encrypted_value"]), bytes(row["nonce"]), key)


def delete_secret(secret_type: str, profile_id: str | None = None) -> None:
    """シークレットを DB から削除する。"""
    pid = _profile_id(profile_id)
    with _lock:
        conn = _open_db()
        try:
            conn.execute(
                "DELETE FROM encrypted_secrets WHERE profile_id=? AND secret_type=?",
                (pid, secret_type),
            )
            conn.commit()
        finally:
            conn.close()
    _logger.debug("[SecretStore] 削除完了: type=%s profile=%s", secret_type, pid)


def has_secret(secret_type: str, profile_id: str | None = None) -> bool:
    """
    DB に暗号化エントリが存在するかを確認する（復号しない）。
    """
    pid = _profile_id(profile_id)
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT 1 FROM encrypted_secrets WHERE profile_id=? AND secret_type=?",
                (pid, secret_type),
            ).fetchone()
        finally:
            conn.close()
    return row is not None


def list_secret_status(profile_id: str | None = None) -> dict[str, bool]:
    """
    各 secret_type の登録状態を返す（値は一切返さない）。
    """
    pid = _profile_id(profile_id)
    with _lock:
        conn = _open_db()
        try:
            rows = conn.execute(
                "SELECT secret_type FROM encrypted_secrets WHERE profile_id=?",
                (pid,),
            ).fetchall()
        finally:
            conn.close()
    registered = {r["secret_type"] for r in rows}
    return {t: (t in registered) for t in KNOWN_SECRET_TYPES}
