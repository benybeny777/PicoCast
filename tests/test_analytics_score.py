import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.analytics_score import score_item, score_items, to_tsv


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


if __name__ == "__main__":
    unittest.main()
