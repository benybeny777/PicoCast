"""製品版バックアップ/復元サービス。"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from core.runtime_env import app_base_dir as _app_base_dir
_ROOT = Path(_app_base_dir())  # 永続データの基準。exe(onefile)では exe と同じフォルダ
_BACKUP_DIR = _ROOT / "output" / "_backups"
_SETTINGS_DB = _ROOT / "data" / "settings.db"
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _is_sqlite_file(path: Path) -> bool:
    if not path.is_file():
        return False
    with open(path, "rb") as fh:
        return fh.read(16) == _SQLITE_MAGIC


def _checkpoint_sqlite(path: Path) -> None:
    """WALモードのDBを main ファイルへチェックポイントし、ファイルコピーで取りこぼさないようにする。

    SQLite以外のファイル（テスト用プレースホルダ等）はチェックポイント対象外。
    DBエラーは握り潰さず上位へ伝播させる。
    """
    if not _is_sqlite_file(path):
        return
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _remove_wal_siblings(target: Path) -> None:
    """復元後、古い -wal / -shm を消して main ファイルへの不整合な再生を防ぐ。"""
    for suffix in ("-wal", "-shm"):
        sibling = target.with_name(target.name + suffix)
        if sibling.exists():
            sibling.unlink()


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _settings_schema_snapshot() -> dict:
    if not _SETTINGS_DB.exists():
        return {}
    with sqlite3.connect(_SETTINGS_DB) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {"tables": tables}


_SECRETS_EXPORT_NAME = "secrets_export.enc"


def create_backup(passphrase: str = "") -> dict[str, str]:
    """settings.db と profile 別 metadata.db をZIP化する。

    passphrase を指定すると、認証情報（encrypted_secrets）をそのパスフレーズで
    再暗号化したエクスポートを同梱し、別PCでも同じパスフレーズで復元できるようにする。
    passphrase 未指定時は従来どおり同一PC専用（認証情報は別PCで復号不可）。
    """
    from core.channel_profile import list_profiles
    from core.metadata_db import SCHEMA_VERSION

    passphrase = (passphrase or "").strip()
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = _BACKUP_DIR / f"backup_{_stamp()}.zip"
    secrets_included = False
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if _SETTINGS_DB.exists():
            _checkpoint_sqlite(_SETTINGS_DB)
            zf.write(_SETTINGS_DB, "data/settings.db")
        for profile in list_profiles():
            meta = Path(profile.output_root_abs) / "000_data" / "metadata.db"
            if meta.exists():
                _checkpoint_sqlite(meta)
                zf.write(meta, f"output/{profile.profile_id}/000_data/metadata.db")
        if passphrase:
            from core.secret_store import export_secrets_with_passphrase
            zf.writestr(_SECRETS_EXPORT_NAME, export_secrets_with_passphrase(passphrase))
            secrets_included = True
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata_schema_version": SCHEMA_VERSION,
            "settings_schema": _settings_schema_snapshot(),
            "secrets_export_included": secrets_included,
            "encrypted_secrets_note": (
                "認証情報をパスフレーズで再暗号化して同梱しました。別PCでは同じパスフレーズを入力して復元してください。"
                if secrets_included
                else "encrypted_secrets は同一PCのマスターキーでのみ復号可能です。別PCでは認証情報を再登録してください。"
            ),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"path": str(path), "filename": path.name, "secrets_included": secrets_included}


def _pre_restore_backup() -> Path:
    dest = _BACKUP_DIR / f"pre_restore_{_stamp()}"
    dest.mkdir(parents=True, exist_ok=False)
    _copy_if_exists(_SETTINGS_DB, dest / "data" / "settings.db")
    from core.channel_profile import list_profiles
    for profile in list_profiles():
        meta = Path(profile.output_root_abs) / "000_data" / "metadata.db"
        _copy_if_exists(meta, dest / "output" / profile.profile_id / "000_data" / "metadata.db")
    return dest


def restore_backup(backup_path: str, *, confirmed: bool = False, passphrase: str = "") -> dict:
    if not confirmed:
        raise RuntimeError("confirmed=true が必要です")
    src = Path(backup_path).resolve()
    if not src.is_file() or src.suffix.lower() != ".zip":
        raise FileNotFoundError("バックアップZIPが見つかりません")
    if _ROOT not in src.parents and _BACKUP_DIR not in src.parents:
        raise RuntimeError("復元できるのはプロジェクト配下のバックアップZIPだけです")

    passphrase = (passphrase or "").strip()
    secrets_imported = 0
    with zipfile.ZipFile(src, "r") as zf:
        names = set(zf.namelist())
        if "manifest.json" not in names:
            raise RuntimeError("manifest.json がないため復元を中止しました")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        from core.metadata_db import SCHEMA_VERSION
        if int(manifest.get("metadata_schema_version", -1)) > SCHEMA_VERSION:
            raise RuntimeError("バックアップのDBスキーマが新しすぎるため復元を中止しました")

        has_secrets_export = _SECRETS_EXPORT_NAME in names
        if has_secrets_export and not passphrase:
            raise RuntimeError("このバックアップには暗号化された認証情報が含まれます。復元にはパスフレーズが必要です。")

        pre = _pre_restore_backup()
        for name in names:
            if name.endswith("/") or name == "manifest.json":
                continue
            if not (name == "data/settings.db" or (name.startswith("output/") and name.endswith("/000_data/metadata.db"))):
                continue
            target = (_ROOT / name).resolve()
            if _ROOT not in target.parents:
                raise RuntimeError("不正な復元パスを検出したため中止しました")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as source, open(target, "wb") as dest:
                shutil.copyfileobj(source, dest)
            # 復元した main ファイルに古い WAL が再生されないよう -wal / -shm を除去する
            _remove_wal_siblings(target)

        # settings.db 復元後に、同梱の認証情報を「この PC のマスターキー」で保存し直す。
        # これで別PCのマスターキーで暗号化された encrypted_secrets を上書きし、クロスPC復元を成立させる。
        if has_secrets_export and passphrase:
            from core.secret_store import import_secrets_with_passphrase
            secrets_imported = import_secrets_with_passphrase(zf.read(_SECRETS_EXPORT_NAME), passphrase)
    return {
        "restored": str(src),
        "pre_restore_backup": str(pre),
        "secrets_imported": secrets_imported,
        "note": "復元を反映するためアプリの再起動を推奨します。",
    }
