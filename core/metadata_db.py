"""
ローカルメタデータ SQLite DB。

DB ファイル: output/000_data/metadata.db

テーブル構成:
  videos             — 生成動画の基本情報
  video_metadata     — 台本由来のメタ情報
  youtube_status     — YouTube 投稿・公開状態
  analytics_snapshots — Analytics スナップショット
  playlists          — 再生リスト登録状態
  topic_history      — 食材・トピックの生成履歴（重複チェック用）
  script_quality     — 台本品質スコア

使い方:
  from core.metadata_db import sync_folder_to_db, get_videos

  sync_folder_to_db("/path/to/output/theme_dir")
  videos = get_videos(video_type="shorts", limit=50)

インポートコマンド:
  py -3 -m core.metadata_db import-output
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger(__name__)

# 接続追跡（shutdown hook 用）
_connections: list[sqlite3.Connection] = []
_conn_lock = threading.Lock()
_db_path_cache: str | None = None

SCHEMA_VERSION = 1


# ── パス ────────────────────────────────────────────────────────────────────

def get_db_path() -> str:
    global _db_path_cache
    if _db_path_cache is None:
        from config.config import OUTPUT_DATA_DIR
        _db_path_cache = os.path.join(OUTPUT_DATA_DIR, "metadata.db")
    return _db_path_cache


# ── 接続 ────────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """DB 接続を取得する。呼び出し元は必ず close() または ManagedConnection で解放すること。"""
    path = get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with _conn_lock:
        _connections.append(conn)
    return conn


def release_connection(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except Exception as e:
        _logger.warning("DB接続close失敗: %s", e)
    with _conn_lock:
        try:
            _connections.remove(conn)
        except ValueError:
            pass


def close_all_connections() -> None:
    """shutdown hook として登録される。全接続をクローズする。"""
    with _conn_lock:
        targets = list(_connections)
    for conn in targets:
        try:
            conn.close()
        except Exception as e:
            _logger.warning("DB接続close失敗: %s", e)
    with _conn_lock:
        _connections.clear()
    _logger.info("全DB接続をクローズしました")


def is_initialized() -> bool:
    return os.path.isfile(get_db_path())


class ManagedConnection:
    """with 文で使える DB 接続ラッパー。例外時は rollback。"""

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


# ── スキーマ ────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS videos (
    local_id       TEXT PRIMARY KEY,
    output_dir     TEXT NOT NULL,
    title          TEXT,
    video_type     TEXT,
    created_at     TEXT,
    updated_at     TEXT,
    script_path    TEXT,
    mp4_path       TEXT,
    thumbnail_path TEXT
);

CREATE TABLE IF NOT EXISTS video_metadata (
    local_id          TEXT PRIMARY KEY REFERENCES videos(local_id),
    food_name         TEXT,
    topic_key         TEXT,
    genre             TEXT,
    character_pattern TEXT,
    generation_type   TEXT,
    source_video_title TEXT,
    purpose           TEXT,
    thumbnail_text    TEXT,
    fixed_comment     TEXT,
    description       TEXT,
    tags              TEXT,
    playlist_categories TEXT,
    video_format      TEXT,
    screen_format     TEXT
);

CREATE TABLE IF NOT EXISTS youtube_status (
    local_id               TEXT PRIMARY KEY REFERENCES videos(local_id),
    youtube_video_id       TEXT UNIQUE,
    publish_status         TEXT,
    publish_at             TEXT,
    uploaded_at            TEXT,
    published_at           TEXT,
    privacy_status         TEXT,
    fixed_comment_posted   INTEGER DEFAULT 0,
    fixed_comment_id       TEXT,
    playlist_registered    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_video_id         TEXT NOT NULL,
    collected_at             TEXT NOT NULL,
    window_days              INTEGER,
    views                    INTEGER,
    average_view_duration    REAL,
    average_percentage_viewed REAL,
    likes                    INTEGER,
    comments                 INTEGER,
    subscribers_net          INTEGER,
    like_rate                REAL,
    score                    TEXT,
    action                   TEXT,
    analysis_status          TEXT,
    UNIQUE(youtube_video_id, collected_at, window_days)
);

CREATE TABLE IF NOT EXISTS playlists (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_name    TEXT NOT NULL,
    playlist_id      TEXT,
    youtube_video_id TEXT,
    local_id         TEXT,
    registered_at    TEXT,
    status           TEXT,
    UNIQUE(playlist_name, youtube_video_id)
);

CREATE TABLE IF NOT EXISTS topic_history (
    local_id         TEXT PRIMARY KEY,
    topic_key        TEXT,
    food_name        TEXT,
    title            TEXT,
    youtube_video_id TEXT,
    status           TEXT,
    created_at       TEXT
);

CREATE TABLE IF NOT EXISTS script_quality (
    local_id               TEXT PRIMARY KEY REFERENCES videos(local_id),
    dialogue_lines         INTEGER,
    total_chars            INTEGER,
    avg_chars              REAL,
    short_line_count       INTEGER,
    estimated_duration     REAL,
    actual_duration        REAL,
    actual_duration_status TEXT,
    opening_score          REAL,
    final_review_score     REAL,
    validation_status      TEXT,
    validation_errors_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_youtube_status_vid ON youtube_status(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_analytics_vid ON analytics_snapshots(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_topic_key ON topic_history(topic_key);
CREATE INDEX IF NOT EXISTS idx_food_name ON topic_history(food_name);
CREATE INDEX IF NOT EXISTS idx_videos_type ON videos(video_type);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);
"""


