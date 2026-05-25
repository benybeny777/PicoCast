from __future__ import annotations

import argparse
import gc
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFont

from config import CHARACTER_PNGS, CHARACTER_PSD_DIR


ROOT_DIR = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT_DIR / "assets" / "characters"
DEBUG_DIR = ROOT_DIR / "output" / "000_debug"

CHARACTER_KEYS = {
    "zundamon": "ずんだもん",
    "metan": "四国めたん",
}

PSD_PATHS = {
    "zundamon": Path(os.environ.get("ZUNDAMON_PSD_PATH", str(Path(CHARACTER_PSD_DIR) / "zundamon.psd"))),
    "metan": Path(os.environ.get("METAN_PSD_PATH", str(Path(CHARACTER_PSD_DIR) / "metan.psd"))),
}


@dataclass(frozen=True)
class VariantChoice:
    marker: str
    preferred: tuple[str, ...]
    mode: str = "children"


EXPRESSION_PRESETS: dict[str, dict[str, dict]] = {
    "zundamon": {
        "驚き": {
            "out": "zundamon_surprise.png",
            "choices": [
                VariantChoice("!目", ("*〇〇", "*見開き白目")),
                VariantChoice("!眉", ("*上がり眉",)),
                VariantChoice("!口", ("*ほあー", "*ほあ")),
                VariantChoice("!顔色", ("*ほっぺ赤め", "*ほっぺ")),
            ],
            "effects": [],
        },
        "焦り": {
            "out": "zundamon_panic.png",
            "choices": [
                VariantChoice("!目", ("*><", "*ぐるぐる")),
                VariantChoice("!眉", ("*困り眉2", "*困り眉1")),
                VariantChoice("!口", ("*はへえ", "*んあー", "*ほあー")),
                VariantChoice("!顔色", ("*青ざめ", "かげり")),
            ],
            "effects": ["汗3", "汗2", "汗1"],
        },
        "得意げ": {
            "out": "zundamon_confident.png",
            "choices": [
                VariantChoice("!目", ("*にっこり2", "*にっこり", "*細め目")),
                VariantChoice("!眉", ("*上がり眉", "*普通眉")),
                VariantChoice("!口", ("*むふ", "*んへー")),
                VariantChoice("!顔色", ("*ほっぺ赤め", "*ほっぺ")),
            ],
            "effects": [],
        },
        "困惑": {
            "out": "zundamon_confused.png",
            "choices": [
                VariantChoice("!目", ("*目セット",)),
                VariantChoice("!黒目", ("*目逸らし3", "*目逸らし2", "*目逸らし")),
                VariantChoice("!眉", ("*困り眉1", "*困り眉2")),
                VariantChoice("!口", ("*むー", "*△")),
                VariantChoice("!顔色", ("*ほっぺ2", "*ほっぺ")),
            ],
            "effects": ["汗2", "汗1"],
        },
        "にやけ": {
            "out": "zundamon_smirk.png",
            "choices": [
                VariantChoice("!目", ("*細め目", "*にっこり")),
                VariantChoice("!眉", ("*上がり眉", "*普通眉")),
                VariantChoice("!口", ("*むふ", "*んへー")),
                VariantChoice("!顔色", ("*ほっぺ赤め", "*ほっぺ")),
            ],
            "effects": [],
        },
    },
    "metan": {
        "驚き": {
            "out": "metan_surprise.png",
            "choices": [
                VariantChoice("!目", ("*○○", "*見開き白目")),
                VariantChoice("!眉", ("*太眉こまり", "*こまり")),
                VariantChoice("!口", ("*わあー", "*お")),
                VariantChoice("!顔色", ("*赤面", "*普通2")),
            ],
            "effects": [],
        },
        "呆れ": {
            "out": "metan_exasperated.png",
            "choices": [
                VariantChoice("!目", ("*目閉じ2", "*目閉じ")),
                VariantChoice("!眉", ("*太眉こまり", "*こまり")),
                VariantChoice("!口", ("*うえー", "*んー")),
                VariantChoice("!顔色", ("*普通2", "*普通")),
            ],
            "effects": [],
        },
        "ジト目": {
            "out": "metan_suspicious.png",
            "choices": [
                VariantChoice("!目", ("*目セット",)),
                VariantChoice("!黒目", ("*目そらし2", "*目そらし")),
                VariantChoice("!眉", ("*太眉おこ", "*ややおこ", "*おこ")),
                VariantChoice("!口", ("*んー", "*む")),
                VariantChoice("!顔色", ("*普通2", "*普通")),
            ],
            "effects": [],
        },
        "ドン引き": {
            "out": "metan_appalled.png",
            "choices": [
                VariantChoice("!目", ("*><", "*目閉じ2")),
                VariantChoice("!眉", ("*太眉こまり", "*こまり")),
                VariantChoice("!口", ("*うえー", "*△")),
                VariantChoice("!顔色", ("*青ざめ", "かげり")),
            ],
            "effects": ["汗"],
        },
        "ニヤリ": {
            "out": "metan_smirk.png",
            "choices": [
                VariantChoice("!目", ("*見上げ2", "*見上げ", "*目閉じ")),
                VariantChoice("!眉", ("*太眉ごきげん", "*ごきげん")),
                VariantChoice("!口", ("*にやり", "*ぺろり")),
                VariantChoice("!顔色", ("*普通2", "*普通")),
            ],
            "effects": [],
        },
    },
}

