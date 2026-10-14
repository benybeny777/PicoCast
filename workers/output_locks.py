"""出力フォルダのロック診断。"""
from __future__ import annotations

import logging
import os

_logger = logging.getLogger("yj.pipeline")


class OutputDirectoryLockedError(Exception):
    """既存の出力フォルダが開かれていて退避できない場合の再試行用エラー。"""


def find_locking_process(path: str) -> str | None:
    """ファイルをロックしているプロセスの 'Name (PID)' を返す。ロックなしは None。"""
    try:
        import psutil
        target = os.path.abspath(path).lower()
        for proc in psutil.process_iter(["pid", "name", "open_files"]):
            try:
                for opened_file in proc.open_files():
                    if opened_file.path.lower() == target:
                        return f"{proc.info['name']} (PID {proc.info['pid']})"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # 調べている間に終了したプロセスや権限外のプロセスは対象外
                _logger.debug("プロセスのファイル一覧を取得できません: pid=%s", proc.info.get("pid"), exc_info=True)
                continue
    except Exception:
        _logger.warning("プロセスロック情報の確認に失敗しました", exc_info=True)
        return None  # フォールバック許可: プロセスロック確認は補助情報のため失敗しても継続
    return None
