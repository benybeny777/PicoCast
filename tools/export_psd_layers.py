"""PSDを一度だけPNGと検証済みmanifestへ書き出す。実設定・元PSDは変更しない。"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import logging
from pathlib import Path
import sys
from unittest.mock import patch

from PIL import Image, ImageChops
from psd_tools import PSDImage
import psd_tools

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_logger = logging.getLogger("picocast.psd_import")


class ExportError(Exception):
    code = "E-PSD-EXPORT"


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def walk_layers(document):
    def walk(parent, parent_id=None):
        for index, layer in enumerate(parent):
            identifier = f"{parent_id}/{index}" if parent_id is not None else str(index)
            yield identifier, parent_id, layer
            if layer.is_group():
                yield from walk(layer, identifier)
    yield from walk(document)


def visibility(document) -> dict[str, bool]:
    return {identifier: bool(layer.visible) for identifier, _, layer in walk_layers(document)}


def apply_visibility(document, selected: dict[str, bool]) -> None:
    layers = {identifier: layer for identifier, _, layer in walk_layers(document)}
    if set(selected) != set(layers) or any(type(value) is not bool for value in selected.values()):
        raise ExportError("全レイヤーのIDと真偽値を指定してください。")
    for identifier, shown in selected.items():
        layers[identifier].visible = shown


def image_record(image: Image.Image, target: Path, output: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")
    return {"path": target.relative_to(output).as_posix(), "sha256": file_digest(target), "bytes": target.stat().st_size}


def rasterize(document, output: Path) -> tuple[list[dict], list[dict]]:
    layers, unsupported = [], []
    viewport = (0, 0, document.width, document.height)
    for order, (identifier, parent_id, layer) in enumerate(walk_layers(document)):
        mode = layer.blend_mode.value.decode("ascii").strip()
        if mode not in ("norm", "pass") or bool(layer.clipping):
            unsupported.append({"layer_id": identifier, "reason": "blend_or_clipping"})
        if layer.is_group() and (int(layer.opacity) != 255 or layer.has_mask()):
            unsupported.append({"layer_id": identifier, "reason": "group_opacity_or_mask"})
        image = layer.composite(viewport=viewport, force=True,
            layer_filter=lambda item: item is layer or bool(item.visible))
        if image is None:
            raise ExportError(f"レイヤーを画像化できません: {identifier}")
        try:
            with image.convert("RGBA") as rgba:
                record = image_record(rgba, output / "layers" / f"{order:06d}.png", output)
        finally:
            image.close()
        layers.append({"id": identifier, "parent_id": parent_id, "order": order,
            "name": str(layer.name), "kind": str(layer.kind), "visible": bool(layer.visible),
            "opacity": int(layer.opacity), "blend_mode": mode, "clipping": bool(layer.clipping),
            "bbox": list(layer.bbox), "is_group": bool(layer.is_group()), "image": record})
    return layers, unsupported


def compose_layers(manifest: dict, output: Path, selected: dict[str, bool]) -> Image.Image:
    canvas = Image.new("RGBA", (manifest["canvas"]["width"], manifest["canvas"]["height"]), (255, 255, 255, 0))
    by_id = {layer["id"]: layer for layer in manifest["layers"]}
    try:
        for layer in manifest["layers"]:
            if layer["is_group"]:
                continue
            visible = selected[layer["id"]]
            parent_id = layer["parent_id"]
            while parent_id is not None:
                visible = visible and selected[parent_id]
                parent_id = by_id[parent_id]["parent_id"]
            if visible:
                with Image.open(output / layer["image"]["path"]) as png:
                    with png.convert("RGBA") as rgba:
                        canvas.alpha_composite(rgba)
        return canvas
    except BaseException:
        canvas.close()
        raise


def pixel_difference(left: Image.Image, right: Image.Image) -> dict:
    if left.size != right.size:
        raise ExportError("合成結果の大きさが一致しません。")
    with ImageChops.difference(left, right) as difference:
        maximum = max(high for _, high in difference.getextrema())
        # alphaが0のRGB差も含め、4チャンネルの画素値を比較する。
        changed = sum(any(value != 0 for value in pixel) for pixel in difference.get_flattened_data())
    return {"max_abs_channel_diff": maximum, "mismatched_pixels": changed}


def load_legacy_modules():
    # 通常importのconfig初期化を避け、オラクルと同じ隔離境界を使う。
    from tools.oracle_environment import isolate
    isolate(work_name="psd-layer-export")
    from core import native_character_assets as native, character_expressions as expressions
    return native, expressions


def native_variant_requests(source: Path, cache: Path, character: str, native, japanese: str):
    requests = []
    def capture_request(psd_path, out_path, **kwargs):
        requests.append((Path(out_path).stem, kwargs))
        return str(out_path)
    with patch.object(native, "CACHE_DIR", str(cache)), patch.object(native, "_expression_paths", return_value={}), patch.object(native, "_save_variant", capture_request):
        native._ensure_variants(character, japanese, str(source), None)
    return requests


def legacy_references(source: Path, character: str) -> tuple[list[dict], dict]:
    native, expressions = load_legacy_modules()

    captured = []
    original_save = native._save_variant
    original_composite = PSDImage.composite
    active = {"id": None}
    reference_root = Path(native.CACHE_DIR).parent / "psd-references"

    def capture_composite(document, *args, **kwargs):
        if active["id"] is None:
            raise ExportError("旧合成の対象表情が未指定です。")
        captured.append({"id": active["id"], "visibility": visibility(document)})
        return original_composite(document, *args, **kwargs)

    japanese = expressions.CHARACTER_KEYS[character]
    requests = native_variant_requests(source, Path(native.CACHE_DIR), character, native, japanese)
    # キャッシュ差分生成は呼ばず、旧関数が列挙したPSD合成の要求をそのまま実行する。
    def require_selection(operation):
        def checked(*args, **kwargs):
            if not operation(*args, **kwargs):
                raise ExportError("旧版の合成に必要な表情レイヤーがありません。")
            return True
        return checked

    with ExitStack() as guards:
        guards.enter_context(patch.object(PSDImage, "composite", capture_composite))
        guards.enter_context(patch.object(expressions, "ASSET_DIR", reference_root))
        guards.enter_context(patch.dict(expressions.PSD_PATHS, {character: source}))
        for name in ("_set_group_variant", "_set_group_variant_deep", "_set_group_visible"):
            guards.enter_context(patch.object(native, name, require_selection(getattr(native, name))))
        for name, kwargs in requests:
            active["id"] = f"native:{name}"
            target = reference_root / f"native-{name}.png"
            if original_save(str(source), str(target), **kwargs) is None or not target.is_file():
                raise ExportError(f"旧版の合成に失敗しました: {name}")
            captured[-1]["reference"] = target
        for name, preset in expressions.EXPRESSION_PRESETS[character].items():
            active["id"] = f"expression:{name}"
            result = expressions._composite_expression(character, name, preset)
            used = result["used"]
            if any(choice["missing"] for choice in used["choices"] + used["arm_normalized"]) or used["effects"]["missing"]:
                raise ExportError(f"旧版の表情レイヤーが不足しています: {name}")
            captured[-1]["reference"] = Path(result["output"])
    if len(captured) != len(requests) + len(expressions.EXPRESSION_PRESETS[character]):
        raise ExportError("旧版の表情と合成回数が一致しません。")
    return captured, {"kind": "legacy_psd_presets", "character": character,
        "expressions": list(expressions.EXPRESSION_PRESETS[character]), "native_variants": [name for name, _ in requests]}


def export_psd(source: Path, output: Path, *, pixel_tolerance: int, variants: list[dict] | None = None,
               legacy_character: str | None = None) -> dict:
    source, output = source.resolve(strict=True), output.resolve()
    if not source.is_file() or source.suffix.lower() not in (".psd", ".psb"):
        raise ExportError("入力はPSDまたはPSBファイルを指定してください。")
    if type(pixel_tolerance) is not int or not 0 <= pixel_tolerance <= 255:
        raise ExportError("画素の許容差は0から255の整数で指定してください。")
    before = file_digest(source)
    output.mkdir(parents=True, exist_ok=False)
    with source.open("rb") as stream:
        document = PSDImage.open(stream)
        layers, unsupported = rasterize(document, output)
        if not layers:
            raise ExportError("書き出せるPSDレイヤーがありません。")
        original_visibility = visibility(document)
        manifest = {"schema_version": 1, "source": {"sha256": before, "bytes": source.stat().st_size,
            "psd_tools_version": psd_tools.__version__, "depth": document.depth, "color_mode": document.color_mode.name},
            "canvas": {"width": document.width, "height": document.height}, "pixel_tolerance": pixel_tolerance,
            "layers": layers, "variants": [], "unsupported_composition": unsupported,
            "expression_overlay_policy": "disable_mouth_and_blink_on_expression_png"}
        requested = [{"id": "default", "visibility": original_visibility}]
        for variant in variants or []:
            if not isinstance(variant, dict) or set(variant) != {"id", "visibility"}:
                raise ExportError("表情はidと全レイヤーのvisibilityを指定してください。")
            requested.append(variant)
        manifest["coverage"] = {"kind": "explicit_variants", "legacy_presets_verified": False}
        if legacy_character is not None:
            legacy, coverage = legacy_references(source, legacy_character)
            requested.extend(legacy)
            manifest["coverage"] = coverage
        identifiers = [variant["id"] for variant in requested]
        if any(not isinstance(identifier, str) or not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
            raise ExportError("表情IDが空または重複しています。")
        for index, variant in enumerate(requested):
            apply_visibility(document, variant["visibility"])
            if "reference" in variant:
                reference = Image.open(variant["reference"])
            else:
                reference = document.composite(force=True)
            if reference is None:
                raise ExportError("PSD全体を合成できません。")
            try:
                with reference.convert("RGBA") as expected, compose_layers(manifest, output, variant["visibility"]) as actual:
                    comparison = pixel_difference(expected, actual)
                    comparison["qualified"] = comparison["max_abs_channel_diff"] <= pixel_tolerance and not unsupported
                    image = image_record(expected, output / "variants" / f"{index:06d}.png", output)
            finally:
                reference.close()
            manifest["variants"].append({"id": variant["id"], "visibility": variant["visibility"], "image": image, "validation": comparison})
        apply_visibility(document, original_visibility)
        del document
    if file_digest(source) != before:
        raise ExportError("書き出し中に元PSDの内容が変わりました。元ファイルは上書きしていません。")
    manifest["qualified"] = all(variant["validation"]["qualified"] for variant in manifest["variants"])
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pixel-tolerance", required=True, type=int)
    parser.add_argument("--variants", type=Path)
    parser.add_argument("--legacy-character", choices=("zundamon", "metan"))
    parser.add_argument("--log-dir", type=Path, default=ROOT / "temp" / "psd-layer-export" / "logs")
    args = parser.parse_args()
    args.log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(args.log_dir / "app_debug_import.log", encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        variants = json.loads(args.variants.read_text(encoding="utf-8")) if args.variants else None
        result = export_psd(args.source, args.output, pixel_tolerance=args.pixel_tolerance, variants=variants, legacy_character=args.legacy_character)
        maximum = max(variant["validation"]["max_abs_channel_diff"] for variant in result["variants"])
        print(json.dumps({"qualified": result["qualified"], "layers": len(result["layers"]), "variants": len(result["variants"]),
            "max_abs_channel_diff": maximum, "manifest": str(args.output / "manifest.json")}, ensure_ascii=False))
        if not result["qualified"]:
            _logger.error("PSDのレイヤー合成が許容差または対応範囲を超えました: max_abs_channel_diff=%s", maximum)
            print("[E-PSD-EXPORT] 合成の画素差または未対応の混合方式を確認してください。登録はできません。", file=sys.stderr)
            return 2
        return 0
    except Exception:
        _logger.error("PSD書き出しに失敗しました", exc_info=True)
        print("[E-PSD-EXPORT] PSDを書き出せません。入力・出力先・表情指定とapp_debug_import.logを確認してください。", file=sys.stderr)
        return 2
    finally:
        handler.close()
        logging.getLogger().removeHandler(handler)


if __name__ == "__main__":
    raise SystemExit(main())
