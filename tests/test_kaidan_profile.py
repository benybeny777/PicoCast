from __future__ import annotations

import sqlite3
from types import SimpleNamespace


def _profile(genre_profile: str):
    return SimpleNamespace(
        profile_id=genre_profile,
        genre_profile=genre_profile,
        default_hashtags="",
    )


def test_kowai_uses_exact_default_descriptions(monkeypatch):
    import core.channel_profile as channel_profile
    from core.youtube_metadata import optimize_description

    monkeypatch.setattr(channel_profile, "require_active_profile", lambda: _profile("zundamon_kowai"))

    shorts = optimize_description("生成された題材別説明", is_shorts=True)
    long = optimize_description("生成された題材別説明", is_shorts=False)

    assert shorts.startswith("ずんだもんと四国めたんが、怪談・都市伝説")
    assert "今回は、真偽不明ながら語り継がれている" in shorts
    assert "#ショート" in shorts
    assert "似た話が残る背景" in long
    assert "現地訪問や迷惑行為を推奨するものではありません" in long
    assert "#実話怪談" in long
    assert "生成された題材別説明" not in shorts + long


def test_food_description_behavior_is_unchanged(monkeypatch):
    import core.channel_profile as channel_profile
    from core.youtube_metadata import optimize_description

    monkeypatch.setattr(channel_profile, "require_active_profile", lambda: _profile("zunkami"))
    result = optimize_description("食べ物の題材別説明", is_shorts=True, keep_hashtags=False)

    assert "身近な食べ物雑学" in result
    assert "食べ物の題材別説明" in result
    assert "真偽不明" not in result


def test_kowai_default_tags_use_kaidan_policy(monkeypatch):
    import core.channel_profile as channel_profile
    from core.youtube_metadata import build_youtube_tags

    monkeypatch.setattr(channel_profile, "require_active_profile", lambda: _profile("zundamon_kowai"))
    tags = build_youtube_tags("東北の山間部で語られる呼ぶ声")

    assert tags[:3] == ["ずんだもん", "ゆっくり解説", "VOICEVOX"]
    assert 10 <= len(tags) <= 15
    for required in ("都市伝説・怖い話", "怖い話", "怪談", "実話怪談", "真偽不明"):
        assert required in tags
    assert "聞こえるはずのない音" in tags


def test_kowai_tags_remove_trivia_and_food_tags(monkeypatch):
    import core.channel_profile as channel_profile
    from core.youtube_metadata import optimize_tags

    monkeypatch.setattr(channel_profile, "require_active_profile", lambda: _profile("zundamon_kowai"))
    tags = optimize_tags(
        "雑学ショート,都市伝説 雑学,豆知識,トリビア,怖い雑学,食べ物雑学,食べ物の歴史,無人駅",
        title="ネットで実話扱いされたきさらぎ駅",
    ).split(",")

    assert tags[:3] == ["ずんだもん", "ゆっくり解説", "VOICEVOX"]
    assert "無人駅" in tags
    assert 10 <= len(tags) <= 15
    for forbidden in ("雑学ショート", "都市伝説 雑学", "豆知識", "トリビア", "怖い雑学", "食べ物雑学", "食べ物の歴史"):
        assert forbidden not in tags


def test_kowai_upload_metadata_reapplies_tag_policy(monkeypatch):
    import core.channel_profile as channel_profile
    from core.youtube_metadata import optimize_upload_metadata

    monkeypatch.setattr(channel_profile, "require_active_profile", lambda: _profile("zundamon_kowai"))
    _title, _description, tags = optimize_upload_metadata(
        "団地の空き部屋",
        "真偽不明の怪談です。",
        "ずんだもん,雑学ショート,食べ物雑学,トリビア",
        is_shorts=True,
        script_text="関西の団地にある空き部屋で語られた噂",
    )
    tag_list = tags.split(",")

    assert tag_list[:3] == ["ずんだもん", "ゆっくり解説", "VOICEVOX"]
    assert "団地怪談" in tag_list
    assert "雑学ショート" not in tag_list
    assert "食べ物雑学" not in tag_list
    assert "トリビア" not in tag_list


def test_food_tags_are_unchanged_by_kaidan_policy(monkeypatch):
    import core.channel_profile as channel_profile
    from core.youtube_metadata import optimize_tags

    monkeypatch.setattr(channel_profile, "require_active_profile", lambda: _profile("zunkami"))
    tags = optimize_tags("食べ物雑学,食べ物の歴史", title="プリンの歴史").split(",")

    assert tags[:3] == ["ずんだもん", "ゆっくり解説", "VOICEVOX"]
    assert "食べ物雑学" in tags
    assert "食べ物の歴史" in tags


def test_kaidan_safety_check_rejects_assertion(monkeypatch):
    import core.channel_profile as channel_profile
    from core.generation_checks import _check_kaidan_safety

    monkeypatch.setattr(channel_profile, "get_active_profile", lambda: _profile("zundamon_kowai"))
    meta = {"video_title": "実在する呪われた場所"}
    dialogue = [{"text": "これは実際に起きた話なのだ"}]

    errors = _check_kaidan_safety(meta, dialogue)

    assert any("実在する呪われた場所" in error for error in errors)
    assert any("これは実際に起きた" in error for error in errors)
    assert any("真偽不明・噂" in error for error in errors)


def test_kaidan_safety_check_accepts_uncertain_wording(monkeypatch):
    import core.channel_profile as channel_profile
    from core.generation_checks import _check_kaidan_safety

    monkeypatch.setattr(channel_profile, "get_active_profile", lambda: _profile("zundamon_kowai"))
    meta = {"video_title": "東北で語られる呼ぶ声の噂"}
    dialogue = [{"text": "実話として語られるが真偽は不明なのだ"}]

    assert _check_kaidan_safety(meta, dialogue) == []


def test_old_kowai_templates_are_preserved_and_new_defaults_are_added(tmp_path, monkeypatch):
    import core.prompt_template_store as store
    from core.prompt_template_seeder import sync_quality_rules_for_profile

    db_path = tmp_path / "settings.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE channel_profiles (profile_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO channel_profiles(profile_id) VALUES ('zundamon_kowai')")
        conn.commit()
    monkeypatch.setattr(store, "_DB_PATH", str(db_path))

    store.create_template(
        profile_id="zundamon_kowai",
        template_name="旧都市伝説台本",
        template_kind="script",
        system_rules="## 都市伝説専用の具体性",
        is_default=True,
    )
    store.create_template(
        profile_id="zundamon_kowai",
        template_name="旧都市伝説タイトル",
        template_kind="title",
        system_rules="都市伝説・怖い話専門",
        is_default=True,
    )
    store.create_template(
        profile_id="zundamon_kowai",
        template_name="旧都市伝説会議",
        template_kind="meeting",
        system_rules="### 都市伝説ネタ会議の評価軸",
        is_default=True,
    )

    assert sync_quality_rules_for_profile("zundamon_kowai", "zundamon_kowai") == 3
    templates = store.list_templates("zundamon_kowai")

    assert len(templates) == 6
    assert any(template.template_name == "旧都市伝説台本" for template in templates)
    assert store.get_default_template("zundamon_kowai", "script").template_name == "怪談・都市伝説 怪談寄りShorts台本"
    assert "怪談チャンネル安全表現ルール" in store.get_default_template("zundamon_kowai", "title").ng_rules
    assert sync_quality_rules_for_profile("zundamon_kowai", "zundamon_kowai") == 0
