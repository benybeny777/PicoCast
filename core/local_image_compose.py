"""ローカル画像生成（ComfyUI）の後処理: 日本語の文字入れと立ち絵の合成。

Nano Banana は台本の「背景:」に書かれたキャッチコピー（「」で囲んだ文字）やテロップを
画像の中に描いてくれるが、ローカルの画像モデルに日本語を描かせると崩れる。そこで
プロンプトから文字の指定を取り除いて文字なしで生成し、生成後に Pillow で文字を重ねる。
文字の見た目は Nano Banana へ指示していたものに揃える（白文字・極太の黒縁・影・太ゴシック）。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from config import config as cfg
from core.error_codes import AppError

_logger = logging.getLogger(__name__)

_QUOTED = re.compile(r"「([^「」]{1,40})」")
# workers/main.py:merge_telops_into_backgrounds() が背景プロンプトへ足すテロップ演出の文
_TELOP_SENTENCE = re.compile(r"【テロップ演出】[^【]*?「([^「」]{1,40})」[^【]*")

NO_TEXT_INSTRUCTION = "文字・ロゴ・看板の文字・字幕は一切描かない。人物・キャラクターは描かない。"


@dataclass
class PromptText:
    """文字の指定を取り除いたプロンプトと、画像へ重ねる文字。"""
    prompt: str
    overlay_text: str


def split_overlay_text(description: str) -> PromptText:
    """背景プロンプトから重ねる文字を取り出す。テロップ演出があればテロップを、無ければ最初の「」を使う。"""
    telop_match = _TELOP_SENTENCE.search(description)
    telop = telop_match.group(1).strip() if telop_match else ""
    without_telop = _TELOP_SENTENCE.sub("", description)
    quoted = _QUOTED.findall(without_telop)
    overlay = telop or (quoted[0].strip() if quoted else "")
    prompt = _QUOTED.sub("", without_telop)
    # 「キャッチコピーを上部中央に」のような文字配置の指示は、文字を消したあとでは誤解を招くため落とす
    prompt = re.sub(r"[^。]*(キャッチコピー|テキスト|文字)[^。]*(配置|描画|入れ)[^。]*。?", "", prompt)
    prompt = re.sub(r"\s+", " ", prompt).strip(" 、。")
    return PromptText(prompt=prompt, overlay_text=overlay)


def _font(size: int):
    from PIL import ImageFont

    path = cfg.IMAGE_TEXT_FONT_PATH
    if not path or not os.path.isfile(path):
        _logger.error("画像の文字入れに使うフォントが見つかりません: path=%s", path)
        raise AppError("E-IMG-FONT", path or "IMAGE_TEXT_FONT_PATH が未設定")
    return ImageFont.truetype(path, size)


def draw_overlay_text(image, text: str) -> None:
    """画像の上部中央へ文字を描く（白文字・極太の黒縁・影）。image は RGB/RGBA の PIL 画像。"""
    from PIL import ImageDraw

    text = text.strip()
    if not text:
        return
    width, height = image.size
    is_portrait = height > width
    target_height = height * (cfg.IMAGE_TEXT_HEIGHT_RATIO_SHORTS if is_portrait else cfg.IMAGE_TEXT_HEIGHT_RATIO_LONG)
    max_width = width * cfg.IMAGE_TEXT_MAX_WIDTH_RATIO
    size = max(12, int(target_height))
    font = _font(size)
    draw = ImageDraw.Draw(image)
    stroke = max(2, size // 9)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    if bbox[2] - bbox[0] > max_width:
        size = max(12, int(size * max_width / (bbox[2] - bbox[0])))
        font = _font(size)
        stroke = max(2, size // 9)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) / 2 - bbox[0]
    y = height * (cfg.IMAGE_TEXT_TOP_RATIO_SHORTS if is_portrait else cfg.IMAGE_TEXT_TOP_RATIO_LONG) - bbox[1]
    shadow = max(3, size // 14)
    draw.text((x + shadow, y + shadow), text, font=font, fill=(0, 0, 0), stroke_width=stroke, stroke_fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=(255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0))


def paste_characters(image, character_paths: list[str]) -> None:
    """サムネイル用に立ち絵を左下・右下へ合成する（最大2体）。"""
    from PIL import Image

    paths = [p for p in character_paths if p and os.path.isfile(p)][:2]
    width, height = image.size
    target_h = int(height * cfg.THUMBNAIL_CHARACTER_HEIGHT_RATIO)
    for index, path in enumerate(paths):
        with Image.open(path) as src:
            char = src.convert("RGBA")
        scale = target_h / char.height
        resized = char.resize((max(1, int(char.width * scale)), target_h), Image.LANCZOS)
        char.close()
        x = 0 if index == 0 else width - resized.width
        image.paste(resized, (x, height - target_h), resized)
        resized.close()