CATEGORY_KEYWORDS = {
    "eyes": ("!目", "目", "黒目", "白目"),
    "brows": ("!眉", "眉"),
    "mouth": ("!口", "口"),
    "face_color": ("!顔色", "顔色", "青ざめ", "赤面", "ほっぺ", "かげり"),
    "effects": ("汗", "涙", "記号"),
    "arms": ("!右腕", "!左腕", "腕", "手"),
}


def _load_psd(path: Path):
    from psd_tools import PSDImage

    return PSDImage.open(path)


def _iter_layers(layer) -> Iterable:
    yield layer
    if layer.is_group():
        for child in layer:
            yield from _iter_layers(child)


def _walk_layers(psd) -> Iterable[tuple[object, list[str]]]:
    def walk(layer, parents: list[str]):
        yield layer, parents
        if layer.is_group():
            for child in layer:
                yield from walk(child, parents + [str(layer.name)])

    for layer in psd:
        yield from walk(layer, [])


def _layer_category(path: str) -> str:
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in path for keyword in keywords):
            return category
    return "other"


def _layer_bbox(layer) -> tuple[int, int, int, int] | None:
    bbox = getattr(layer, "bbox", None)
    if bbox is None:
        return None
    if isinstance(bbox, tuple):
        return tuple(int(v) for v in bbox)
    return (int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2))


def _dump_layers(character: str) -> dict:
    psd = None
    try:
        psd = _load_psd(PSD_PATHS[character])
        lines = []
        categories: dict[str, list[str]] = {key: [] for key in CATEGORY_KEYWORDS}
        categories["other"] = []
        for layer, parents in _walk_layers(psd):
            full_path = " / ".join(parents + [str(layer.name)])
            bbox = _layer_bbox(layer)
            category = _layer_category(full_path)
            categories.setdefault(category, []).append(full_path)
            lines.append(
                json.dumps(
                    {
                        "path": full_path,
                        "name": str(layer.name),
                        "parent": " / ".join(parents),
                        "category": category,
                        "visible": bool(layer.visible),
                        "is_group": bool(layer.is_group()),
                        "bbox": bbox,
                    },
                    ensure_ascii=False,
                )
            )
        out_path = DEBUG_DIR / f"psd_layers_{character}.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"path": str(out_path), "categories": categories}
    finally:
        if psd is not None:
            close = getattr(psd, "close", None)
            if callable(close):
                close()
            del psd
        gc.collect()


def _find_groups(psd, marker: str) -> list:
    groups = []
    for layer, _parents in _walk_layers(psd):
        if layer.is_group() and marker in str(layer.name):
            groups.append(layer)
    return groups


def _variant_children(group) -> list:
    return list(group) or [item for item in _iter_layers(group) if item is not group]


def _set_variant(group, preferred: tuple[str, ...]) -> tuple[str | None, list[str]]:
    children = _variant_children(group)
    selected = None
    for preferred_name in preferred:
        for layer in children:
            if preferred_name in str(layer.name):
                selected = layer
                break
        if selected is not None:
            break
    if selected is None:
        return None, list(preferred)
    for layer in children:
        layer.visible = layer is selected
    selected.visible = True
    group.visible = True
    return str(selected.name), []


