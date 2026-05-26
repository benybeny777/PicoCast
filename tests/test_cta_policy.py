import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core import cta_policy
from core.parser import ScriptParser


class CtaPolicyTests(unittest.TestCase):
    def test_topic_request_cta_allows_every_fifth_candidate_short(self):
        allowed = []
        for idx in range(10):
            ok = cta_policy.should_allow_topic_request_cta(
                video_type="Shorts",
                generation_kind="横展開",
                batch_index=idx,
                batch_size=10,
                already_allowed_in_batch=False,
            )
            allowed.append(ok)

        self.assertEqual(allowed, [False, False, False, False, True, False, False, False, False, True])

    def test_topic_request_cta_blocks_until_fifth_candidate_short(self):
        allowed = [
            cta_policy.should_allow_topic_request_cta(
                video_type="Shorts",
                generation_kind="横展開",
                batch_index=idx,
                batch_size=3,
                already_allowed_in_batch=False,
            )
            for idx in range(3)
        ]

        self.assertEqual(allowed, [False, False, False])

    def test_apply_topic_request_policy_uses_existing_count(self):
        scripts = [
            "動画形式: Shorts\n生成区分: 新規\n動画タイトル: テスト1",
            "動画形式: Shorts\n生成区分: 横展開\n動画タイトル: テスト2",
        ]

        updated = cta_policy.apply_topic_request_cta_policy_to_scripts(scripts, existing_candidate_count=4)

        self.assertIn("ネタ募集CTA: 許可", updated[0])
        self.assertIn("通算5本目", updated[0])
        self.assertIn("固定コメント:", updated[0])
        self.assertIn("ネタ募集CTA: 禁止", updated[1])

    def test_topic_request_cta_interval_zero_disables_auto_allow(self):
        original = cta_policy.TOPIC_REQUEST_CTA_EVERY_N
        try:
            cta_policy.TOPIC_REQUEST_CTA_EVERY_N = 0
            ok = cta_policy.should_allow_topic_request_cta(
                video_type="Shorts",
                generation_kind="新規",
                batch_index=4,
                batch_size=5,
                already_allowed_in_batch=False,
            )
            reason = cta_policy.topic_request_cta_reason(
                video_type="Shorts",
                generation_kind="新規",
                batch_index=4,
                batch_size=5,
                already_allowed_in_batch=False,
            )
        finally:
            cta_policy.TOPIC_REQUEST_CTA_EVERY_N = original

        self.assertFalse(ok)
        self.assertIn("自動付与なし", reason)

    def test_shorts_navigation_warning_detects_next_episode(self):
        hits = cta_policy.check_shorts_navigation_ng(
            "ずんだもん(ノーマル): 次回はエンガワを解説するのだ",
            "Shorts",
        )

        self.assertIn("次回は", hits)

    def test_long_chapters_are_appended_from_chapter_line(self):
        description, added = cta_policy.append_long_youtube_chapters(
            "説明文",
            "チャプター: 1.イントロ / 2.起源 / 3.広まった理由 / 4.まとめ",
            duration_sec=300,
        )

        self.assertTrue(added)
        self.assertIn("【目次】", description)
        self.assertIn("0:00 イントロ", description)
        self.assertIn("1:03 起源", description)

    def test_topic_request_flag_is_inserted_into_script(self):
        script = "動画形式: Shorts\n生成区分: 横展開\n動画タイトル: テスト"

        updated = cta_policy.update_script_topic_request_cta(script, True, "通算5本目")

        self.assertIn("ネタ募集CTA: 許可", updated)
        self.assertIn("ネタ募集CTA理由: 通算5本目", updated)

    def test_parser_reads_topic_request_cta_meta(self):
        script = "\n".join([
            "動画形式: Shorts",
            "生成区分: 横展開",
            "ネタ募集CTA: 許可",
            "ネタ募集CTA理由: 通算5本目",
            "固定コメント: 次に見たい食べ物雑学ありますか？",
            "動画タイトル: テスト",
        ])

        meta = {
            item["type"]: item["text"]
            for item in ScriptParser.parse_string(script)
            if item["type"] in ScriptParser.META_TYPES
        }

        self.assertEqual(meta["video_format"], "Shorts")
        self.assertEqual(meta["generation_kind"], "横展開")
        self.assertEqual(meta["topic_request_cta"], "許可")
        self.assertEqual(meta["topic_request_cta_reason"], "通算5本目")


if __name__ == "__main__":
    unittest.main()
