"""リファクタリングヘルパーのスモークテスト。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.opening_quality import opening_score_tag, review_human_status, review_warning_text
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


def test_opening_review_warning_label_for_70s_without_must_fix():
    review = {"overall_score": 78, "score": 78, "must_fix": []}
    assert review_human_status(review) == "生成継続可 / 軽微改善推奨"
    assert review_warning_text(review) == "中止不要。冒頭改善余地あり"


def test_save_opening_review_keeps_debug_in_db_payload(tmp_path, monkeypatch):
    import core.metadata_db as m
    from core.opening_quality import save_opening_review

    saved = {}
    monkeypatch.setattr(m, "is_initialized", lambda: True)
    monkeypatch.setattr(m, "upsert_opening_review", lambda local_id, data: saved.update({"local_id": local_id, "data": data}))
    theme_dir = tmp_path / "Shorts_test"
    theme_dir.mkdir()
    save_opening_review(
        str(theme_dir),
        {"score": 80, "status": "pass"},
        {
            "score": 78,
            "status": "warning",
            "review_debug": {
                "model": "qwen-test",
                "prompt_version": "ollama_opening_review_v2",
                "raw_response": "{\"overall_score\":78}",
                "parsed_score": 78,
                "parsed_subscores": {"hook": 70},
                "warning_text": "中止不要。冒頭改善余地あり",
            },
        },
        None,
    )

    debug_path = theme_dir / "_meta" / "review_debug.json"
    assert not debug_path.exists()
    assert saved["data"]["llm_review"]["review_debug"]["model"] == "qwen-test"


if __name__ == "__main__":
    test_opening_score_tag()
    test_normalize_meta_empty()
    test_normalize_meta_description()
    test_normalize_meta_tags()
    test_effective_background_count_ignores_reuse_markers()
    test_strip_video_folder_prefix_accepts_legacy_short_prefixes()
    test_resolution_label_shows_final_size_and_quality()
    test_nanobanana_summary_uses_pixel_resolution_not_api_size_label()
    test_opening_review_warning_label_for_70s_without_must_fix()
    print("ALL TESTS PASSED")
