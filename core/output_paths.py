"""
出力パス管理モジュール。

active channel profile の output_root を基準にすべてのパスを解決する。
profile が未設定でも動作するよう、フォールバックとして config の OUTPUT_DIR を使う。

ディレクトリ構造（profile 別）:
  output/{profile_id}/
    videos/        ← 動画生成フォルダ（テーマ別サブディレクトリ）
    000_uploaded/  ← アップロード済みアーカイブ
    000_backups/   ← バックアップ
    000_data/      ← metadata.db / uploaded_titles.txt など
    000_analytics/ ← Analytics TSV/JSON

別 profile の output_root へのアクセスは web_app/security.py で拒否される。

使い方:
  from core.output_paths import (
      get_output_videos_dir, get_data_dir, get_analytics_dir,
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
    """
    active profile の output_root の絶対パスを返す。
    profile 未設定なら config の OUTPUT_DIR を使う（後方互換）。
    """
    try:
        from core.channel_profile import get_active_profile
        profile = get_active_profile()
        if profile:
            return profile.output_root_abs
    except Exception:
        pass
    # フォールバック: config の OUTPUT_DIR
    from config.config import OUTPUT_DIR as _cfg_output
    return _abs(_cfg_output)


def get_output_root() -> str:
    """active profile の output_root 絶対パス。"""
    return _get_output_root()


def get_output_videos_dir() -> str:
    """動画テーマフォルダを置くルート。output/{profile_id}/videos/"""
    return os.path.join(_get_output_root(), "videos")


def get_data_dir() -> str:
    """metadata.db など永続データを置くディレクトリ。output/{profile_id}/000_data/"""
    return os.path.join(_get_output_root(), "000_data")


def get_analytics_dir() -> str:
    """Analytics TSV / JSON を置くディレクトリ。output/{profile_id}/000_analytics/"""
    return os.path.join(_get_output_root(), "000_analytics")


def get_uploaded_dir() -> str:
    """アップロード済みアーカイブ。output/{profile_id}/000_uploaded/"""
    return os.path.join(_get_output_root(), "000_uploaded")


def get_backups_dir() -> str:
    """バックアップフォルダ。output/{profile_id}/000_backups/"""
    return os.path.join(_get_output_root(), "000_backups")


def get_db_path() -> str:
    """profile 別 metadata.db の絶対パス。"""
    return os.path.join(get_data_dir(), "metadata.db")


def get_legacy_dir() -> str:
    """旧 output/000_legacy/ に相当するパス（後方互換）。"""
    return os.path.join(_get_output_root(), "000_legacy")


# ─────────────────────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────────────────────

def ensure_output_dirs() -> None:
    """active profile の出力ディレクトリをすべて作成する。"""
    for path in (
        get_output_videos_dir(),
        get_data_dir(),
        get_analytics_dir(),
        get_uploaded_dir(),
        get_backups_dir(),
    ):
        os.makedirs(path, exist_ok=True)


def analytics_paths(pattern_suffix: str) -> list[str]:
    """Analytics ファイルのパスリストを返す。"""
    paths: list[str] = []
    for directory in (get_analytics_dir(), get_output_videos_dir()):
        try:
            paths.extend(
                os.path.join(directory, name)
                for name in os.listdir(directory)
                if name.startswith("analytics_score_") and name.endswith(pattern_suffix)
            )
        except OSError:
            continue
    return paths


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


# ─────────────────────────────────────────────────────────────────────────────
# 旧互換シム（他モジュールが module 属性アクセスした場合に動的解決）
# Python 3.7+ の module-level __getattr__ を利用する。
# from core.output_paths import OUTPUT_DIR のような既存コードは変更済みだが、
# 万が一残っている場合の安全弁として定義する。
# ─────────────────────────────────────────────────────────────────────────────

def __getattr__(name: str):
    _compat = {
        "OUTPUT_DIR":    get_output_videos_dir,
        "DATA_DIR":      get_data_dir,
        "ANALYTICS_DIR": get_analytics_dir,
        "LEGACY_DIR":    get_uploaded_dir,
    }
    if name in _compat:
        return _compat[name]()
    raise AttributeError(f"module 'core.output_paths' has no attribute {name!r}")
