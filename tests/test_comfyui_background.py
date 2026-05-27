import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _write_preset(tmp_path, workflow_path, checkpoint="TestModel.safetensors"):
    preset_path = tmp_path / "presets.json"
    preset_path.write_text(
        json.dumps({
            "anime_standard": {
                "label": "背景（漫画風・標準）",
                "model_type": "sdxl",
                "checkpoint": checkpoint,
                "loras": [],
                "sampler": "dpmpp_2m_karras",
                "steps": 24,
                "cfg": 6.5,
                "width": 832,
                "height": 1472,
                "negative_prompt": "text, logo",
                "workflow_path": str(workflow_path),
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    return preset_path


def test_comfyui_not_running_aborts(monkeypatch):
    import httpx
    from core.comfyui_client import ComfyUIClient

    def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(httpx.ConnectError):
        ComfyUIClient().check_connection()


def test_preset_file_invalid_aborts(tmp_path):
    from core.comfyui_client import ComfyUIClient

    preset_path = tmp_path / "presets.json"
    preset_path.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="プリセット定義が不正"):
        ComfyUIClient(preset_file=str(preset_path)).load_presets()


def test_model_manifest_invalid_aborts(tmp_path):
    from core.comfyui_model_manager import ComfyUIModelManager

    manifest_path = tmp_path / "model_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    manager = ComfyUIModelManager()
    manager.manifest_path = str(manifest_path)

    with pytest.raises(RuntimeError, match="モデルマニフェストが不正"):
        manager._load_manifest()


def test_workflow_file_invalid_aborts(tmp_path):
    from core.comfyui_client import ComfyUIClient

    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text("[]", encoding="utf-8")
    preset_path = _write_preset(tmp_path, workflow_path)
    client = ComfyUIClient(preset_file=str(preset_path))

    with pytest.raises(RuntimeError, match="workflow JSONが不正"):
        client._load_workflow(str(workflow_path))


def test_checkpoint_unset_aborts(tmp_path):
    from core.comfyui_client import ComfyUIClient

    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text("{}", encoding="utf-8")
    preset_path = _write_preset(tmp_path, workflow_path, checkpoint="")

    with pytest.raises(RuntimeError, match="checkpointが未設定"):
        ComfyUIClient(preset_file=str(preset_path)).load_preset("anime_standard")


def test_checkpoint_missing_aborts(monkeypatch, tmp_path):
    import httpx
    from core.comfyui_client import ComfyUIClient

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "CheckpointLoaderSimple": {
                    "input": {"required": {"ckpt_name": [["OtherModel.safetensors"]]}}
                }
            }

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kwargs: FakeResponse())

    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text("{}", encoding="utf-8")
    preset_path = _write_preset(tmp_path, workflow_path)

    with pytest.raises(RuntimeError, match="checkpointが見つかりません"):
        ComfyUIClient(preset_file=str(preset_path))._validate_checkpoint_available("TestModel.safetensors")


def test_invalid_output_image_aborts(tmp_path):
    from core.comfyui_client import ComfyUIClient

    img_path = tmp_path / "bad.png"
    img_path.write_bytes(b"bad")

    with pytest.raises(RuntimeError, match="ファイルサイズが小さすぎます"):
        ComfyUIClient()._validate_image(str(img_path), 832, 1472)


def test_local_comfyui_failure_writes_failed_meta_and_does_not_call_nanobanana(monkeypatch, tmp_path):
    from core.comfyui_client import ComfyUIClient
    from core.comfyui_model_manager import ComfyUIModelManager
    from core.image_generator import ImageGenerator

    monkeypatch.setattr(ComfyUIModelManager, "check_all_models_ready", lambda self: True)
    # COMFYUI_PROMPT_TRANSLATE_ENABLED=True 時の Ollama 接続を回避する
    import config as _cfg
    monkeypatch.setattr(_cfg, "COMFYUI_PROMPT_TRANSLATE_ENABLED", False)

    def fail_generate(self, **kwargs):
        raise RuntimeError("ComfyUI down")

    def fail_nanobanana(self, description, raw=False):
        raise AssertionError("Nano Banana path must not be called")

    monkeypatch.setattr(ComfyUIClient, "generate_image", fail_generate)
    monkeypatch.setattr(ImageGenerator, "_build_full_prompt", fail_nanobanana)

    bg_dir = tmp_path / "theme" / "backgrounds"
    gen = ImageGenerator(background_engine="local_comfyui", comfyui_preset="anime_standard")
    with pytest.raises(RuntimeError, match="ComfyUI down"):
        gen.generate_background("背景: テスト", target_dir=str(bg_dir), fname="bg_001_001.png")

    meta_path = tmp_path / "theme" / "_meta" / "image_generation.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["fallback_used"] is False
    assert "ComfyUI down" in data["error_message"]
    assert data["entries"][-1]["status"] == "failed"


def test_local_comfyui_model_missing_writes_failed_meta(monkeypatch, tmp_path):
    from core.comfyui_model_manager import ComfyUIModelManager
    from core.image_generator import ImageGenerator

    # COMFYUI_PROMPT_TRANSLATE_ENABLED=True 時の Ollama 接続を回避する
    import config as _cfg
    monkeypatch.setattr(_cfg, "COMFYUI_PROMPT_TRANSLATE_ENABLED", False)

    def fail_model_check(self):
        raise RuntimeError("ComfyUI必要モデルが不足しています。不足: TestModel.safetensors")

    monkeypatch.setattr(ComfyUIModelManager, "check_all_models_ready", fail_model_check)

    bg_dir = tmp_path / "theme" / "backgrounds"
    gen = ImageGenerator(background_engine="local_comfyui", comfyui_preset="anime_standard")
    with pytest.raises(RuntimeError, match="TestModel"):
        gen.generate_background("背景: テスト", target_dir=str(bg_dir), fname="bg_001_001.png")

    meta_path = tmp_path / "theme" / "_meta" / "image_generation.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["fallback_used"] is False
    assert "TestModel.safetensors" in data["error_message"]


def test_nanobanana_engine_keeps_existing_no_key_behavior(monkeypatch):
    import core.image_generator as image_generator

    monkeypatch.setattr(image_generator, "GOOGLE_API_KEY", "")
    gen = image_generator.ImageGenerator(background_engine="nanobanana")
    assert gen.generate_background("背景") is None
