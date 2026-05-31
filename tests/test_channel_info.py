"""core/channel_info のユニットテスト。"""
import unittest
from unittest.mock import patch

from core.channel_profile import ChannelProfile
from core.channel_info import _build_from_profile, get_channel_info


def _profile(**kwargs):
    return ChannelProfile(
        profile_id=kwargs.get("profile_id", "test_profile"),
        channel_name=kwargs.get("channel_name", ""),
        channel_handle=kwargs.get("channel_handle", ""),
        genre_profile=kwargs.get("genre_profile", "food_trivia"),
        output_root=kwargs.get("output_root", "output/test_profile"),
        default_hashtags=kwargs.get("default_hashtags", ""),
        channel_theme=kwargs.get("channel_theme", ""),
        channel_accent_color=kwargs.get("channel_accent_color", ""),
    )


class TestGetChannelInfo(unittest.TestCase):

    def test_all_set_returns_no_warnings(self):
        info = _build_from_profile(_profile(
            channel_name="ずんだもんとめたんの食べ物雑学堂",
            channel_handle="@zundamon_food",
            channel_theme="食べ物雑学",
            channel_accent_color="#7c2d12",
            default_hashtags="#ずんだもん",
        ))
        self.assertTrue(info["upload_allowed"])
        self.assertEqual(info["warnings"], [])
        self.assertEqual(info["name"], "ずんだもんとめたんの食べ物雑学堂")
        self.assertEqual(info["handle"], "@zundamon_food")
        self.assertEqual(info["accent_color"], "#7c2d12")
        self.assertTrue(info["accent_color_set"])
        self.assertEqual(info["hashtags"], "#ずんだもん")
        self.assertEqual(info["genre_profile"], "food_trivia")
        self.assertEqual(info["profile_id"], "test_profile")

    def test_missing_name_gives_error_warning(self):
        info = _build_from_profile(_profile(channel_handle="@handle"))
        self.assertFalse(info["upload_allowed"])
        msgs = [w["message"] for w in info["warnings"]]
        self.assertTrue(any("channel_name" in m for m in msgs))

    def test_missing_handle_gives_error_warning(self):
        info = _build_from_profile(_profile(channel_name="テストチャンネル"))
        self.assertFalse(info["upload_allowed"])
        msgs = [w["message"] for w in info["warnings"]]
        self.assertTrue(any("channel_handle" in m for m in msgs))

    def test_both_set_no_warnings(self):
        info = _build_from_profile(_profile(
            channel_name="テストチャンネル",
            channel_handle="@handle",
        ))
        self.assertTrue(info["upload_allowed"])
        self.assertEqual(info["warnings"], [])

    def test_invalid_accent_color_gives_warn_and_uses_default(self):
        info = _build_from_profile(_profile(
            channel_name="テストチャンネル",
            channel_handle="@handle",
            channel_accent_color="notacolor",
        ))
        self.assertFalse(info["accent_color_set"])
        self.assertEqual(info["accent_color"], "#4a5568")
        msgs = [w["message"] for w in info["warnings"]]
        self.assertTrue(any("channel_accent_color" in m for m in msgs))

    def test_valid_accent_color_is_applied(self):
        info = _build_from_profile(_profile(
            channel_name="テストチャンネル",
            channel_handle="@handle",
            channel_accent_color="#ff0000",
        ))
        self.assertTrue(info["accent_color_set"])
        self.assertEqual(info["accent_color"], "#ff0000")

    def test_no_channel_info_upload_not_allowed(self):
        info = _build_from_profile(_profile())
        self.assertFalse(info["upload_allowed"])

    def test_optional_fields_return_none_when_empty(self):
        info = _build_from_profile(_profile(
            channel_name="テストチャンネル",
            channel_handle="@handle",
        ))
        self.assertIsNone(info["theme"])
        self.assertIsNone(info["hashtags"])

    def test_no_hardcoded_channel_fallback(self):
        """未設定時に特定チャンネルへフォールバックしない。"""
        info = _build_from_profile(_profile())
        self.assertIsNone(info["name"])
        self.assertIsNone(info["handle"])

    def test_handle_at_prefix_added_if_missing(self):
        info = _build_from_profile(_profile(channel_name="テストチャンネル", channel_handle="zundamon_food"))
        self.assertEqual(info["handle"], "@zundamon_food")

    def test_handle_at_prefix_not_duplicated(self):
        info = _build_from_profile(_profile(channel_name="テストチャンネル", channel_handle="@zundamon_food"))
        self.assertEqual(info["handle"], "@zundamon_food")

    def test_hashtags_returned_when_set(self):
        info = _build_from_profile(_profile(
            channel_name="テストチャンネル",
            channel_handle="@handle",
            default_hashtags="#ずんだもん #テスト",
        ))
        self.assertEqual(info["hashtags"], "#ずんだもん #テスト")

    def test_get_channel_info_requires_active_profile(self):
        import core.channel_profile as cp
        with patch("core.channel_profile.require_active_profile", side_effect=cp.NoActiveProfileError("no active")):
            with self.assertRaises(cp.NoActiveProfileError):
                get_channel_info()


if __name__ == "__main__":
    unittest.main()
