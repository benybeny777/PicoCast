import unittest

from core.generation_checks import duration_tag, estimate_duration, pre_generate_check
from core.gui_support import split_input_scripts


class GuiSupportTests(unittest.TestCase):
    def test_split_input_scripts_by_format_lines(self):
        raw = "動画形式: Shorts\n動画タイトル: A\n\n動画形式: Long\n動画タイトル: B"
        scripts = split_input_scripts(raw)
        self.assertEqual(len(scripts), 2)
        self.assertTrue(scripts[0].startswith("動画形式: Shorts"))
        self.assertTrue(scripts[1].startswith("動画形式: Long"))

    def test_split_input_scripts_by_separator(self):
        scripts = split_input_scripts("動画形式: Shorts\n---\n動画形式: Shorts")
        self.assertEqual(len(scripts), 2)


class GenerationChecksTests(unittest.TestCase):
    def test_estimate_duration_uses_dialogue_count_and_average(self):
        items = [
            {"type": "dialogue", "text": "これはテストなのだ"},
            {"type": "dialogue", "text": "もう一行ですわね"},
        ]
        seconds, count, avg = estimate_duration(items, True)
        self.assertIsNotNone(seconds)
        self.assertEqual(count, 2)
        self.assertGreater(avg, 0)

    def test_duration_tag(self):
        self.assertEqual(duration_tag("ideal"), "success")
        self.assertEqual(duration_tag("ok_but_long"), "warning")
        self.assertEqual(duration_tag("needs_review"), "warning")
        self.assertEqual(duration_tag("unknown"), "duration")

    def test_pre_generate_check_requires_title(self):
        errors, warnings = pre_generate_check([
            {"type": "video_format", "text": "Long"},
            {"type": "dialogue", "text": "これはテストです"},
        ], False)
        self.assertIn("video_titleがありません", errors)
        self.assertTrue(any("背景数が少ない" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
