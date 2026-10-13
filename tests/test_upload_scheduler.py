import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from core import upload_scheduler


class UploadSchedulerTests(unittest.TestCase):
    def setUp(self):
        # 実DB(settings.db)依存を排除し、スロット設定を固定してアルゴリズムを検証する。
        # 個別テストが with patch.object(...) で上書きする場合はそちらが優先される。
        patcher = patch.object(
            upload_scheduler, "_active_schedule", return_value=self._default_schedule()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _default_schedule(self):
        return SimpleNamespace(
            timezone_name="Asia/Tokyo",
            shorts_slot_hours=(7, 12, 21),
            long_slot_hours=(22,),
        )

    def _youtube_statuses(self, records):
        statuses = {}
        for idx, record in enumerate(records):
            video_id = str(record.get("video_id") or f"auto-{idx}")
            statuses[video_id] = {
                "video_type": record.get("video_type"),
                "title": record.get("title"),
                "privacyStatus": record.get("privacy_status") or record.get("privacyStatus") or "private",
                "publishAt": record.get("publish_at"),
            }
        return statuses

    def test_rebalance_builds_schedule_without_duplicate_slots(self):
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)
        schedule = {
            "2026-05-21T07:00:00+09:00": "already fixed",
            "2026-05-25T07:00:00+09:00": "future a",
            "2026-05-25T12:00:00+09:00": "future b",
            "2026-05-25T21:00:00+09:00": "future c",
        }

        with patch.object(upload_scheduler, "_active_schedule", return_value=self._default_schedule()):
            new_schedule, changes = upload_scheduler.build_rebalanced_schedule(schedule, "shorts", now)

        self.assertEqual(len(new_schedule), len(schedule))
        self.assertEqual(len(new_schedule), len(set(new_schedule)))
        self.assertEqual(new_schedule["2026-05-21T07:00:00+09:00"], "already fixed")
        self.assertEqual(new_schedule["2026-05-21T12:00:00+09:00"], "future a")
        self.assertEqual(new_schedule["2026-05-21T21:00:00+09:00"], "future b")
        self.assertEqual(new_schedule["2026-05-22T07:00:00+09:00"], "future c")
        self.assertEqual(
            changes,
            [
                ("2026-05-25T07:00:00+09:00", "2026-05-21T12:00:00+09:00", "future a"),
                ("2026-05-25T12:00:00+09:00", "2026-05-21T21:00:00+09:00", "future b"),
                ("2026-05-25T21:00:00+09:00", "2026-05-22T07:00:00+09:00", "future c"),
            ],
        )

    def test_new_slots_use_channel_schedule_defaults(self):
        now = datetime(2026, 5, 21, 6, 0, tzinfo=upload_scheduler.JST)
        current_default = SimpleNamespace(
            timezone_name="Asia/Tokyo",
            shorts_slot_hours=(12, 21),
            long_slot_hours=(22,),
        )
        with patch.object(upload_scheduler, "_active_schedule", return_value=current_default):
            shorts = upload_scheduler._assign_slots_from_used(2, "shorts", set(), now)
            long = upload_scheduler._assign_slots_from_used(1, "long", set(), now)
        self.assertEqual([s.strftime("%H:%M") for s in shorts], ["12:00", "21:00"])
        self.assertEqual([s.strftime("%H:%M") for s in long], ["22:00"])

    def test_rebalance_reads_records_without_writing_schedule_json(self):
        records = [
            {
                "video_type": "shorts",
                "title": "past",
                "publish_at": "2026-05-21T07:00:00+09:00",
                "publish_status": "scheduled",
            },
            {
                "video_type": "shorts",
                "title": "future",
                "publish_at": "2026-05-25T07:00:00+09:00",
                "publish_status": "scheduled",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots("shorts")

        self.assertEqual(changes, [("2026-05-25T07:00:00+09:00", "2026-05-21T12:00:00+09:00", "future")])

    def test_rebalance_preserves_duplicate_record_slots(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "future a",
                "publish_at": "2026-05-21T12:00:00+09:00",
                "publish_status": "scheduled",
            },
            {
                "video_id": "v2",
                "video_type": "shorts",
                "title": "future b",
                "publish_at": "2026-05-21T12:00:00+09:00",
                "publish_status": "scheduled",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots("shorts")

        self.assertEqual(changes, [("2026-05-21T12:00:00+09:00", "2026-05-21T21:00:00+09:00", "future b")])

    def test_rebalance_detailed_includes_youtube_video_id_for_duplicate_slots(self):
        records = [
            {
                "video_type": "shorts",
                "title": "same title",
                "publish_at": "2026-05-21T12:00:00+09:00",
                "publish_status": "scheduled",
            },
            {
                "video_type": "shorts",
                "title": "same title",
                "publish_at": "2026-05-21T12:00:00+09:00",
                "publish_status": "scheduled",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots_detailed("shorts")

        self.assertEqual(
            changes,
            [("2026-05-21T12:00:00+09:00", "2026-05-21T21:00:00+09:00", "same title", "auto-1", None)],
        )

    def test_long_rebalance_preserves_duplicate_record_slots(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "long",
                "title": "long a",
                "publish_at": "2026-05-23T22:00:00+09:00",
                "publish_status": "scheduled",
            },
            {
                "video_id": "v2",
                "video_type": "long",
                "title": "long b",
                "publish_at": "2026-05-23T22:00:00+09:00",
                "publish_status": "scheduled",
            },
        ]
        now = datetime(2026, 5, 22, 22, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots("long")

        self.assertEqual(changes, [("2026-05-23T22:00:00+09:00", "2026-05-24T22:00:00+09:00", "long b")])

    def test_rebalance_uses_youtube_order_without_local_generation_kind_priority(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "normal first",
                "publish_at": "2026-05-21T12:00:00+09:00",
                "publish_status": "scheduled",
            },
            {
                "video_id": "v2",
                "video_type": "shorts",
                "title": "derived later",
                "generation_kind": "横展開",
                "publish_at": "2026-05-21T21:00:00+09:00",
                "publish_status": "scheduled",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots("shorts")

        self.assertEqual(changes, [])

    def test_rebalance_preserves_youtube_order_when_slots_are_duplicated(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "normal duplicate",
                "publish_at": "2026-05-21T12:00:00+09:00",
                "publish_status": "scheduled",
            },
            {
                "video_id": "v2",
                "video_type": "shorts",
                "title": "derived duplicate",
                "generation_kind": "品質改善版",
                "publish_at": "2026-05-21T12:00:00+09:00",
                "publish_status": "scheduled",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots("shorts")

        self.assertEqual(changes, [("2026-05-21T12:00:00+09:00", "2026-05-21T21:00:00+09:00", "derived duplicate")])

    def test_rebalance_includes_unlisted_records_with_publish_at(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "unlisted future",
                "publish_at": "2026-05-25T07:00:00+09:00",
                "publish_status": "unlisted",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots("shorts")

        self.assertEqual(changes, [("2026-05-25T07:00:00+09:00", "2026-05-21T12:00:00+09:00", "unlisted future")])

    def test_rebalance_includes_empty_status_records_with_publish_at(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "empty status future",
                "publish_at": "2026-05-25T07:00:00+09:00",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots("shorts")

        self.assertEqual(changes, [("2026-05-25T07:00:00+09:00", "2026-05-21T12:00:00+09:00", "empty status future")])

    def test_sync_treats_unlisted_with_publish_at_as_scheduled(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "unlisted scheduled",
            }
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.upload_records.load_upload_records", return_value=records),
            patch("core.upload_records.save_upload_records"),
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value={
                "v1": {"privacyStatus": "unlisted", "publishAt": "2026-05-23T03:00:00Z"}
            }),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            result = upload_scheduler.sync_schedule_from_youtube()

        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(records[0]["publish_at"], "2026-05-23T12:00:00+09:00")
        self.assertEqual(records[0]["publish_status"], "scheduled")
        self.assertEqual(records[0]["privacy_status"], "unlisted")
        self.assertEqual(result["changed"], 1)

    def test_rebalance_skips_unlisted_without_publish_at(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "unlisted no schedule",
                "publish_status": "unlisted",
                "privacy_status": "unlisted",
                "uploaded_at": "2026-05-21T00:00:00+09:00",
            },
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value=self._youtube_statuses(records)),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            changes = upload_scheduler.rebalance_slots_detailed("shorts")

        self.assertEqual(changes, [])

    def test_sync_treats_unlisted_without_publish_at_as_not_scheduled(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "unlisted no schedule",
                "publish_at": "2026-05-25T07:00:00+09:00",
                "publish_status": "scheduled",
            }
        ]

        with (
            patch("core.upload_records.load_upload_records", return_value=records),
            patch("core.upload_records.save_upload_records"),
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value={
                "v1": {"privacyStatus": "unlisted", "publishAt": None}
            }),
        ):
            result = upload_scheduler.sync_schedule_from_youtube()

        self.assertIsNone(records[0]["publish_at"])
        self.assertEqual(records[0]["publish_status"], "unlisted")
        self.assertEqual(records[0]["privacy_status"], "unlisted")
        self.assertEqual(result["scheduled"], 0)
        self.assertEqual(result["changed"], 1)

    def test_sync_clears_stale_past_publish_at_with_empty_status(self):
        records = [
            {
                "video_id": "v-old",
                "video_type": "shorts",
                "title": "old stale",
                "publish_at": "2026-05-19T12:00:00+09:00",
            }
        ]

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        with (
            patch("core.upload_records.load_upload_records", return_value=records),
            patch("core.upload_records.save_upload_records"),
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value={}),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            result = upload_scheduler.sync_schedule_from_youtube()

        self.assertEqual(records[0]["publish_at"], None)
        self.assertEqual(records[0]["publish_status"], "private")
        self.assertEqual(result["changed"], 1)

    def test_long_rebalance_uses_daily_2200_only(self):
        now = datetime(2026, 5, 22, 22, 0, tzinfo=upload_scheduler.JST)
        schedule = {
            "2026-05-25T21:00:00+09:00": "future a",
            "2026-05-26T21:00:00+09:00": "future b",
        }

        new_schedule, _changes = upload_scheduler.build_rebalanced_schedule(schedule, "long", now)

        self.assertEqual(new_schedule["2026-05-23T22:00:00+09:00"], "future a")
        self.assertEqual(new_schedule["2026-05-24T22:00:00+09:00"], "future b")

    def test_sync_schedule_from_youtube_updates_local_publish_at(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "moved",
                "publish_at": "2026-05-25T07:00:00+09:00",
            }
        ]
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.upload_records.load_upload_records", return_value=records),
            patch("core.upload_records.save_upload_records"),
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value={
                "v1": {"privacyStatus": "private", "publishAt": "2026-05-23T03:00:00Z"}
            }),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            result = upload_scheduler.sync_schedule_from_youtube()

        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(records[0]["publish_at"], "2026-05-23T12:00:00+09:00")
        self.assertEqual(records[0]["publish_status"], "scheduled")
        self.assertEqual(result["changed"], 1)

    def test_sync_clears_publish_at_when_youtube_is_not_scheduled(self):
        records = [
            {
                "video_id": "v1",
                "video_type": "shorts",
                "title": "not scheduled",
                "publish_at": "2026-05-25T07:00:00+09:00",
                "publish_status": "scheduled",
            }
        ]
        with (
            patch("core.upload_records.load_upload_records", return_value=records),
            patch("core.upload_records.save_upload_records"),
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value={
                "v1": {"privacyStatus": "private", "publishAt": None}
            }),
        ):
            result = upload_scheduler.sync_schedule_from_youtube()

        self.assertEqual(result["scheduled"], 0)
        self.assertIsNone(records[0]["publish_at"])
        self.assertEqual(records[0]["publish_status"], "private")

    def test_schedule_from_records_uses_publish_at_records_except_published(self):
        records = [
            {
                "video_type": "shorts",
                "title": "scheduled",
                "publish_at": "2026-05-25T07:00:00+09:00",
                "publish_status": "scheduled",
            },
            {
                "video_type": "shorts",
                "title": "private with publish at",
                "publish_at": "2026-05-25T12:00:00+09:00",
                "publish_status": "private",
            },
            {
                "video_type": "shorts",
                "title": "published",
                "publish_at": "2026-05-25T21:00:00+09:00",
                "publish_status": "published",
            },
        ]

        schedule = upload_scheduler.schedule_from_records(records)

        self.assertIn("2026-05-25T07:00:00+09:00", schedule["shorts"])
        self.assertIn("2026-05-25T12:00:00+09:00", schedule["shorts"])
        self.assertNotIn("2026-05-25T21:00:00+09:00", schedule["shorts"])

    def test_sync_imports_scheduled_video_missing_from_local_records(self):
        records = []
        now = datetime(2026, 5, 21, 10, 0, tzinfo=upload_scheduler.JST)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with (
            patch("core.upload_records.load_upload_records", return_value=records),
            patch("core.upload_records.save_upload_records"),
            patch("core.youtube_uploader.get_channel_upload_video_statuses", return_value={
                "v-new": {
                    "privacyStatus": "private",
                    "publishAt": "2026-05-23T03:00:00Z",
                    "title": "missing scheduled",
                    "video_type": "shorts",
                    "publishedAt": "2026-05-20T00:00:00Z",
                }
            }),
            patch.object(upload_scheduler, "datetime", FixedDateTime),
        ):
            result = upload_scheduler.sync_schedule_from_youtube()

        self.assertEqual(result["scheduled"], 1)
        self.assertEqual(records[0]["video_id"], "v-new")
        self.assertEqual(records[0]["publish_status"], "scheduled")
        self.assertEqual(records[0]["publish_at"], "2026-05-23T12:00:00+09:00")
        self.assertEqual(result["changed"], 1)


if __name__ == "__main__":
    unittest.main()


import pytest as _pytest


@_pytest.mark.parametrize("call", [
    lambda us: us.assign_slots_from_youtube(1, "shorts"),
    lambda us: us.schedule_from_youtube(),
    lambda us: us.sync_schedule_from_youtube(),
])
def test_youtube_failure_stops_instead_of_guessing_from_local_records(monkeypatch, call):
    """YouTube から予約状況を取れないとき、ローカル記録だけで推定・同期しない（予約の重複を防ぐ）。"""
    import core.upload_scheduler as us
    import core.youtube_uploader as yu
    from core.error_codes import AppError

    def broken():
        raise RuntimeError("network down")

    monkeypatch.setattr(yu, "get_channel_upload_video_statuses", broken)
    monkeypatch.setattr(us, "load_upload_records", lambda: [], raising=False)
    with _pytest.raises(AppError) as exc:
        call(us)
    assert exc.value.code == "E-YOUTUBE-SCHEDULE"
