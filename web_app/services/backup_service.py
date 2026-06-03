"""製品版バックアップ/復元サービス。"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BACKUP_DIR = _ROOT / "output" / "_backups"
_SETTINGS_DB = _ROOT / "data" / "settings.db"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def create_backup() -> dict[str, str]:
    from core.channel_profile import list_profiles
    from core.metadata_db import SCHEMA_VERSION

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = _BACKUP_DIR / f"backup_{_stamp()}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if _SETTINGS_DB.exists():
            zf.write(_SETTINGS_DB, "data/settings.db")
        for profile in list_profiles():
            meta = Path(profile.output_root_abs) / "000_data" / "metadata.db"
            if meta.exists():
                zf.write(meta, f"output/{profile.profile_id}/000_data/metadata.db")
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata_schema_version": SCHEMA_VERSION,
            "settings_schema": _settings_schema_snapshot(),
            "encrypted_secrets_note": "encrypted_secrets は同一PCのマスターキーでのみ復号可能です。別PCでは認証情報を再登録してください。",
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"path": str(path), "filename": path.name}


def _pre_restore_backup() -> Path:
    dest = _BACKUP_DIR / f"pre_restore_{_stamp()}"
    dest.mkdir(parents=True, exist_ok=False)
    _copy_if_exists(_SETTINGS_DB, dest / "data" / "settings.db")
    from core.channel_profile import list_profiles
    for profile in list_profiles():
        meta = Path(profile.output_root_abs) / "000_data" / "metadata.db"
        _copy_if_exists(meta, dest / "output" / profile.profile_id / "000_data" / "metadata.db")
    return dest


def restore_backup(backup_path: str, *, confirmed: bool = False) -> dict:
    if not confirmed:
        raise RuntimeError("confirmed=true が必要です")
    src = Path(backup_path).resolve()
    if not src.is_file() or src.suffix.lower() != ".zip":
        raise FileNotFoundError("バックアップZIPが見つかりません")
    if _ROOT not in src.parents and _BACKUP_DIR not in src.parents:
        raise RuntimeError("復元できるのはプロジェクト配下のバックアップZIPだけです")

    with zipfile.ZipFile(src, "r") as zf:
        names = set(zf.namelist())
        if "manifest.json" not in names:
            raise RuntimeError("manifest.json がないため復元を中止しました")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        from core.metadata_db import SCHEMA_VERSION
        if int(manifest.get("metadata_schema_version", -1)) > SCHEMA_VERSION:
            raise RuntimeError("バックアップのDBスキーマが新しすぎるため復元を中止しました")

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
    return {"restored": str(src), "pre_restore_backup": str(pre)}