def _apply_choice(psd, choice: VariantChoice) -> dict:
    missing = []
    for group in _find_groups(psd, choice.marker):
        selected, missing = _set_variant(group, choice.preferred)
        if selected:
            return {
                "marker": choice.marker,
                "selected": selected,
                "preferred": list(choice.preferred),
                "missing": [],
            }
    return {
        "marker": choice.marker,
        "selected": None,
        "preferred": list(choice.preferred),
        "missing": missing or [choice.marker],
    }


def _set_effects(psd, wanted: list[str]) -> dict:
    used = []
    missing = []
    groups = _find_groups(psd, "記号など")
    if not groups and wanted:
        return {"used": [], "missing": wanted}
    for group in groups:
        leaves = [item for item in _iter_layers(group) if item is not group and not item.is_group()]
        for layer in leaves:
            should_show = any(name in str(layer.name) for name in wanted)
            layer.visible = should_show
            if should_show:
                used.append(str(layer.name))
        group.visible = bool(wanted)
    for name in wanted:
        if not any(name in used_name for used_name in used):
            missing.append(name)
    return {"used": used, "missing": missing}


def _set_metan_normal_arms(psd) -> list[dict]:
    results = []
    for marker in ("!右腕", "!左腕"):
        for group in _find_groups(psd, marker):
            selected, missing = _set_variant(group, ("*普通",))
            results.append({"marker": marker, "selected": selected, "missing": missing})
    return results


def _composite_expression(character: str, expression: str, preset: dict) -> dict:
    psd = None
    image = None
    try:
        psd = _load_psd(PSD_PATHS[character])
        used = {"choices": [], "effects": {}, "arm_normalized": []}
        if character == "metan":
            used["arm_normalized"] = _set_metan_normal_arms(psd)
        for choice in preset["choices"]:
            used["choices"].append(_apply_choice(psd, choice))
        used["effects"] = _set_effects(psd, list(preset.get("effects", [])))
        image = psd.composite(force=True)
        if image is None:
            raise RuntimeError(f"PSD composite failed: {character}[{expression}]")
        image = image.convert("RGBA")
        out_path = ASSET_DIR / preset["out"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path)
        return {"output": str(out_path), "used": used}
    finally:
        if image is not None:
            del image
        if psd is not None:
            close = getattr(psd, "close", None)
            if callable(close):
                close()
            del psd
        gc.collect()


def _face_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    bbox = image.getbbox() or (0, 0, image.width, image.height)
    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    face_top = top
    face_bottom = top + int(height * 0.43)
    face_left = max(0, left + int(width * 0.18))
    face_right = min(image.width, right - int(width * 0.18))
    return face_left, max(0, face_top), face_right, min(image.height, face_bottom)


def _face_diff_score(default_path: Path, expression_path: Path) -> float:
    with Image.open(default_path) as default_src, Image.open(expression_path) as expr_src:
        default = default_src.convert("RGBA")
        expr = expr_src.convert("RGBA")
        bbox = _face_bbox(default)
        default_crop = default.crop(bbox)
        expr_crop = expr.crop(bbox)
        if default_crop.size != expr_crop.size:
            expr_crop = expr_crop.resize(default_crop.size)
        diff = ImageChops.difference(default_crop, expr_crop).convert("L")
        stat = sum(diff.histogram()[i] * i for i in range(256))
        return stat / max(1, default_crop.width * default_crop.height * 255)


