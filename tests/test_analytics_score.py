import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.analytics_score import (
    build_performance_summary,
    build_shorts_title_prompt,
    score_item,
    score_items,
    to_tsv,
)


def _short(**overrides):
    item = {
        "title": "test",
        "published_at": "2026-05-13T12:00:00Z",
        "duration": 45,
        "publish_status": "published",
        "analytics_available": True,
        "views": 1052,
        "impressions": 0,
        "average_view_duration": 31.5,
        "average_percentage_viewed": 70.03,
        "likes": 0,
        "comments": 1,
        "subscribers_gained": 0,
        "subscribers_lost": 0,
    }
    item.update(overrides)
    return item


class AnalyticsScoreTests(unittest.TestCase):
    def test_old_short_with_signal_gets_audio_cutoff_improvement_candidate(self):
        result = score_item(_short())

        self.assertIs(result["audio_cutoff_risk"], True)
        self.assertIn("音切れ改善候補", result["action"])

    def test_newer_short_does_not_get_audio_cutoff_improvement_candidate(self):
        result = score_item(_short(
            published_at="2026-05-18T12:00:00Z",
            views=1246,
            average_percentage_viewed=84.44,
        ))

        self.assertIs(result["audio_cutoff_risk"], False)
        self.assertNotIn("音切れ改善候補", result["action"])

    def test_old_short_without_signal_keeps_risk_but_no_improvement_candidate(self):
        result = score_item(_short(
            published_at="2026-05-15T12:00:00Z",
            views=99,
            average_view_duration=9,
            average_percentage_viewed=20,
            likes=0,
            comments=0,
            subscribers_gained=0,
            subscribers_lost=0,
        ))

        self.assertIs(result["audio_cutoff_risk"], True)
        self.assertNotIn("音切れ改善候補", result["action"])

    def test_audio_cutoff_risk_boundary_date_is_inclusive(self):
        result = score_item(_short(published_at="2026-05-16T23:59:59Z"))

        self.assertIs(result["audio_cutoff_risk"], True)

    def test_audio_cutoff_risk_day_after_boundary_is_false(self):
        result = score_item(_short(published_at="2026-05-17T00:00:00Z"))

        self.assertIs(result["audio_cutoff_risk"], False)

    def test_tsv_includes_audio_cutoff_risk_column(self):
        items = score_items([_short()])
        tsv = to_tsv(items)

        header, first_row = tsv.splitlines()[:2]
        self.assertIn("audio_cutoff_risk", header.split("\t"))
        self.assertIn("True", first_row.split("\t"))

    def test_tsv_includes_topic_request_cta_columns(self):
        items = score_items([_short(topic_request_cta="許可", topic_request_cta_reason="通算5本目", final_cta_type="topic_request")])
        tsv = to_tsv(items)

        header, first_row = tsv.splitlines()[:2]
        columns = header.split("\t")
        values = first_row.split("\t")
        self.assertIn("topic_request_cta", columns)
        self.assertIn("topic_request_cta_reason", columns)
        self.assertIn("final_cta_type", columns)
        self.assertEqual(values[columns.index("topic_request_cta")], "許可")

    def test_single_strong_short_is_reference_observation_not_expansion(self):
        result = score_items([_short(
            title="単発の強い動画",
            views=8000,
            average_view_duration=40,
            average_percentage_viewed=82,
            likes=160,
            comments=3,
            subscribers_gained=2,
            genre_group="名前の勘違い",
        )])[0]

        self.assertIn("参考観察・単発", result["action"])
        self.assertNotIn("横展開", result["action"])
        self.assertTrue(result["expansion_eligible"])

    def test_two_strong_shorts_with_same_pattern_become_expansion_candidates(self):
        common = {
            "views": 8000,
            "average_view_duration": 40,
            "average_percentage_viewed": 82,
            "likes": 160,
            "comments": 3,
            "subscribers_gained": 2,
            "genre_group": "名前の勘違い",
        }
        results = score_items([
            _short(title="候補1", **common),
            _short(title="候補2", **common),
        ])

        self.assertTrue(all("横展開候補" in item["action"] for item in results))

    def test_data_wait_never_becomes_expansion_candidate(self):
        result = score_items([_short(
            analytics_available=False,
            views=50000,
            likes=5000,
            comments=100,
            subscribers_gained=100,
            genre_group="名前の勘違い",
        )])[0]

        self.assertEqual(result["analysis_status"], "data_wait")
        self.assertEqual(result["action"], "データ待ち")
        self.assertFalse(result.get("expansion_eligible", False))

    def test_low_view_video_is_not_called_expansion_even_with_retention(self):
        result = score_items([_short(
            views=1800,
            average_view_duration=40,
            average_percentage_viewed=82,
            likes=60,
            comments=3,
            subscribers_gained=2,
            genre_group="名前の勘違い",
        )])[0]

        self.assertNotIn("横展開", result["action"])
        self.assertFalse(result["expansion_eligible"])

    def test_summary_and_title_prompt_prioritize_new_exploration_without_expansion(self):
        items = score_items([_short(title="参考動画", views=1800, genre_group="名前の勘違い")])

        summary = build_performance_summary(items)
        prompt = build_shorts_title_prompt(items)

        self.assertIn("横展開対象: なし", summary)
        self.assertIn("今回の主軸: 新規開拓枠", summary)
        self.assertIn("data_waitは横展開根拠にしない", prompt)
        self.assertIn("同じ構造で2本以上", prompt)
        self.assertNotIn("【弱い動画ランキング", summary)

    def test_expansion_criteria_text_follows_current_settings(self):
        from unittest import mock

        import config.config as cfg
        from core.analytics_score import expansion_criteria_lines

        with mock.patch.object(cfg, "ANALYTICS_EXPANSION_MIN_VIEWS_SHORTS", 6000), \
                mock.patch.object(cfg, "ANALYTICS_EXPANSION_MIN_PATTERN_COUNT", 3):
            text = "\n".join(expansion_criteria_lines())

        self.assertIn("再生数6,000以上", text)
        self.assertIn("同じ構造で3本以上", text)


if __name__ == "__main__":
    unittest.main()
