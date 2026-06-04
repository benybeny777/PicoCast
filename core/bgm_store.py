"""
BGMアセット管理。
管理情報は data/settings.db の bgm_assets を正本とし、実ファイルは profile 別 output 配下へ保存する。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime
from typing import Any

from config import config
from core.channel_profile import get_profile, require_active_profile

from core.runtime_env import app_base_dir as _app_base_dir
_ROOT = _app_base_dir()  # 永続データ(settings.db)の基準。exe(onefile)では exe と同じフォルダ
_DB_PATH = os.path.join(_ROOT, "data", "settings.db")
_ALLOWED_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
# BGM 実ファイルの既定保存先（プロファイルルート相対）
_BGM_REL_DIR = os.path.join("000_assets", "bgm")
_MIGRATED_REL = False


def _to_rel(profile, path: str) -> str:
    """profile ルート相対パスへ正規化して保存用に返す。

    output ディレクトリごと移動しても壊れないよう、DB には絶対パスを保存しない。
    profile ルート外の絶対パス（旧プロファイルの残骸等）は basename を
    000_assets/bgm 配下とみなす。
    """
    p = str(path or "")
    if not p:
        return p
    if not os.path.isabs(p):
        return p.replace("\\", "/")
    rel = None
    try:
        rel = os.path.relpath(p, profile.output_root_abs)
    except ValueError:
        rel = None  # 別ドライブ等
    if rel is None or rel.startswith(".."):
        rel = os.path.join(_BGM_REL_DIR, os.path.basename(p))
    return rel.replace("\\", "/")


def _to_abs(profile_id: str, stored: str) -> str:
    """DB 保存値（相対）を現プロファイルの絶対パスへ解決する。"""
    p = str(stored or "")
    if not p:
        return p
    if os.path.isabs(p):
        return p  # 移行前の旧絶対パス（マイグレーションで相対化される）
    prof = get_profile(profile_id)
    if prof is None:
        return p
    return os.path.normpath(os.path.join(prof.output_root_abs, p))


def _resolve_row(row) -> dict[str, Any]:
    """DB 行を dict 化し file_path を絶対パスへ解決して返す（消費側は絶対前提のまま）。"""
    data = dict(row)
    data["file_path"] = _to_abs(data.get("profile_id"), data.get("file_path"))
    return data


def _migrate_paths_to_relative() -> None:
    """既存の絶対 file_path を一度だけプロファイル相対へ書き換える。"""
    global _MIGRATED_REL
    if _MIGRATED_REL:
        return
    _MIGRATED_REL = True
    try:
        with _open() as conn:
            rows = conn.execute("SELECT bgm_id, profile_id, file_path FROM bgm_assets").fetchall()
        updates = []
        for r in rows:
            fp = r["file_path"]
            if not fp or not os.path.isabs(fp):
                continue
            prof = get_profile(r["profile_id"])
            if prof is None:
                continue  # 存在しないプロファイルの孤立行は触らない（別途掃除）
            updates.append((_to_rel(prof, fp), r["bgm_id"]))
        if updates:
            with _open() as conn:
                conn.executemany("UPDATE bgm_assets SET file_path=? WHERE bgm_id=?", updates)
                conn.commit()
    except Exception:
        _MIGRATED_REL = False  # 次回再試行（フォールバックではなく一時失敗の再試行）
        raise


def _open() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bgm_assets (
            bgm_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            default_volume_db REAL NOT NULL,
            loop_enabled INTEGER NOT NULL DEFAULT 1,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            is_default INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            duration_sec REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(profile_id, display_name)
        )
    """)
    conn.commit()
    return conn


def list_bgm_assets(profile_id: str | None = None, include_disabled: bool = False) -> list[dict[str, Any]]:
    profile_id = profile_id or require_active_profile().profile_id
    _migrate_paths_to_relative()
    ensure_legacy_default(profile_id)
    sql = "SELECT * FROM bgm_assets WHERE profile_id=?"
    params: list[Any] = [profile_id]
    if not include_disabled:
        sql += " AND is_enabled=1"
    sql += " ORDER BY is_default DESC, display_name ASC"
    with _open() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_resolve_row(row) for row in rows]


