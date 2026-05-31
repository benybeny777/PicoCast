import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.native_character_assets import CharacterVariantSet
from core.native_renderer import _character_base_path, _duration_status, _expression_fallback_reason, _native_loudnorm_filter, _run_ffmpeg, _save_render_info, _subtitles_filter_path, _write_subtitles


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


class TestFfmpegRunner(unittest.TestCase):
    def test_ffmpeg_runs_noninteractive_with_timeout(self):
        calls = {}

        def fake_run(args, **kwargs):
            calls["args"] = args
            calls["kwargs"] = kwargs

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch("core.native_renderer.subprocess.run", fake_run):
            _run_ffmpeg(["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"])

        self.assertIn("-nostdin", calls["args"])
        self.assertEqual(calls["kwargs"]["stdin"], subprocess.DEVNULL)
        self.assertGreater(calls["kwargs"]["timeout"], 0)

    def test_subtitles_filter_path_escapes_brackets(self):
        escaped = _subtitles_filter_path("output/[Shorts]りんご/subtitle_0001.ass")
        self.assertIn(r"\[Shorts\]", escaped)


class TestSaveRenderInfo(unittest.TestCase):
    def _patch_db_path(self, tmpdir: str):
        import core.metadata_db as metadata_db
        patcher = patch.object(metadata_db, "get_db_path", return_value=os.path.join(tmpdir, "metadata.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(metadata_db.close_all_connections)
        return metadata_db

    def test_creates_meta_dir_and_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata_db = self._patch_db_path(tmpdir)
            info = {"render_engine": "native", "actual_duration_sec": 43.7, "actual_duration_status": "ideal"}
            _save_render_info(tmpdir, info)
            data = metadata_db.get_render_info(os.path.basename(tmpdir))
            self.assertIsNotNone(data)
            self.assertEqual(data["render_engine"], "native")
            self.assertAlmostEqual(data["actual_duration_sec"], 43.7)
            self.assertEqual(data["actual_duration_status"], "ideal")

    def test_merges_with_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata_db = self._patch_db_path(tmpdir)
            local_id = os.path.basename(tmpdir)
            metadata_db.initialize_db()
            metadata_db.upsert_render_info(local_id, {"video_title": "既存タイトル"})

            _save_render_info(tmpdir, {"actual_duration_sec": 12.5})

            data = metadata_db.get_render_info(local_id)
            self.assertEqual(data["video_title"], "既存タイトル")
            self.assertAlmostEqual(data["actual_duration_sec"], 12.5)

    def test_new_value_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata_db = self._patch_db_path(tmpdir)
            _save_render_info(tmpdir, {"actual_duration_sec": 40.0})
            _save_render_info(tmpdir, {"actual_duration_sec": 45.0})
            data = metadata_db.get_render_info(os.path.basename(tmpdir))
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


class TestWriteSubtitles(unittest.TestCase):
    def test_telop_icon_escaping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ass_path = os.path.join(tmpdir, "test.ass")
            _write_subtitles(
                path=ass_path,
                chunks=[("テストセリフ", "Default", None)],
                audio_durations=[2.0],
                width=1080,
                height=1920,
                offset_sec=0.0,
                telop="チューブ文化",
                icon="？",
            )
            self.assertTrue(os.path.exists(ass_path))
            with open(ass_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
            
            # テロップやアイコンのアニメーションタグが「}}」ではなく「}」で閉じられていることを検証
            self.assertNotIn("}}チューブ文化", content)
            self.assertNotIn("}}？", content)
            self.assertIn("}チューブ文化", content)
            self.assertIn("}？", content)


if __name__ == "__main__":
    unittest.main()
