"""
SDWebUIModelManager 統合テスト + ImageGenerator の SD WebUI モデル準備フローテスト。
実ネットワーク通信は行わない（monkeypatch で分離）。
"""
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ─────────────────────────────────────────────────────────────────
# ヘルパー
# ─────────────────────────────────────────────────────────────────

def _write_manifest(tmp_path, sha256="", source_url="http://example.com/test.safetensors"):
    models = [{
        "id": "test_model",
        "display_name": "Test",
        "type": "checkpoint",
        "filename": "test.safetensors",
        "target_subdir": "models/Stable-diffusion",
        "source_url": source_url,
        "sha256": sha256,
        "description": "",
        "recommended": True,
        "requires_auth": False,
        "api_match_hint": "test",
    }]
    path = tmp_path / "model_manifest.json"
    path.write_text(json.dumps({"version": 1, "models": models}, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ─────────────────────────────────────────────────────────────────
# StableDiffusionWebUIGenerator のモデル管理メソッドテスト
# ─────────────────────────────────────────────────────────────────

class TestStableDiffusionWebUIGeneratorModelMethods:
    def test_get_current_model_returns_checkpoint_name(self, monkeypatch):
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        class FakeResp:
            status_code = 200
            text = ""
            def json(self):
                return {"sd_model_checkpoint": "test.safetensors [abc123]"}

        monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
        gen = StableDiffusionWebUIGenerator()
        assert gen.get_current_model() == "test.safetensors [abc123]"

    def test_get_models_returns_list(self, monkeypatch):
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        class FakeResp:
            status_code = 200
            text = ""
            def json(self):
                return [{"title": "test.safetensors [abc]", "model_name": "test", "filename": "/models/test.safetensors"}]

        monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeResp())
        gen = StableDiffusionWebUIGenerator()
        models = gen.get_models()
        assert isinstance(models, list)
        assert models[0]["title"] == "test.safetensors [abc]"

    def test_set_active_model_success(self, monkeypatch):
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        class FakeGetResp:
            status_code = 200
            text = ""
            def json(self):
                return [{"title": "test.safetensors [abc]", "model_name": "test", "filename": "/models/test.safetensors"}]

        class FakePostResp:
            status_code = 200
            text = ""
            def json(self):
                return {}

        monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeGetResp())
        monkeypatch.setattr(httpx, "post", lambda url, **kw: FakePostResp())
        gen = StableDiffusionWebUIGenerator()
        # Should not raise
        gen.set_active_model("test")

    def test_set_active_model_not_found_raises(self, monkeypatch):
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        class FakeGetResp:
            status_code = 200
            text = ""
            def json(self):
                return [{"title": "other.safetensors [abc]", "model_name": "other", "filename": "/models/other.safetensors"}]

        monkeypatch.setattr(httpx, "get", lambda url, **kw: FakeGetResp())
        gen = StableDiffusionWebUIGenerator()
        with pytest.raises(RuntimeError, match="見つかりません"):
            gen.set_active_model("nonexistent_model")

    def test_rescan_models_calls_refresh_endpoint(self, monkeypatch):
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        called = []

        class FakePostResp:
            status_code = 200
            text = ""

        def fake_post(url, **kw):
            called.append(url)
            return FakePostResp()

        monkeypatch.setattr(httpx, "post", fake_post)
        gen = StableDiffusionWebUIGenerator()
        gen.rescan_models()
        assert any("refresh-checkpoints" in u for u in called)

    def test_connect_error_on_get_models_raises_runtime(self, monkeypatch):
        import httpx
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        monkeypatch.setattr(httpx, "get", lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("refused")))
        gen = StableDiffusionWebUIGenerator()
        with pytest.raises(RuntimeError, match="接続できません"):
            gen.get_models()


# ─────────────────────────────────────────────────────────────────
# ImageGenerator の _prepare_sd_webui_model テスト
# ─────────────────────────────────────────────────────────────────

