"""リファクタリングヘルパーのスモークテスト。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.opening_quality import opening_score_tag, review_human_status, review_warning_text
from workers import main
from workers import pipeline_helpers
from workers import pipeline_metadata
from workers.pipeline_models import GenerationReport, fallback_title_variants


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
    pipeline_metadata.normalize_metadata(
        meta,
        True,
        "test",
        lambda m, t="info": None,
    )
    assert meta == {}
    print("_normalize_meta empty: OK")


def test_normalize_meta_description():
    stripped_flag = []
    def log(m, t="info"):
        if "自動除去" in m:
            stripped_flag.append(True)
    meta = {"description": "テスト\nVOICEVOX:ずんだもん"}
    pipeline_metadata.normalize_metadata(meta, True, "test", log)
    # 手書きクレジットが除去されたことをログで確認
    assert stripped_flag, "should have logged credit removal"
    # 標準VOICEVOXフッターが自動付与されること
    assert "VOICEVOX" in meta["description"]
    assert "使用音声合成" in meta["description"]
    print("_normalize_meta description: OK")


def test_normalize_meta_tags():
    meta = {"tags": "食べ物,雑学,ずんだもん", "video_title": "テスト動画"}
    pipeline_metadata.normalize_metadata(
        meta,
        True,
        "テスト動画",
        lambda m, t="info": None,
    )
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


def test_character_names_for_credits_preserves_dialogue_order():
    items = [
        {"type": "background", "text": "背景"},
        {"type": "dialogue", "character": "ずんだもん"},
        {"type": "dialogue", "character": "四国めたん"},
        {"type": "dialogue", "character": "ずんだもん"},
    ]
    assert pipeline_metadata.character_names_for_credits(items) == [
        "ずんだもん",
        "四国めたん",
    ]


def test_strip_video_folder_prefix_accepts_legacy_short_prefixes():
    assert main._strip_video_folder_prefix("short_テスト") == "テスト"
    assert main._strip_video_folder_prefix("shorts_テスト") == "テスト"
    assert main._strip_video_folder_prefix("Shorts_テスト") == "テスト"


def test_background_filename_format():
    assert pipeline_helpers.background_filename(4) == "bg_004_001.png"
    assert pipeline_helpers.background_filename(12) == "bg_012_001.png"


def test_background_reuse_is_filename_based_not_index(tmp_path):
    # 欠番（bg_004）がある状態でも、再利用は番号一致のファイルだけを使い、
    # 欠番は「存在しない」と判定される（=再生成対象になる）こと。
    import os
    for n in (1, 2, 3, 5, 6, 7, 8):  # bg_004 が欠番
        (tmp_path / pipeline_helpers.background_filename(n)).write_bytes(b"x")
    reuse, regen = [], []
    for n in range(1, 9):
        if os.path.isfile(os.path.join(str(tmp_path), pipeline_helpers.background_filename(n))):
            reuse.append(n)
        else:
            regen.append(n)
    assert reuse == [1, 2, 3, 5, 6, 7, 8]
    assert regen == [4]  # 旧実装は範囲外で bg_008 を落とし bg_004 を作らなかった


def test_cleanup_orphan_audio(tmp_path):
    # 期待ファイル名に無い .wav（台本変更で不要になった旧音声）だけ削除する
    for name in ("001_001_a.wav", "001_002_b.wav", "099_009_old.wav", "memo.txt"):
        (tmp_path / name).write_bytes(b"x")
    expected = {"001_001_a.wav", "001_002_b.wav"}
    removed = pipeline_helpers.cleanup_orphan_audio(str(tmp_path), expected)
    assert removed == 1
    assert not (tmp_path / "099_009_old.wav").exists()
    assert (tmp_path / "001_001_a.wav").exists()
    assert (tmp_path / "memo.txt").exists()  # 非WAVは触らない
    # expected が空なら安全側に倒して何も消さない
    assert pipeline_helpers.cleanup_orphan_audio(str(tmp_path), set()) == 0
    assert (tmp_path / "001_001_a.wav").exists()


def test_sd_webui_error_carries_code():
    from core.image_generator import ImageGenerationError
    # SD WebUI 経路の失敗もカテゴリ→コードに分類される
    assert ImageGenerationError("x", category="api_busy", backend="sd_webui").code == "E-IMG-BUSY"
    assert ImageGenerationError("x", category="generic", backend="sd_webui").code == "E-IMG-FAIL"


def test_resolution_label_shows_final_size():
    assert pipeline_helpers.resolution_label(1080, 1920) == "1080x1920"
    assert pipeline_helpers.resolution_label(1920, 1080) == "1920x1080"


def test_script_format_detection():
    assert pipeline_helpers.detect_is_shorts("動画形式: Shorts")
    assert pipeline_helpers.detect_is_shorts("Format: ショート")
    assert not pipeline_helpers.detect_is_shorts("動画形式: Long")
    assert pipeline_helpers.detect_is_netakaigi("動画形式: ネタ会議Long")
    assert pipeline_helpers.detect_netakaigi_variant(
        "動画形式: ネタ会議\n画面形式: 横"
    ) == "Long"
    assert pipeline_helpers.detect_netakaigi_variant(
        "動画形式: ネタ会議"
    ) == "Shorts"


def test_split_at_punctuation_keeps_consecutive_marks():
    assert pipeline_helpers.split_at_punctuation("本当！？次なのだ。") == [
        "本当！？",
        "次なのだ。",
    ]


def test_generation_report_summary():
    report = GenerationReport(
        voices_generated=3,
        voices_failed=1,
        backgrounds_generated=2,
        backgrounds_failed=0,
        elapsed_sec=65,
    )
    assert report.summary() == (
        "⏱  所要時間: 1分5秒\n"
        "🎤 音声: 生成=3 / 失敗=1\n"
        "🖼  背景: 生成=2 / 失敗=0"
    )


def test_fallback_title_variants_are_complete_and_bounded():
    variants = fallback_title_variants("長" * 50)
    assert [item["variant"] for item in variants] == ["A", "B", "C"]
    assert all(len(item["title"]) <= 45 for item in variants)


def test_nanobanana_summary_shows_final_size():
    from core.image_generator import ImageGenerator

    assert ImageGenerator(width=1080, height=1920).nanobanana_request_summary() == (
        "Google送信設定: Nano Banana 1080x1920"
    )
    assert ImageGenerator(width=1920, height=1080).nanobanana_request_summary() == (
        "Google送信設定: Nano Banana 1920x1080"
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
    test_nanobanana_summary_shows_sd_to_fhd_arrow()
    test_opening_review_warning_label_for_70s_without_must_fix()
    print("ALL TESTS PASSED")
