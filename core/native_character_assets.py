import os
import gc
from dataclasses import dataclass
from typing import Iterable

from config import CHARACTER_EXPRESSION_PNGS, CHARACTER_PNGS, METAN_PSD_PATH, ZUNDAMON_PSD_PATH
from core.runtime_env import app_base_dir


CACHE_DIR = os.path.join(app_base_dir(), "data", "native_character_cache")


@dataclass
class CharacterVariantSet:
    name: str
    static: str | None
    base: str | None
    mouth_closed: str | None
    mouth_half: str | None
    mouth_open: str | None
    eye_closed: str | None
    expressions: dict[str, str]
    jp_name: str | None = None

    def base_for_expression(self, expression: str | None) -> str | None:
        if expression:
            path = self.expressions.get(str(expression).strip())
            if path and os.path.exists(path):
                return path
        return self.base


def _find_psd(keyword: str) -> str | None:
    configured = ZUNDAMON_PSD_PATH if keyword == "zundamon" else METAN_PSD_PATH
    if configured and os.path.exists(configured):
        return configured
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        return None
    jp_keyword = "ずんだもん" if keyword == "zundamon" else "四国めたん"
    for root, _dirs, files in os.walk(desktop):
        for file_name in files:
            if file_name.lower().endswith(".psd") and jp_keyword in file_name:
                return os.path.join(root, file_name)
    return None


def _iter_layers(layer) -> Iterable:
    yield layer
    if layer.is_group():
        for child in layer:
            yield from _iter_layers(child)


def _find_group(psd, marker: str):
    for layer in psd:
        for item in _iter_layers(layer):
            if item.is_group() and marker in str(item.name):
                return item
    return None


def _set_group_variant(group, preferred_names: list[str]) -> bool:
    if group is None:
        return False
    leaves = [child for child in group if not child.is_group()]
    if not leaves:
        leaves = [item for item in _iter_layers(group) if not item.is_group()]
    selected = None
    for preferred in preferred_names:
        for layer in leaves:
            if preferred in str(layer.name):
                selected = layer
                break
        if selected is not None:
            break
    if selected is None:
        return False
    for layer in leaves:
        layer.visible = layer is selected
    selected.visible = True
    group.visible = True
    return True


def _set_group_variant_deep(group, preferred_names: list[str]) -> bool:
    if group is None:
        return False
    leaves = [item for item in _iter_layers(group) if not item.is_group()]
    selected = None
    for preferred in preferred_names:
        for layer in leaves:
            if preferred in str(layer.name):
                selected = layer
                break
        if selected is not None:
            break
    if selected is None:
        return False
    for layer in leaves:
        layer.visible = layer is selected
    selected.visible = True
    group.visible = True
    return True


def _set_group_visible(group, visible: bool) -> bool:
    if group is None:
        return False
    for item in _iter_layers(group):
        item.visible = visible
    group.visible = visible
    return True


def _save_variant(
    psd_path: str,
    out_path: str,
    mouth_names: list[str] | None = None,
    eye_names: list[str] | None = None,
    hide_markers: list[str] | None = None,
) -> str | None:
    try:
        from psd_tools import PSDImage
    except Exception:
        return None
    psd = None
    try:
        psd = PSDImage.open(psd_path)
        if mouth_names:
            _set_group_variant(_find_group(psd, "!口"), mouth_names)
        if eye_names:
            _set_group_variant_deep(_find_group(psd, "!目"), eye_names)
        for marker in hide_markers or []:
            _set_group_visible(_find_group(psd, marker), False)
        if "四国めたん" in os.path.basename(psd_path):
            _set_group_variant(_find_group(psd, "!左腕"), ["普通"])
            _set_group_variant(_find_group(psd, "!右腕"), ["普通"])
        image = psd.composite(force=True)
        if image is None:
            return None
        image = image.convert("RGBA")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        image.save(out_path)
        return out_path
    except Exception:
        return None
    finally:
        try:
            del image
        except Exception:
            pass  # フォールバック許可: 画像リソース解放の失敗は無視
        close = getattr(psd, "close", None)
        if callable(close):
            close()
        del psd
        gc.collect()


