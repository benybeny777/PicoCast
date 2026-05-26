import json

import pytest


def _set_paths(monkeypatch, tmp_path):
    import config

    base_path = tmp_path / "base.json"
    user_path = tmp_path / "user.json"
    cand_path = tmp_path / "candidates.json"
    base_path.write_text(json.dumps({"東京": "とうきょう"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "VOICE_READING_BASE_DICT_PATH", str(base_path))
    monkeypatch.setattr(config, "VOICE_READING_USER_DICT_PATH", str(user_path))
    monkeypatch.setattr(config, "VOICE_READING_CANDIDATES_PATH", str(cand_path))
    return base_path, user_path, cand_path


def test_dictionary_mode_uses_configured_dictionary(monkeypatch, tmp_path):
    import config
    from core.reading_normalizer import ReadingNormalizer

    _set_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOICE_READING_MODE", "dictionary")

    normalizer = ReadingNormalizer()
    assert normalizer.normalize_batch(["東京の話"])["東京の話"] == "とうきょうの話"


def test_invalid_dictionary_json_aborts(monkeypatch, tmp_path):
    import config
    from core.reading_normalizer import ReadingNormalizer

    base_path, user_path, cand_path = _set_paths(monkeypatch, tmp_path)
    base_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config, "VOICE_READING_MODE", "dictionary")

    with pytest.raises(RuntimeError, match="同梱辞書が不正"):
        ReadingNormalizer()


def test_safe_auto_initializes_with_sudachipy(monkeypatch, tmp_path):
    import config
    from core.reading_normalizer import ReadingNormalizer

    _set_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOICE_READING_MODE", "safe_auto")

    normalizer = ReadingNormalizer()
    result = normalizer.normalize_batch(["東京の話"])["東京の話"]
    assert result
