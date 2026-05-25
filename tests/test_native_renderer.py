import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.native_character_assets import CharacterVariantSet
from core.native_renderer import _character_base_path, _duration_status, _expression_fallback_reason, _native_loudnorm_filter, _save_render_info


class TestDurationStatus(unittest.TestCase):
    def test_ideal(self):
        for sec in (38.0, 43.7, 50.0):
            key, label = _duration_status(sec)
            self.assertEqual(key, "ideal", f"{sec}s should be ideal")
            self.assertIn("理想", label)

    def test_ok_but_short(self):
        for sec in (35.0, 36.5, 37.9):
            key, _ = _duration_status(sec)
            self.assertEqual(key, "ok_but_short", f"{sec}s should be ok_but_short")

    def test_ok_but_long(self):
        for sec in (51.0, 53.3, 55.0):
            key, _ = _duration_status(sec)
            self.assertEqual(key, "ok_but_long", f"{sec}s should be ok_but_long")

    def test_warning(self):
        for sec in (32.0, 34.9, 55.1, 58.0):
            key, _ = _duration_status(sec)
            self.assertEqual(key, "warning", f"{sec}s should be warning")

    def test_needs_review(self):
        for sec in (10.0, 31.9, 58.1, 90.0):
            key, _ = _duration_status(sec)
            self.assertEqual(key, "needs_review", f"{sec}s should be needs_review")


class TestLoudnormFilter(unittest.TestCase):
    def test_default_values(self):
        f = _native_loudnorm_filter()
        self.assertIn("loudnorm", f)
        self.assertIn("I=-15", f)
        self.assertIn("TP=-1.5", f)
        self.assertIn("LRA=6", f)

    def test_enabled_guard(self):
        from config import NATIVE_AUDIO_LOUDNORM_ENABLED
        f = _native_loudnorm_filter()
        if NATIVE_AUDIO_LOUDNORM_ENABLED:
            self.assertTrue(f.startswith("loudnorm"))


class TestSaveRenderInfo(unittest.TestCase):
    def test_creates_meta_dir_and_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            info = {"render_engine": "native", "actual_duration_sec": 43.7, "actual_duration_status": "ideal"}
            _save_render_info(tmpdir, info)
            path = os.path.join(tmpdir, "_meta", "render_info.json")
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["render_engine"], "native")
            self.assertAlmostEqual(data["actual_duration_sec"], 43.7)
            self.assertEqual(data["actual_duration_status"], "ideal")

    def test_merges_with_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_dir = os.path.join(tmpdir, "_meta")
            os.makedirs(meta_dir)
            existing_path = os.path.join(meta_dir, "render_info.json")
            with open(existing_path, "w", encoding="utf-8") as f:
                json.dump({"previous_key": "previous_value"}, f)

            _save_render_info(tmpdir, {"new_key": "new_value"})

            with open(existing_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["previous_key"], "previous_value")
            self.assertEqual(data["new_key"], "new_value")

    def test_new_value_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _save_render_info(tmpdir, {"actual_duration_sec": 40.0})
            _save_render_info(tmpdir, {"actual_duration_sec": 45.0})
            path = os.path.join(tmpdir, "_meta", "render_info.json")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertAlmostEqual(data["actual_duration_sec"], 45.0)


class TestCharacterExpressionFallback(unittest.TestCase):
    def test_missing_expression_asset_falls_back_to_base(self):
        character = CharacterVariantSet(
            name="zundamon",
            static="static.png",
            base="base.png",
            mouth_closed=None,
            mouth_half=None,
            mouth_open=None,
            eye_closed=None,
            expressions={},
        )
        self.assertEqual(_character_base_path(character, "zundamon", "驚き"), "base.png")
        self.assertEqual(_expression_fallback_reason([character], "zundamon", "驚き"), "missing_asset")

    def test_unknown_expression_reports_unknown(self):
        character = CharacterVariantSet(
            name="metan",
            static="static.png",
            base="base.png",
            mouth_closed=None,
            mouth_half=None,
            mouth_open=None,
            eye_closed=None,
            expressions={},
        )
        self.assertEqual(_expression_fallback_reason([character], "metan", "未知顔"), "unknown")


if __name__ == "__main__":
    unittest.main()
