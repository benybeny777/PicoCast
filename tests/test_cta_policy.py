import unittest

from core import cta_policy
from core.parser import ScriptParser


class CtaPolicyTests(unittest.TestCase):
    def test_topic_request_cta_allows_only_last_of_five_shorts(self):
        allowed = []
        already = False
        for idx in range(5):
            ok = cta_policy.should_allow_topic_request_cta(
                video_type="Shorts",
                generation_kind="横展開",
                batch_index=idx,
                batch_size=5,
                already_allowed_in_batch=already,
            )
            allowed.append(ok)
            already = already or ok

        self.assertEqual(allowed, [False, False, False, False, True])

    def test_topic_request_cta_blocks_three_shorts(self):
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

        updated = cta_policy.update_script_topic_request_cta(script, True, "batch_size=5")

        self.assertIn("ネタ募集CTA: 許可", updated)
        self.assertIn("ネタ募集CTA理由: batch_size=5", updated)

    def test_parser_reads_topic_request_cta_meta(self):
        script = "\n".join([
            "動画形式: Shorts",
            "生成区分: 横展開",
            "ネタ募集CTA: 許可",
            "ネタ募集CTA理由: batch_size=5",
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
        self.assertEqual(meta["topic_request_cta_reason"], "batch_size=5")


if __name__ == "__main__":
    unittest.main()
