"""
ローカルメタデータ SQLite DB 接続管理。

現在は shutdown hook 用の close_all_connections() のみ実装。
テーブル定義・upsert・query は将来の実装で追加する。

DB ファイル: output/000_data/metadata.db
"""
import logging
import sqlite3
import threading
from typing import Any

_logger = logging.getLogger(__name__)

# 全接続を追跡してshutdown時にcloseできるようにする
_connections: list[sqlite3.Connection] = []
_conn_lock = threading.Lock()

# DB ファイルパスは起動時に解決する（循環インポート回避のため遅延参照）
_db_path: str | None = None


def get_db_path() -> str:
    """DB ファイルのパスを返す。"""
    global _db_path
    if _db_path is None:
        from core.output_paths import OUTPUT_DIR
        import os
        _db_path = os.path.join(OUTPUT_DIR, "000_data", "metadata.db")
    return _db_path


def get_connection() -> sqlite3.Connection:
    """DB 接続を取得する。呼び出し元は必ず close() または with 文で解放すること。"""
    import os
    path = get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    with _conn_lock:
        _connections.append(conn)
    return conn


def release_connection(conn: sqlite3.Connection) -> None:
    """接続を閉じてトラッキングリストから削除する。"""
    try:
        conn.close()
    except Exception as e:
        _logger.warning("DB接続のclose失敗: %s", e)
    with _conn_lock:
        try:
            _connections.remove(conn)
        except ValueError:
            pass


def close_all_connections() -> None:
    """全DB接続をクローズする。shutdown hook として登録される。"""
    with _conn_lock:
        targets = list(_connections)
    for conn in targets:
        try:
            conn.close()
            _logger.debug("DB接続をcloseしました")
        except Exception as e:
            _logger.warning("DB接続のclose失敗: %s", e)
    with _conn_lock:
        _connections.clear()
    _logger.info("全DB接続をクローズしました")


class ManagedConnection:
    """with 文で使える DB 接続ラッパー。close を自動で呼ぶ。"""

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = get_connection()
        return self._conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self._conn is not None:
            if exc_type is not None:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
            release_connection(self._conn)
            self._conn = None
        return False


def is_initialized() -> bool:
    """DB ファイルが存在するかどうかを返す。"""
    import os
    return os.path.isfile(get_db_path())
