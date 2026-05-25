"""リファクタリングヘルパーのスモークテスト。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.opening_quality import opening_score_tag
import main


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


if __name__ == "__main__":
    test_opening_score_tag()
    test_normalize_meta_empty()
    test_normalize_meta_description()
    test_normalize_meta_tags()
    print("ALL TESTS PASSED")
