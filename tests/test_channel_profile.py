"""
core/channel_profile.py のユニットテスト。
外部API実通信なし。data/settings.db は tmp_path に分離。
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture()
def profile_db(tmp_path, monkeypatch):
    import core.channel_profile as cp
    import core.channel_schedule as cs
    monkeypatch.setattr(cp, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(cp, "_ROOT", str(tmp_path))
    monkeypatch.setattr(cp, "_RES_ROOT", str(tmp_path))
    monkeypatch.setattr(cs, "_DB_PATH", str(tmp_path / "settings.db"))
    yield cp


def _make_profile(
    profile_id="test_ch", genre="food_trivia", output_root=None,
    channel_handle=None, **kw
):
    from core.channel_profile import ChannelProfile
    handle = channel_handle or f"@{profile_id}"
    return ChannelProfile(
        profile_id=profile_id,
        channel_name="テストチャンネル",
        channel_handle=handle,
        genre_profile=genre,
        output_root=output_root or profile_id,
        **kw,
    )


# ── 基本 CRUD ─────────────────────────────────────────────────────────────────

def test_save_and_get(profile_db):
    cp = profile_db
    p = _make_profile(output_root="output/old_test_ch")
    cp.save_profile(p)
    got = cp.get_profile("test_ch")
    assert got is not None
    assert got.channel_name == "テストチャンネル"
    assert got.genre_profile == "test_ch"
    assert got.output_root == "test_ch"


def test_list_profiles_empty(profile_db):
    cp = profile_db
    assert cp.list_profiles() == []


def test_list_profiles_active_first(profile_db):
    cp = profile_db
    p1 = _make_profile("ch1")
    p2 = _make_profile("ch2")
    cp.save_profile(p1)
    cp.save_profile(p2)
    cp.activate_profile("ch2")
    profiles = cp.list_profiles()
    assert profiles[0].profile_id == "ch2"
    assert profiles[0].is_active is True


def test_activate_profile(profile_db):
    cp = profile_db
    p1 = _make_profile("ch1")
    p2 = _make_profile("ch2")
    cp.save_profile(p1)
    cp.save_profile(p2)
    cp.activate_profile("ch1")
    active = cp.get_active_profile()
    assert active is not None
    assert active.profile_id == "ch1"

    # ch2 に切り替え → ch1 は非アクティブになる
    cp.activate_profile("ch2")
    active = cp.get_active_profile()
    assert active.profile_id == "ch2"

    p1_fresh = cp.get_profile("ch1")
    assert p1_fresh.is_active is False


def test_get_active_profile_none_when_empty(profile_db):
    cp = profile_db
    assert cp.get_active_profile() is None


def test_require_active_profile_raises_when_none(profile_db):
    cp = profile_db
    with pytest.raises(cp.NoActiveProfileError):
        cp.require_active_profile()


def test_delete_profile_ok(profile_db):
    cp = profile_db
    p1 = _make_profile("ch1")
    p2 = _make_profile("ch2")
    cp.save_profile(p1)
    cp.save_profile(p2)
    cp.activate_profile("ch1")
    cp.delete_profile("ch2", confirmed=True)
    assert cp.get_profile("ch2") is None


def test_delete_active_profile_raises(profile_db):
    cp = profile_db
    p = _make_profile("ch1")
    cp.save_profile(p)
    cp.activate_profile("ch1")
    with pytest.raises(cp.ChannelProfileError):
        cp.delete_profile("ch1", confirmed=True)


def test_delete_without_confirmed_raises(profile_db):
    cp = profile_db
    p = _make_profile("ch1")
    cp.save_profile(p)
    with pytest.raises(cp.ChannelProfileError):
        cp.delete_profile("ch1", confirmed=False)


# ── バリデーション ────────────────────────────────────────────────────────────

def test_validate_invalid_profile_id(profile_db):
    from core.channel_profile import ChannelProfile, ProfileValidationError
    p = ChannelProfile(
        profile_id="INVALID ID!",  # 大文字・スペースは不可
        channel_name="テスト",
        channel_handle="",
        genre_profile="food_trivia",
        output_root="output/test",
    )
    with pytest.raises(ProfileValidationError):
        profile_db.validate_profile(p)


def test_validate_invalid_accent_color(profile_db):
    from core.channel_profile import ChannelProfile, ProfileValidationError
    p = ChannelProfile(
        profile_id="ch1",
        channel_name="テスト",
        channel_handle="",
        genre_profile="food_trivia",
        output_root="output/ch1",
        channel_accent_color="not_a_color",
    )
    with pytest.raises(ProfileValidationError):
        profile_db.validate_profile(p)


# ── handle_normalized ─────────────────────────────────────────────────────────

def test_handle_normalized_adds_at(profile_db):
    p = _make_profile(profile_id="zunkami", channel_handle="zunkami")
    assert p.handle_normalized == "@zunkami"


def test_handle_normalized_keeps_at(profile_db):
    p = _make_profile(profile_id="zunkami", channel_handle="@zunkami")
    assert p.handle_normalized == "@zunkami"


# ── output_root_abs ───────────────────────────────────────────────────────────

def test_output_root_abs_relative(profile_db):
    p = _make_profile(profile_id="food_trivia")
    assert os.path.isabs(p.output_root_abs)
    # Windows/Unix どちらでも動くようにパス正規化して比較
    assert os.path.normpath("output/food_trivia") in os.path.normpath(p.output_root_abs)


def test_existing_output_root_migrates_to_profile_id(profile_db):
    cp = profile_db
    conn = cp._open_db()
    try:
        conn.execute(
            """
            INSERT INTO channel_profiles(
                profile_id, channel_name, channel_handle, genre_profile, output_root,
                default_hashtags, channel_theme, channel_accent_color, is_active,
                created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "legacy_ch", "旧チャンネル", "@legacy", "food_trivia", "output/legacy_ch",
                "", "", "", 0, "2026-06-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    got = cp.get_profile("legacy")

    assert got is not None
    assert got.profile_id == "legacy"
    assert got.output_root == "legacy"
    assert got.genre_profile == "legacy"


def test_default_api_keys_are_copied_to_profiles(profile_db):
    cp = profile_db
    conn = cp._open_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS encrypted_secrets (
                secret_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL DEFAULT 'default',
                secret_type TEXT NOT NULL,
                encrypted_value BLOB NOT NULL,
                nonce BLOB NOT NULL,
                salt BLOB,
                key_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(profile_id, secret_type)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO encrypted_secrets(
                secret_id, profile_id, secret_type, encrypted_value, nonce,
                key_version, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            ("default_google", "default", "google_api_key", b"encrypted", b"nonce", 1, "old", "old"),
        )
        conn.commit()
    finally:
        conn.close()

    cp.save_profile(_make_profile(profile_id="zunkami", channel_handle="@zunkami"))

    conn = cp._open_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM encrypted_secrets WHERE profile_id=? AND secret_type=?",
            ("zunkami", "google_api_key"),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_profile_schedule_is_created_with_default_slots(profile_db):
    cp = profile_db
    import core.channel_schedule as cs

    cp.save_profile(_make_profile(profile_id="zunkami", channel_handle="@zunkami"))

    schedule = cs.get_schedule("zunkami")
    assert schedule.timezone_name == "Asia/Tokyo"
    assert schedule.shorts_times == ["21:00"]
    assert schedule.long_times == ["22:00"]


def test_existing_profile_schedule_is_updated_to_current_default(profile_db):
    cp = profile_db
    import core.channel_schedule as cs

    conn = cp._open_db()
    try:
        conn.execute(
            """
            INSERT INTO channel_profiles(
                profile_id, channel_name, channel_handle, genre_profile, output_root,
                default_hashtags, channel_theme, channel_accent_color, is_active,
                created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "zunkami", "食べ物雑学", "@zunkami", "zunkami", "zunkami",
                "", "", "", 1, "2026-06-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_schedule_settings (
                profile_id TEXT PRIMARY KEY,
                timezone_name TEXT NOT NULL,
                shorts_slot_hours TEXT NOT NULL,
                long_slot_hours TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO channel_schedule_settings(
                profile_id, timezone_name, shorts_slot_hours, long_slot_hours,
                created_at, updated_at
            ) VALUES(?,?,?,?,?,?)
            """,
            ("zunkami", "Asia/Tokyo", "07:00,12:00,19:00", "12:00,21:00", "old", "old"),
        )
        conn.commit()
    finally:
        conn.close()

    cs.initialize()
    schedule = cs.get_schedule("zunkami")

    assert schedule.shorts_times == ["21:00"]
    assert schedule.long_times == ["22:00"]


def test_get_schedule_without_active_profile_raises(profile_db):
    cp = profile_db
    import core.channel_schedule as cs

    assert cp.get_active_profile() is None
    with pytest.raises(cp.NoActiveProfileError):
        cs.get_schedule()


# ── 初期プロファイル自動作成なし ────────────────────────────────────────────

def test_env_config_does_not_create_profile(profile_db, monkeypatch):
    cp = profile_db
    import config.config as cfg
    monkeypatch.setattr(cfg, "CHANNEL_NAME", "食べ物雑学堂")
    monkeypatch.setattr(cfg, "CHANNEL_HANDLE", "@zunkami")
    monkeypatch.setattr(cfg, "CHANNEL_THEME", "食べ物")
    monkeypatch.setattr(cfg, "CHANNEL_ACCENT_COLOR", "")
    monkeypatch.setattr(cfg, "DEFAULT_HASHTAGS", "#ずんだもん")

    assert cp.list_profiles() == []
    assert cp.get_active_profile() is None
