"""キャラクター設定の分離・合成・チャンネル分離のテスト。"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── seed セットのジャンル分岐 ──────────────────────────────────────────────────

def test_food_genre_enables_toxic_metan():
    """食べ物雑学堂: 両めたんを投入するが、enabled は辛口相方のみ。"""
    from core.character_profiles_seed import _seed_set_for_genre
    by_key = {c["character_key"]: c for c in _seed_set_for_genre("zunkami")}
    assert "zundamon" in by_key
    assert by_key["metan_food_toxic"]["enabled"] is True
    assert by_key["metan_standard_toxic"]["enabled"] is False


def test_urban_genre_enables_standard_metan():
    """都市伝説: 両めたんを投入するが、enabled はお嬢様毒舌のみ。"""
    from core.character_profiles_seed import _seed_set_for_genre
    by_key = {c["character_key"]: c for c in _seed_set_for_genre("zundamon_kowai")}
    assert by_key["metan_standard_toxic"]["enabled"] is True
    assert by_key["metan_food_toxic"]["enabled"] is False


# ── 合成（compose） ────────────────────────────────────────────────────────────

def _fake_char(**kw):
    from core.character_profile_store import CharacterProfile
    base = dict(
        character_id="x", profile_id="p", character_key="k", display_name="d",
        character_name="四国めたん", role="", tone_style="", speaking_rules="",
        forbidden_phrases="", dialogue_rules="", enabled=True, sort_order=0,
        created_at="t", updated_at="t",
    )
    base.update(kw)
    return CharacterProfile(**base)


def test_compose_raises_without_characters(monkeypatch):
    import core.character_profiles_seed as cps
    monkeypatch.setattr(cps, "list_characters", lambda pid, enabled_only=False: [])
    with pytest.raises(RuntimeError):
        cps.compose_character_section("nobody")


def test_compose_includes_role_and_tone(monkeypatch):
    import core.character_profiles_seed as cps
    chars = [
        _fake_char(character_name="ずんだもん", display_name="ナビ", role="情報を出す", tone_style="〜なのだ"),
        _fake_char(character_name="四国めたん", display_name="辛口相方", tone_style="あんたを使う", forbidden_phrases="なるほどですわ"),
    ]
    monkeypatch.setattr(cps, "list_characters", lambda pid, enabled_only=False: chars)
    text = cps.compose_character_section("p")
    assert "キャラクター設定" in text
    assert "ずんだもん" in text and "四国めたん" in text
    assert "あんた" in text
    assert "なるほどですわ" in text  # 禁止表現として列挙される


# ── 共通ルールからキャラ設定が分離されていること ─────────────────────────────

def test_common_script_rules_excludes_character_block():
    from core.prompt_template_seeder import _load_common_script_rules
    rules = _load_common_script_rules("zunkami")
    # キャラ設定の長文（旧めたん毒舌ルール）はテンプレート側に含めない
    assert "四国めたん 役割固定ルール" not in rules
    # 構成・分量ルールは維持
    assert "native Shorts 台本量" in rules or "分量ルール" in rules


# ── ストア CRUD（tmp DB） ──────────────────────────────────────────────────────

@pytest.fixture()
def tmp_char_store(tmp_path, monkeypatch):
    import core.character_profile_store as cps_store
    db = tmp_path / "settings.db"
    # FK 参照先 channel_profiles を最小構成で用意する
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE channel_profiles (profile_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO channel_profiles(profile_id) VALUES ('zunkami')")
        conn.commit()
    monkeypatch.setattr(cps_store, "_DB_PATH", str(db))
    return cps_store


def test_store_create_list_enabled(tmp_char_store):
    s = tmp_char_store
    s.create_character(profile_id="zunkami", character_key="metan_food_toxic",
                       display_name="辛口相方めたん", character_name="四国めたん", enabled=True, sort_order=20)
    s.create_character(profile_id="zunkami", character_key="metan_standard_toxic",
                       display_name="標準めたん", character_name="四国めたん", enabled=False, sort_order=30)
    assert s.has_characters("zunkami")
    enabled = s.list_characters("zunkami", enabled_only=True)
    assert [c.character_key for c in enabled] == ["metan_food_toxic"]


# ── API（別 profile 改変防止） ─────────────────────────────────────────────────

def test_api_update_rejects_other_profile_character(monkeypatch):
    import core.channel_profile as cp
    import core.character_profile_store as store
    from web_app.routes.api_character_profiles import update_character_profile, CharacterUpdateRequest
    from fastapi import HTTPException
    from types import SimpleNamespace

    monkeypatch.setattr(cp, "require_active_profile", lambda: SimpleNamespace(profile_id="zunkami"))
    # active profile には character_id 'mine' しか無い
    monkeypatch.setattr(store, "list_characters", lambda pid, enabled_only=False: [
        store.CharacterProfile("mine", "zunkami", "k", "d", "四国めたん", "", "", "", "", "", True, 0, "t", "t")
    ])
    with pytest.raises(HTTPException) as exc:
        update_character_profile("other", CharacterUpdateRequest(enabled=False))
    assert exc.value.status_code == 404
