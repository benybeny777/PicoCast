"""
SDWebUIModelManager のユニットテスト。
実ファイルIO・ネットワーク通信は行わない（tmp_path / monkeypatch で分離）。
"""
import hashlib
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

def _write_manifest(tmp_path, models=None):
    if models is None:
        models = [
            {
                "id": "test_model",
                "display_name": "Test Checkpoint",
                "type": "checkpoint",
                "filename": "test.safetensors",
                "target_subdir": "models/Stable-diffusion",
                "source_url": "http://example.com/test.safetensors",
                "sha256": "",
                "description": "テスト用モデル",
                "recommended": True,
                "requires_auth": False,
                "api_match_hint": "test",
            }
        ]
    path = tmp_path / "model_manifest.json"
    path.write_text(json.dumps({"version": 1, "models": models}, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────────
# マニフェスト読み込みテスト
# ─────────────────────────────────────────────────────────────────

class TestLoadManifest:
    def test_valid_manifest_loads_ok(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        manager = SDWebUIModelManager(manifest_path=manifest_path)
        data = manager._load_manifest()
        assert data["version"] == 1
        assert len(data["models"]) == 1

    def test_missing_file_raises(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manager = SDWebUIModelManager(manifest_path=str(tmp_path / "nonexistent.json"))
        with pytest.raises(RuntimeError, match="見つかりません"):
            manager._load_manifest()

    def test_invalid_json_raises(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid}", encoding="utf-8")
        manager = SDWebUIModelManager(manifest_path=str(bad))
        with pytest.raises(RuntimeError, match="JSON解析に失敗"):
            manager._load_manifest()

    def test_missing_required_keys_raises(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        path = tmp_path / "m.json"
        path.write_text(json.dumps({"version": 1}), encoding="utf-8")  # models キーなし
        manager = SDWebUIModelManager(manifest_path=str(path))
        with pytest.raises(RuntimeError, match="不正です"):
            manager._load_manifest()

    def test_models_not_list_raises(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        path = tmp_path / "m.json"
        path.write_text(json.dumps({"version": 1, "models": {}}), encoding="utf-8")
        manager = SDWebUIModelManager(manifest_path=str(path))
        with pytest.raises(RuntimeError, match="不正です"):
            manager._load_manifest()


# ─────────────────────────────────────────────────────────────────
# get_model_status テスト
# ─────────────────────────────────────────────────────────────────

class TestGetModelStatus:
    def test_model_not_installed_when_file_missing(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        sd_root = str(tmp_path / "sd_root")
        manager = SDWebUIModelManager(sd_root=sd_root, manifest_path=manifest_path)
        statuses = manager.get_model_status()
        assert len(statuses) == 1
        assert statuses[0]["installed"] is False
        assert statuses[0]["id"] == "test_model"

    def test_model_installed_when_file_exists(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        sd_root = tmp_path / "sd_root"
        model_dir = sd_root / "models" / "Stable-diffusion"
        model_dir.mkdir(parents=True)
        (model_dir / "test.safetensors").write_bytes(b"fake model data")
        manager = SDWebUIModelManager(sd_root=str(sd_root), manifest_path=manifest_path)
        statuses = manager.get_model_status()
        assert statuses[0]["installed"] is True

    def test_no_sd_root_path_is_none(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        manager = SDWebUIModelManager(sd_root="", manifest_path=manifest_path)
        statuses = manager.get_model_status()
        assert statuses[0]["path"] is None
        assert statuses[0]["installed"] is False

    def test_can_download_true_when_url_set(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        manager = SDWebUIModelManager(sd_root="", manifest_path=manifest_path)
        statuses = manager.get_model_status()
        assert statuses[0]["can_download"] is True

    def test_can_download_false_when_url_empty(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        models = [{
            "id": "no_url",
            "display_name": "No URL Model",
            "type": "checkpoint",
            "filename": "nourl.safetensors",
            "target_subdir": "models/Stable-diffusion",
            "source_url": "",
            "sha256": "",
            "description": "",
            "recommended": False,
            "requires_auth": False,
            "api_match_hint": "",
        }]
        manifest_path = _write_manifest(tmp_path, models)
        manager = SDWebUIModelManager(sd_root="", manifest_path=manifest_path)
        statuses = manager.get_model_status()
        assert statuses[0]["can_download"] is False


# ─────────────────────────────────────────────────────────────────
# check_all_models_ready テスト
# ─────────────────────────────────────────────────────────────────

class TestCheckAllModelsReady:
    def test_raises_when_model_missing(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        manager = SDWebUIModelManager(sd_root=str(tmp_path / "sd_root"), manifest_path=manifest_path)
        with pytest.raises(RuntimeError, match="不足"):
            manager.check_all_models_ready()

    def test_returns_true_when_all_installed(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        sd_root = tmp_path / "sd_root"
        model_dir = sd_root / "models" / "Stable-diffusion"
        model_dir.mkdir(parents=True)
        (model_dir / "test.safetensors").write_bytes(b"fake")
        manager = SDWebUIModelManager(sd_root=str(sd_root), manifest_path=manifest_path)
        assert manager.check_all_models_ready() is True


# ─────────────────────────────────────────────────────────────────
# download_model テスト
# ─────────────────────────────────────────────────────────────────

class TestDownloadModel:
    def test_unknown_id_raises(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        manifest_path = _write_manifest(tmp_path)
        manager = SDWebUIModelManager(sd_root=str(tmp_path / "sd_root"), manifest_path=manifest_path)
        with pytest.raises(RuntimeError, match="見つかりません"):
            manager.download_model("nonexistent_id")

    def test_empty_source_url_raises(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        models = [{
            "id": "no_url",
            "display_name": "No URL",
            "type": "checkpoint",
            "filename": "nourl.safetensors",
            "target_subdir": "models/Stable-diffusion",
            "source_url": "",
            "sha256": "",
            "description": "",
            "recommended": False,
            "requires_auth": False,
            "api_match_hint": "",
        }]
        manifest_path = _write_manifest(tmp_path, models)
        manager = SDWebUIModelManager(sd_root=str(tmp_path / "sd_root"), manifest_path=manifest_path)
        with pytest.raises(RuntimeError, match="URL.*設定されていません|ダウンロードURL"):
            manager.download_model("no_url")

    def test_download_success_with_sha256_skip(self, tmp_path, monkeypatch):
        """SHA256 が空文字の場合は検証スキップし、ファイルが正しく配置される"""
        import httpx
        from core.sd_model_manager import SDWebUIModelManager

        fake_content = b"fake model content"
        manifest_path = _write_manifest(tmp_path)  # sha256=""
        sd_root = tmp_path / "sd_root"
        manager = SDWebUIModelManager(sd_root=str(sd_root), manifest_path=manifest_path)

        class FakeStream:
            status_code = 200
            headers = {"content-length": str(len(fake_content))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_bytes(self, chunk_size=65536):
                yield fake_content

        monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FakeStream())

        dest = manager.download_model("test_model")
        assert os.path.isfile(dest)
        assert open(dest, "rb").read() == fake_content

    def test_download_sha256_mismatch_raises_and_cleans_part(self, tmp_path, monkeypatch):
        """SHA256 が不一致の場合は RuntimeError を送出し .part ファイルが残らない"""
        import httpx
        from core.sd_model_manager import SDWebUIModelManager

        fake_content = b"fake model content"
        wrong_sha256 = "a" * 64  # 明らかに不一致

        models = [{
            "id": "sha_model",
            "display_name": "SHA Model",
            "type": "checkpoint",
            "filename": "sha.safetensors",
            "target_subdir": "models/Stable-diffusion",
            "source_url": "http://example.com/sha.safetensors",
            "sha256": wrong_sha256,
            "description": "",
            "recommended": False,
            "requires_auth": False,
            "api_match_hint": "",
        }]
        manifest_path = _write_manifest(tmp_path, models)
        sd_root = tmp_path / "sd_root"
        manager = SDWebUIModelManager(sd_root=str(sd_root), manifest_path=manifest_path)

        class FakeStream:
            status_code = 200
            headers = {"content-length": str(len(fake_content))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_bytes(self, chunk_size=65536):
                yield fake_content

        monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FakeStream())

        with pytest.raises(RuntimeError, match="SHA256"):
            manager.download_model("sha_model")

        # .part ファイルが残っていないこと
        dest_dir = sd_root / "models" / "Stable-diffusion"
        parts = list(dest_dir.glob("*.part")) if dest_dir.exists() else []
        assert parts == [], f".part ファイルが残っています: {parts}"

    def test_download_http_error_raises(self, tmp_path, monkeypatch):
        """HTTP 非200応答は RuntimeError を送出する"""
        import httpx
        from core.sd_model_manager import SDWebUIModelManager

        manifest_path = _write_manifest(tmp_path)
        sd_root = tmp_path / "sd_root"
        manager = SDWebUIModelManager(sd_root=str(sd_root), manifest_path=manifest_path)

        class FakeStream:
            status_code = 403
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_bytes(self, chunk_size=65536):
                return iter([])

        monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FakeStream())

        with pytest.raises(RuntimeError, match="HTTP 403"):
            manager.download_model("test_model")

    def test_progress_callback_called(self, tmp_path, monkeypatch):
        """ダウンロード中に進捗コールバックが呼ばれる"""
        import httpx
        from core.sd_model_manager import SDWebUIModelManager

        fake_content = b"x" * 1024
        manifest_path = _write_manifest(tmp_path)
        sd_root = tmp_path / "sd_root"
        manager = SDWebUIModelManager(sd_root=str(sd_root), manifest_path=manifest_path)

        class FakeStream:
            status_code = 200
            headers = {"content-length": str(len(fake_content))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_bytes(self, chunk_size=65536):
                yield fake_content

        monkeypatch.setattr(httpx, "stream", lambda *a, **kw: FakeStream())

        calls = []
        manager.download_model("test_model", progress_callback=lambda f, d, t: calls.append((f, d, t)))
        assert len(calls) >= 1
        assert calls[0][0] == "test.safetensors"


# ─────────────────────────────────────────────────────────────────
# SHA256 ユーティリティ
# ─────────────────────────────────────────────────────────────────

class TestSha256File:
    def test_sha256_matches(self, tmp_path):
        from core.sd_model_manager import SDWebUIModelManager
        data = b"hello world"
        f = tmp_path / "file.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert SDWebUIModelManager._sha256_file(str(f)) == expected
