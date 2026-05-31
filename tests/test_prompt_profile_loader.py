"""
core/prompt_profile_loader.py のユニットテスト。

- genre_profile が存在しない場合はエラー
- food_trivia profile では urban_legend の prompt file を読まない
- urban_legend profile では food_trivia の prompt file を読まない
- playlist_categories / default_hashtags が正しく返る

ローカル上書き (local/) は廃止済みのためテスト対象外。
外部API実通信なし。
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture()
def fake_genres(tmp_path, monkeypatch):
    """一時ディレクトリに genres/food_trivia/ と genres/urban_legend/ を作成する。"""
    import core.prompt_profile_loader as ppl

    profiles_dir = tmp_path / "prompt_profiles"
    genres_dir = profiles_dir / "genres"
    (genres_dir / "food_trivia").mkdir(parents=True)
    (genres_dir / "urban_legend").mkdir(parents=True)

    (genres_dir / "food_trivia" / "script_context.md").write_text(
        "food_trivia script context", encoding="utf-8"
    )
    (genres_dir / "food_trivia" / "title_context.md").write_text(
        "food_trivia title context", encoding="utf-8"
    )
    (genres_dir / "food_trivia" / "meeting_context.md").write_text(
        "food_trivia meeting context", encoding="utf-8"
    )
    (genres_dir / "food_trivia" / "profile.yaml").write_text(
        "genre_profile: food_trivia\ndefault_hashtags: '#食べ物'", encoding="utf-8"
    )
    (genres_dir / "food_trivia" / "playlist_categories.md").write_text(
        "# categories\n食べ物カテゴリA\n食べ物カテゴリB", encoding="utf-8"
    )

    (genres_dir / "urban_legend" / "script_context.md").write_text(
        "urban_legend script context", encoding="utf-8"
    )
    (genres_dir / "urban_legend" / "title_context.md").write_text(
        "urban_legend title context", encoding="utf-8"
    )
    (genres_dir / "urban_legend" / "profile.yaml").write_text(
        "genre_profile: urban_legend\ndefault_hashtags: '#都市伝説'", encoding="utf-8"
    )
    (genres_dir / "urban_legend" / "playlist_categories.md").write_text(
        "# categories\n都市伝説カテゴリA", encoding="utf-8"
    )

    monkeypatch.setattr(ppl, "_PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(ppl, "_GENRES_DIR", genres_dir)
    yield ppl, genres_dir


# ── genre_profile 存在チェック ────────────────────────────────────────────────

def test_validate_existing_genre_ok(fake_genres):
    ppl, *_ = fake_genres
    ppl.validate_genre_profile_exists("food_trivia")


def test_validate_missing_genre_raises(fake_genres):
    ppl, *_ = fake_genres
    with pytest.raises(ppl.GenreProfileNotFoundError):
        ppl.validate_genre_profile_exists("nonexistent_genre")


def test_list_available_genre_profiles(fake_genres):
    ppl, *_ = fake_genres
    profiles = ppl.list_available_genre_profiles()
    assert "food_trivia" in profiles
    assert "urban_legend" in profiles


# ── script_context 読み込み ────────────────────────────────────────────────────

def test_build_script_prompt_context_food_trivia(fake_genres):
    ppl, *_ = fake_genres
    result = ppl.build_script_prompt_context("food_trivia")
    assert "food_trivia script context" in result
    assert "urban_legend" not in result


def test_build_script_prompt_context_urban_legend(fake_genres):
    ppl, *_ = fake_genres
    result = ppl.build_script_prompt_context("urban_legend")
    assert "urban_legend script context" in result
    assert "food_trivia" not in result


# ── ジャンル分離チェック ──────────────────────────────────────────────────────

def test_food_trivia_does_not_read_urban_legend_files(fake_genres):
    ppl, genres_dir = fake_genres
    (genres_dir / "urban_legend" / "script_context.md").write_text(
        "URBAN_LEGEND_UNIQUE_MARKER", encoding="utf-8"
    )
    result = ppl.build_script_prompt_context("food_trivia")
    assert "URBAN_LEGEND_UNIQUE_MARKER" not in result


def test_urban_legend_does_not_read_food_trivia_files(fake_genres):
    ppl, genres_dir = fake_genres
    (genres_dir / "food_trivia" / "script_context.md").write_text(
        "FOOD_TRIVIA_UNIQUE_MARKER", encoding="utf-8"
    )
    result = ppl.build_script_prompt_context("urban_legend")
    assert "FOOD_TRIVIA_UNIQUE_MARKER" not in result


# ── playlist_categories ───────────────────────────────────────────────────────

def test_get_playlist_categories_food_trivia(fake_genres):
    ppl, *_ = fake_genres
    cats = ppl.get_playlist_categories("food_trivia")
    assert "食べ物カテゴリA" in cats
    assert "食べ物カテゴリB" in cats
    assert "都市伝説カテゴリA" not in cats


def test_get_playlist_categories_urban_legend(fake_genres):
    ppl, *_ = fake_genres
    cats = ppl.get_playlist_categories("urban_legend")
    assert "都市伝説カテゴリA" in cats
    assert "食べ物カテゴリA" not in cats


# ── default_hashtags ──────────────────────────────────────────────────────────

def test_get_default_hashtags_food_trivia(fake_genres):
    ppl, *_ = fake_genres
    ht = ppl.get_default_hashtags("food_trivia")
    assert "#食べ物" in ht


def test_get_default_hashtags_urban_legend(fake_genres):
    ppl, *_ = fake_genres
    ht = ppl.get_default_hashtags("urban_legend")
    assert "#都市伝説" in ht
