"""
ローカルメタデータ SQLite DB。

DB ファイル: output/{profile_id}/000_data/metadata.db

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

SCHEMA_VERSION = 7


# ── パス ────────────────────────────────────────────────────────────────────

def get_db_path() -> str:
    """
    active profile の output_root 配下の metadata.db パスを返す。
    profile 未設定なら config の OUTPUT_DATA_DIR にフォールバック（後方互換）。
    profile が変わるとパスが変わるため、キャッシュしない。
    """
    try:
        from core.output_paths import get_db_path as _op_get_db_path
        return _op_get_db_path()
    except Exception:
        from config.config import OUTPUT_DATA_DIR
        return os.path.join(OUTPUT_DATA_DIR, "metadata.db")


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
    count = len(targets)
    for conn in targets:
        try:
            conn.close()
        except Exception as e:
            _logger.warning("[SQLite] DB接続close失敗: %s", e)
    with _conn_lock:
        _connections.clear()
    _logger.info("[SQLite] DB 終了: %d 接続をクローズしました", count)


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
                    pass  # フォールバック許可: クリーンアップ中の rollback 失敗は無視
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
    thumbnail_path TEXT,
    script_content TEXT
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
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    youtube_video_id          TEXT NOT NULL,
    collected_at              TEXT NOT NULL,
    window_days               INTEGER,
    title                     TEXT,
    video_type                TEXT,
    published_at              TEXT,
    duration                  REAL,
    duration_status           TEXT,
    publish_status            TEXT,
    views                     INTEGER,
    average_view_duration     REAL,
    average_percentage_viewed REAL,
    likes                     INTEGER,
    dislikes                  INTEGER,
    comments                  INTEGER,
    subscribers_gained        INTEGER,
    subscribers_lost          INTEGER,
    subscribers_net           INTEGER,
    impressions               INTEGER,
    ctr                       REAL,
    like_rate                 REAL,
    dislike_rate              REAL,
    score                     TEXT,
    action                    TEXT,
    analysis_status           TEXT,
    is_provisional            INTEGER,
    audio_cutoff_risk         INTEGER,
    blacklist_candidate       INTEGER,
    weak_reason               TEXT,
    avoid_pattern             TEXT,
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
    opening_score_status   TEXT,
    opening_rewrite_needed INTEGER,
    final_review_score     REAL,
    validation_status      TEXT,
    validation_errors_json TEXT,
    final_review_skipped   INTEGER,
    final_review_reason    TEXT,
    final_review_stage     TEXT,
    final_review_model     TEXT,
    opening_review_debug   TEXT
);

CREATE TABLE IF NOT EXISTS render_info (
    local_id                      TEXT PRIMARY KEY,
    render_engine                 TEXT,
    video_title                   TEXT,
    description                   TEXT,
    tags                          TEXT,
    video_format                  TEXT,
    screen_format                 TEXT,
    playlist_categories           TEXT,
    native_renderer_json          TEXT,
    estimated_duration_sec        REAL,
    actual_duration_sec           REAL,
    actual_duration_status        TEXT,
    loudnorm_enabled              INTEGER,
    loudnorm_i                    REAL,
    loudnorm_tp                   REAL,
    loudnorm_lra                  REAL,
    motion_effects_enabled        INTEGER,
    motion_effects_fallback_count INTEGER,
    bgm_mode                      TEXT,
    bgm_id                        TEXT,
    bgm_display_name              TEXT,
    bgm_file_path                 TEXT,
    bgm_volume_db                 REAL,
    bgm_loop_enabled              INTEGER
);

CREATE TABLE IF NOT EXISTS image_replacements (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id          TEXT NOT NULL,
    target_rel_path   TEXT NOT NULL,
    target_kind       TEXT NOT NULL,
    source_type       TEXT NOT NULL,
    backup_file_path  TEXT,
    applied_file_path TEXT NOT NULL,
    original_width    INTEGER,
    original_height   INTEGER,
    applied_width     INTEGER,
    applied_height    INTEGER,
    status            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    note              TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    job_type      TEXT,
    profile_id    TEXT,
    status        TEXT,
    progress_text TEXT DEFAULT '',
    started_at    TEXT,
    finished_at   TEXT,
    logs_json     TEXT DEFAULT '[]',
    result_json   TEXT,
    error         TEXT,
    params_json   TEXT,
    cancel_requested INTEGER DEFAULT 0,
    heartbeat_at  TEXT,
    runner_pid    INTEGER,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS image_generation_failures (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id          TEXT NOT NULL,
    failed_index      INTEGER,
    total_backgrounds INTEGER,
    model             TEXT,
    backend           TEXT,
    status_code       INTEGER,
    category          TEXT,
    error_code        TEXT,
    error_message     TEXT,
    prompt            TEXT,
    retry_recommended INTEGER,
    failed_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_youtube_status_vid ON youtube_status(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_analytics_vid ON analytics_snapshots(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_topic_key ON topic_history(topic_key);
CREATE INDEX IF NOT EXISTS idx_food_name ON topic_history(food_name);
CREATE INDEX IF NOT EXISTS idx_videos_type ON videos(video_type);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at);
CREATE INDEX IF NOT EXISTS idx_image_replacements_local_id ON image_replacements(local_id);
CREATE INDEX IF NOT EXISTS idx_image_gen_failures_local_id ON image_generation_failures(local_id);
"""


def _add_column(conn: sqlite3.Connection, table: str, col: str, typedef: str) -> None:
    """列が存在しなければ追加する。"""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise


