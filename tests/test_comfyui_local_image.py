"""ComfyUI（ローカル）画像生成と文字入れのテスト。実際の ComfyUI・GPU は使わず、偽の API サーバーで確かめる。"""
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from config import config as cfg
from core import comfyui_generator, local_image_compose
from core.comfyui_generator import ComfyUIError, ComfyUIGenerator

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FONT_CANDIDATES = [
    cfg.IMAGE_TEXT_FONT_PATH,
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]


@pytest.fixture
def font(monkeypatch):
    path = next((p for p in _FONT_CANDIDATES if p and os.path.isfile(p)), None)
    if path is None:
        pytest.skip("この環境には日本語フォントが無い（Windows は YuGothB.ttc、macOS はヒラギノで実行される）")
    monkeypatch.setattr(cfg, "IMAGE_TEXT_FONT_PATH", path)
    return path


def _png(width, height, color=(40, 90, 160)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeComfy(BaseHTTPRequestHandler):
    """/prompt → /history → /view の流れだけを真似る。"""
    received = []
    fail = False

    def log_message(self, *_args):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).received.append(json.loads(self.rfile.read(length)))
        self._json(200, {"prompt_id": "p1"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/history/p1":
            if type(self).fail:
                record = {"status": {"status_str": "error", "messages": [
                    ["execution_error", {"exception_message": "モデルが見つかりません"}]]}}
            else:
                record = {"status": {"status_str": "success"},
                          "outputs": {"9": {"images": [{"filename": "bg.png", "subfolder": "yukkurijidou", "type": "output"}]}}}
            self._json(200, {"p1": record})
        elif url.path == "/view":
            assert parse_qs(url.query)["filename"] == ["bg.png"]
            body = _png(64, 36)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json(404, {})


@pytest.fixture
def fake_comfy():
    _FakeComfy.received = []
    _FakeComfy.fail = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeComfy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _FakeComfy
    finally:
        server.shutdown()
        server.server_close()


def test_generate_png_sends_krea_workflow_and_returns_image(fake_comfy, monkeypatch):
    url, handler = fake_comfy
    monkeypatch.setattr(cfg, "COMFYUI_WORKFLOW_PATH", "")
    with ComfyUIGenerator(base_url=url, timeout=10) as gen:
        png, seed = gen.generate_png("夜の商店街", width=1344, height=768, seed=7)
    assert png.startswith(b"\x89PNG") and seed == 7
    workflow = handler.received[0]["prompt"]
    assert workflow["4"]["inputs"]["text"] == "夜の商店街"
    assert workflow["1"]["inputs"]["unet_name"] == cfg.COMFYUI_KREA_UNET
    assert workflow["6"]["inputs"]["width"] == 1344 and workflow["7"]["inputs"]["seed"] == 7


def test_comfy_execution_error_is_raised_with_reason(fake_comfy):
    url, handler = fake_comfy
    handler.fail = True
    with ComfyUIGenerator(base_url=url, timeout=10) as gen:
        with pytest.raises(ComfyUIError, match="モデルが見つかりません"):
            gen.generate_png("x", width=64, height=64)


def test_custom_workflow_placeholders(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text(json.dumps({"1": {"class_type": "X", "inputs": {"text": "{{PROMPT}}", "w": "{{WIDTH}}", "seed": "{{SEED}}"}}}), encoding="utf-8")
    wf = comfyui_generator.custom_workflow(str(path), "猫", width=512, height=512, seed=3, steps=8)
    assert wf["1"]["inputs"] == {"text": "猫", "w": 512, "seed": 3}
    path.write_text(json.dumps({"1": {"class_type": "X", "inputs": {"text": "固定"}}}), encoding="utf-8")
    with pytest.raises(ComfyUIError):
        comfyui_generator.custom_workflow(str(path), "猫", width=512, height=512, seed=3, steps=8)


def test_generation_size_keeps_orientation_and_multiple_of_16(monkeypatch):
    monkeypatch.setattr(cfg, "COMFYUI_GEN_LONG_EDGE", 1350)
    monkeypatch.setattr(cfg, "COMFYUI_GEN_SHORT_EDGE", 770)
    assert comfyui_generator.generation_size(1920, 1080) == (1344, 768)
    assert comfyui_generator.generation_size(1080, 1920) == (768, 1344)


@pytest.mark.parametrize(
    ("description", "prompt_part", "text"),
    [
        ("漫画風の会議室。「ネタ会議」", "漫画風の会議室", "ネタ会議"),
        ("夕焼けの田んぼ。キャッチコピー「実は危険」を上部中央に配置。", "夕焼けの田んぼ", "実は危険"),
        ("工場の内部「驚きの製法」。【テロップ演出】画面上部中央に超大型の日本語テロップ「衝撃」を描画。フォント：極太", "工場の内部", "衝撃"),
        ("文字のない森の背景", "文字のない森の背景", ""),
    ],
)
def test_split_overlay_text(description, prompt_part, text):
    parts = local_image_compose.split_overlay_text(description)
    assert parts.overlay_text == text
    assert prompt_part in parts.prompt
    assert "「" not in parts.prompt and "テロップ" not in parts.prompt


def test_missing_font_stops_with_error_code(monkeypatch):
    from core.error_codes import AppError
    monkeypatch.setattr(cfg, "IMAGE_TEXT_FONT_PATH", "/no/such/font.ttc")
    with pytest.raises(AppError) as exc:
        local_image_compose.draw_overlay_text(Image.new("RGB", (100, 100)), "文字")
    assert exc.value.code == "E-IMG-FONT"


def _pixels(img, box):
    data = img.crop(box).convert("RGB").tobytes()
    return [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]


def _white_pixels(img, box):
    return sum(1 for p in _pixels(img, box) if min(p) > 240)


def test_background_is_generated_without_text_then_text_is_drawn(font, monkeypatch, tmp_path):
    from core.image_generator import ImageGenerator

    monkeypatch.setattr(cfg, "IMAGE_BACKEND", "comfyui")
    sent = {}

    def fake_generate_png(self, prompt, *, width, height, seed=None):
        sent.update(prompt=prompt, width=width, height=height)
        return _png(width, height), 11

    monkeypatch.setattr(ComfyUIGenerator, "generate_png", fake_generate_png)
    with ImageGenerator(width=1920, height=1080) as gen:
        name = gen.generate_background("夜の屋台。「実は危険」", target_dir=str(tmp_path))
    assert name == "bg_001_001.png"
    assert "「" not in sent["prompt"] and "文字" in sent["prompt"]
    assert (sent["width"], sent["height"]) == comfyui_generator.generation_size(1920, 1080)
    with Image.open(tmp_path / name) as img:
        assert img.size == (1920, 1080)
        assert _white_pixels(img, (0, 0, 1920, 300)) > 500      # 上部に白文字
        assert _white_pixels(img, (0, 600, 1920, 1080)) == 0    # 下部には何も描かない


def test_local_thumbnail_pastes_characters_and_title(font, monkeypatch, tmp_path):
    from core.image_generator import ImageGenerator

    monkeypatch.setattr(cfg, "IMAGE_BACKEND", "comfyui")
    monkeypatch.setattr(ComfyUIGenerator, "generate_png", lambda self, prompt, **k: (_png(k["width"], k["height"], (0, 0, 0)), 1))
    zundamon = os.path.join(_ROOT, "assets", "characters", "zundamon.png")
    with ImageGenerator(width=1280, height=720) as gen:
        name = gen.generate_background(
            "題材の絵", target_dir=str(tmp_path), raw=True, is_thumbnail=True,
            reference_image_paths=[zundamon], overlay_text="ずんだ餅の秘密",
        )
    with Image.open(tmp_path / name) as img:
        assert any(p != (0, 0, 0) for p in _pixels(img, (0, 400, 300, 720)))   # 立ち絵が左下にある
        assert _white_pixels(img, (0, 0, 1280, 200)) > 300           # 上部にサムネ文字