def get_bgm_asset(bgm_id: str, profile_id: str | None = None, *, require_enabled: bool = True) -> dict[str, Any]:
    profile_id = profile_id or require_active_profile().profile_id
    _migrate_paths_to_relative()
    with _open() as conn:
        row = conn.execute(
            "SELECT * FROM bgm_assets WHERE bgm_id=? AND profile_id=?",
            (bgm_id, profile_id),
        ).fetchone()
    if not row:
        raise ValueError("BGMが見つかりません")
    data = _resolve_row(row)
    if require_enabled and not data.get("is_enabled"):
        raise ValueError("無効化済みBGMは使用できません")
    return data


def get_default_bgm(profile_id: str | None = None) -> dict[str, Any] | None:
    profile_id = profile_id or require_active_profile().profile_id
    _migrate_paths_to_relative()
    ensure_legacy_default(profile_id)
    with _open() as conn:
        row = conn.execute(
            "SELECT * FROM bgm_assets WHERE profile_id=? AND is_enabled=1 AND is_default=1 LIMIT 1",
            (profile_id,),
        ).fetchone()
    return _resolve_row(row) if row else None


def create_bgm_asset(
    *,
    display_name: str,
    source_path: str,
    default_volume_db: float,
    loop_enabled: bool,
    is_default: bool,
    note: str = "",
    profile_id: str | None = None,
) -> dict[str, Any]:
    active_profile = require_active_profile()
    profile_id = profile_id or active_profile.profile_id
    profile = active_profile if profile_id == active_profile.profile_id else get_profile(profile_id)
    if profile is None:
        raise ValueError("チャンネルプロファイルが見つかりません")
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("表示名が空です")
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in _ALLOWED_EXTS:
        raise ValueError("対応BGM形式は mp3 / wav / m4a / aac / ogg / flac です")
    if not os.path.isfile(source_path):
        raise FileNotFoundError("BGMファイルが見つかりません")

    duration = _probe_duration(source_path)
    bgm_id = uuid.uuid4().hex
    dest_dir = os.path.join(profile.output_root_abs, "000_assets", "bgm")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, f"{bgm_id}{ext}")
    shutil.copy2(source_path, dest_path)
    now = _now_iso()
    with _open() as conn:
        if is_default:
            conn.execute("UPDATE bgm_assets SET is_default=0 WHERE profile_id=?", (profile_id,))
        conn.execute(
            """
            INSERT INTO bgm_assets(
                bgm_id, profile_id, display_name, file_path, default_volume_db,
                loop_enabled, is_enabled, is_default, note, duration_sec, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                bgm_id, profile_id, display_name, _to_rel(profile, dest_path), float(default_volume_db),
                int(bool(loop_enabled)), 1, int(bool(is_default)), note.strip(),
                duration, now, now,
            ),
        )
        conn.commit()
    return get_bgm_asset(bgm_id, profile_id)


def update_bgm_asset(bgm_id: str, updates: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
    profile_id = profile_id or require_active_profile().profile_id
    current = get_bgm_asset(bgm_id, profile_id, require_enabled=False)
    display_name = str(updates.get("display_name", current["display_name"])).strip()
    if not display_name:
        raise ValueError("表示名が空です")
    default_volume_db = float(updates.get("default_volume_db", current["default_volume_db"]))
    loop_enabled = int(bool(updates.get("loop_enabled", current["loop_enabled"])))
    note = str(updates.get("note", current.get("note") or ""))
    with _open() as conn:
        conn.execute(
            """
            UPDATE bgm_assets
            SET display_name=?, default_volume_db=?, loop_enabled=?, note=?, updated_at=?
            WHERE bgm_id=? AND profile_id=?
            """,
            (display_name, default_volume_db, loop_enabled, note, _now_iso(), bgm_id, profile_id),
        )
        conn.commit()
    return get_bgm_asset(bgm_id, profile_id, require_enabled=False)


def set_default_bgm(bgm_id: str, profile_id: str | None = None) -> dict[str, Any]:
    profile_id = profile_id or require_active_profile().profile_id
    asset = get_bgm_asset(bgm_id, profile_id)
    with _open() as conn:
        conn.execute("UPDATE bgm_assets SET is_default=0 WHERE profile_id=?", (profile_id,))
        conn.execute("UPDATE bgm_assets SET is_default=1, updated_at=? WHERE bgm_id=?", (_now_iso(), bgm_id))
        conn.commit()
    return asset


def disable_bgm_asset(bgm_id: str, confirmed: bool, profile_id: str | None = None) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("confirmed=true が必要です")
    profile_id = profile_id or require_active_profile().profile_id
    get_bgm_asset(bgm_id, profile_id, require_enabled=False)
    with _open() as conn:
        conn.execute(
            "UPDATE bgm_assets SET is_enabled=0, is_default=0, updated_at=? WHERE bgm_id=? AND profile_id=?",
            (_now_iso(), bgm_id, profile_id),
        )
        conn.commit()
    return {"success": True, "bgm_id": bgm_id}


def resolve_bgm_selection(
    *,
    bgm_mode: str | None,
    bgm_id: str | None,
    bgm_volume_db: float | None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    profile_id = profile_id or require_active_profile().profile_id
    ensure_legacy_default(profile_id)
    mode = (bgm_mode or "profile_default").strip() or "profile_default"
    if mode == "none":
        return {"bgm_mode": "none", "bgm_id": None, "bgm_display_name": "BGMなし", "bgm_file_path": "", "bgm_volume_db": None, "bgm_loop_enabled": 0}
    if mode == "profile_default":
        asset = get_default_bgm(profile_id)
        if not asset:
            raise ValueError("チャンネル既定BGMが設定されていません")
    elif mode == "selected":
        if not bgm_id:
            raise ValueError("BGMが選択されていません")
        asset = get_bgm_asset(bgm_id, profile_id)
    else:
        raise ValueError(f"未対応のBGMモードです: {mode}")

    file_path = str(asset["file_path"])
    if not os.path.isfile(file_path):
        # 旧絶対パス等で実体が無い場合、現プロファイルの資産配下をファイル名で探索する
        prof = get_profile(profile_id)
        if prof:
            candidate = os.path.join(prof.output_root_abs, _BGM_REL_DIR, os.path.basename(file_path))
            if os.path.isfile(candidate):
                file_path = candidate
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"BGMファイルが見つかりません: {file_path}")
    volume = float(bgm_volume_db) if bgm_volume_db is not None else float(asset["default_volume_db"])
    return {
        "bgm_mode": mode,
        "bgm_id": asset["bgm_id"],
        "bgm_display_name": asset["display_name"],
        "bgm_file_path": file_path,
        "bgm_volume_db": volume,
        "bgm_loop_enabled": int(bool(asset["loop_enabled"])),
    }


def ensure_legacy_default(profile_id: str | None = None) -> dict[str, Any] | None:
    """旧 BGM_FILE 設定がある環境では、初回だけチャンネル別BGMへ移行する。"""
    profile_id = profile_id or require_active_profile().profile_id
    with _open() as conn:
        existing = conn.execute(
            "SELECT bgm_id FROM bgm_assets WHERE profile_id=? LIMIT 1",
            (profile_id,),
        ).fetchone()
    if existing:
        return None
    legacy_path = str(config.BGM_PATH or "").strip()
    if not legacy_path or not os.path.isfile(legacy_path):
        return None
    display_name = os.path.splitext(os.path.basename(legacy_path))[0]
    return create_bgm_asset(
        display_name=display_name,
        source_path=legacy_path,
        default_volume_db=float(config.NATIVE_BGM_VOLUME_DB),
        loop_enabled=True,
        is_default=True,
        note="旧BGM_FILE設定から自動移行",
        profile_id=profile_id,
    )


def _probe_duration(path: str) -> float | None:
    try:
        result = subprocess.run(
            [_ffprobe_bin(), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", path],
            capture_output=True,
            text=True,
            timeout=config.NATIVE_FFPROBE_TIMEOUT_SEC,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception as e:
        raise RuntimeError(f"BGMの再生時間取得に失敗しました: {e}") from e


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ffprobe_bin() -> str:
    base = os.path.basename(str(config.FFMPEG_BIN or "ffmpeg")).lower()
    if base in ("ffmpeg", "ffmpeg.exe"):
        if os.path.dirname(config.FFMPEG_BIN):
            return os.path.join(
                os.path.dirname(config.FFMPEG_BIN),
                "ffprobe.exe" if base.endswith(".exe") else "ffprobe",
            )
        return "ffprobe.exe" if base.endswith(".exe") else "ffprobe"
    return "ffprobe"