def _migrate(conn: sqlite3.Connection, current_ver: int) -> None:
    """
    スキーマを最新版に揃える。
    _add_column は「既に存在する列」を無視するため全列を無条件に適用しても安全。
    schema_version の値にかかわらず不足列を確実に補完する。
    """
    # v2: videos.script_content
    _add_column(conn, "videos", "script_content", "TEXT")
    _add_column(conn, "jobs", "profile_id", "TEXT")
    _add_column(conn, "jobs", "params_json", "TEXT")
    _add_column(conn, "jobs", "cancel_requested", "INTEGER DEFAULT 0")
    _add_column(conn, "jobs", "heartbeat_at", "TEXT")
    _add_column(conn, "jobs", "runner_pid", "INTEGER")

    # v3: analytics_snapshots 追加列
    for col, typedef in [
        ("title",              "TEXT"),
        ("video_type",         "TEXT"),
        ("published_at",       "TEXT"),
        ("duration",           "REAL"),
        ("duration_status",    "TEXT"),
        ("publish_status",     "TEXT"),
        ("dislikes",           "INTEGER"),
        ("subscribers_gained", "INTEGER"),
        ("subscribers_lost",   "INTEGER"),
        ("impressions",        "INTEGER"),
        ("ctr",                "REAL"),
        ("dislike_rate",       "REAL"),
        ("is_provisional",     "INTEGER"),
        ("audio_cutoff_risk",  "INTEGER"),
        ("blacklist_candidate","INTEGER"),
        ("weak_reason",        "TEXT"),
        ("avoid_pattern",      "TEXT"),
    ]:
        _add_column(conn, "analytics_snapshots", col, typedef)

    # v4: video_metadata CTA 列
    for col, typedef in [
        ("cta_shorts_loop_priority",     "INTEGER"),
        ("cta_direct_next_video_allowed","INTEGER"),
        ("cta_topic_request",            "TEXT"),
        ("cta_topic_request_reason",     "TEXT"),
        ("cta_final_type",               "TEXT"),
    ]:
        _add_column(conn, "video_metadata", col, typedef)

    # v4: script_quality final_review / opening 列
    for col, typedef in [
        ("opening_score_status",  "TEXT"),
        ("opening_rewrite_needed","INTEGER"),
        ("final_review_skipped",  "INTEGER"),
        ("final_review_reason",   "TEXT"),
        ("final_review_stage",    "TEXT"),
        ("final_review_model",    "TEXT"),
        ("opening_review_debug",  "TEXT"),  # v5: 冒頭レビューの採点デバッグ情報(JSON)
    ]:
        _add_column(conn, "script_quality", col, typedef)

    # v7: image_generation_failures にエラーコード列
    _add_column(conn, "image_generation_failures", "error_code", "TEXT")

    # render_info / jobs テーブルは DDL の CREATE TABLE IF NOT EXISTS で作成済み
    for col, typedef in [
        ("bgm_mode",         "TEXT"),
        ("bgm_id",           "TEXT"),
        ("bgm_display_name", "TEXT"),
        ("bgm_file_path",    "TEXT"),
        ("bgm_volume_db",    "REAL"),
        ("bgm_loop_enabled", "INTEGER"),
    ]:
        _add_column(conn, "render_info", col, typedef)

    _logger.debug("[SQLite] スキーマ補完完了 (v%s → v%s)", current_ver, SCHEMA_VERSION)


def initialize_db() -> None:
    """DB を初期化する。既存 DB が存在する場合はスキーマ移行のみ行う。"""
    path = get_db_path()
    existed = os.path.isfile(path)
    with ManagedConnection() as conn:
        conn.executescript(_DDL)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current_ver = row[0] if row else 0
        # バージョンにかかわらず常に補完マイグレーションを実行する
        # (_add_column は冪等なので既存列があっても安全)
        _migrate(conn, current_ver)
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,))
        elif current_ver != SCHEMA_VERSION:
            conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
        conn.commit()
    if existed:
        _logger.info("[SQLite] DB 起動（既存 v%s）: %s", SCHEMA_VERSION, path)
    else:
        _logger.info("[SQLite] DB 起動（新規作成 v%s）: %s", SCHEMA_VERSION, path)


# ── ヘルパー ─────────────────────────────────────────────────────────────────

def _now_jst() -> str:
    from datetime import timedelta
    JST = timezone(timedelta(hours=9))
    return datetime.now(JST).isoformat()


def _local_id_from_dir(output_dir: str) -> str:
    return os.path.basename(os.path.abspath(output_dir).rstrip("/\\"))


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