def _save_difference_overlay(base_path: str, variant_path: str, out_path: str, padding: int = 8) -> str | None:
    try:
        from PIL import Image, ImageChops, ImageFilter

        with Image.open(base_path) as base_src:
            base = base_src.convert("RGBA")
        with Image.open(variant_path) as variant_src:
            variant = variant_src.convert("RGBA")
        if base.size != variant.size:
            return None
        diff = ImageChops.difference(base, variant)
        bbox = diff.getbbox()
        if not bbox:
            return None
        left, top, right, bottom = bbox
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(variant.width, right + padding)
        bottom = min(variant.height, bottom + padding)
        cropped_variant = variant.crop((left, top, right, bottom))
        cropped_diff = diff.crop((left, top, right, bottom))
        mask = cropped_diff.convert("L").point(lambda p: 255 if p > 6 else 0)
        mask = mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(0.8))
        original_alpha = cropped_variant.getchannel("A")
        mask = ImageChops.multiply(mask, original_alpha)
        cropped_variant.putalpha(mask)

        overlay = Image.new("RGBA", variant.size, (0, 0, 0, 0))
        overlay.alpha_composite(cropped_variant, (left, top))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        overlay.save(out_path)
        return out_path
    except Exception:
        return None
    finally:
        try:
            del base, variant, diff, cropped_variant, cropped_diff, mask, original_alpha, overlay
        except Exception:
            pass  # フォールバック許可: 画像リソース解放の失敗は無視
        gc.collect()


def _save_mouth_overlay(base_path: str, variant_path: str, out_path: str) -> str | None:
    return _save_difference_overlay(base_path, variant_path, out_path, padding=12)


def _save_manual_blink_overlay(name: str, base_path: str, out_path: str) -> str | None:
    try:
        from PIL import Image, ImageDraw

        with Image.open(base_path) as base_src:
            base = base_src.convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        if name == "zundamon":
            skin = base.getpixel((500, 455))[:3] + (255,)
            line = (64, 48, 48, 255)
            covers = [(382, 377, 482, 456), (505, 377, 605, 456)]
            arcs = [(390, 404, 478, 445), (513, 404, 601, 445)]
            width = 7
        else:
            skin = base.getpixel((510, 365))[:3] + (255,)
            line = (64, 48, 48, 255)
            covers = [(397, 242, 508, 363), (522, 242, 633, 363)]
            arcs = [(405, 288, 505, 350), (525, 288, 625, 350)]
            width = 10

        for box in covers:
            draw.ellipse(box, fill=skin)
        for box in arcs:
            draw.arc(box, start=200, end=340, fill=line, width=width)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        overlay.save(out_path)
        return out_path
    except Exception:
        return None
    finally:
        try:
            del base, overlay, draw
        except Exception:
            pass  # フォールバック許可: 画像リソース解放の失敗は無視
        gc.collect()


def _expression_paths(jp_name: str) -> dict[str, str]:
    configured = CHARACTER_EXPRESSION_PNGS.get(jp_name, {})
    return {
        str(expression).strip(): path
        for expression, path in configured.items()
        if expression and path and os.path.exists(path)
    }


