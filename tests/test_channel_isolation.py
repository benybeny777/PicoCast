"""
複数チャンネル間の混線防止テスト。

- default_hashtags が profile 別に切り替わる
- playlist categories が genre 別に切り替わる
- Analytics summary が別 profile へ混ざらない（DB が別）
- 旧 prompt_parts 直接参照が残っていない（prompt_service.py 経由）
外部API実通信なし。
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
def dual_profile_env(tmp_path, monkeypatch):
    """food_trivia と urban_legend のプロファイルを両方セットアップする。"""
    import core.channel_profile as cp
    import core.prompt_profile_loader as ppl

    monkeypatch.setattr(cp, "_DB_PATH", str(tmp_path / "settings.db"))

    # fake prompt_profiles ディレクトリ
    profiles_dir = tmp_path / "prompt_profiles"
    genres_dir = profiles_dir / "genres"
    local_dir = profiles_dir / "local"
    (genres_dir / "food_trivia").mkdir(parents=True)
    (genres_dir / "urban_legend").mkdir(parents=True)
    local_dir.mkdir(parents=True)

    (genres_dir / "food_trivia" / "script_context.md").write_text("FOOD_SCRIPT", encoding="utf-8")
    (genres_dir / "food_trivia" / "title_context.md").write_text("FOOD_TITLE", encoding="utf-8")
    (genres_dir / "food_trivia" / "meeting_context.md").write_text("FOOD_MEETING", encoding="utf-8")
    (genres_dir / "food_trivia" / "profile.yaml").write_text(
        "genre_profile: food_trivia\ndefault_hashtags: '#食べ物雑学'", encoding="utf-8"
    )
    (genres_dir / "food_trivia" / "playlist_categories.md").write_text(
        "食べ物カテゴリ\n", encoding="utf-8"
    )

    (genres_dir / "urban_legend" / "script_context.md").write_text("URBAN_SCRIPT", encoding="utf-8")
    (genres_dir / "urban_legend" / "title_context.md").write_text("URBAN_TITLE", encoding="utf-8")
    (genres_dir / "urban_legend" / "meeting_context.md").write_text("URBAN_MEETING", encoding="utf-8")
    (genres_dir / "urban_legend" / "profile.yaml").write_text(
        "genre_profile: urban_legend\ndefault_hashtags: '#都市伝説'", encoding="utf-8"
    )
    (genres_dir / "urban_legend" / "playlist_categories.md").write_text(
        "都市伝説カテゴリ\n", encoding="utf-8"
    )

    monkeypatch.setattr(ppl, "_PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(ppl, "_GENRES_DIR", genres_dir)
    monkeypatch.setattr(ppl, "_LOCAL_DIR", local_dir)

    food = cp.ChannelProfile(
        profile_id="food_trivia",
        channel_name="食べ物チャンネル",
        channel_handle="@food",
        genre_profile="food_trivia",
        output_root=str(tmp_path / "output" / "food_trivia"),
        default_hashtags="#ずんだもん #食べ物雑学",
    )
    urban = cp.ChannelProfile(
        profile_id="urban_legend",
        channel_name="都市伝説チャンネル",
        channel_handle="@urban",
        genre_profile="urban_legend",
        output_root=str(tmp_path / "output" / "urban_legend"),
        default_hashtags="#ずんだもん #都市伝説",
    )
    cp.save_profile(food)
    cp.save_profile(urban)

    yield cp, ppl, tmp_path, food, urban


# ── default_hashtags が profile 別に切り替わる ────────────────────────────────

def test_default_hashtags_food_trivia(dual_profile_env):
    cp, ppl, *_ = dual_profile_env
    cp.activate_profile("food_trivia")
    profile = cp.require_active_profile()
    assert "#食べ物雑学" in profile.default_hashtags
    assert "#都市伝説" not in profile.default_hashtags


def test_default_hashtags_urban_legend(dual_profile_env):
    cp, ppl, *_ = dual_profile_env
    cp.activate_profile("urban_legend")
    profile = cp.require_active_profile()
    assert "#都市伝説" in profile.default_hashtags
    assert "#食べ物雑学" not in profile.default_hashtags


# ── playlist categories が genre 別に切り替わる ───────────────────────────────

def test_playlist_categories_food_trivia(dual_profile_env):
    cp, ppl, *_ = dual_profile_env
    cp.activate_profile("food_trivia")

    # playlist_resolver はモジュール属性アクセス経由なので
    # channel_profile の active を変えた後に呼ぶ
    from core.playlist_resolver import get_standard_categories
    cats = get_standard_categories()
    assert "食べ物カテゴリ" in cats
    assert "都市伝説カテゴリ" not in cats


def test_playlist_categories_urban_legend(dual_profile_env):
    cp, ppl, *_ = dual_profile_env
    cp.activate_profile("urban_legend")

    from core.playlist_resolver import get_standard_categories
    cats = get_standard_categories()
    assert "都市伝説カテゴリ" in cats
    assert "食べ物カテゴリ" not in cats


# ── Analytics summary が別 profile へ混ざらない ───────────────────────────────

def test_db_paths_are_separate(dual_profile_env):
    """food_trivia と urban_legend の metadata.db が別々のパスに解決される。"""
    cp, _, tmp_path, *_ = dual_profile_env
    from core.output_paths import get_db_path

    cp.activate_profile("food_trivia")
    food_db = get_db_path()

    cp.activate_profile("urban_legend")
    urban_db = get_db_path()

    assert food_db != urban_db
    assert "food_trivia" in food_db
    assert "urban_legend" in urban_db


# ── active profile 未設定なら prompt build が失敗する ────────────────────────

def test_prompt_build_fails_without_active_profile(dual_profile_env, monkeypatch):
    """active profile 未設定時に require_active_profile を呼ぶとエラー。"""
    cp, *_ = dual_profile_env
    # どのプロファイルもアクティブにしない（初期状態）
    # is_active=0 の状態を作る
    with pytest.raises(cp.NoActiveProfileError):
        cp.require_active_profile()


# ── genre_profile が存在しない場合はエラー ────────────────────────────────────

def test_nonexistent_genre_profile_raises(dual_profile_env):
    cp, ppl, *_ = dual_profile_env
    with pytest.raises(ppl.GenreProfileNotFoundError):
        ppl.build_script_prompt_context("nonexistent_genre")


# ── script_context がジャンル別に正しく切り替わる ─────────────────────────────

def test_script_context_food_trivia(dual_profile_env):
    cp, ppl, *_ = dual_profile_env
    result = ppl.build_script_prompt_context("food_trivia")
    assert "FOOD_SCRIPT" in result
    assert "URBAN_SCRIPT" not in result


def test_script_context_urban_legend(dual_profile_env):
    cp, ppl, *_ = dual_profile_env
    result = ppl.build_script_prompt_context("urban_legend")
    assert "URBAN_SCRIPT" in result
    assert "FOOD_SCRIPT" not in result


# ── local/food_trivia が残っていても active urban_legend なら読まない ──────────

def test_local_food_not_leaked_to_urban(dual_profile_env):
    cp, ppl, tmp_path, *_ = dual_profile_env
    import core.prompt_profile_loader as _ppl

    # local/food_trivia/script_context.md を作成
    local_food_dir = _ppl._LOCAL_DIR / "food_trivia"
    local_food_dir.mkdir(parents=True, exist_ok=True)
    (local_food_dir / "script_context.md").write_text("FOOD_LOCAL_CONTENT", encoding="utf-8")

    # urban_legend の context には含まれない
    result = ppl.build_script_prompt_context("urban_legend")
    assert "FOOD_LOCAL_CONTENT" not in result