def _font(size: int):
    for path in (
        Path(r"C:/Windows/Fonts/meiryo.ttc"),
        Path(r"C:/Windows/Fonts/YuGothB.ttc"),
        Path(r"C:/Windows/Fonts/msgothic.ttc"),
    ):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _draw_preview(full: bool, report: dict) -> Path:
    variants = [
        (
            "ずんだもん",
            [("既定", Path(CHARACTER_PNGS["ずんだもん"]))]
            + [(name, ASSET_DIR / preset["out"]) for name, preset in EXPRESSION_PRESETS["zundamon"].items()],
        ),
        (
            "四国めたん",
            [("既定", Path(CHARACTER_PNGS["四国めたん"]))]
            + [(name, ASSET_DIR / preset["out"]) for name, preset in EXPRESSION_PRESETS["metan"].items()],
        ),
    ]
    cell_w, cell_h = (230, 360) if full else (230, 260)
    label_w = 180
    pad = 24
    cols = max(len(row[1]) for row in variants)
    canvas = Image.new("RGB", (label_w + cols * cell_w + pad * 2, len(variants) * cell_h + pad * 2), "#f3f5f7")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(32)
    label_font = _font(21)
    small_font = _font(13)
    for row_idx, (char_name, entries) in enumerate(variants):
        y0 = pad + row_idx * cell_h
        draw.text((pad, y0 + cell_h // 2 - 20), char_name, font=title_font, fill="#20242a")
        for col_idx, (label, path) in enumerate(entries):
            x0 = pad + label_w + col_idx * cell_w
            draw.rounded_rectangle((x0 + 8, y0 + 8, x0 + cell_w - 8, y0 + cell_h - 8), radius=8, fill="#ffffff", outline="#cfd6df", width=2)
            with Image.open(path) as src:
                img = src.convert("RGBA")
                if not full:
                    img = img.crop(_face_bbox(img))
                    img.thumbnail((cell_w - 26, int(cell_h * 0.68)), Image.Resampling.LANCZOS)
                else:
                    img.thumbnail((cell_w - 32, cell_h - 95), Image.Resampling.LANCZOS)
                canvas.paste(img, (x0 + (cell_w - img.width) // 2, y0 + 16), img)
            label_y = y0 + cell_h - 70
            draw.text((x0 + 16, label_y), label, font=label_font, fill="#20242a")
            if label != "既定":
                char_key = "zundamon" if char_name == "ずんだもん" else "metan"
                score = report[char_key][label]["diff_score"]
                draw.text((x0 + 16, label_y + 34), f"diff {score:.3f}", font=small_font, fill="#5b6470")
    out_path = DEBUG_DIR / ("expression_preview_full.png" if full else "expression_preview_face.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def generate_all() -> dict:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    layer_reports = {character: _dump_layers(character) for character in CHARACTER_KEYS}
    report: dict = {}
    warnings: list[str] = []
    for character, presets in EXPRESSION_PRESETS.items():
        report[character] = {}
        default_path = Path(CHARACTER_PNGS[CHARACTER_KEYS[character]])
        for expression, preset in presets.items():
            result = _composite_expression(character, expression, preset)
            expression_path = Path(result["output"])
            score = _face_diff_score(default_path, expression_path)
            missing = []
            for choice_result in result["used"]["choices"]:
                missing.extend(choice_result.get("missing", []))
            missing.extend(result["used"]["effects"].get("missing", []))
            if score < 0.012:
                warnings.append(f"WARNING: {CHARACTER_KEYS[character]}[{expression}] は既定との差分が小さいです。diff={score:.3f}")
            if missing:
                warnings.append(f"WARNING: {CHARACTER_KEYS[character]}[{expression}] 未発見レイヤー: {', '.join(missing)}")
            report[character][expression] = {
                "character_name": CHARACTER_KEYS[character],
                "expression": expression,
                "output": result["output"],
                "used_layers": result["used"],
                "missing_layers": missing,
                "diff_score": score,
            }
    full_preview = _draw_preview(True, report)
    face_preview = _draw_preview(False, report)
    out_json = DEBUG_DIR / "expression_layers_used.json"
    payload = {
        "layers": layer_reports,
        "expressions": report,
        "previews": {
            "full": str(full_preview),
            "face": str(face_preview),
        },
        "warnings": warnings,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if warnings:
        print("\n".join(warnings))
    print(f"layers: {layer_reports['zundamon']['path']}")
    print(f"layers: {layer_reports['metan']['path']}")
    print(f"preview: {full_preview}")
    print(f"preview: {face_preview}")
    print(f"report: {out_json}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate native character expression PNGs and PSD diagnostics.")
    parser.add_argument("--diagnose", action="store_true", help="write PSD layer dumps")
    parser.add_argument("--generate", action="store_true", help="generate expression PNGs and previews")
    args = parser.parse_args()
    if args.generate or not args.diagnose:
        generate_all()
    else:
        for character in CHARACTER_KEYS:
            result = _dump_layers(character)
            print(result["path"])


if __name__ == "__main__":
    main()
