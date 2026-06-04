import unittest
from datetime import datetime

import pytest

from core import youtube_uploader


class YouTubeUploaderTests(unittest.TestCase):
    def test_youtube_publish_at_converts_jst_to_utc_z(self):
        utc_text, display = youtube_uploader._youtube_publish_at("2026-05-22T07:00:00+09:00")

        self.assertEqual(utc_text, "2026-05-21T22:00:00Z")
        self.assertEqual(display, "2026-05-22 07:00 JST")

    def test_youtube_publish_at_treats_naive_datetime_as_jst(self):
        utc_text, display = youtube_uploader._youtube_publish_at(datetime(2026, 5, 22, 7, 0))

        self.assertEqual(utc_text, "2026-05-21T22:00:00Z")
        self.assertEqual(display, "2026-05-22 07:00 JST")


def test_youtube_uploader_requires_active_profile(monkeypatch):
    import core.channel_profile as channel_profile
    from core.error_codes import AppError

    monkeypatch.setattr(channel_profile, "get_active_profile", lambda: None)

    with pytest.raises(AppError) as exc:
        youtube_uploader._resolve_profile_id(None)
    assert exc.value.code == "E-PROFILE-MISSING"


def test_youtube_analytics_requires_active_profile(monkeypatch):
    import core.channel_profile as channel_profile
    from core.error_codes import AppError
    from core import youtube_analytics

    monkeypatch.setattr(channel_profile, "get_active_profile", lambda: None)

    with pytest.raises(AppError) as exc:
        youtube_analytics._resolve_profile_id(None)
    assert exc.value.code == "E-PROFILE-MISSING"


if __name__ == "__main__":
    unittest.main()
