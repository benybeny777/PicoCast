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

import logging
import os
import shutil

_logger = logging.getLogger(__name__)

from core.runtime_env import app_base_dir

# 出力(動画・metadata.db等の永続データ)の基準。exe(onefile)では exe と同じフォルダ。
_ROOT = app_base_dir()


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_ROOT, path)


# ─────────────────────────────────────────────────────────────────────────────
# 出力ベースディレクトリ（全プロファイル共通・設定で変更可能）
# ─────────────────────────────────────────────────────────────────────────────

def default_output_base_dir() -> str:
    """既定の出力ベース（リポジトリ直下 output/）の絶対パス。"""
    return os.path.join(_ROOT, "output")


def output_base_dir() -> str:
    """全プロファイル共通の出力ベースディレクトリ（絶対パス）。

    config.OUTPUT_BASE_DIR が空なら既定の output/ を使う。相対指定なら
    リポジトリルート基準で解決する。各 profile の出力はこの直下に置かれる。
    """
    from config import config as cfg
    base = (getattr(cfg, "OUTPUT_BASE_DIR", "") or "").strip()
    if not base:
        return default_output_base_dir()
    return base if os.path.isabs(base) else os.path.join(_ROOT, base)


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


def _is_subpath(child: str, parent: str) -> bool:
    """child が parent の配下（または同一）かどうかを判定する。"""
    child_n = os.path.normcase(os.path.normpath(os.path.abspath(child)))
    parent_n = os.path.normcase(os.path.normpath(os.path.abspath(parent)))
    if child_n == parent_n:
        return True
    return child_n.startswith(parent_n + os.sep)


def relocate_output_base(new_base: str, *, move: bool = True) -> dict:
    """出力ベースディレクトリを new_base へ変更し、既存データを移動/コピーする。

    全プロファイルの output_root（各 profile_id フォルダ）と metadata.db を含む
    既存の出力一式を新しいベースへ移し、config.OUTPUT_BASE_DIR を更新して永続化する。

    呼び出し側で「実行中/待機中ジョブが無いこと」を保証してから呼ぶこと
    （移動中に runner が metadata.db を掴んでいると破損するため）。

    Args:
        new_base: 新しい出力ベース（絶対パス推奨。相対ならリポジトリルート基準）。
        move: True=移動（shutil.move）/ False=コピー（既存は残す）。

    Returns:
        {"old_base", "new_base", "moved", "entries"} の要約。
    """
    old_base = output_base_dir()
    new_abs = new_base.strip()
    if not new_abs:
        raise ValueError("出力ベースのパスが空です")
    new_abs = new_abs if os.path.isabs(new_abs) else os.path.join(_ROOT, new_abs)
    new_abs = os.path.normpath(new_abs)
    old_norm = os.path.normpath(old_base)

    # 同一なら何もしない（設定だけ確定させる）
    if os.path.normcase(new_abs) == os.path.normcase(old_norm):
        _persist_output_base(new_abs)
        return {"old_base": old_norm, "new_base": new_abs, "moved": False, "entries": []}

    # 入れ子は不可（再帰移動・自己包含で壊れる）
    if _is_subpath(new_abs, old_norm) or _is_subpath(old_norm, new_abs):
        raise ValueError(
            "新しい出力ベースは現在の出力ベースの内側/外側に入れ子にできません: "
            f"old={old_norm} new={new_abs}"
        )

    if os.path.isfile(new_abs):
        raise ValueError(f"指定パスは既存のファイルです: {new_abs}")

    moved_entries: list[str] = []
    if os.path.isdir(old_norm):
        os.makedirs(new_abs, exist_ok=True)
        for name in os.listdir(old_norm):
            src = os.path.join(old_norm, name)
            dst = os.path.join(new_abs, name)
            if os.path.exists(dst):
                raise FileExistsError(f"移動先に同名のエントリが既に存在します: {dst}")
            if move:
                shutil.move(src, dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            moved_entries.append(name)
        _logger.info(
            "[OutputBase] 出力ベースを移設しました: %s -> %s (%s, %d 件)",
            old_norm, new_abs, "move" if move else "copy", len(moved_entries),
        )
    else:
        os.makedirs(new_abs, exist_ok=True)
        _logger.info("[OutputBase] 旧出力ベースが無いため新規作成のみ: %s", new_abs)

    _persist_output_base(new_abs)
    return {
        "old_base": old_norm,
        "new_base": new_abs,
        "moved": bool(moved_entries),
        "entries": moved_entries,
    }


def _persist_output_base(new_abs: str) -> None:
    """OUTPUT_BASE_DIR を設定 DB に保存し、現在プロセスへ即時反映する。"""
    import sys
    from core import settings_store
    from config import config as cfg

    settings_store.set_many({"OUTPUT_BASE_DIR": new_abs})
    os.environ["OUTPUT_BASE_DIR"] = new_abs
    setattr(cfg, "OUTPUT_BASE_DIR", new_abs)
    # 'from config import OUTPUT_BASE_DIR' でキャプチャ済みのモジュールにも反映
    for mod in list(sys.modules.values()):
        if mod is None or mod is cfg:
            continue
        if hasattr(mod, "OUTPUT_BASE_DIR"):
            try:
                setattr(mod, "OUTPUT_BASE_DIR", new_abs)
            except (AttributeError, TypeError):
                _logger.warning("OUTPUT_BASE_DIR の実行時反映に失敗しました: module=%s", getattr(mod, "__name__", ""), exc_info=True)
                pass


