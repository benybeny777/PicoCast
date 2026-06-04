"""実行環境（開発 / Nuitka・PyInstaller でビルドした exe）の判定とパス基準。

ビルドした exe（onefile）では `__file__` が一時展開先を指すため、`data/` や
`output/` を `__file__` 基準で作るとアプリ終了時に消える一時領域に書いてしまう。
永続データは exe と同じフォルダ基準にする必要があるため、ここで基準ディレクトリを集約する。
"""
from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """Nuitka / PyInstaller でビルドされた exe として動作しているか。"""
    # Nuitka は各モジュールに __compiled__ を設定する
    if "__compiled__" in globals():
        return True
    # PyInstaller / 一般的な freezer は sys.frozen を設定する
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> str:
    """永続データ（data/ や output/）の基準ディレクトリを返す。

    - 開発時: リポジトリのルート（このファイルの1階層上）
    - exe 時: exe が置かれているフォルダ
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.argv[0] or sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_base_dir() -> str:
    """同梱リソース（templates / static / legal / SEED 等）の基準ディレクトリを返す。

    Nuitka onefile では展開先（`__file__` の基準）にリソースが入る。開発時はリポジトリルート。
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
