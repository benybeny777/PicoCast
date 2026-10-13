"""
tests/test_sd_webui_generator.py

StableDiffusionWebUIGenerator の単体テスト。
実APIは叩かず requests / httpx を monkeypatch/mock する。
"""
import base64
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ─────────────────────────────────────────────────────────────────────────────
# テスト用ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

def _make_fake_response(status_code=200, json_data=None, text=""):
    """httpx.Response の最小モックを返す。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def _fake_client(*, get=None, post=None):
    client = MagicMock()
    if get is not None and hasattr(get, "status_code"):
        client.get.return_value = get
    elif get is not None:
        client.get.side_effect = get
    if post is not None and hasattr(post, "status_code"):
        client.post.return_value = post
    elif post is not None:
        client.post.side_effect = post
    return patch("core.sd_webui_generator.httpx.Client", return_value=client)


def _png_b64() -> str:
    """1x1 白ピクセルの最小 PNG を base64 エンコードして返す。"""
    # 最小有効 PNG バイト列（1x1 px, 白）
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"                     # シグネチャ
        b"\x00\x00\x00\rIHDR"                     # IHDR チャンク長
        b"\x00\x00\x00\x01\x00\x00\x00\x01"       # width=1, height=1
        b"\x08\x02\x00\x00\x00\x90wS\xde"         # bit depth, color type, compress, filter, interlace + CRC
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00" # IDAT チャンク
        b"\x00\x01\x01\x00\x05\x18\xd8N"          # IDAT data + CRC
        b"\x00\x00\x00\x00IEND\xaeB`\x82"         # IEND チャンク
    )
    return base64.b64encode(png_bytes).decode()


# ─────────────────────────────────────────────────────────────────────────────
# StableDiffusionWebUIGenerator テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckHealth:
    def test_ok(self):
        """check_health が正常レスポンスを返すとき {'ok': True, 'model': ...} が返る。"""
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        fake = _make_fake_response(200, {"sd_model_checkpoint": "someModel.safetensors"})
        with _fake_client(get=fake):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            result = gen.check_health()

        assert result["ok"] is True
        assert result["model"] == "someModel.safetensors"
        assert result["url"] == "http://127.0.0.1:7860"

    def test_connect_error_raises(self):
        """API 未起動時 (ConnectError) は RuntimeError に変換される。"""
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        with _fake_client(get=lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("connection refused"))):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            with pytest.raises(RuntimeError, match="接続できません"):
                gen.check_health()

    def test_http_error_raises(self):
        """HTTP 500 エラー時は RuntimeError になる。"""
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        fake = _make_fake_response(500, text="internal server error")
        with _fake_client(get=fake):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            with pytest.raises(RuntimeError, match="status=500"):
                gen.check_health()


def _fake_get_ok(url, **kwargs):
    """httpx.get のスタブ — SD WebUI が起動済みの状態をシミュレートする。"""
    return _make_fake_response(200, {"sd_model_checkpoint": "mock.safetensors"})


class TestGenerateImage:
    def test_success_saves_png(self, tmp_path):
        """正常レスポンス → base64 PNG を指定パスに保存して output_path を返す。"""
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        b64 = _png_b64()
        fake_post = _make_fake_response(200, {"images": [b64]})
        output = str(tmp_path / "out.png")

        with _fake_client(get=_fake_get_ok, post=fake_post):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            result = gen.generate_image("テスト背景", output)

        assert result == output
        assert os.path.isfile(output)
        assert os.path.getsize(output) > 0

    def test_parent_dir_created(self, tmp_path):
        """output_path の親ディレクトリが存在しなければ自動作成される。"""
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        b64 = _png_b64()
        fake_post = _make_fake_response(200, {"images": [b64]})
        nested = str(tmp_path / "a" / "b" / "out.png")

        with _fake_client(get=_fake_get_ok, post=fake_post):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            gen.generate_image("テスト", nested)

        assert os.path.isfile(nested)

    def test_api_error_raises_no_garbage_file(self, tmp_path):
        """APIエラー時は RuntimeError を上げ、壊れたファイルを残さない。"""
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        fake_post = _make_fake_response(500, text="GPU out of memory")
        output = str(tmp_path / "fail.png")

        with _fake_client(get=_fake_get_ok, post=fake_post):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            with pytest.raises(RuntimeError):
                gen.generate_image("test", output)

        assert not os.path.exists(output)
        assert not os.path.exists(output + ".tmp")

    def test_connect_error_post_no_garbage_file(self, tmp_path):
        """POST ConnectError 時も壊れたファイルを残さない。"""
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        output = str(tmp_path / "conn_fail.png")
        with _fake_client(
            get=_fake_get_ok,
            post=lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        ):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            with pytest.raises(RuntimeError, match="接続できません"):
                gen.generate_image("test", output)

        assert not os.path.exists(output)

    def test_empty_images_raises(self, tmp_path):
        """レスポンスに images キーがない場合は RuntimeError になる。"""
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        fake_post = _make_fake_response(200, {"images": []})
        output = str(tmp_path / "empty.png")

        with _fake_client(get=_fake_get_ok, post=fake_post):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            with pytest.raises(RuntimeError, match="画像データがありません"):
                gen.generate_image("test", output)

    def test_prompt_suffix_appended(self, tmp_path):
        """prompt_suffix が送信ペイロードの prompt に付加される。"""
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        b64 = _png_b64()
        fake_post = _make_fake_response(200, {"images": [b64]})
        output = str(tmp_path / "suffix.png")
        captured = {}

        def mock_post(url, json=None, timeout=None):
            captured["prompt"] = json.get("prompt", "")
            return fake_post

        with _fake_client(get=_fake_get_ok, post=mock_post):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            gen.generate_image("ベースプロンプト", output, prompt_suffix=", anime style")

        assert captured["prompt"] == "ベースプロンプト, anime style"

    def test_timeout_raises_runtime_error(self, tmp_path):
        """タイムアウト時は RuntimeError になる。"""
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        output = str(tmp_path / "timeout.png")
        with _fake_client(
            get=_fake_get_ok,
            post=lambda *a, **kw: (_ for _ in ()).throw(httpx.TimeoutException("timed out")),
        ):
            gen = StableDiffusionWebUIGenerator(base_url="http://127.0.0.1:7860")
            with pytest.raises(RuntimeError, match="タイムアウト"):
                gen.generate_image("test", output)


# ─────────────────────────────────────────────────────────────────────────────
# ImageGenerator バックエンド分岐テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestImageGeneratorBackendDispatch:
    def test_sd_webui_backend_calls_sd_generator(self, tmp_path, monkeypatch):
        """background_engine='sd_webui' のとき SD WebUI 生成関数が呼ばれる。"""
        from core.image_generator import ImageGenerator

        called = {}

        def fake_sd_webui(self_inner, desc, save_dir, fname, *, is_thumbnail=False):
            called["args"] = (desc, save_dir, fname)
            return "bg_001_001.png"

        monkeypatch.setattr(
            "core.image_generator.ImageGenerator._generate_background_sd_webui",
            fake_sd_webui,
        )
        bg_dir = str(tmp_path / "backgrounds")
        os.makedirs(bg_dir, exist_ok=True)

        with ImageGenerator(width=1920, height=1080, background_engine="sd_webui") as gen:
            result = gen.generate_background("山の風景", target_dir=bg_dir)

        assert result == "bg_001_001.png"
        assert "args" in called

    def test_unsupported_backend_raises(self):
        """未対応エンジン名を渡すと RuntimeError になる。"""
        from core.image_generator import ImageGenerator

        with pytest.raises((RuntimeError, ValueError)):
            with ImageGenerator(background_engine="unknown_engine") as gen:
                gen.generate_background("test", target_dir="/tmp")

    def test_image_backend_env_sd_webui(self, monkeypatch, tmp_path):
        """IMAGE_BACKEND=sd_webui のとき sd_webui エンジンが選ばれる。"""
        from config import config
        monkeypatch.setattr(config, "IMAGE_BACKEND", "sd_webui")

        from core.image_generator import ImageGenerator

        # background_engine 明示なし → IMAGE_BACKEND に従う
        gen = ImageGenerator(width=1920, height=1080)
        try:
            assert gen.background_engine == "sd_webui"
        finally:
            gen.close()

    def test_image_backend_env_gemini(self, monkeypatch, dummy_google_api_key):
        """IMAGE_BACKEND=gemini のとき nanobanana が選ばれる。"""
        from config import config
        monkeypatch.setattr(config, "IMAGE_BACKEND", "gemini")

        from core.image_generator import ImageGenerator

        gen = ImageGenerator(width=1920, height=1080)
        try:
            assert gen.background_engine == "nanobanana"
        finally:
            gen.close()

    def test_unsupported_image_backend_raises(self, monkeypatch):
        """IMAGE_BACKEND に未対応値を設定すると ValueError になる。"""
        from config import config
        monkeypatch.setattr(config, "IMAGE_BACKEND", "totally_unknown")

        from core.image_generator import ImageGenerator

        with pytest.raises(ValueError, match="未対応の IMAGE_BACKEND"):
            ImageGenerator(width=1920, height=1080)


@pytest.mark.parametrize(("width", "height"), [(1080, 1920), (1920, 1080)])
def test_sd_webui_keeps_requested_orientation(monkeypatch, tmp_path, width, height):
    """Shorts（1080x1920）は縦長のまま Stable Diffusion WebUI に依頼する（以前は横長に入れ替わっていた）。"""
    import core.image_generator as ig
    import core.sd_webui_generator as sd

    sizes = []

    class FakeGenerator:
        def __init__(self, width, height):
            sizes.append((width, height))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def generate_image(self, prompt, output_path, prompt_suffix=""):
            return output_path

    monkeypatch.setattr(sd, "StableDiffusionWebUIGenerator", FakeGenerator)
    monkeypatch.setattr(ig, "_translate_to_english_for_sd", lambda description, debug=False: "background")
    monkeypatch.setattr(ig.ImageGenerator, "_prepare_sd_webui_model", lambda self: None)
    with ig.ImageGenerator(width=width, height=height, background_engine="sd_webui") as gen:
        gen.generate_background("背景", target_dir=str(tmp_path))
    assert sizes == [(width, height)]
