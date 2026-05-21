import unittest
from datetime import datetime

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


if __name__ == "__main__":
    unittest.main()
