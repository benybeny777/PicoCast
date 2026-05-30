"""core/channel_info のユニットテスト。"""
import importlib
import sys
import types
import unittest
from unittest.mock import patch


def _make_config(**kwargs):
    """テスト用の config モジュールもどきを作る。"""
    cfg = types.SimpleNamespace(
        CHANNEL_NAME=kwargs.get("CHANNEL_NAME", ""),
        CHANNEL_HANDLE=kwargs.get("CHANNEL_HANDLE", ""),
        CHANNEL_THEME=kwargs.get("CHANNEL_THEME", ""),
        CHANNEL_ACCENT_COLOR=kwargs.get("CHANNEL_ACCENT_COLOR", ""),
        DEFAULT_HASHTAGS=kwargs.get("DEFAULT_HASHTAGS", ""),
    )
    mod = types.SimpleNamespace(config=cfg)
    return mod


class TestGetChannelInfo(unittest.TestCase):

    def _call(self, **kwargs):
        fake = _make_config(**kwargs)
        with patch.dict(sys.modules, {"config": fake}):
            import core.channel_info as ci
            importlib.reload(ci)
            return ci.get_channel_info()

    def test_all_set_returns_no_warnings(self):
        info = self._call(
            CHANNEL_NAME="ずんだもんとめたんの食べ物雑学堂",
            CHANNEL_HANDLE="@zundamon_food",
            CHANNEL_THEME="食べ物雑学",
            CHANNEL_ACCENT_COLOR="#7c2d12",
            DEFAULT_HASHTAGS="#ずんだもん",
        )
        self.assertTrue(info["upload_allowed"])
        self.assertEqual(info["warnings"], [])
        self.assertEqual(info["name"], "ずんだもんとめたんの食べ物雑学堂")
        self.assertEqual(info["handle"], "@zundamon_food")
        self.assertEqual(info["accent_color"], "#7c2d12")
        self.assertTrue(info["accent_color_set"])

    def test_missing_name_gives_error_warning(self):
        info = self._call(CHANNEL_HANDLE="@handle")
        self.assertFalse(info["upload_allowed"])
        levels = [w["level"] for w in info["warnings"]]
        self.assertIn("error", levels)
        msgs = [w["message"] for w in info["warnings"]]
        self.assertTrue(any("CHANNEL_NAME" in m for m in msgs))

    def test_missing_handle_gives_error_warning(self):
        info = self._call(CHANNEL_NAME="テストチャンネル")
        self.assertFalse(info["upload_allowed"])
        msgs = [w["message"] for w in info["warnings"]]
        self.assertTrue(any("CHANNEL_HANDLE" in m for m in msgs))

    def test_both_set_no_warnings(self):
        info = self._call(
            CHANNEL_NAME="テストチャンネル",
            CHANNEL_HANDLE="@handle",
        )
        self.assertTrue(info["upload_allowed"])
        self.assertEqual(info["warnings"], [])

    def test_invalid_accent_color_gives_warn_and_uses_default(self):
        info = self._call(
            CHANNEL_NAME="テストチャンネル",
            CHANNEL_HANDLE="@handle",
            CHANNEL_ACCENT_COLOR="notacolor",
        )
        self.assertFalse(info["accent_color_set"])
        self.assertEqual(info["accent_color"], "#4a5568")
        msgs = [w["message"] for w in info["warnings"]]
        self.assertTrue(any("CHANNEL_ACCENT_COLOR" in m for m in msgs))

    def test_valid_accent_color_is_applied(self):
        info = self._call(
            CHANNEL_NAME="テストチャンネル",
            CHANNEL_HANDLE="@handle",
            CHANNEL_ACCENT_COLOR="#ff0000",
        )
        self.assertTrue(info["accent_color_set"])
        self.assertEqual(info["accent_color"], "#ff0000")

    def test_no_channel_info_upload_not_allowed(self):
        info = self._call()
        self.assertFalse(info["upload_allowed"])

    def test_optional_fields_return_none_when_empty(self):
        info = self._call(
            CHANNEL_NAME="テストチャンネル",
            CHANNEL_HANDLE="@handle",
        )
        self.assertIsNone(info["theme"])
        self.assertIsNone(info["hashtags"])

    def test_no_hardcoded_channel_fallback(self):
        """未設定時に特定チャンネルへフォールバックしない。"""
        info = self._call()
        self.assertIsNone(info["name"])
        self.assertIsNone(info["handle"])

    def test_hashtags_returned_when_set(self):
        info = self._call(
            CHANNEL_NAME="テストチャンネル",
            CHANNEL_HANDLE="@handle",
            DEFAULT_HASHTAGS="#ずんだもん #テスト",
        )
        self.assertEqual(info["hashtags"], "#ずんだもん #テスト")


if __name__ == "__main__":
    unittest.main()
