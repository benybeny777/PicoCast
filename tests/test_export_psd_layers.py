"""実素材・実設定を使わないPSD書き出しの画素契約。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import Group, PixelLayer
from psd_tools.constants import BlendMode

from tools.export_psd_layers import ExportError, export_psd, file_digest

ROOT = Path(__file__).resolve().parents[1]


class ExportLayersTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "temp" / "psd-layer-export" / "tests"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def fixture(self):
        document = PSDImage.new("RGB", (12, 12))
        with Image.new("RGBA", (8, 8), (200, 30, 50, 255)) as pixels:
            PixelLayer.frompil(pixels, document, "base", top=1, left=2)
        group = Group.new(document, "variants")
        with Image.new("RGBA", (3, 4), (30, 200, 90, 255)) as pixels:
            PixelLayer.frompil(pixels, group, "visible", top=3, left=4)
        with Image.new("RGBA", (3, 4), (30, 90, 200, 255)) as pixels:
            hidden = PixelLayer.frompil(pixels, group, "hidden", top=4, left=2)
            hidden.visible = False
        path = self.root / "fixture.psd"
        document.save(path)
        return path

    def test_all_layers_hidden_variants_and_original_digest(self):
        source = self.fixture()
        before = file_digest(source)
        output = self.root / "export"
        manifest = export_psd(source, output, pixel_tolerance=0, variants=[
            {"id": "alternate", "visibility": {"0": True, "1": True, "1/0": False, "1/1": True}},
        ])
        self.assertTrue(manifest["qualified"])
        self.assertEqual(len(manifest["layers"]), 4)
        self.assertEqual(len(manifest["variants"]), 2)
        self.assertEqual(file_digest(source), before)
        self.assertTrue(all(item["validation"]["max_abs_channel_diff"] == 0 for item in manifest["variants"]))
        for layer in manifest["layers"]:
            self.assertEqual(file_digest(output / layer["image"]["path"]), layer["image"]["sha256"])
        with self.assertRaises(FileExistsError):
            export_psd(source, output, pixel_tolerance=0)

    def test_unsupported_blend_is_marked_unqualified(self):
        source = self.fixture()
        document = PSDImage.open(source)
        document[1][0].blend_mode = BlendMode.MULTIPLY
        document.save(source)
        manifest = export_psd(source, self.root / "unsupported", pixel_tolerance=255)
        self.assertFalse(manifest["qualified"])
        self.assertTrue(manifest["unsupported_composition"])

    def test_incomplete_or_duplicate_visibility_does_not_produce_success_manifest(self):
        source = self.fixture()
        for index, variants in enumerate([
            [{"id": "bad", "visibility": {"0": True}}],
            [{"id": "default", "visibility": {}}],
        ]):
            output = self.root / f"failed-{index}"
            with self.assertRaises(ExportError):
                export_psd(source, output, pixel_tolerance=0, variants=variants)
            self.assertFalse((output / "manifest.json").exists())

    def test_all_legacy_character_presets_use_existing_selection_in_isolation(self):
        # 旧moduleの設定初期化を親プロセスへ持ち込まず、合成PSDだけを作る。
        generator = r'''
from pathlib import Path
import sys
from PIL import Image
from psd_tools import PSDImage
from psd_tools.api.layers import Group, PixelLayer
from tools.export_psd_layers import load_legacy_modules, native_variant_requests
native, expressions = load_legacy_modules()
root = Path(sys.argv[1])
for character, japanese in expressions.CHARACTER_KEYS.items():
    source = root / (character + '.psd')
    source.write_bytes(b'placeholder')
    requests = native_variant_requests(source, root / ('capture-' + character), character, native, japanese)
    groups = {}
    for _, arguments in requests:
        for key, marker in [('mouth_names','!口'),('eye_names','!目')]:
            groups.setdefault(marker,set()).update(arguments.get(key) or [])
        for marker in arguments.get('hide_markers') or []:
            groups.setdefault(marker,set()).add('黒目')
        if arguments.get('normalize_arms'):
            for marker in ['!左腕','!右腕']: groups.setdefault(marker,set()).add('*普通')
    for preset in expressions.EXPRESSION_PRESETS[character].values():
        for choice in preset['choices']: groups.setdefault(choice.marker,set()).update(choice.preferred)
        groups.setdefault('記号など',set()).update(preset.get('effects',[]))
    document = PSDImage.new('RGB',(12,12))
    for index,(marker,names) in enumerate(groups.items()):
        group = Group.new(document,marker)
        for variant,name in enumerate(sorted(names)):
            with Image.new('RGBA',(2,2),((index*31)%255,(variant*47)%255,150,255)) as pixels:
                layer = PixelLayer.frompil(pixels,group,name,top=index%8,left=variant%8)
                layer.name = name
                layer.visible = variant == 0
    document.save(source, encoding='utf-8')
'''
        generated = subprocess.run([sys.executable, "-c", generator, str(self.root)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        for character in ("zundamon", "metan"):
            output = self.root / f"legacy-{character}"
            completed = subprocess.run([sys.executable, str(ROOT / "tools/export_psd_layers.py"), str(self.root / f"{character}.psd"), str(output),
                "--pixel-tolerance", "0", "--legacy-character", character, "--log-dir", str(self.root / "logs")],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(completed.returncode, 0, completed.stderr + (self.root / "logs/app_debug_import.log").read_text(encoding="utf-8"))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            expected = len(manifest["coverage"]["expressions"]) + len(manifest["coverage"]["native_variants"]) + 1
            self.assertEqual(len(manifest["variants"]), expected)
            self.assertEqual(manifest["coverage"]["character"], character)
            self.assertTrue(manifest["qualified"])


if __name__ == "__main__":
    unittest.main()
