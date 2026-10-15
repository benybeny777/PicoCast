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
    assert by_key["zundamon"]["portrait_png_path"] == "asset:assets/characters/zundamon.png"
    assert by_key["reimu"]["portrait_png_path"] == "asset:assets/characters/reimu.png"
    assert by_key["metan_food_toxic"]["enabled"] is True
    assert by_key["metan_standard_toxic"]["enabled"] is False
    assert by_key["reimu"]["enabled"] is False
    assert by_key["marisa"]["enabled"] is False


def test_kaidan_genre_enables_viewer_metan():
    """怪談チャンネル: 視聴者目線めたんだけを有効にする。"""
    from core.character_profiles_seed import _seed_set_for_genre
    by_key = {c["character_key"]: c for c in _seed_set_for_genre("zundamon_kowai")}
    assert by_key["metan_kaidan_viewer"]["enabled"] is True
    assert by_key["metan_standard_toxic"]["enabled"] is False
    assert by_key["metan_food_toxic"]["enabled"] is False
    assert "説明しない" in by_key["metan_kaidan_viewer"]["role"]


def test_food_toxic_genres_are_configurable(monkeypatch):
    """辛口相方めたんを既定有効にするジャンルは設定から差し替えられる。"""
    import core.character_profiles_seed as cps

    monkeypatch.setattr(cps, "CHARACTER_FOOD_TOXIC_GENRE_PROFILES", ("custom_food",))
    custom = {c["character_key"]: c for c in cps._seed_set_for_genre("custom_food")}
    default = {c["character_key"]: c for c in cps._seed_set_for_genre("zunkami")}

    assert custom["metan_food_toxic"]["enabled"] is True
    assert custom["metan_standard_toxic"]["enabled"] is False
    assert default["metan_food_toxic"]["enabled"] is False
    assert default["metan_standard_toxic"]["enabled"] is True


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
    assert "説明密度・掛け合い品質ルール" in rules
    assert "機械的な交互会話" in rules
    assert "2〜4行連続" in rules
    assert "めたんは毎回返事をしなくてよい" in rules
    assert "相槌・復唱・空会話で増やさない" in rules
    assert "ずんだもんが事実・理由・背景" in rules


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


def test_store_enables_same_character_name_exclusively(tmp_char_store):
    """同じチャンネル・同じキャラ名のバリアントは1つだけ有効にする。"""
    s = tmp_char_store
    food_id = s.create_character(profile_id="zunkami", character_key="metan_food_toxic",
                                 display_name="辛口相方めたん", character_name="四国めたん", enabled=True, sort_order=20)
    standard_id = s.create_character(profile_id="zunkami", character_key="metan_standard_toxic",
                                     display_name="標準めたん", character_name="四国めたん", enabled=False, sort_order=30)
    s.enable_character_exclusive(standard_id)

    chars = {c.character_key: c for c in s.list_characters("zunkami")}
    assert chars["metan_food_toxic"].enabled is False
    assert chars["metan_standard_toxic"].enabled is True
    assert food_id != standard_id


def test_store_create_enabled_disables_same_character_name(tmp_char_store):
    """追加時に有効指定した場合も、既存の同名キャラを無効化する。"""
    s = tmp_char_store
    s.create_character(profile_id="zunkami", character_key="metan_food_toxic",
                       display_name="辛口相方めたん", character_name="四国めたん", enabled=True, sort_order=20)
    s.create_character(profile_id="zunkami", character_key="metan_standard_toxic",
                       display_name="標準めたん", character_name="四国めたん", enabled=True, sort_order=30)

    enabled = s.list_characters("zunkami", enabled_only=True)
    assert [c.character_key for c in enabled] == ["metan_standard_toxic"]


def test_store_normalizes_portrait_path_under_resource_root(tmp_char_store, tmp_path, monkeypatch):
    """同梱リソース配下の絶対パスはDB保存時に asset: 参照へ寄せる。"""
    import core.path_refs as refs

    resource_root = tmp_path / "bundle"
    portrait = resource_root / "assets" / "characters" / "reimu.png"
    monkeypatch.setattr(refs, "resource_base_dir", lambda: str(resource_root))
    monkeypatch.setattr(refs, "app_base_dir", lambda: str(tmp_path / "app"))

    s = tmp_char_store
    s.create_character(profile_id="zunkami", character_key="reimu",
                       display_name="霊夢", character_name="霊夢",
                       portrait_png_path=str(portrait), enabled=True, sort_order=40)

    chars = {c.character_key: c for c in s.list_characters("zunkami")}
    assert chars["reimu"].portrait_png_path == "asset:assets/characters/reimu.png"


def test_store_update_enabled_true_is_exclusive(tmp_char_store):
    """update_character で有効化しても同名キャラの排他制御を通る。"""
    s = tmp_char_store
    s.create_character(profile_id="zunkami", character_key="metan_food_toxic",
                       display_name="辛口相方めたん", character_name="四国めたん", enabled=True, sort_order=20)
    standard_id = s.create_character(profile_id="zunkami", character_key="metan_standard_toxic",
                                     display_name="標準めたん", character_name="四国めたん", enabled=False, sort_order=30)
    s.update_character(standard_id, enabled=True)

    enabled = s.list_characters("zunkami", enabled_only=True)
    assert [c.character_key for c in enabled] == ["metan_standard_toxic"]


def test_store_resolves_profile_voice_settings(tmp_char_store):
    """キャラ設定に保存した音声バックエンド・話者IDを生成側で解決できる。"""
    s = tmp_char_store
    s.create_character(profile_id="zunkami", character_key="reimu",
                       display_name="霊夢", character_name="霊夢",
                       voice_backend="voicevox", voice_speaker="8",
                       voice_styles={"怒り": 9}, enabled=True, sort_order=40)
    assert s.resolve_character_voice("zunkami", "霊夢", "ノーマル") == 8
    assert s.resolve_character_voice("zunkami", "霊夢", "怒り") == 9


def test_store_rejects_unimplemented_voice_backend(tmp_char_store):
    """VOICEVOX以外のバックエンド設定は保存できるが、生成は未実装として止める。"""
    s = tmp_char_store
    s.create_character(profile_id="zunkami", character_key="external",
                       display_name="外部キャラ", character_name="外部キャラ",
                       voice_backend="external_tts", voice_speaker="speaker-a",
                       enabled=True, sort_order=40)
    with pytest.raises(RuntimeError, match="未対応"):
        s.resolve_character_voice("zunkami", "外部キャラ", "ノーマル")


def test_store_builds_character_credit_block(tmp_char_store):
    """使用キャラのクレジット表記をキャラ設定から組み立てられる。"""
    s = tmp_char_store
    s.create_character(profile_id="zunkami", character_key="reimu",
                       display_name="霊夢", character_name="霊夢",
                       voice_backend="voicevox", voice_speaker="8",
                       credit_text="VOICEVOX:テスト霊夢",
                       enabled=True, sort_order=40)
    s.create_character(profile_id="zunkami", character_key="no_credit",
                       display_name="表示しない", character_name="表示しない",
                       voice_backend="voicevox", voice_speaker="9",
                       credit_required=False,
                       enabled=True, sort_order=41)
    block = s.build_character_credit_block("zunkami", ["霊夢", "表示しない", "霊夢"])
    assert "【使用音声合成】" in block
    assert "VOICEVOX:テスト霊夢" in block
    assert "表示しない" not in block


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
