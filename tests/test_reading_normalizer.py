def _set_paths(monkeypatch, tmp_path):
    import core.settings_store as settings_store
    from core import reading_dictionary_store

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))
    reading_dictionary_store.seed_initial_entries({"base": {"東京": "とうきょう"}, "user": {}})


def test_dictionary_mode_uses_configured_dictionary(monkeypatch, tmp_path):
    from config import config
    from core.reading_normalizer import ReadingNormalizer

    _set_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOICE_READING_MODE", "dictionary")

    normalizer = ReadingNormalizer()
    assert normalizer.normalize_batch(["東京の話"])["東京の話"] == "とうきょうの話"


def test_auto_dictionary_duplicate_is_distinct(monkeypatch, tmp_path):
    import core.settings_store as settings_store
    from core import reading_dictionary_store

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))
    reading_dictionary_store.seed_initial_entries({
        "base": {"薄衣": "うすごろも"},
        "user": {"薄衣": "うすぎぬ", "東京": "とうきょう"},
    })

    data = reading_dictionary_store.load_all()

    assert data["base"]["薄衣"] == "うすごろも"
    assert "薄衣" not in data["user"]
    assert data["user"]["東京"] == "とうきょう"


def test_reading_dictionary_seeds_initial_data_for_empty_db(monkeypatch, tmp_path):
    import core.settings_store as settings_store
    from core import reading_dictionary_store

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))

    data = reading_dictionary_store.load_all()

    assert data["base"]["黒板"] == "こくばん"
    assert data["user"]["東京"] == "とうきょう"


def test_safe_auto_initializes_with_sudachipy(monkeypatch, tmp_path):
    from config import config
    from core.reading_normalizer import ReadingNormalizer

    _set_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOICE_READING_MODE", "safe_auto")

    normalizer = ReadingNormalizer()
    result = normalizer.normalize_batch(["東京の話"])["東京の話"]
    assert result


def test_full_hiragana_converts_every_kanji_word(monkeypatch, tmp_path):
    """動詞・形容詞・1文字の漢字も含めて、漢字を含む語をすべてひらがなで渡す。"""
    from config import config
    from core import reading_dictionary_store
    from core.reading_normalizer import ReadingNormalizer

    _set_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOICE_READING_MODE", "full_hiragana")
    reading_dictionary_store.upsert_entry("base", "辛", "から")  # 利用者が確認した読みが優先される

    result = ReadingNormalizer().normalize_batch(["辛いカレーを食べに行く。東京の方が人が多い。3人でVOICEVOX"])
    text = next(iter(result.values()))
    assert text == "からいカレーをたべにいく。とうきょうのほうがひとがおおい。3にんでVOICEVOX"
    # 形態素解析の読みを自動学習辞書へ書き足さない（確認前の読みを固定しない）
    assert "食べ" not in reading_dictionary_store.load_dict("user")


def test_unknown_reading_mode_is_rejected(monkeypatch, tmp_path):
    import pytest
    from config import config
    from core.reading_normalizer import ReadingNormalizer

    _set_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOICE_READING_MODE", "all_kana")
    with pytest.raises(RuntimeError, match="未対応の VOICE_READING_MODE"):
        ReadingNormalizer()
