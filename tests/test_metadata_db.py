"""
tests/test_metadata_db.py — メタデータDB のユニットテスト
"""
import os
import tempfile

import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """テスト用に一時ディレクトリを DB パスとして設定する。"""
    import core.metadata_db as m
    db_path = str(tmp_path / "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()
    yield m
    m.close_all_connections()


@pytest.fixture
def tmp_folder(tmp_path):
    """テスト用の動画フォルダを作成する。"""
    folder = tmp_path / "Shorts_テスト動画_20260601_abc123"
    folder.mkdir(parents=True)
    (folder / "script.txt").write_text(
        "動画形式: Shorts\n動画タイトル: テスト食べ物の雑学\n生成区分: 新規\nジャンル: 薬・毒\n\n"
        "背景: テスト\nずんだもん(ノーマル): テストなのだ！\n",
        encoding="utf-8",
    )
    return str(folder)


# ── DB 初期化 ────────────────────────────────────────────────────────────────

def test_initialize_creates_tables(tmp_db):
    """initialize_db() で全テーブルが作成されること。"""
    with tmp_db.ManagedConnection() as conn:
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    expected = {"videos", "video_metadata", "youtube_status",
                "analytics_snapshots", "playlists", "topic_history", "script_quality"}
    assert expected.issubset(tables)


def test_initialize_idempotent(tmp_db):
    """2回呼んでもエラーが出ないこと。"""
    tmp_db.initialize_db()  # 2回目


def test_get_db_path_without_active_profile_raises(tmp_path, monkeypatch):
    """active profile 未設定時は互換 metadata.db パスへ戻さず停止する。"""
    import core.channel_profile as cp
    import core.metadata_db as m

    monkeypatch.setattr(cp, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(cp, "_ROOT", str(tmp_path))
    monkeypatch.setattr(cp, "_RES_ROOT", str(tmp_path))

    with pytest.raises(cp.NoActiveProfileError):
        m.get_db_path()

    assert not (tmp_path / "metadata.db").exists()


def test_reap_stale_running_jobs_only_marks_runner_jobs(tmp_db):
    """runner 管轄外の軽量ジョブは stale 回収で failed にしない。"""
    old_heartbeat = "2026-01-01T00:00:00+09:00"
    with tmp_db.ManagedConnection() as conn:
        conn.execute(
            """
            INSERT INTO jobs(job_id, job_type, status, heartbeat_at, runner_pid, created_at)
            VALUES(?,?,?,?,?,?)
            """,
            ("generate-old", "generate", "running", old_heartbeat, 111, old_heartbeat),
        )
        conn.execute(
            """
            INSERT INTO jobs(job_id, job_type, status, heartbeat_at, runner_pid, created_at)
            VALUES(?,?,?,?,?,?)
            """,
            ("check-old", "check", "running", old_heartbeat, None, old_heartbeat),
        )
        conn.commit()

    count = tmp_db.reap_stale_running_jobs(30.0)

    with tmp_db.ManagedConnection() as conn:
        generate_status = conn.execute("SELECT status FROM jobs WHERE job_id='generate-old'").fetchone()["status"]
        check_status = conn.execute("SELECT status FROM jobs WHERE job_id='check-old'").fetchone()["status"]

    assert count == 1
    assert generate_status == "failed"
    assert check_status == "running"


# ── upsert ───────────────────────────────────────────────────────────────────

def test_sync_folder_to_db(tmp_db, tmp_folder):
    """sync_folder_to_db でレコードが作成されること。"""
    tmp_db.sync_folder_to_db(tmp_folder)
    local_id = os.path.basename(tmp_folder)
    with tmp_db.ManagedConnection() as conn:
        v = conn.execute("SELECT * FROM videos WHERE local_id=?", (local_id,)).fetchone()
        ys = conn.execute("SELECT * FROM youtube_status WHERE local_id=?", (local_id,)).fetchone()
    assert v is not None
    assert v["title"] == "テスト食べ物の雑学"
    # youtube_status は sync_folder_to_db では設定しない。アップロード後に別途 upsert_youtube_status で設定する。
    assert ys is None or ys["youtube_video_id"] is None


def test_sync_folder_upsert(tmp_db, tmp_folder):
    """2回同期してもレコードが重複しないこと。"""
    tmp_db.sync_folder_to_db(tmp_folder)
    tmp_db.sync_folder_to_db(tmp_folder)
    local_id = os.path.basename(tmp_folder)
    with tmp_db.ManagedConnection() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM videos WHERE local_id=?", (local_id,)).fetchone()[0]
    assert cnt == 1


def test_sync_stores_script_content_without_file(tmp_db, tmp_path):
    """script.txt ファイルが無くても script_content 引数から DB に台本を保存できること。"""
    folder = tmp_path / "Shorts_DB直接_20260601_def456"
    folder.mkdir(parents=True)
    # script.txt は作らない（新規生成の挙動）
    assert not (folder / "script.txt").exists()

    script_text = (
        "動画形式: Shorts\n動画タイトル: DB直接保存のテスト\n生成区分: 新規\n\n"
        "背景: テスト\nずんだもん(ノーマル): DBに入るのだ！\n"
    )
    tmp_db.sync_folder_to_db(str(folder), script_content=script_text)

    local_id = os.path.basename(str(folder))
    assert tmp_db.get_script_content(local_id) == script_text
    with tmp_db.ManagedConnection() as conn:
        v = conn.execute("SELECT title FROM videos WHERE local_id=?", (local_id,)).fetchone()
    assert v["title"] == "DB直接保存のテスト"
    # 同期しても script.txt ファイルは生成されない
    assert not (folder / "script.txt").exists()


def test_get_script_content_missing_returns_none(tmp_db):
    """未登録 local_id では get_script_content が None を返すこと。"""
    assert tmp_db.get_script_content("存在しないID") is None


# ── analytics_snapshot ───────────────────────────────────────────────────────

def test_insert_analytics_snapshot(tmp_db, tmp_folder):
    """analytics snapshot が insert されること。"""
    tmp_db.sync_folder_to_db(tmp_folder)
    tmp_db.insert_analytics_snapshot(
        video_id="TEST_VIDEO_ID_001",
        collected_at="2026-06-02T00:00:00+09:00",
        window_days=7,
        data={
            "views": 1500,
            "average_view_duration": 35.0,
            "average_percentage_viewed": 82.0,
            "likes": 20,
            "comments": 3,
            "subscribers_net": 2,
            "score": "A",
            "action": "継続",
        },
    )
    with tmp_db.ManagedConnection() as conn:
        row = conn.execute(
            "SELECT * FROM analytics_snapshots WHERE youtube_video_id='TEST_VIDEO_ID_001'"
        ).fetchone()
    assert row is not None
    assert row["views"] == 1500
    assert abs(row["like_rate"] - 1.33) < 0.1


def test_insert_analytics_snapshot_duplicate_ignored(tmp_db, tmp_folder):
    """同じ video_id + collected_at + window_days の重複は無視されること。"""
    tmp_db.sync_folder_to_db(tmp_folder)
    kwargs = dict(video_id="TEST_VIDEO_ID_001",
                  collected_at="2026-06-02T00:00:00+09:00",
                  window_days=7, data={"views": 100})
    tmp_db.insert_analytics_snapshot(**kwargs)
    tmp_db.insert_analytics_snapshot(**kwargs)
    with tmp_db.ManagedConnection() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM analytics_snapshots").fetchone()[0]
    assert cnt == 1


def test_sync_youtube_statuses_updates_db_and_deletes_missing(tmp_db, tmp_path):
    """YouTube API 由来の状態でDBを更新し、存在しない動画を削除できること。"""
    folder = tmp_path / "Shorts_DB同期テスト"
    folder.mkdir()
    missing_folder = tmp_path / "Shorts_削除済みテスト"
    missing_folder.mkdir()
    with tmp_db.ManagedConnection() as conn:
        conn.execute(
            "INSERT INTO videos(local_id, output_dir, title) VALUES(?,?,?)",
            ("local_keep", str(folder), "古いタイトル"),
        )
        conn.execute(
            "INSERT INTO render_info(local_id, video_title) VALUES(?,?)",
            ("local_keep", "古いタイトル"),
        )
        conn.execute(
            "INSERT INTO youtube_status(local_id, youtube_video_id) VALUES(?,?)",
            ("local_keep", "YT_KEEP"),
        )
        conn.execute(
            "INSERT INTO videos(local_id, output_dir, title) VALUES(?,?,?)",
            ("local_missing", str(missing_folder), "削除済み"),
        )
        conn.execute(
            "INSERT INTO youtube_status(local_id, youtube_video_id) VALUES(?,?)",
            ("local_missing", "YT_MISSING"),
        )
        conn.commit()

    result = tmp_db.sync_youtube_statuses(
        {
            "YT_KEEP": {
                "title": "YouTube側タイトル",
                "video_type": "Shorts",
                "privacyStatus": "public",
                "publishedAt": "2026-05-31T03:00:00Z",
            }
        },
        delete_missing=True,
    )

    assert result == {
        "checked": 2,
        "updated": 1,
        "missing": 1,
        "deleted": 1,
        "orphan_deleted": 0,
    }
    with tmp_db.ManagedConnection() as conn:
        kept = conn.execute(
            """
            SELECT v.title, v.video_type, ys.publish_status, ys.published_at,
                   ys.uploaded_at, ys.privacy_status, ri.video_title, ri.screen_format
            FROM videos v
            JOIN youtube_status ys ON ys.local_id = v.local_id
            JOIN render_info ri ON ri.local_id = v.local_id
            WHERE v.local_id='local_keep'
            """
        ).fetchone()
        missing = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE local_id='local_missing'"
        ).fetchone()[0]

    assert kept["title"] == "YouTube側タイトル"
    assert kept["video_type"] == "Shorts"
    assert kept["publish_status"] == "published"
    assert kept["published_at"] == "2026-05-31T03:00:00+00:00"
    assert kept["uploaded_at"] == "2026-05-31T03:00:00+00:00"
    assert kept["privacy_status"] == "public"
    assert kept["video_title"] == "YouTube側タイトル"
    assert kept["screen_format"] == "縦"
    assert missing == 0


# ── duplicate check ──────────────────────────────────────────────────────────

def test_get_duplicate_topics(tmp_db, tmp_folder, tmp_path):
    """同一 topic_key が複数あるとき get_duplicate_topics に現れること。"""
    # 2件目のフォルダ（同じ topic_key）
    folder2 = tmp_path / "Shorts_テスト2_20260602_xyz"
    folder2.mkdir(parents=True)
    (folder2 / "script.txt").write_text("動画形式: Shorts\n動画タイトル: テスト2\n\n背景: test\nずんだもん(ノーマル): test\n", encoding="utf-8")

    tmp_db.sync_folder_to_db(tmp_folder)
    tmp_db.sync_folder_to_db(str(folder2))

    # 同じ topic_key を手動挿入して重複テスト
    with tmp_db.ManagedConnection() as conn:
        conn.execute("INSERT OR IGNORE INTO topic_history(local_id, topic_key, food_name, title) VALUES(?,?,?,?)",
                     (os.path.basename(tmp_folder), "テスト食材", "テスト食材", "タイトル1"))
        conn.execute("INSERT OR IGNORE INTO topic_history(local_id, topic_key, food_name, title) VALUES(?,?,?,?)",
                     (os.path.basename(str(folder2)), "テスト食材", "テスト食材", "タイトル2"))
        conn.commit()

    dups = tmp_db.get_duplicate_topics()
    assert any(d["cnt"] >= 2 for d in dups)


# ── get_videos / stats ───────────────────────────────────────────────────────

def test_get_videos_returns_records(tmp_db, tmp_folder):
    tmp_db.sync_folder_to_db(tmp_folder)
    videos = tmp_db.get_videos()
    assert len(videos) >= 1
    assert any(v["title"] == "テスト食べ物の雑学" for v in videos)


def test_get_videos_filter_by_type(tmp_db, tmp_folder):
    tmp_db.sync_folder_to_db(tmp_folder)
    shorts = tmp_db.get_videos(video_type="shorts")
    assert all("short" in (v["video_type"] or "").lower() for v in shorts)


def test_get_stats(tmp_db, tmp_folder):
    tmp_db.sync_folder_to_db(tmp_folder)
    stats = tmp_db.get_stats()
    assert stats["total"] >= 1
    # uploaded は youtube_video_id がある行のカウント。sync_folder_to_db では設定しないため 0。
    assert stats["uploaded"] == 0
