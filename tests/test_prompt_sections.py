import unittest
from pathlib import Path


class PromptSectionTests(unittest.TestCase):
    def test_food_sample_prompt_contains_shorts_hook_block(self):
        prompt = Path("config/samples/prompt_parts/food/script_generation_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("データ反映ルール：Shorts冒頭・サムネ・中盤の勝ち型", prompt)
        self.assertIn("1行目フック公式", prompt)
        self.assertIn("サムネ文字と1行目の連動公式", prompt)
        self.assertIn("Shortsの2段階驚き構造", prompt)

    def test_local_prompt_contains_shorts_hook_block_when_present(self):
        path = Path("config/prompt_parts/local/script_generation_prompt.txt")
        if not path.exists():
            self.skipTest("local prompt is not present")
        prompt = path.read_text(encoding="utf-8")
        self.assertIn("データ反映ルール：Shorts冒頭・サムネ・中盤の勝ち型", prompt)


if __name__ == "__main__":
    unittest.main()
