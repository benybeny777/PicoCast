"""
core/secret_store.py のユニットテスト。

- DB の暗号化エントリに平文が含まれないことを確認
- nonce が保存ごとに変わることを確認
- master key がない場合は fail closed
- 壊れた encrypted_value は SecretDecryptionError
- has_secret は復号せず True/False を返す
外部API実通信なし。DPAPI はモック。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_secret_store(tmp_path, monkeypatch):
    """
    secret_store モジュールを一時ディレクトリへリダイレクトし、
    固定の 32 byte マスターキーを使うようにパッチする。
    """
    import importlib
    import core.secret_store as ss

    _fixed_key = b"\x01" * 32

    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(ss, "_MASTER_KEY_PATH", str(tmp_path / "secret_master.key"))
    monkeypatch.setattr(ss, "_get_master_key", lambda: _fixed_key)

    yield ss


# ── 基本 CRUD ─────────────────────────────────────────────────────────────────

def test_save_and_load(tmp_secret_store):
    """シークレットを保存して復号できる。"""
    ss = tmp_secret_store
    ss.save_secret("google_api_key", "AIzaTestKey123")
    assert ss.load_secret("google_api_key") == "AIzaTestKey123"


def test_encrypted_value_does_not_contain_plaintext(tmp_secret_store):
    """encrypted_value に平文が含まれない。"""
    ss = tmp_secret_store
    ss.save_secret("openai_api_key", "sk-supersecret")

    conn = sqlite3.connect(ss._DB_PATH)
    row = conn.execute(
        "SELECT encrypted_value FROM encrypted_secrets WHERE secret_type='openai_api_key'"
    ).fetchone()
    conn.close()

    assert row is not None
    raw_blob = bytes(row[0])
    assert b"sk-supersecret" not in raw_blob


def test_nonce_changes_per_save(tmp_secret_store):
    """同じ値を2回保存しても nonce が変わる。"""
    ss = tmp_secret_store
    ss.save_secret("hf_token", "hf_xyz")

    conn = sqlite3.connect(ss._DB_PATH)
    nonce1 = bytes(
        conn.execute(
            "SELECT nonce FROM encrypted_secrets WHERE secret_type='hf_token'"
        ).fetchone()[0]
    )
    conn.close()

    ss.save_secret("hf_token", "hf_xyz")

    conn = sqlite3.connect(ss._DB_PATH)
    nonce2 = bytes(
        conn.execute(
            "SELECT nonce FROM encrypted_secrets WHERE secret_type='hf_token'"
        ).fetchone()[0]
    )
    conn.close()

    assert nonce1 != nonce2


def test_has_secret_without_decryption(tmp_secret_store):
    """has_secret は DB 存在チェックのみで True/False を返す。"""
    ss = tmp_secret_store
    assert not ss.has_secret("google_api_key")
    ss.save_secret("google_api_key", "AIzaTestKey")
    assert ss.has_secret("google_api_key")


def test_delete_secret(tmp_secret_store):
    """delete_secret 後は has_secret が False になる。"""
    ss = tmp_secret_store
    ss.save_secret("hf_token", "hf_del_test")
    assert ss.has_secret("hf_token")
    ss.delete_secret("hf_token")
    assert not ss.has_secret("hf_token")


def test_list_secret_status(tmp_secret_store):
    """list_secret_status は全 secret_type の登録状態 dict を返す。"""
    ss = tmp_secret_store
    ss.save_secret("google_api_key", "AIzaXxx")
    status = ss.list_secret_status()
    assert status["google_api_key"] is True
    assert status["openai_api_key"] is False


# ── エラーケース ──────────────────────────────────────────────────────────────

def test_load_secret_not_found_raises(tmp_secret_store):
    """未登録の secret を load_secret すると SecretNotFoundError。"""
    ss = tmp_secret_store
    with pytest.raises(ss.SecretNotFoundError):
        ss.load_secret("google_api_key")


def test_corrupted_blob_raises_decryption_error(tmp_secret_store):
    """encrypted_value を破壊すると SecretDecryptionError。"""
    ss = tmp_secret_store
    ss.save_secret("hf_token", "hf_corrupt")

    conn = sqlite3.connect(ss._DB_PATH)
    conn.execute(
        "UPDATE encrypted_secrets SET encrypted_value=? WHERE secret_type='hf_token'",
        (b"\x00" * 32,),
    )
    conn.commit()
    conn.close()

    with pytest.raises(ss.SecretDecryptionError):
        ss.load_secret("hf_token")


def test_master_key_failure_raises(tmp_secret_store, monkeypatch):
    """master key が取得できない場合は MasterKeyError (fail closed)。"""
    ss = tmp_secret_store

    def _fail():
        raise ss.MasterKeyError("テスト用マスターキー取得失敗")

    monkeypatch.setattr(ss, "_get_master_key", _fail)
    with pytest.raises(ss.MasterKeyError):
        ss.save_secret("openai_api_key", "sk-test")


# ── profile_id ────────────────────────────────────────────────────────────────

def test_profile_id_isolation(tmp_secret_store):
    """異なる profile_id のシークレットは互いに干渉しない。"""
    ss = tmp_secret_store
    ss.save_secret("youtube_upload_token", "token_food", profile_id="food_trivia")
    ss.save_secret("youtube_upload_token", "token_urban", profile_id="urban_legend")

    assert ss.load_secret("youtube_upload_token", profile_id="food_trivia") == "token_food"
    assert ss.load_secret("youtube_upload_token", profile_id="urban_legend") == "token_urban"
    assert not ss.has_secret("youtube_upload_token", profile_id="default")


# ── パスフレーズ再暗号化（クロスPC） ──────────────────────────────────────────

def test_passphrase_export_import_roundtrip_across_master_keys(tmp_secret_store, monkeypatch):
    """別PC（別マスターキー）でも同じパスフレーズで認証情報を復元できる。"""
    ss = tmp_secret_store
    # PC-A のマスターキーで保存
    ss.save_secret("google_api_key", "AIza-A", profile_id="chan_a")
    ss.save_secret("youtube_upload_token", "tok-A", profile_id="chan_a")

    blob = ss.export_secrets_with_passphrase("correct horse battery")

    # 別PCを模す: 全シークレットを消し、マスターキーを別物に差し替える
    ss.delete_secret("google_api_key", profile_id="chan_a")
    ss.delete_secret("youtube_upload_token", profile_id="chan_a")
    monkeypatch.setattr(ss, "_get_master_key", lambda: b"\x02" * 32)

    count = ss.import_secrets_with_passphrase(blob, "correct horse battery")
    assert count == 2
    assert ss.load_secret("google_api_key", profile_id="chan_a") == "AIza-A"
    assert ss.load_secret("youtube_upload_token", profile_id="chan_a") == "tok-A"


def test_passphrase_import_wrong_passphrase_fails(tmp_secret_store):
    """誤ったパスフレーズでは復号できない。"""
    ss = tmp_secret_store
    ss.save_secret("google_api_key", "AIza-secret")
    blob = ss.export_secrets_with_passphrase("right-pass")
    with pytest.raises(ss.SecretDecryptionError):
        ss.import_secrets_with_passphrase(blob, "wrong-pass")


# ── スレッドセーフ ────────────────────────────────────────────────────────────

def test_concurrent_save_load(tmp_secret_store):
    """並列スレッドから同時に save/load しても例外が出ない。"""
    ss = tmp_secret_store
    errors: list[Exception] = []

    def _worker(i: int):
        try:
            ss.save_secret("google_api_key", f"AIzaKey{i}", profile_id=f"p{i}")
            val = ss.load_secret("google_api_key", profile_id=f"p{i}")
            assert val == f"AIzaKey{i}"
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"並列実行エラー: {errors}"
