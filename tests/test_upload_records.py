import unittest
from unittest.mock import patch

from core import upload_records


class UploadRecordsTests(unittest.TestCase):
    def test_find_upload_record_uses_title_when_publish_at_is_duplicated(self):
        records = [
            {
                "title": "first",
                "video_type": "shorts",
                "publish_at": "2026-05-21T07:00:00+09:00",
                "video_id": "wrong",
            },
            {
                "title": "second",
                "video_type": "shorts",
                "publish_at": "2026-05-21T07:00:00+09:00",
                "video_id": "right",
            },
        ]

        with patch.object(upload_records, "load_upload_records", return_value=records):
            record = upload_records.find_upload_record(
                title="second",
                video_type="shorts",
                publish_at="2026-05-21T07:00:00+09:00",
            )

        self.assertEqual(record["video_id"], "right")


if __name__ == "__main__":
    unittest.main()