def _ensure_variants(name: str, jp_name: str, psd_path: str | None, static_path: str | None) -> CharacterVariantSet:
    char_dir = os.path.join(CACHE_DIR, name)
    os.makedirs(char_dir, exist_ok=True)
    expressions = _expression_paths(jp_name)
    if not psd_path or not os.path.exists(psd_path):
        return CharacterVariantSet(name, static_path, static_path, static_path, static_path, static_path, static_path, expressions, jp_name)

    if name == "zundamon":
        mouth_closed = ["んー", "むー"]
        mouth_half = ["△", "お"]
        mouth_open = ["ほあー", "ほあ"]
        eye_closed = ["UU", "にっこり"]
    else:
        mouth_closed = ["んー", "む"]
        mouth_half = ["△", "▽", "お"]
        mouth_open = ["わあー", "うえー"]
        eye_closed = ["目閉じ", "目閉じ2"]

    outputs = {
        "base": os.path.join(char_dir, "base.png"),
        "mouth_closed": os.path.join(char_dir, "mouth_closed.png"),
        "mouth_half": os.path.join(char_dir, "mouth_half.png"),
        "mouth_open": os.path.join(char_dir, "mouth_open.png"),
        "mouth_half_overlay": os.path.join(char_dir, "mouth_half_overlay.png"),
        "mouth_open_overlay": os.path.join(char_dir, "mouth_open_overlay.png"),
        "eye_closed": os.path.join(char_dir, "eye_closed.png"),
        "eye_closed_overlay": os.path.join(char_dir, "eye_closed_overlay.png"),
        "eye_closed_manual": os.path.join(char_dir, "eye_closed_manual.png"),
    }
    if not os.path.exists(outputs["base"]):
        _save_variant(psd_path, outputs["base"])
    if not os.path.exists(outputs["mouth_closed"]):
        _save_variant(psd_path, outputs["mouth_closed"], mouth_names=mouth_closed)
    if not os.path.exists(outputs["mouth_half"]):
        _save_variant(psd_path, outputs["mouth_half"], mouth_names=mouth_half)
    if not os.path.exists(outputs["mouth_open"]):
        _save_variant(psd_path, outputs["mouth_open"], mouth_names=mouth_open)
    if not os.path.exists(outputs["eye_closed"]):
        _save_variant(psd_path, outputs["eye_closed"], eye_names=eye_closed, hide_markers=["!黒目"])
    if os.path.exists(outputs["base"]) and not os.path.exists(outputs["eye_closed_manual"]):
        _save_manual_blink_overlay(name, outputs["base"], outputs["eye_closed_manual"])
    if os.path.exists(outputs["base"]) and os.path.exists(outputs["eye_closed"]):
        _save_difference_overlay(outputs["base"], outputs["eye_closed"], outputs["eye_closed_overlay"], padding=10)
    if os.path.exists(outputs["base"]) and os.path.exists(outputs["mouth_half"]):
        _save_mouth_overlay(outputs["base"], outputs["mouth_half"], outputs["mouth_half_overlay"])
    if os.path.exists(outputs["base"]) and os.path.exists(outputs["mouth_open"]):
        _save_mouth_overlay(outputs["base"], outputs["mouth_open"], outputs["mouth_open_overlay"])

    def exists(key: str, fallback_static: bool = True) -> str | None:
        if os.path.exists(outputs[key]):
            return outputs[key]
        return static_path if fallback_static else None

    return CharacterVariantSet(
        name=name,
        static=static_path,
        base=exists("base"),
        mouth_closed=exists("mouth_closed"),
        mouth_half=exists("mouth_half_overlay", fallback_static=False),
        mouth_open=exists("mouth_open_overlay", fallback_static=False),
        eye_closed=exists("eye_closed_overlay", fallback_static=False) or exists("eye_closed_manual", fallback_static=False),
        expressions=expressions,
        jp_name=jp_name,
    )


def character_variant_key(jp_name: str) -> str:
    """ffmpeg filter label に使えるキャラクターキーへ変換する。"""
    aliases = {"ずんだもん": "zundamon", "四国めたん": "metan"}
    if jp_name in aliases:
        return aliases[jp_name]
    return str(jp_name).encode("unicode_escape").decode("ascii").replace("\\u", "u").replace("\\U", "U")


def load_character_variants() -> list[CharacterVariantSet]:
    variants = [
        _ensure_variants("zundamon", "ずんだもん", _find_psd("zundamon"), CHARACTER_PNGS.get("ずんだもん")),
        _ensure_variants("metan", "四国めたん", _find_psd("metan"), CHARACTER_PNGS.get("四国めたん")),
    ]
    for jp_name, path in CHARACTER_PNGS.items():
        if jp_name in {"ずんだもん", "四国めたん"}:
            continue
        key = character_variant_key(jp_name)
        variants.append(_ensure_variants(key, jp_name, None, path))
    return variants
