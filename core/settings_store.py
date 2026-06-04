"""
非認証設定の SQLite ストア。

DB ファイル: {project_root}/data/settings.db

config.py より先にインポートできるよう、config への依存を持たない。
起動フロー:
  1. config.py が load_dotenv() を呼ぶ（.env がなければスキップ）
  2. config.py が initialize() を呼ぶ
     a. .env に残っている非認証設定を DB へ移行（初回のみ。.env がなければスキップ）
     b. DB の設定を os.environ に反映
  3. config.py の os.environ.get() がDB由来の値を読む

.env は移行元としてのみ参照する。なくても動作する。
認証情報（GOOGLE_API_KEY 等）は encrypted_secrets テーブルで管理（core/secret_store.py）。
"""
import logging
import os
import sqlite3
import threading

_logger = logging.getLogger(__name__)

# 永続データの基準ディレクトリ（開発=リポジトリルート / exe=exe のあるフォルダ）。
# exe(onefile)では __file__ が一時展開先になるため app_base_dir() で anchor する。
from core.runtime_env import app_base_dir
_ROOT = app_base_dir()
_DB_PATH = os.path.join(_ROOT, "data", "settings.db")
_ENV_PATH = os.path.join(_ROOT, ".env")
_lock = threading.Lock()

# .env に残す認証情報キー（これらは DB に移行しない）
AUTH_KEYS: frozenset[str] = frozenset({
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "HF_TOKEN",
})


# ── 接続 ────────────────────────────────────────────────────────────────────

def _open() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=5)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()
    return conn


# ── 公開API ─────────────────────────────────────────────────────────────────

def get_all() -> dict[str, str]:
    """DB の全設定を辞書で返す。"""
    try:
        with _lock:
            conn = _open()
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        _logger.warning("[SettingsDB] 読み込み失敗: %s", e)
        return {}


def set_many(updates: dict[str, str]) -> None:
    """複数キーを DB へ upsert 保存する。"""
    if not updates:
        return
    with _lock:
        conn = _open()
        try:
            conn.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                list(updates.items()),
            )
            conn.commit()
        finally:
            conn.close()


def apply_to_env() -> None:
    """DB の設定を os.environ に反映する（既存の env 値を上書き）。"""
    settings = get_all()
    for key, value in settings.items():
        os.environ[key] = value
    if settings:
        _logger.debug("[SettingsDB] %d 件の設定を環境変数に反映しました", len(settings))


def bootstrap_from_env() -> int:
    """
    .env の非認証キーを DB へ移行し、.env から削除する（初回のみ実行される）。
    DB に既にエントリが存在するキーはスキップする（上書きしない）。
    返値: 移行したキーの数
    """
    if not os.path.isfile(_ENV_PATH):
        return 0

    existing = set(get_all().keys())

    with open(_ENV_PATH, encoding="utf-8") as f:
        lines = f.readlines()

    to_migrate: dict[str, str] = {}
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, v = stripped.partition("=")
            k = k.strip()
            v = v.strip()
            if k not in AUTH_KEYS and k not in existing:
                to_migrate[k] = v
                continue  # .env から除去
        new_lines.append(line)

    if to_migrate:
        set_many(to_migrate)
        with open(_ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        _logger.info(
            "[SettingsDB] .env から %d 件の設定を DB に移行しました: %s",
            len(to_migrate), sorted(to_migrate.keys()),
        )

    return len(to_migrate)


def initialize() -> None:
    """
    起動時に呼ぶ。
      1. .env の非認証設定を DB に移行（初回のみ）
      2. DB の設定を os.environ に反映
    """
    try:
        migrated = bootstrap_from_env()
        apply_to_env()
        count = len(get_all())
        if migrated:
            _logger.info("[SettingsDB] 起動: %d 件ロード（%d 件を.envから移行）", count, migrated)
        else:
            _logger.debug("[SettingsDB] 起動: %d 件ロード", count)
    except Exception as e:
        _logger.error("[SettingsDB] 初期化失敗（デフォルト値で続行）: %s", e)
