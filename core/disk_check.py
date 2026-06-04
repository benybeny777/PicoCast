"""生成・レンダー前のディスク空き容量チェック。

出力先ドライブの空きが `DISK_MIN_FREE_GB` 未満なら E-DISK で停止する。
MP4 レンダリングは一時ファイル・最終ファイルでディスクを消費するため、
枯渇による中途半端な失敗を未然に防ぐ。
"""
from __future__ import annotations

import os
import shutil

from config import config
from core.error_codes import AppError


def _nearest_existing(path: str) -> str:
    """存在する最も近い祖先ディレクトリを返す（出力フォルダ未作成でも測れるように）。"""
    p = os.path.abspath(path)
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p or os.path.abspath(os.sep)


def _default_output_path() -> str:
    from core.channel_profile import get_active_profile
    profile = get_active_profile()
    if profile is not None and getattr(profile, "output_root_abs", ""):
        return profile.output_root_abs
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_gb(path: str | None = None) -> float:
    """対象パスのあるドライブの空き容量(GB)を返す。"""
    target = _nearest_existing(path or _default_output_path())
    return shutil.disk_usage(target).free / (1024 ** 3)


def assert_enough_disk(path: str | None = None) -> None:
    """空き容量が閾値未満なら AppError(E-DISK) を送出する。閾値 <=0 で無効。"""
    min_gb = float(config.DISK_MIN_FREE_GB)
    if min_gb <= 0:
        return
    target = _nearest_existing(path or _default_output_path())
    free = shutil.disk_usage(target).free / (1024 ** 3)
    if free < min_gb:
        raise AppError("E-DISK", detail=f"空き {free:.1f}GB / 必要 {min_gb:.1f}GB（{target}）")
