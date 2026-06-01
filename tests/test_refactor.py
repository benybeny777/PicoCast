"""リファクタリングヘルパーのスモークテスト。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.opening_quality import opening_score_tag
from workers import main


def test_opening_score_tag():
    assert opening_score_tag(90, ["err"]) == "score"
    assert opening_score_tag(75, ["err"]) == "score"
    assert opening_score_tag(80, []) == "score_ok"
    assert opening_score_tag(79, []) == "score_warn"
    assert opening_score_tag(70, []) == "score_warn"
    assert opening_score_tag(69, []) == "score"
    assert opening_score_tag(80) == "score_ok"
    assert opening_score_tag(75) == "score_warn"
    assert opening_score_tag(65) == "score"
    print("opening_score_tag: OK")


def test_normalize_meta_empty():
    meta = {}
    main._normalize_meta(meta, True, "test", lambda m, t="info": None)
    assert meta == {}
    print("_normalize_meta empty: OK")


def test_normalize_meta_description():
    stripped_flag = []
    def log(m, t="info"):
        if "自動除去" in m:
            stripped_flag.append(True)
    meta = {"description": "テスト\nVOICEVOX:ずんだもん"}
    main._normalize_meta(meta, True, "test", log)
    # 手書きクレジットが除去されたことをログで確認
    assert stripped_flag, "should have logged credit removal"
    # 標準VOICEVOXフッターが自動付与されること
    assert "VOICEVOX" in meta["description"]
    assert "使用音声合成" in meta["description"]
    print("_normalize_meta description: OK")


def test_normalize_meta_tags():
    meta = {"tags": "食べ物,雑学,ずんだもん", "video_title": "テスト動画"}
    main._normalize_meta(meta, True, "テスト動画", lambda m, t="info": None)
    assert "tags" in meta
    print("_normalize_meta tags: OK")


def test_effective_background_count_ignores_reuse_markers():
    items = [
        {"type": "background", "text": "古い台所"},
        {"type": "background", "text": "前と同じ"},
        {"type": "background", "text": "[再利用] 直前の背景"},
        {"type": "dialogue", "text": "これはテストなのだ"},
        {"type": "background", "text": "夜の路地"},
    ]
    assert main._effective_background_count(items, max_backgrounds=10) == 2
    assert main._effective_background_count(items, max_backgrounds=1) == 1


def test_strip_video_folder_prefix_accepts_legacy_short_prefixes():
    assert main._strip_video_folder_prefix("short_テスト") == "テスト"
    assert main._strip_video_folder_prefix("shorts_テスト") == "テスト"
    assert main._strip_video_folder_prefix("Shorts_テスト") == "テスト"


def test_resolution_label_shows_final_size_and_quality():
    assert main._resolution_label(1080, 1920, True) == "1080x1920 (SD)"
    assert main._resolution_label(1920, 1080, False) == "1920x1080 (FHD)"


def test_nanobanana_summary_uses_pixel_resolution_not_api_size_label():
    from core.image_generator import ImageGenerator

    assert ImageGenerator(width=1080, height=1920, sd_size_mode=True).nanobanana_request_summary() == (
        "Google送信設定: Nano Banana SD: 解像度: 1080x1920 (SD)"
    )
    assert ImageGenerator(width=1920, height=1080, sd_size_mode=False).nanobanana_request_summary() == (
        "Google送信設定: Nano Banana FHD: 解像度: 1920x1080 (FHD)"
    )


if __name__ == "__main__":
    test_opening_score_tag()
    test_normalize_meta_empty()
    test_normalize_meta_description()
    test_normalize_meta_tags()
    test_effective_background_count_ignores_reuse_markers()
    test_strip_video_folder_prefix_accepts_legacy_short_prefixes()
    test_resolution_label_shows_final_size_and_quality()
    test_nanobanana_summary_uses_pixel_resolution_not_api_size_label()
    print("ALL TESTS PASSED")
