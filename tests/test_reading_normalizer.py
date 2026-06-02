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
