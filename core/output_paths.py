"""
出力パス管理モジュール。

active channel profile の output_root を基準にすべてのパスを解決する。

ディレクトリ構造（profile 別）:
  output/{profile_id}/
    videos/        ← 動画生成フォルダ（テーマ別サブディレクトリ）
    000_uploaded/  ← アップロード済みアーカイブ
    000_backups/   ← バックアップ
    000_data/      ← metadata.db など

別 profile の output_root へのアクセスは web_app/security.py で拒否される。

使い方:
  from core.output_paths import (
      get_output_videos_dir, get_data_dir,
      get_uploaded_dir, get_backups_dir, get_db_path,
  )
"""
from __future__ import annotations

import os
import shutil

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_ROOT, path)


# ─────────────────────────────────────────────────────────────────────────────
# active profile を使ったパス解決
# ─────────────────────────────────────────────────────────────────────────────

def _get_output_root() -> str:
    """active profile の output_root の絶対パスを返す。"""
    from core.channel_profile import require_active_profile
    return require_active_profile().output_root_abs


def get_output_root() -> str:
    """active profile の output_root 絶対パス。"""
    return _get_output_root()


def get_output_videos_dir() -> str:
    """動画テーマフォルダを置くルート。output/{profile_id}/videos/"""
    return os.path.join(_get_output_root(), "videos")


def get_data_dir() -> str:
    """metadata.db など永続データを置くディレクトリ。output/{profile_id}/000_data/"""
    return os.path.join(_get_output_root(), "000_data")


def get_uploaded_dir() -> str:
    """アップロード済みアーカイブ。output/{profile_id}/000_uploaded/"""
    return os.path.join(_get_output_root(), "000_uploaded")


def get_backups_dir() -> str:
    """バックアップフォルダ。output/{profile_id}/000_backups/"""
    return os.path.join(_get_output_root(), "000_backups")


def get_db_path() -> str:
    """profile 別 metadata.db の絶対パス。"""
    return os.path.join(get_data_dir(), "metadata.db")


# ─────────────────────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────────────────────

def ensure_output_dirs() -> None:
    """active profile の出力ディレクトリをすべて作成する。"""
    for path in (
        get_output_videos_dir(),
        get_data_dir(),
        get_uploaded_dir(),
        get_backups_dir(),
    ):
        os.makedirs(path, exist_ok=True)


def migrate_root_file(
    filename: str, destination_dir: str, *, overwrite: bool = False
) -> str:
    """旧出力ルートのファイルを整理済みディレクトリへ移動する（必要な場合のみ）。"""
    ensure_output_dirs()
    old_path = os.path.join(get_output_videos_dir(), filename)
    new_path = os.path.join(destination_dir, filename)
    if os.path.exists(old_path) and (overwrite or not os.path.exists(new_path)):
        shutil.move(old_path, new_path)
    return new_path


