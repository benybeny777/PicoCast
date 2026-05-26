import config


def test_image_style_choices_strip_env_quotes():
    choices = config._split_env_choices("'通常',’アニメ’,\"水彩\"")
    assert choices == ("通常", "アニメ", "水彩")


def test_image_style_choices_accept_tuple_repr():
    choices = config._split_env_choices("('通常', 'アニメ', '水彩')")
    assert choices == ("通常", "アニメ", "水彩")


def test_default_image_style_strips_env_quotes():
    assert config._clean_env_choice("’通常’") == "通常"
