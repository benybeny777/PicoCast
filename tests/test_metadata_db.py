"""
tests/test_metadata_db.py — メタデータDB のユニットテスト
"""
import json
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
    meta_dir = folder / "_meta"
    meta_dir.mkdir(parents=True)
    (folder / "script.txt").write_text(
        "動画形式: Shorts\n動画タイトル: テスト食べ物の雑学\n生成区分: 新規\nジャンル: 薬・毒\n\n"
        "背景: テスト\nずんだもん(ノーマル): テストなのだ！\n",
        encoding="utf-8",
    )
    (meta_dir / "render_info.json").write_text(json.dumps({
        "video_title": "テスト食べ物の雑学",
        "description": "テスト説明",
        "tags": ["テスト", "雑学"],
        "video_format": "Shorts",
        "screen_format": "縦",
        "actual_duration_sec": 42.5,
        "actual_duration_status": "ideal",
    }, ensure_ascii=False), encoding="utf-8")
    (meta_dir / "upload_record.json").write_text(json.dumps({
        "video_id": "TEST_VIDEO_ID_001",
        "title": "テスト食べ物の雑学",
        "video_type": "shorts",
        "uploaded_at": "2026-06-01T10:00:00+09:00",
        "publish_status": "published",
        "published_at": "2026-06-01T19:00:00+09:00",
    }, ensure_ascii=False), encoding="utf-8")
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
    # youtube_status は sync_folder_to_db では DB 正本（youtube API 側）を参照するため
    # upload_record.json からは読まない。アップロード後に別途 upsert_youtube_status で設定する。
    assert ys is None or ys["youtube_video_id"] is None


def test_sync_folder_upsert(tmp_db, tmp_folder):
    """2回同期してもレコードが重複しないこと。"""
    tmp_db.sync_folder_to_db(tmp_folder)
    tmp_db.sync_folder_to_db(tmp_folder)
    local_id = os.path.basename(tmp_folder)
    with tmp_db.ManagedConnection() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM videos WHERE local_id=?", (local_id,)).fetchone()[0]
    assert cnt == 1


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


# ── duplicate check ──────────────────────────────────────────────────────────

def test_get_duplicate_topics(tmp_db, tmp_folder, tmp_path):
    """同一 topic_key が複数あるとき get_duplicate_topics に現れること。"""
    # 2件目のフォルダ（同じ topic_key）
    folder2 = tmp_path / "Shorts_テスト2_20260602_xyz"
    meta2 = folder2 / "_meta"
    meta2.mkdir(parents=True)
    (folder2 / "script.txt").write_text("動画形式: Shorts\n動画タイトル: テスト2\n\n背景: test\nずんだもん(ノーマル): test\n", encoding="utf-8")
    (meta2 / "render_info.json").write_text(json.dumps({"video_title": "テスト2", "video_format": "Shorts"}), encoding="utf-8")

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
