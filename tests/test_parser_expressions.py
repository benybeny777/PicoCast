import unittest

from core.parser import ScriptParser


class ParserExpressionTests(unittest.TestCase):
    def test_parses_zundamon_expression(self):
        items = ScriptParser.parse_string("ずんだもん(ノーマル)[驚き]: 200年も毒扱いなのだ！？")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "dialogue")
        self.assertEqual(items[0]["character"], "ずんだもん")
        self.assertEqual(items[0]["emotion"], "ノーマル")
        self.assertEqual(items[0]["expression"], "驚き")
        self.assertEqual(items[0]["text"], "200年も毒扱いなのだ！？")

    def test_parses_metan_expression(self):
        items = ScriptParser.parse_string("四国めたん(ツンツン)[ジト目]: 食べ物のせいじゃないですわ")
        self.assertEqual(items[0]["character"], "四国めたん")
        self.assertEqual(items[0]["emotion"], "ツンツン")
        self.assertEqual(items[0]["expression"], "ジト目")

    def test_existing_format_keeps_expression_none(self):
        items = ScriptParser.parse_string("ずんだもん(ノーマル): 従来形式なのだ")
        self.assertEqual(items[0]["character"], "ずんだもん")
        self.assertEqual(items[0]["emotion"], "ノーマル")
        self.assertIsNone(items[0]["expression"])

    def test_unknown_expression_does_not_fail_parse(self):
        items = ScriptParser.parse_string("\n".join([
            "四国めたん(ツンツン)[未知顔]: 止めずに読むですわ",
            "ずんだもん(ノーマル): そのまま続くのだ",
            "四国めたん(ツンツン): 既定表情ですわ",
            "ずんだもん(ノーマル): 互換性は大事なのだ",
            "四国めたん(ツンツン): そこは堅実ですわ",
        ]))
        self.assertEqual(items[0]["expression"], "未知顔")
        is_valid, messages = ScriptParser.validate(items)
        self.assertTrue(is_valid)
        self.assertTrue(any("表情" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
