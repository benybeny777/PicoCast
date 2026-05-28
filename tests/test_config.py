import config
import importlib


def test_image_style_choices_strip_env_quotes():
    choices = config._split_env_choices("'通常',’アニメ’,\"水彩\"")
    assert choices == ("通常", "アニメ", "水彩")


def test_image_style_choices_accept_tuple_repr():
    choices = config._split_env_choices("('通常', 'アニメ', '水彩')")
    assert choices == ("通常", "アニメ", "水彩")


def test_default_image_style_strips_env_quotes():
    assert config._clean_env_choice("’通常’") == "通常"


def test_libx264_default_preset_is_x264_compatible(monkeypatch):
    monkeypatch.setenv("NATIVE_FFMPEG_ENCODER", "libx264")
    monkeypatch.delenv("NATIVE_FFMPEG_PRESET", raising=False)
    reloaded = importlib.reload(config)
    try:
        assert reloaded.NATIVE_FFMPEG_PRESET == "veryfast"
    finally:
        importlib.reload(config)