class TestPrepareSDWebUIModel:
    def test_no_model_set_skips_all_checks(self, monkeypatch, tmp_path):
        """SD_WEBUI_MODEL が空のときはモデル準備を完全スキップする"""
        import config as _cfg
        from core.image_generator import ImageGenerator

        monkeypatch.setattr(_cfg, "IMAGE_BACKEND", "sd_webui")
        monkeypatch.setattr(_cfg, "SD_WEBUI_MODEL", "")

        gen = ImageGenerator()
        # should not raise even without SD WebUI running
        gen._prepare_sd_webui_model()

    def test_model_set_and_installed_calls_set_active(self, monkeypatch, tmp_path):
        """モデルがインストール済みであれば set_active_model が呼ばれる"""
        import config as _cfg
        from core.image_generator import ImageGenerator
        from core.sd_model_manager import SDWebUIModelManager
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        monkeypatch.setattr(_cfg, "IMAGE_BACKEND", "sd_webui")
        monkeypatch.setattr(_cfg, "SD_WEBUI_MODEL", "test.safetensors")
        monkeypatch.setattr(_cfg, "SD_WEBUI_ROOT", str(tmp_path / "sd_root"))

        manifest_path = _write_manifest(tmp_path)
        monkeypatch.setattr(_cfg, "SD_MODEL_MANIFEST_PATH", manifest_path)

        # モデルファイルを作成（インストール済みにする）
        model_dir = tmp_path / "sd_root" / "models" / "Stable-diffusion"
        model_dir.mkdir(parents=True)
        (model_dir / "test.safetensors").write_bytes(b"fake")

        set_active_called = []
        monkeypatch.setattr(StableDiffusionWebUIGenerator, "set_active_model",
                            lambda self, name: set_active_called.append(name))

        gen = ImageGenerator()
        gen._prepare_sd_webui_model()
        assert "test.safetensors" in set_active_called

    def test_model_missing_no_auto_download_raises(self, monkeypatch, tmp_path):
        """モデル未インストール + AUTO_DOWNLOAD_SD_MODELS=False → RuntimeError"""
        import config as _cfg
        from core.image_generator import ImageGenerator

        monkeypatch.setattr(_cfg, "IMAGE_BACKEND", "sd_webui")
        monkeypatch.setattr(_cfg, "SD_WEBUI_MODEL", "test.safetensors")
        monkeypatch.setattr(_cfg, "SD_WEBUI_ROOT", str(tmp_path / "sd_root"))
        monkeypatch.setattr(_cfg, "AUTO_DOWNLOAD_SD_MODELS", False)

        manifest_path = _write_manifest(tmp_path)
        monkeypatch.setattr(_cfg, "SD_MODEL_MANIFEST_PATH", manifest_path)

        gen = ImageGenerator()
        with pytest.raises(RuntimeError, match="インストールされていません"):
            gen._prepare_sd_webui_model()

    def test_model_missing_with_auto_download_triggers_download(self, monkeypatch, tmp_path):
        """モデル未インストール + AUTO_DOWNLOAD_SD_MODELS=True → ダウンロードが呼ばれる"""
        import httpx
        import config as _cfg
        from core.image_generator import ImageGenerator
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        monkeypatch.setattr(_cfg, "IMAGE_BACKEND", "sd_webui")
        monkeypatch.setattr(_cfg, "SD_WEBUI_MODEL", "test.safetensors")
        monkeypatch.setattr(_cfg, "SD_WEBUI_ROOT", str(tmp_path / "sd_root"))
        monkeypatch.setattr(_cfg, "AUTO_DOWNLOAD_SD_MODELS", True)

        manifest_path = _write_manifest(tmp_path)
        monkeypatch.setattr(_cfg, "SD_MODEL_MANIFEST_PATH", manifest_path)

        fake_content = b"fake model"

        class FakeStream:
            status_code = 200
            headers = {"content-length": str(len(fake_content))}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def iter_bytes(self, chunk_size=65536): yield fake_content

        monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FakeStream())

        set_active_called = []
        rescan_called = []
        monkeypatch.setattr(StableDiffusionWebUIGenerator, "set_active_model",
                            lambda self, name: set_active_called.append(name))
        monkeypatch.setattr(StableDiffusionWebUIGenerator, "rescan_models",
                            lambda self: rescan_called.append(True))

        gen = ImageGenerator()
        gen._prepare_sd_webui_model()

        assert rescan_called, "rescan_models が呼ばれていません"
        assert set_active_called, "set_active_model が呼ばれていません"