def initialize_db() -> None:
    """DB を初期化する。既存 DB が存在する場合は何もしない（テーブルがなければ作る）。"""
    with ManagedConnection() as conn:
        conn.executescript(_DDL)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,))
        conn.commit()
    _logger.info("DB初期化完了: %s", get_db_path())


# ── ヘルパー ─────────────────────────────────────────────────────────────────

def _now_jst() -> str:
    from datetime import timedelta
    JST = timezone(timedelta(hours=9))
    return datetime.now(JST).isoformat()


def _local_id_from_dir(output_dir: str) -> str:
    return os.path.basename(os.path.abspath(output_dir).rstrip("/\\"))


def _safe_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        _logger.warning("JSON読み込み失敗 %s: %s", path, e)
        return {}


def _find_mp4(output_dir: str) -> str | None:
    try:
        for f in os.listdir(output_dir):
            if f.endswith("_native.mp4") or f.endswith(".mp4"):
                return os.path.join(output_dir, f)
    except OSError:
        pass
    return None


def _find_thumbnail(output_dir: str) -> str | None:
    candidates = [
        os.path.join(output_dir, "thumbnails", "thumbnail.png"),
        os.path.join(output_dir, "thumbnail.png"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


# ── upsert 関数 ──────────────────────────────────────────────────────────────

def upsert_video(conn: sqlite3.Connection, local_id: str, output_dir: str,
                 render_info: dict, upload_record: dict) -> None:
    title = (render_info.get("video_title")
             or upload_record.get("title")
             or local_id)
    video_type = (render_info.get("video_format")
                  or upload_record.get("video_type")
                  or "")
    mp4 = _find_mp4(output_dir)
    thumb = _find_thumbnail(output_dir)
    script = os.path.join(output_dir, "script.txt") if os.path.isfile(os.path.join(output_dir, "script.txt")) else None
    now = _now_jst()
    conn.execute("""
        INSERT INTO videos(local_id, output_dir, title, video_type,
                           created_at, updated_at, script_path, mp4_path, thumbnail_path)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(local_id) DO UPDATE SET
            title=excluded.title, video_type=excluded.video_type,
            updated_at=excluded.updated_at, mp4_path=excluded.mp4_path,
            thumbnail_path=excluded.thumbnail_path, script_path=excluded.script_path
    """, (local_id, output_dir, title, video_type, now, now, script, mp4, thumb))


def upsert_video_metadata(conn: sqlite3.Connection, local_id: str,
                           render_info: dict, script_meta: dict) -> None:
    tags = render_info.get("tags") or script_meta.get("tags") or []
    cats = render_info.get("playlist_categories") or []
    conn.execute("""
        INSERT INTO video_metadata(
            local_id, food_name, topic_key, genre, character_pattern,
            generation_type, source_video_title, purpose, thumbnail_text,
            fixed_comment, description, tags, playlist_categories, video_format, screen_format)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(local_id) DO UPDATE SET
            genre=excluded.genre, character_pattern=excluded.character_pattern,
            generation_type=excluded.generation_type, source_video_title=excluded.source_video_title,
            purpose=excluded.purpose, thumbnail_text=excluded.thumbnail_text,
            fixed_comment=excluded.fixed_comment, description=excluded.description,
            tags=excluded.tags, playlist_categories=excluded.playlist_categories,
            video_format=excluded.video_format, screen_format=excluded.screen_format
    """, (
        local_id,
        script_meta.get("food_name"),
        script_meta.get("topic_key"),
        script_meta.get("genre_group") or script_meta.get("genre"),
        script_meta.get("character_pattern"),
        script_meta.get("generation_kind"),
        script_meta.get("source_video_title"),
        script_meta.get("generation_purpose"),
        script_meta.get("thumbnail_text"),
        script_meta.get("fixed_comment"),
        render_info.get("description") or script_meta.get("description"),
        json.dumps(tags, ensure_ascii=False),
        json.dumps(cats, ensure_ascii=False),
        render_info.get("video_format") or script_meta.get("video_format"),
        render_info.get("screen_format") or script_meta.get("screen_format"),
    ))


def upsert_youtube_status(conn: sqlite3.Connection, local_id: str,
                           upload_record: dict) -> None:
    vid = upload_record.get("video_id") or upload_record.get("youtube_video_id")
    if not vid and not local_id:
        return
    fc_posted = int(bool(upload_record.get("fixed_comment_auto_posted")
                         or upload_record.get("fixed_comment_posted")))
    fc_id = (upload_record.get("fixed_comment_thread_id")
             or upload_record.get("fixed_comment_id"))
    conn.execute("""
        INSERT INTO youtube_status(
            local_id, youtube_video_id, publish_status, publish_at,
            uploaded_at, published_at, privacy_status,
            fixed_comment_posted, fixed_comment_id)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(local_id) DO UPDATE SET
            youtube_video_id=COALESCE(excluded.youtube_video_id, youtube_video_id),
            publish_status=excluded.publish_status,
            publish_at=excluded.publish_at,
            uploaded_at=excluded.uploaded_at,
            published_at=excluded.published_at,
            fixed_comment_posted=excluded.fixed_comment_posted,
            fixed_comment_id=COALESCE(excluded.fixed_comment_id, fixed_comment_id)
    """, (
        local_id, vid,
        upload_record.get("publish_status"),
        upload_record.get("publish_at"),
        upload_record.get("uploaded_at"),
        upload_record.get("published_at"),
        upload_record.get("privacy_status"),
        fc_posted, fc_id,
    ))


def upsert_script_quality(conn: sqlite3.Connection, local_id: str,
                            render_info: dict, opening_review: dict) -> None:
    conn.execute("""
        INSERT INTO script_quality(
            local_id, estimated_duration, actual_duration, actual_duration_status,
            opening_score, final_review_score, validation_status)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(local_id) DO UPDATE SET
            estimated_duration=excluded.estimated_duration,
            actual_duration=excluded.actual_duration,
            actual_duration_status=excluded.actual_duration_status,
            opening_score=excluded.opening_score
    """, (
        local_id,
        render_info.get("estimated_duration_sec"),
        render_info.get("actual_duration_sec"),
        render_info.get("actual_duration_status"),
        opening_review.get("final_score") or opening_review.get("overall_score"),
        None,
        "ok" if not opening_review.get("must_fix") else "must_fix",
    ))


def insert_analytics_snapshot(video_id: str, collected_at: str, window_days: int,
                               data: dict) -> None:
    """analytics データを snapshots テーブルに insert する。重複はスキップ。"""
    with ManagedConnection() as conn:
        like_rate = None
        views = data.get("views") or 0
        likes = data.get("likes") or 0
        if views > 0:
            like_rate = round(likes / views * 100, 2)
        try:
            conn.execute("""
                INSERT OR IGNORE INTO analytics_snapshots(
                    youtube_video_id, collected_at, window_days, views,
                    average_view_duration, average_percentage_viewed,
                    likes, comments, subscribers_net, like_rate, score, action)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                video_id, collected_at, window_days, views,
                data.get("average_view_duration"),
                data.get("average_percentage_viewed"),
                likes,
                data.get("comments") or data.get("comment_count"),
                data.get("subscribers_net") or data.get("subscribers_gained"),
                like_rate,
                str(data.get("score") or ""),
                data.get("action"),
            ))
            conn.commit()
        except Exception as e:
            _logger.error("analytics_snapshot insert失敗 %s: %s", video_id, e)
            raise


def upsert_playlist_registration(local_id: str, youtube_video_id: str,
                                   playlist_name: str, playlist_id: str | None,
                                   status: str = "registered") -> None:
    """再生リスト登録結果を playlists テーブルに upsert する。"""
    with ManagedConnection() as conn:
        conn.execute("""
            INSERT INTO playlists(playlist_name, playlist_id, youtube_video_id, local_id,
                                   registered_at, status)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(playlist_name, youtube_video_id) DO UPDATE SET
                playlist_id=COALESCE(excluded.playlist_id, playlist_id),
                registered_at=excluded.registered_at,
                status=excluded.status
        """, (playlist_name, playlist_id, youtube_video_id, local_id, _now_jst(), status))
        # youtube_status の playlist_registered フラグも更新
        if status == "registered" and local_id:
            conn.execute(
                "UPDATE youtube_status SET playlist_registered=1 WHERE local_id=?", (local_id,))
        conn.commit()


# ── フォルダ同期 ─────────────────────────────────────────────────────────────

def sync_folder_to_db(output_dir: str) -> None:
    """
    output_dir 配下のメタファイルを読んで DB に upsert する。
    失敗時はログに出して例外を伝播させる（サイレントスキップ禁止）。
    """
    local_id = _local_id_from_dir(output_dir)
    meta_dir = os.path.join(output_dir, "_meta")

    render_info  = _safe_json(os.path.join(meta_dir, "render_info.json"))
    upload_rec   = _safe_json(os.path.join(meta_dir, "upload_record.json"))
    opening_rev  = _safe_json(os.path.join(meta_dir, "opening_review.json"))

    # 台本メタを ScriptParser で取得
    script_meta: dict = {}
    script_path = os.path.join(output_dir, "script.txt")
    if os.path.isfile(script_path):
        try:
            from core.parser import ScriptParser
            with open(script_path, encoding="utf-8") as f:
                content = f.read()
            items = ScriptParser.parse_string(content)
            script_meta = {it["type"]: it["text"] for it in items
                           if it["type"] in ScriptParser.META_TYPES}
        except Exception as e:
            _logger.warning("script.txt パース失敗 %s: %s", local_id, e)

    with ManagedConnection() as conn:
        upsert_video(conn, local_id, output_dir, render_info, upload_rec)
        upsert_video_metadata(conn, local_id, render_info, script_meta)
        if upload_rec:
            upsert_youtube_status(conn, local_id, upload_rec)
        upsert_script_quality(conn, local_id, render_info, opening_rev)
        conn.commit()

    _logger.debug("sync_folder_to_db 完了: %s", local_id)


# ── クエリ ───────────────────────────────────────────────────────────────────

def get_videos(
    video_type: str | None = None,
    publish_status: str | None = None,
    generation_type: str | None = None,
    genre: str | None = None,
    playlist_unregistered: bool = False,
    has_youtube_id: bool | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """管理画面用のビデオ一覧を返す。"""
    where: list[str] = []
    params: list[Any] = []

    if video_type:
        where.append("LOWER(v.video_type) LIKE ?")
        params.append(f"%{video_type.lower()}%")
    if publish_status:
        where.append("ys.publish_status=?")
        params.append(publish_status)
    if generation_type:
        where.append("vm.generation_type=?")
        params.append(generation_type)
    if genre:
        where.append("vm.genre=?")
        params.append(genre)
    if playlist_unregistered:
        where.append("(ys.playlist_registered IS NULL OR ys.playlist_registered=0)")
    if has_youtube_id is True:
        where.append("ys.youtube_video_id IS NOT NULL")
    elif has_youtube_id is False:
        where.append("ys.youtube_video_id IS NULL")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT
            v.local_id, v.title, v.video_type, v.created_at, v.updated_at,
            vm.genre, vm.generation_type, vm.food_name, vm.playlist_categories,
            ys.youtube_video_id, ys.publish_status, ys.publish_at, ys.uploaded_at,
            ys.fixed_comment_posted, ys.playlist_registered,
            (SELECT a.views FROM analytics_snapshots a
             WHERE a.youtube_video_id=ys.youtube_video_id
             ORDER BY a.collected_at DESC LIMIT 1) AS latest_views,
            (SELECT a.average_percentage_viewed FROM analytics_snapshots a
             WHERE a.youtube_video_id=ys.youtube_video_id
             ORDER BY a.collected_at DESC LIMIT 1) AS latest_avg_pct,
            (SELECT a.score FROM analytics_snapshots a
             WHERE a.youtube_video_id=ys.youtube_video_id
             ORDER BY a.collected_at DESC LIMIT 1) AS latest_score
        FROM videos v
        LEFT JOIN video_metadata vm ON vm.local_id=v.local_id
        LEFT JOIN youtube_status ys ON ys.local_id=v.local_id
        {where_sql}
        ORDER BY v.created_at DESC
        LIMIT ? OFFSET ?
    """
    params += [limit, offset]

    with ManagedConnection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_duplicate_topics() -> list[dict]:
    """同一 topic_key または food_name が重複している動画を返す。"""
    sql = """
        SELECT topic_key, food_name, COUNT(*) AS cnt,
               GROUP_CONCAT(local_id, '|') AS local_ids,
               GROUP_CONCAT(title, '|') AS titles
        FROM topic_history
        WHERE topic_key IS NOT NULL OR food_name IS NOT NULL
        GROUP BY COALESCE(topic_key, food_name)
        HAVING cnt > 1
        ORDER BY cnt DESC
    """
    with ManagedConnection() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_stats() -> dict:
    """DB の概要統計を返す。"""
    with ManagedConnection() as conn:
        total     = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        uploaded  = conn.execute("SELECT COUNT(*) FROM youtube_status WHERE youtube_video_id IS NOT NULL").fetchone()[0]
        published = conn.execute("SELECT COUNT(*) FROM youtube_status WHERE publish_status='published'").fetchone()[0]
        scheduled = conn.execute("SELECT COUNT(*) FROM youtube_status WHERE publish_status='scheduled' OR publish_status='private'").fetchone()[0]
        pl_reg    = conn.execute("SELECT COUNT(*) FROM youtube_status WHERE playlist_registered=1").fetchone()[0]
        return {
            "total": total, "uploaded": uploaded,
            "published": published, "scheduled": scheduled,
            "playlist_registered": pl_reg,
        }


# ── インポートコマンド ────────────────────────────────────────────────────────

def import_output_dir(output_dir_root: str | None = None) -> None:
    """
    output/ 配下の全動画フォルダを走査して DB に取り込む。

    py -3 -m core.metadata_db import-output
    """
    from core.output_paths import OUTPUT_DIR
    root = output_dir_root or OUTPUT_DIR

    initialize_db()

    ok = warn = fail = 0
    for entry in sorted(os.scandir(root), key=lambda e: e.name):
        if not entry.is_dir():
            continue
        name = entry.name
        # 000_ 系の管理フォルダは再帰的に走査
        if name.startswith("000_"):
            for sub in sorted(os.scandir(entry.path), key=lambda e: e.name):
                if sub.is_dir() and not sub.name.startswith("000_"):
                    _import_one(sub.path, ok_ref := [ok], warn_ref := [warn], fail_ref := [fail])
                    ok, warn, fail = ok_ref[0], warn_ref[0], fail_ref[0]
            continue
        _import_one(entry.path, ok_ref := [ok], warn_ref := [warn], fail_ref := [fail])
        ok, warn, fail = ok_ref[0], warn_ref[0], fail_ref[0]

    print(f"\n✅ 取り込み完了: 成功={ok} / 警告={warn} / 失敗={fail}")


def _import_one(folder: str, ok_ref: list, warn_ref: list, fail_ref: list) -> None:
    meta_dir = os.path.join(folder, "_meta")
    if not os.path.isdir(meta_dir):
        return  # 動画フォルダではない
    try:
        missing = []
        for fname in ("render_info.json",):
            if not os.path.isfile(os.path.join(meta_dir, fname)):
                missing.append(fname)
        if missing:
            warn_ref[0] += 1
            print(f"  ⚠ {os.path.basename(folder)}: 欠損ファイル {missing}")

        sync_folder_to_db(folder)
        ok_ref[0] += 1
        print(f"  ✅ {os.path.basename(folder)}")
    except Exception as e:
        fail_ref[0] += 1
        print(f"  ❌ {os.path.basename(folder)}: {e}")


# ── __main__（コマンド実行） ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("使い方: py -3 -m core.metadata_db import-output")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "import-output":
        import_output_dir()
    else:
        print(f"不明なコマンド: {cmd}")
        sys.exit(1)
