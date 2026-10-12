"""Web UI の多重起動を OS のファイルロックで防ぐ。

ポートの応答確認だけでは、既定ポートを別アプリが使っていて空きポートへ退避した場合に
2つ目の起動を検出できない。2つ目の Web UI が起動すると、その job-runner が起動時の
残骸破棄（`discard_pending_jobs`）で1つ目が待機させている生成・レンダーのジョブを
キャンセルしてしまうため、同じデータフォルダを使う Web UI は1つだけにする。

ロックは OS がプロセス終了時に必ず解放するため、異常終了後に残ったロックファイルが
次の起動を妨げることはない。起動中インスタンスの URL は別ファイルに記録する。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import IO

from core.runtime_env import app_base_dir

_logger = logging.getLogger(__name__)

_LOCK_FILE_NAME = "web_ui.lock"
_INFO_FILE_NAME = "web_ui_instance.json"


def _data_dir() -> str:
    return os.path.join(app_base_dir(), "data")


def _try_lock(handle: IO[bytes]) -> bool:
    """ロックを取れたら True、他プロセス（または別ハンドル）が保持中なら False。"""
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


class InstanceLock:
    """取得済みのロック。プロセスの生存中は保持し続ける。"""

    def __init__(self, handle: IO[bytes]):
        self._handle: IO[bytes] | None = handle

    def record_url(self, url: str) -> None:
        """起動中インスタンスの URL を記録する（2つ目の起動が既存画面を開くため）。"""
        path = os.path.join(_data_dir(), _INFO_FILE_NAME)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "url": url}, f, ensure_ascii=False)
        os.replace(tmp, path)

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            # ファイルを閉じると OS がロックを解放する
            handle.close()


def acquire() -> InstanceLock | None:
    """Web UI のロックを取る。既に別の Web UI が保持していれば None。"""
    data_dir = _data_dir()
    os.makedirs(data_dir, exist_ok=True)
    handle = open(os.path.join(data_dir, _LOCK_FILE_NAME), "a+b")
    if _try_lock(handle):
        return InstanceLock(handle)
    handle.close()
    return None


def running_instance_url() -> str | None:
    """ロックを保持している Web UI が記録した URL。記録が無い・読めない場合は None。"""
    path = os.path.join(_data_dir(), _INFO_FILE_NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            url = json.load(f).get("url")
    except (OSError, ValueError, AttributeError):
        _logger.warning("起動中インスタンス情報を読めませんでした: path=%s", path, exc_info=True)
        return None
    return url if isinstance(url, str) and url else None