def _parse_youtube_time(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()


def _youtube_publish_status(privacy_status: str | None, publish_at: str | None) -> str:
    privacy = str(privacy_status or "").lower()
    if privacy == "public":
        return "published"
    if privacy in {"private", "unlisted"} and publish_at:
        publish_dt = datetime.fromisoformat(str(publish_at).replace("Z", "+00:00"))
        return "scheduled" if publish_dt > datetime.now(timezone.utc) else privacy
    if privacy:
        return privacy
    return "unknown"


def _screen_format_from_video_type(video_type: str | None) -> str | None:
    vt = str(video_type or "").lower()
    if vt == "shorts":
        return "縦"
    if vt == "long":
        return "横"
    return None


# ── upsert 関数 ──────────────────────────────────────────────────────────────

def upsert_video(conn: sqlite3.Connection, local_id: str, output_dir: str,
                 render_info: dict, upload_record: dict,
                 script_content: str | None = None) -> None:
    title = (render_info.get("video_title")
             or upload_record.get("title")
             or local_id)
    video_type = (render_info.get("video_format")
                  or upload_record.get("video_type")
                  or "")
    mp4 = _find_mp4(output_dir)
    thumb = _find_thumbnail(output_dir)
    # 台本本文は呼び出し元（生成パイプライン）から DB へ直接渡すのが正本経路。
    # script_content が未指定のときに限り、既存フォルダ取り込みの後方互換として
    # ディスクの script.txt を読む（新規生成では script.txt は作らない）。
    if script_content is None:
        script_path_val = os.path.join(output_dir, "script.txt")
        if os.path.isfile(script_path_val):
            try:
                with open(script_path_val, encoding="utf-8") as f:
                    script_content = f.read()
            except Exception as e:
                _logger.warning("script.txt 読み込み失敗 %s: %s", local_id, e)
    now = _now_jst()
    conn.execute("""
        INSERT INTO videos(local_id, output_dir, title, video_type,
                           created_at, updated_at, mp4_path, thumbnail_path,
                           script_content)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(local_id) DO UPDATE SET
            output_dir=excluded.output_dir,
            title=excluded.title, video_type=excluded.video_type,
            updated_at=excluded.updated_at, mp4_path=excluded.mp4_path,
            thumbnail_path=excluded.thumbnail_path,
            script_content=COALESCE(excluded.script_content, script_content)
    """, (local_id, output_dir, title, video_type, now, now, mp4, thumb, script_content))


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
        script_meta.get("fixed_comment") or render_info.get("fixed_comment"),
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


def sync_youtube_statuses(statuses: dict[str, dict], delete_missing: bool = False) -> dict[str, int]:
    """
    YouTube Data API 由来の状態を正として metadata.db を更新する。

    statuses は video_id -> dict の形式で、core.youtube_uploader.get_channel_upload_video_statuses()
    または get_video_statuses() の戻り値を想定する。delete_missing=True の場合、DB上の
    youtube_video_id が statuses に存在しないレコードは YouTube 側で削除済みとして削除する。
    """
    if not is_initialized():
        initialize_db()

    checked = 0
    updated = 0
    deleted = 0
    missing = 0
    orphan_deleted = 0
    now = _now_jst()

    with ManagedConnection() as conn:
        rows = conn.execute("""
            SELECT v.local_id, v.title, v.video_type,
                   ys.youtube_video_id, ys.publish_status, ys.publish_at,
                   ys.uploaded_at, ys.published_at, ys.privacy_status,
                   ri.video_title, ri.video_format, ri.screen_format
            FROM youtube_status ys
            JOIN videos v ON v.local_id = ys.local_id
            LEFT JOIN render_info ri ON ri.local_id = ys.local_id
            WHERE ys.youtube_video_id IS NOT NULL
              AND TRIM(ys.youtube_video_id) <> ''
        """).fetchall()

        for row in rows:
            checked += 1
            local_id = row["local_id"]
            video_id = str(row["youtube_video_id"]).strip()
            status = statuses.get(video_id)
            if status is None:
                missing += 1
                if delete_missing:
                    conn.execute("DELETE FROM render_info      WHERE local_id=?", (local_id,))
                    conn.execute("DELETE FROM script_quality   WHERE local_id=?", (local_id,))
                    conn.execute("DELETE FROM playlists         WHERE local_id=?", (local_id,))
                    conn.execute("DELETE FROM analytics_snapshots WHERE youtube_video_id=?", (video_id,))
                    conn.execute("DELETE FROM youtube_status   WHERE local_id=?", (local_id,))
                    conn.execute("DELETE FROM video_metadata   WHERE local_id=?", (local_id,))
                    conn.execute("DELETE FROM topic_history    WHERE local_id=?", (local_id,))
                    conn.execute("DELETE FROM videos           WHERE local_id=?", (local_id,))
                    deleted += 1
                continue

            title = str(status.get("title") or "").strip() or None
            video_type = str(status.get("video_type") or "").strip() or None
            privacy = str(status.get("privacyStatus") or "").strip() or None
            publish_at = _parse_youtube_time(status.get("publishAt"))
            published_at = _parse_youtube_time(status.get("publishedAt"))
            publish_status = _youtube_publish_status(privacy, status.get("publishAt"))
            uploaded_at = published_at
            screen_format = _screen_format_from_video_type(video_type)

            before = dict(row)

            conn.execute("""
                UPDATE videos
                SET title=COALESCE(?, title),
                    video_type=COALESCE(?, video_type),
                    updated_at=?
                WHERE local_id=?
            """, (title, video_type, now, local_id))

            conn.execute("""
                INSERT INTO render_info(local_id, video_title, video_format, screen_format)
                VALUES(?,?,?,?)
                ON CONFLICT(local_id) DO UPDATE SET
                    video_title=COALESCE(excluded.video_title, render_info.video_title),
                    video_format=COALESCE(excluded.video_format, render_info.video_format),
                    screen_format=COALESCE(excluded.screen_format, render_info.screen_format)
            """, (local_id, title, video_type, screen_format))

            conn.execute("""
                UPDATE youtube_status
                SET publish_status=?,
                    publish_at=?,
                    uploaded_at=COALESCE(NULLIF(uploaded_at, ''), ?),
                    published_at=COALESCE(NULLIF(published_at, ''), ?),
                    privacy_status=?
                WHERE local_id=?
            """, (publish_status, publish_at, uploaded_at, published_at, privacy, local_id))

            after = conn.execute("""
                SELECT v.title, v.video_type,
                       ys.publish_status, ys.publish_at, ys.uploaded_at,
                       ys.published_at, ys.privacy_status,
                       ri.video_title, ri.video_format, ri.screen_format
                FROM videos v
                LEFT JOIN youtube_status ys ON ys.local_id = v.local_id
                LEFT JOIN render_info ri ON ri.local_id = v.local_id
                WHERE v.local_id=?
            """, (local_id,)).fetchone()
            if after is not None and any(before.get(k) != after[k] for k in after.keys()):
                updated += 1

        orphan_deleted += conn.execute("""
            DELETE FROM render_info
            WHERE local_id NOT IN (SELECT local_id FROM videos)
        """).rowcount
        orphan_deleted += conn.execute("""
            DELETE FROM script_quality
            WHERE local_id NOT IN (SELECT local_id FROM videos)
        """).rowcount
        orphan_deleted += conn.execute("""
            DELETE FROM video_metadata
            WHERE local_id NOT IN (SELECT local_id FROM videos)
        """).rowcount
        orphan_deleted += conn.execute("""
            DELETE FROM topic_history
            WHERE local_id IS NOT NULL
              AND local_id NOT IN (SELECT local_id FROM videos)
        """).rowcount
        orphan_deleted += conn.execute("""
            DELETE FROM playlists
            WHERE local_id IS NOT NULL
              AND local_id NOT IN (SELECT local_id FROM videos)
        """).rowcount
        conn.commit()

    return {
        "checked": checked,
        "updated": updated,
        "missing": missing,
        "deleted": deleted,
        "orphan_deleted": orphan_deleted,
    }


def sync_youtube_statuses_from_api(delete_missing: bool = False) -> dict[str, int]:
    """YouTube Data API を正として既知動画IDの DB 状態を更新する。"""
    from core.youtube_uploader import get_channel_upload_video_statuses

    statuses = get_channel_upload_video_statuses()
    result = sync_youtube_statuses(statuses, delete_missing=delete_missing)
    result["youtube_returned"] = len(statuses)
    return result


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
    """analytics データを snapshots テーブルに upsert する。"""
    views = int(data.get("views") or 0)
    likes = int(data.get("likes") or 0)
    like_rate = data.get("like_rate") or (round(likes / views * 100, 2) if views > 0 else None)
    with ManagedConnection() as conn:
        conn.execute("""
            INSERT INTO analytics_snapshots(
                youtube_video_id, collected_at, window_days,
                title, video_type, published_at, duration, duration_status, publish_status,
                views, average_view_duration, average_percentage_viewed,
                likes, dislikes, comments,
                subscribers_gained, subscribers_lost, subscribers_net,
                impressions, ctr, like_rate, dislike_rate,
                score, action, analysis_status,
                is_provisional, audio_cutoff_risk,
                blacklist_candidate, weak_reason, avoid_pattern)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(youtube_video_id, collected_at, window_days) DO UPDATE SET
                title=COALESCE(excluded.title, title),
                video_type=COALESCE(excluded.video_type, video_type),
                published_at=COALESCE(excluded.published_at, published_at),
                duration=COALESCE(excluded.duration, duration),
                duration_status=COALESCE(excluded.duration_status, duration_status),
                publish_status=excluded.publish_status,
                views=excluded.views,
                average_view_duration=excluded.average_view_duration,
                average_percentage_viewed=excluded.average_percentage_viewed,
                likes=excluded.likes, dislikes=excluded.dislikes,
                comments=excluded.comments,
                subscribers_gained=excluded.subscribers_gained,
                subscribers_lost=excluded.subscribers_lost,
                subscribers_net=excluded.subscribers_net,
                impressions=excluded.impressions, ctr=excluded.ctr,
                like_rate=excluded.like_rate, dislike_rate=excluded.dislike_rate,
                score=excluded.score, action=excluded.action,
                analysis_status=excluded.analysis_status,
                is_provisional=excluded.is_provisional,
                audio_cutoff_risk=excluded.audio_cutoff_risk,
                blacklist_candidate=excluded.blacklist_candidate,
                weak_reason=excluded.weak_reason,
                avoid_pattern=excluded.avoid_pattern
        """, (
            video_id, collected_at, int(window_days),
            data.get("title"),
            data.get("video_type"),
            data.get("published_at"),
            data.get("duration"),
            data.get("duration_status"),
            data.get("publish_status"),
            views,
            data.get("average_view_duration"),
            data.get("average_percentage_viewed"),
            likes,
            data.get("dislikes"),
            data.get("comments") or data.get("comment_count"),
            data.get("subscribers_gained"),
            data.get("subscribers_lost"),
            data.get("subscribers_net"),
            data.get("impressions"),
            data.get("ctr"),
            like_rate,
            data.get("dislike_rate"),
            str(data.get("score") or ""),
            data.get("action"),
            data.get("analysis_status"),
            int(bool(data.get("is_provisional"))),
            int(bool(data.get("audio_cutoff_risk"))),
            int(bool(data.get("blacklist_candidate"))),
            data.get("weak_reason"),
            data.get("avoid_pattern"),
        ))
        conn.commit()


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


def upsert_render_info(local_id: str, data: dict) -> None:
    """render_info データを DB に upsert する。"""
    import json as _json
    tags = data.get("tags")
    cats = data.get("playlist_categories")
    nr   = data.get("native_renderer")
    with ManagedConnection() as conn:
        conn.execute("""
            INSERT INTO render_info(
                local_id, render_engine, video_title, description,
                tags, video_format, screen_format, playlist_categories,
                native_renderer_json,
                estimated_duration_sec, actual_duration_sec, actual_duration_status,
                loudnorm_enabled, loudnorm_i, loudnorm_tp, loudnorm_lra,
                motion_effects_enabled, motion_effects_fallback_count,
                bgm_mode, bgm_id, bgm_display_name, bgm_file_path, bgm_volume_db, bgm_loop_enabled)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(local_id) DO UPDATE SET
                render_engine=COALESCE(excluded.render_engine, render_engine),
                video_title=COALESCE(excluded.video_title, video_title),
                description=COALESCE(excluded.description, description),
                tags=COALESCE(excluded.tags, tags),
                video_format=COALESCE(excluded.video_format, video_format),
                screen_format=COALESCE(excluded.screen_format, screen_format),
                playlist_categories=COALESCE(excluded.playlist_categories, playlist_categories),
                native_renderer_json=COALESCE(excluded.native_renderer_json, native_renderer_json),
                estimated_duration_sec=COALESCE(excluded.estimated_duration_sec, estimated_duration_sec),
                actual_duration_sec=COALESCE(excluded.actual_duration_sec, actual_duration_sec),
                actual_duration_status=COALESCE(excluded.actual_duration_status, actual_duration_status),
                loudnorm_enabled=COALESCE(excluded.loudnorm_enabled, loudnorm_enabled),
                loudnorm_i=COALESCE(excluded.loudnorm_i, loudnorm_i),
                loudnorm_tp=COALESCE(excluded.loudnorm_tp, loudnorm_tp),
                loudnorm_lra=COALESCE(excluded.loudnorm_lra, loudnorm_lra),
                motion_effects_enabled=COALESCE(excluded.motion_effects_enabled, motion_effects_enabled),
                motion_effects_fallback_count=COALESCE(excluded.motion_effects_fallback_count, motion_effects_fallback_count),
                bgm_mode=COALESCE(excluded.bgm_mode, bgm_mode),
                bgm_id=COALESCE(excluded.bgm_id, bgm_id),
                bgm_display_name=COALESCE(excluded.bgm_display_name, bgm_display_name),
                bgm_file_path=COALESCE(excluded.bgm_file_path, bgm_file_path),
                bgm_volume_db=COALESCE(excluded.bgm_volume_db, bgm_volume_db),
                bgm_loop_enabled=COALESCE(excluded.bgm_loop_enabled, bgm_loop_enabled)
        """, (
            local_id,
            data.get("render_engine"),
            data.get("video_title"),
            data.get("description"),
            _json.dumps(tags, ensure_ascii=False) if isinstance(tags, (list, dict)) else tags,
            data.get("video_format"),
            data.get("screen_format"),
            _json.dumps(cats, ensure_ascii=False) if isinstance(cats, (list, dict)) else cats,
            _json.dumps(nr, ensure_ascii=False) if isinstance(nr, dict) else None,
            data.get("estimated_duration_sec"),
            data.get("actual_duration_sec"),
            data.get("actual_duration_status"),
            int(bool(data.get("loudnorm_enabled"))) if "loudnorm_enabled" in data else None,
            data.get("loudnorm_i"),
            data.get("loudnorm_tp"),
            data.get("loudnorm_lra"),
            int(bool(data.get("motion_effects_enabled"))) if "motion_effects_enabled" in data else None,
            data.get("motion_effects_fallback_segments"),
            data.get("bgm_mode"),
            data.get("bgm_id"),
            data.get("bgm_display_name"),
            data.get("bgm_file_path"),
            data.get("bgm_volume_db"),
            int(bool(data.get("bgm_loop_enabled"))) if "bgm_loop_enabled" in data else None,
        ))
        conn.commit()


def get_render_info(local_id: str) -> dict:
    """render_info を DB から取得する。"""
    import json as _json
    with ManagedConnection() as conn:
        row = conn.execute(
            "SELECT * FROM render_info WHERE local_id=?", (local_id,)
        ).fetchone()
    if row is None:
        return {}
    d = dict(row)
    for key in ("tags", "playlist_categories"):
        val = d.get(key)
        if val:
            try:
                d[key] = _json.loads(val)
            except Exception:
                pass  # フォールバック許可: JSON列のパース失敗時は生値を保持
    nr = d.pop("native_renderer_json", None)
    if nr:
        try:
            d["native_renderer"] = _json.loads(nr)
        except Exception:
            pass  # フォールバック許可: JSON列のパース失敗時は生値を保持
    return d


def get_script_content(local_id: str) -> str | None:
    """videos.script_content を DB から取得する（metadata.db 正本）。

    未登録 / 空の場合は None を返す。値の読み取りはこの関数経由に統一する。
    """
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        row = conn.execute(
            "SELECT script_content FROM videos WHERE local_id=?", (local_id,)
        ).fetchone()
    if row is None:
        return None
    text = row["script_content"]
    return text if text else None


def save_script_content(local_id: str, output_dir: str, script_content: str, *, title: str | None = None, video_type: str | None = None) -> None:
    """生成途中でも台本本文を videos.script_content へ保存する。"""
    if not is_initialized():
        initialize_db()
    now = _now_jst()
    with ManagedConnection() as conn:
        conn.execute(
            """
            INSERT INTO videos(local_id, output_dir, title, video_type,
                               created_at, updated_at, script_content)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(local_id) DO UPDATE SET
                output_dir=excluded.output_dir,
                title=COALESCE(excluded.title, videos.title),
                video_type=COALESCE(excluded.video_type, videos.video_type),
                updated_at=excluded.updated_at,
                script_content=excluded.script_content
            """,
            (local_id, output_dir, title or local_id, video_type or "", now, now, script_content),
        )
        conn.commit()


def delete_history_record(local_id: str) -> dict[str, int]:
    """履歴 local_id に紐づく metadata.db レコードを削除する。"""
    if not is_initialized():
        initialize_db()
    deleted: dict[str, int] = {}
    with ManagedConnection() as conn:
        yt_rows = conn.execute(
            "SELECT youtube_video_id FROM youtube_status WHERE local_id=?",
            (local_id,),
        ).fetchall()
        video_ids = [str(r["youtube_video_id"]).strip() for r in yt_rows if r["youtube_video_id"]]
        for video_id in video_ids:
            deleted["analytics_snapshots"] = deleted.get("analytics_snapshots", 0) + conn.execute(
                "DELETE FROM analytics_snapshots WHERE youtube_video_id=?",
                (video_id,),
            ).rowcount
        for table in (
            "render_info",
            "script_quality",
            "playlists",
            "youtube_status",
            "video_metadata",
            "topic_history",
            "image_replacements",
            "videos",
        ):
            deleted[table] = conn.execute(
                f"DELETE FROM {table} WHERE local_id=?",
                (local_id,),
            ).rowcount
        conn.commit()
    return deleted


def insert_image_replacement(entry: dict) -> int:
    """画像差し替え履歴をDBへ保存し、履歴IDを返す。"""
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        cur = conn.execute(
            """
            INSERT INTO image_replacements(
                local_id, target_rel_path, target_kind, source_type,
                backup_file_path, applied_file_path,
                original_width, original_height, applied_width, applied_height,
                status, created_at, note
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                entry.get("local_id"),
                entry.get("target_rel_path"),
                entry.get("target_kind"),
                entry.get("source_type"),
                entry.get("backup_file_path"),
                entry.get("applied_file_path"),
                entry.get("original_width"),
                entry.get("original_height"),
                entry.get("applied_width"),
                entry.get("applied_height"),
                entry.get("status"),
                entry.get("created_at"),
                entry.get("note"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_image_replacements(local_id: str) -> list[dict]:
    """local_id の画像差し替え履歴を新しい順に返す。"""
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        rows = conn.execute(
            "SELECT * FROM image_replacements WHERE local_id=? ORDER BY id DESC",
            (local_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_image_replacement(replacement_id: int) -> dict:
    """画像差し替え履歴を1件取得する。"""
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        row = conn.execute(
            "SELECT * FROM image_replacements WHERE id=?",
            (replacement_id,),
        ).fetchone()
    return dict(row) if row else {}


def upsert_cta_policy(local_id: str, policy: dict) -> None:
    """cta_policy を video_metadata の CTA 列に upsert する。"""
    p = policy.get("cta_policy", policy)
    with ManagedConnection() as conn:
        conn.execute("INSERT OR IGNORE INTO videos(local_id, output_dir) VALUES(?, ?)", (local_id, f"output/{local_id}"))
        conn.execute("""
            INSERT INTO video_metadata(local_id,
                cta_shorts_loop_priority, cta_direct_next_video_allowed,
                cta_topic_request, cta_topic_request_reason, cta_final_type)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(local_id) DO UPDATE SET
                cta_shorts_loop_priority=excluded.cta_shorts_loop_priority,
                cta_direct_next_video_allowed=excluded.cta_direct_next_video_allowed,
                cta_topic_request=excluded.cta_topic_request,
                cta_topic_request_reason=excluded.cta_topic_request_reason,
                cta_final_type=excluded.cta_final_type
        """, (
            local_id,
            int(bool(p.get("shorts_loop_priority"))),
            int(bool(p.get("direct_next_video_promo_allowed"))),
            p.get("topic_request_cta"),
            p.get("topic_request_cta_reason"),
            p.get("final_cta_type"),
        ))
        conn.commit()


def get_cta_policy(local_id: str) -> dict:
    """video_metadata から CTA ポリシーを取得する。"""
    with ManagedConnection() as conn:
        row = conn.execute("""
            SELECT cta_shorts_loop_priority, cta_direct_next_video_allowed,
                   cta_topic_request, cta_topic_request_reason, cta_final_type
            FROM video_metadata WHERE local_id=?
        """, (local_id,)).fetchone()
    if row is None:
        return {}
    return {
        "cta_policy": {
            "shorts_loop_priority": bool(row["cta_shorts_loop_priority"]),
            "direct_next_video_promo_allowed": bool(row["cta_direct_next_video_allowed"]),
            "topic_request_cta": row["cta_topic_request"],
            "topic_request_cta_reason": row["cta_topic_request_reason"],
            "final_cta_type": row["cta_final_type"],
        }
    }


def upsert_opening_review(local_id: str, data: dict) -> None:
    """opening_review データを script_quality に upsert する。

    LLMレビューの採点デバッグ情報（model / raw_response / サブスコア等）は
    `opening_review_debug` 列に JSON で保存する（78点頻発などの採点癖を後から検証するため）。
    ローカルJSONファイルは作成しない。
    """
    llm_review = data.get("llm_review") or {}
    final = data.get("local_review", {}) if not llm_review else llm_review
    score = data.get("final_score") or final.get("score")
    status = data.get("final_status") or final.get("status")
    rewrite = int(bool(data.get("rewrite_needed")))
    review_debug = llm_review.get("review_debug")
    debug_json = json.dumps(review_debug, ensure_ascii=False) if review_debug else None
    with ManagedConnection() as conn:
        conn.execute("INSERT OR IGNORE INTO videos(local_id, output_dir) VALUES(?, ?)", (local_id, f"output/{local_id}"))
        conn.execute("""
            INSERT INTO script_quality(local_id, opening_score, opening_score_status,
                                       opening_rewrite_needed, opening_review_debug)
            VALUES(?,?,?,?,?)
            ON CONFLICT(local_id) DO UPDATE SET
                opening_score=COALESCE(excluded.opening_score, opening_score),
                opening_score_status=excluded.opening_score_status,
                opening_rewrite_needed=excluded.opening_rewrite_needed,
                opening_review_debug=COALESCE(excluded.opening_review_debug, opening_review_debug)
        """, (local_id, score, status, rewrite, debug_json))
        conn.commit()


def get_opening_review_debug(local_id: str) -> dict | None:
    """script_quality.opening_review_debug（冒頭レビュー採点デバッグ情報）を返す。未保存なら None。"""
    with ManagedConnection() as conn:
        row = conn.execute(
            "SELECT opening_review_debug FROM script_quality WHERE local_id=?", (local_id,)
        ).fetchone()
    if row is None or not row["opening_review_debug"]:
        return None
    try:
        return json.loads(row["opening_review_debug"])
    except (ValueError, TypeError):
        return None


def record_image_generation_failure(local_id: str, failure: dict) -> None:
    """背景画像生成の失敗を image_generation_failures に記録する（_meta JSONは作らない）。

    failure: failed_index / total_backgrounds / model / backend / status_code /
             category / error_message / prompt / retry_recommended
    """
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        conn.execute("INSERT OR IGNORE INTO videos(local_id, output_dir) VALUES(?, ?)", (local_id, f"output/{local_id}"))
        conn.execute("""
            INSERT INTO image_generation_failures(
                local_id, failed_index, total_backgrounds, model, backend,
                status_code, category, error_code, error_message, prompt,
                retry_recommended, failed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            local_id,
            failure.get("failed_index"),
            failure.get("total_backgrounds"),
            failure.get("model"),
            failure.get("backend"),
            failure.get("status_code"),
            failure.get("category"),
            failure.get("error_code"),
            failure.get("error_message"),
            failure.get("prompt"),
            int(bool(failure.get("retry_recommended"))),
            failure.get("failed_at") or _now_jst(),
        ))
        conn.commit()


def get_image_generation_failures(local_id: str) -> list[dict]:
    """指定動画の背景生成失敗記録を新しい順に返す。"""
    with ManagedConnection() as conn:
        rows = conn.execute(
            "SELECT * FROM image_generation_failures WHERE local_id=? ORDER BY id DESC",
            (local_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def clear_image_generation_failures(local_id: str) -> None:
    """再生成開始時などに、対象動画の失敗記録をクリアする。"""
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        conn.execute("DELETE FROM image_generation_failures WHERE local_id=?", (local_id,))
        conn.commit()


def clear_image_generation_failure(local_id: str, failed_index: int) -> None:
    """指定背景番号の失敗記録だけをクリアする（その背景の再生成成功時に呼ぶ）。"""
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        conn.execute(
            "DELETE FROM image_generation_failures WHERE local_id=? AND failed_index=?",
            (local_id, failed_index),
        )
        conn.commit()


def upsert_final_review(local_id: str, review: dict | None) -> None:
    """final_review データを script_quality に upsert する。"""
    r = review or {"skipped": True}
    with ManagedConnection() as conn:
        conn.execute("INSERT OR IGNORE INTO videos(local_id, output_dir) VALUES(?, ?)", (local_id, f"output/{local_id}"))
        conn.execute("""
            INSERT INTO script_quality(local_id,
                final_review_skipped, final_review_reason, final_review_stage, final_review_model)
            VALUES(?,?,?,?,?)
            ON CONFLICT(local_id) DO UPDATE SET
                final_review_skipped=excluded.final_review_skipped,
                final_review_reason=excluded.final_review_reason,
                final_review_stage=excluded.final_review_stage,
                final_review_model=excluded.final_review_model
        """, (
            local_id,
            int(bool(r.get("skipped"))),
            r.get("reason"),
            r.get("stage"),
            r.get("model"),
        ))
        conn.commit()


def upsert_job(job_dict: dict) -> None:
    """ジョブを jobs テーブルに upsert する。"""
    import json as _json
    with ManagedConnection() as conn:
        conn.execute("""
            INSERT INTO jobs(job_id, job_type, profile_id, status, progress_text,
                             started_at, finished_at, logs_json, result_json, error,
                             params_json, cancel_requested, heartbeat_at, runner_pid, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                profile_id=excluded.profile_id,
                status=excluded.status,
                progress_text=excluded.progress_text,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                logs_json=excluded.logs_json,
                result_json=excluded.result_json,
                error=excluded.error,
                params_json=COALESCE(excluded.params_json, jobs.params_json),
                cancel_requested=excluded.cancel_requested,
                heartbeat_at=excluded.heartbeat_at,
                runner_pid=excluded.runner_pid
        """, (
            job_dict["job_id"],
            job_dict.get("type"),
            job_dict.get("profile_id"),
            job_dict.get("status"),
            job_dict.get("progress_text", ""),
            job_dict.get("started_at"),
            job_dict.get("finished_at"),
            _json.dumps(job_dict.get("logs") or [], ensure_ascii=False),
            _json.dumps(job_dict.get("result"), ensure_ascii=False) if job_dict.get("result") is not None else None,
            job_dict.get("error"),
            _json.dumps(job_dict.get("params") or {}, ensure_ascii=False) if job_dict.get("params") is not None else job_dict.get("params_json"),
            int(bool(job_dict.get("cancel_requested", False))),
            job_dict.get("heartbeat_at"),
            job_dict.get("runner_pid"),
            job_dict.get("started_at") or _now_jst(),
        ))
        conn.commit()


def load_jobs_from_db(max_n: int = 500) -> list[dict]:
    """jobs テーブルから最新 N 件を返す。"""
    import json as _json
    with ManagedConnection() as conn:
        rows = conn.execute("""
            SELECT job_id, job_type, profile_id, status, progress_text,
                   started_at, finished_at, logs_json, result_json, error,
                   params_json, cancel_requested, heartbeat_at, runner_pid, created_at
            FROM jobs
            ORDER BY COALESCE(started_at, created_at) DESC
            LIMIT ?
        """, (max_n,)).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["type"] = d.pop("job_type", None)
        try:
            d["logs"] = _json.loads(d.pop("logs_json") or "[]")
        except Exception:
            d["logs"] = []
        try:
            result_raw = d.pop("result_json", None)
            d["result"] = _json.loads(result_raw) if result_raw else None
        except Exception:
            d["result"] = None
        try:
            params_raw = d.pop("params_json", None)
            d["params"] = _json.loads(params_raw) if params_raw else {}
        except Exception:
            d["params"] = {}
        d["cancel_requested"] = bool(d.get("cancel_requested"))
        result.append(d)
    return result


def claim_queued_job(runner_pid: int, job_types: list[str] | tuple[str, ...] | None = None) -> dict | None:
    """最古の queued ジョブを running に原子的に更新して返す。"""
    with ManagedConnection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if job_types:
            placeholders = ",".join("?" for _ in job_types)
            row = conn.execute(
                f"""
                SELECT * FROM jobs
                WHERE status='queued' AND job_type IN ({placeholders})
                ORDER BY created_at ASC
                LIMIT 1
                """,
                tuple(job_types),
            ).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM jobs
                WHERE status='queued'
                ORDER BY created_at ASC
                LIMIT 1
            """).fetchone()
        if row is None:
            conn.commit()
            return None
        now = _now_jst()
        conn.execute("""
            UPDATE jobs
            SET status='running',
                started_at=COALESCE(started_at, ?),
                progress_text='実行中',
                heartbeat_at=?,
                runner_pid=?,
                cancel_requested=0
            WHERE job_id=? AND status='queued'
        """, (now, now, runner_pid, row["job_id"]))
        conn.commit()
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["type"] = d.pop("job_type", None)
    try:
        d["params"] = json.loads(d.pop("params_json") or "{}")
    except Exception:
        d["params"] = {}
    try:
        d["logs"] = json.loads(d.get("logs_json") or "[]")
    except Exception:
        d["logs"] = []
    return d


def append_job_logs(job_id: str, entries: list[dict]) -> None:
    """ジョブログを jobs.logs_json へ追記する。"""
    if not entries:
        return
    with ManagedConnection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT logs_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            conn.commit()
            return
        try:
            logs = json.loads(row["logs_json"] or "[]")
        except Exception:
            logs = []
        logs.extend(entries)
        progress_text = entries[-1].get("message", "") if entries else ""
        conn.execute(
            "UPDATE jobs SET logs_json=?, progress_text=? WHERE job_id=?",
            (json.dumps(logs, ensure_ascii=False), progress_text, job_id),
        )
        conn.commit()


def update_job_progress(job_id: str, progress_text: str | None = None, heartbeat_at: str | None = None) -> None:
    """進捗テキストと heartbeat を更新する。"""
    with ManagedConnection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET progress_text=COALESCE(?, progress_text),
                heartbeat_at=COALESCE(?, heartbeat_at)
            WHERE job_id=?
            """,
            (progress_text, heartbeat_at, job_id),
        )
        conn.commit()


def set_job_result(job_id: str, status: str, result: dict | None = None, error: str | None = None, finished_at: str | None = None) -> None:
    """ジョブの最終結果を保存する。"""
    with ManagedConnection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status=?, result_json=?, error=?, finished_at=?, heartbeat_at=?, runner_pid=NULL
            WHERE job_id=?
            """,
            (
                status,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error,
                finished_at or _now_jst(),
                _now_jst(),
                job_id,
            ),
        )
        conn.commit()


def request_cancel(job_id: str) -> bool:
    """ジョブへキャンセル要求を記録する。queued は即 cancelled にする。"""
    with ManagedConnection() as conn:
        row = conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return False
        if row["status"] == "queued":
            conn.execute(
                "UPDATE jobs SET status='cancelled', cancel_requested=1, progress_text='キャンセル済み', finished_at=? WHERE job_id=?",
                (_now_jst(), job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET cancel_requested=1, progress_text='キャンセル要求済み' WHERE job_id=?",
                (job_id,),
            )
        conn.commit()
    return True


def is_cancel_requested(job_id: str) -> bool:
    with ManagedConnection() as conn:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def reap_stale_running_jobs(timeout_sec: float) -> int:
    """heartbeat が途絶えた running ジョブを failed にする。"""
    from datetime import datetime as _dt, timedelta as _td

    threshold = (_dt.fromisoformat(_now_jst()) - _td(seconds=float(timeout_sec))).isoformat()
    with ManagedConnection() as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status='failed',
                error='runner停止により中断',
                progress_text='runner停止により中断',
                finished_at=?,
                runner_pid=NULL
            WHERE status='running'
              AND (heartbeat_at IS NULL OR heartbeat_at < ?)
            """,
            (_now_jst(), threshold),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def delete_old_jobs(keep_n: int) -> None:
    """古いジョブを削除して keep_n 件だけ残す。"""
    with ManagedConnection() as conn:
        conn.execute("""
            DELETE FROM jobs WHERE job_id NOT IN (
                SELECT job_id FROM jobs
                ORDER BY COALESCE(started_at, created_at) DESC
                LIMIT ?
            )
        """, (keep_n,))
        conn.commit()


def delete_video(local_id: str) -> None:
    """
    local_id に紐づく全テーブルのレコードを削除する。
    analytics_snapshots は youtube_video_id 経由で削除する。
    """
    with ManagedConnection() as conn:
        row = conn.execute(
            "SELECT youtube_video_id FROM youtube_status WHERE local_id=?", (local_id,)
        ).fetchone()
        yt_id = row[0] if row else None

        conn.execute("DELETE FROM render_info      WHERE local_id=?", (local_id,))
        conn.execute("DELETE FROM script_quality   WHERE local_id=?", (local_id,))
        conn.execute("DELETE FROM playlists         WHERE local_id=?", (local_id,))
        if yt_id:
            conn.execute("DELETE FROM analytics_snapshots WHERE youtube_video_id=?", (yt_id,))
        conn.execute("DELETE FROM youtube_status   WHERE local_id=?", (local_id,))
        conn.execute("DELETE FROM video_metadata   WHERE local_id=?", (local_id,))
        conn.execute("DELETE FROM topic_history    WHERE local_id=?", (local_id,))
        conn.execute("DELETE FROM videos           WHERE local_id=?", (local_id,))
        conn.commit()
    _logger.info("[SQLite] レコード削除: local_id=%s", local_id)


# ── フォルダ同期 ─────────────────────────────────────────────────────────────

def sync_folder_to_db(output_dir: str, script_content: str | None = None) -> None:
    """
    output_dir 配下を DB に同期する。
    DB を正本とし、旧メタJSONは参照しない。
    失敗時はログに出して例外を伝播させる（サイレントスキップ禁止）。

    script_content: 生成パイプラインが台本本文を渡す正本経路。
      未指定のときは DB 既存値 → ディスクの script.txt（既存フォルダ取り込みの
      後方互換）の順で補う。新規生成では script.txt は作らない。
    """
    local_id = _local_id_from_dir(output_dir)

    render_info = get_render_info(local_id)

    upload_rec: dict = {}
    with ManagedConnection() as _c:
        _row = _c.execute(
            "SELECT youtube_video_id FROM youtube_status WHERE local_id=?", (local_id,)
        ).fetchone()
        if _row and _row[0]:
            upload_rec = {"video_id": _row[0]}

    opening_rev: dict = {}
    with ManagedConnection() as _c:
        _row2 = _c.execute(
            "SELECT opening_score FROM script_quality WHERE local_id=?", (local_id,)
        ).fetchone()
        if _row2 and _row2[0] is not None:
            opening_rev = {"final_score": _row2[0]}

    # 台本本文を確定する: 引数 → DB既存値 → script.txt（後方互換）の順。
    if script_content is None:
        script_content = get_script_content(local_id)
    if script_content is None:
        script_path = os.path.join(output_dir, "script.txt")
        if os.path.isfile(script_path):
            try:
                with open(script_path, encoding="utf-8") as f:
                    script_content = f.read()
            except Exception as e:
                _logger.warning("script.txt 読み込み失敗 %s: %s", local_id, e)

    # 台本メタを ScriptParser で取得（台本本文から）
    script_meta: dict = {}
    if script_content:
        try:
            from core.parser import ScriptParser
            items = ScriptParser.parse_string(script_content)
            script_meta = {it["type"]: it["text"] for it in items
                           if it["type"] in ScriptParser.META_TYPES}
        except Exception as e:
            _logger.warning("台本パース失敗 %s: %s", local_id, e)

    render_info_for_video = dict(render_info)
    if script_meta:
        render_info_for_video.setdefault("video_title", script_meta.get("video_title"))
        render_info_for_video.setdefault("video_format", script_meta.get("video_format"))
        render_info_for_video.setdefault("screen_format", script_meta.get("screen_format"))

    with ManagedConnection() as conn:
        upsert_video(conn, local_id, output_dir, render_info_for_video, upload_rec,
                     script_content=script_content)
        upsert_video_metadata(conn, local_id, render_info_for_video, script_meta)
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


def load_latest_analytics_items() -> list[dict]:
    """
    analytics_snapshots の最新バッチを関連テーブルと JOIN して返す。
    返却フィールドは analytics_score.to_tsv() / build_performance_summary() が期待する形式に合わせる。
    """
    with ManagedConnection() as conn:
        meta_row = conn.execute(
            "SELECT collected_at, window_days FROM analytics_snapshots ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
        if meta_row is None:
            return []
        latest_at = meta_row["collected_at"]
        # YouTube API 由来の値（title, video_type 等）は analytics_snapshots に直接保存済み。
        # render_info / video_metadata からは補助情報のみ取得する。
        rows = conn.execute("""
            SELECT
                a.youtube_video_id          AS video_id,
                a.collected_at,
                a.window_days,
                a.title,
                a.video_type,
                a.published_at,
                a.duration,
                a.duration_status,
                a.publish_status,
                a.views,
                a.average_view_duration,
                a.average_percentage_viewed,
                a.likes,
                a.dislikes,
                a.comments,
                a.subscribers_gained,
                a.subscribers_lost,
                a.subscribers_net,
                a.impressions,
                a.ctr,
                a.like_rate,
                a.dislike_rate,
                a.score,
                a.action,
                a.analysis_status,
                a.is_provisional,
                a.audio_cutoff_risk,
                a.blacklist_candidate,
                a.weak_reason,
                a.avoid_pattern,
                ri.render_engine,
                vm.genre                    AS genre_group,
                vm.generation_type          AS generation_kind,
                vm.source_video_title,
                vm.purpose                  AS generation_purpose,
                vm.character_pattern,
                vm.cta_topic_request        AS topic_request_cta,
                vm.cta_topic_request_reason AS topic_request_cta_reason,
                vm.cta_final_type           AS final_cta_type
            FROM analytics_snapshots a
            LEFT JOIN youtube_status ys ON ys.youtube_video_id = a.youtube_video_id
            LEFT JOIN render_info ri    ON ri.local_id = ys.local_id
            LEFT JOIN video_metadata vm ON vm.local_id = ys.local_id
            WHERE a.collected_at = ?
            ORDER BY a.views DESC
        """, (latest_at,)).fetchall()

    items = []
    for row in rows:
        d = dict(row)
        d["analytics_available"] = True
        likes = d.get("likes") or 0
        dislikes = d.get("dislikes") or 0
        d["like_dislike_total"] = likes + dislikes
        d["is_provisional"] = bool(d.get("is_provisional"))
        d["audio_cutoff_risk"] = bool(d.get("audio_cutoff_risk"))
        d["blacklist_candidate"] = bool(d.get("blacklist_candidate"))
        items.append(d)
    return items


def get_latest_analytics_meta() -> dict:
    """最新バッチの collected_at / window_days を返す。"""
    with ManagedConnection() as conn:
        row = conn.execute(
            "SELECT collected_at, window_days FROM analytics_snapshots ORDER BY collected_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {}
    return {"generated_at": row["collected_at"], "window_days": row["window_days"]}


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
    from core.output_paths import get_output_videos_dir
    root = output_dir_root or get_output_videos_dir()

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

    print(f"\n[完了] 取り込み: 成功={ok} / 警告={warn} / 失敗={fail}")


def _import_one(folder: str, ok_ref: list, warn_ref: list, fail_ref: list) -> None:
    script_path = os.path.join(folder, "script.txt")
    if not os.path.isfile(script_path):
        return  # 動画フォルダではない
    try:
        sync_folder_to_db(folder)
        ok_ref[0] += 1
        print(f"  [OK] {os.path.basename(folder)}")
    except Exception as e:
        fail_ref[0] += 1
        print(f"  [NG] {os.path.basename(folder)}: {e}")


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
