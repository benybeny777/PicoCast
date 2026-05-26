import os
import json
import hashlib
import requests
import config as _cfg

class ComfyUIModelManager:
    def __init__(self):
        self.root_dir = _cfg.COMFYUI_ROOT_DIR
        self.manifest_path = _cfg.COMFYUI_MODEL_MANIFEST_PATH
        self.verify_sha256 = getattr(_cfg, "COMFYUI_MODEL_VERIFY_SHA256", True)
        self.timeout = getattr(_cfg, "COMFYUI_MODEL_DOWNLOAD_TIMEOUT_SEC", 3600)
        self.models = self._load_manifest()

    def _load_manifest(self):
        if not os.path.exists(self.manifest_path):
            return []
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def get_model_status(self):
        """全モデルの導入状況を返す"""
        status_list = []
        for model in self.models:
            target_path = os.path.join(self.root_dir, model["target_dir"], model["name"])
            
            if os.path.exists(target_path):
                status = "installed"
            else:
                status = "missing"
            
            status_list.append({
                "name": model["name"],
                "type": model["type"],
                "target_dir": model["target_dir"],
                "target_path": target_path,
                "status": status,
                "manual_download": model.get("manual_download", False),
                "download_url": model.get("download_url", ""),
                "license_note": model.get("license_note", "")
            })
        return status_list

    def verify_sha256_hash(self, file_path, expected_hash):
        """ファイルのSHA256ハッシュを検証する"""
        if not self.verify_sha256 or not expected_hash:
            return True
            
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest() == expected_hash
        except Exception:
            return False

    def download_model(self, model_name):
        """特定のモデルをダウンロードする"""
        model = next((m for m in self.models if m["name"] == model_name), None)
        if not model:
            raise ValueError(f"マニフェストに存在しないモデルです: {model_name}")
            
        if model.get("manual_download"):
            raise ValueError(f"{model_name} は手動ダウンロードが必要です。")
            
        target_dir = os.path.join(self.root_dir, model["target_dir"])
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, model["name"])
        
        try:
            response = requests.get(model["download_url"], stream=True, timeout=self.timeout)
            response.raise_for_status()
            
            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            # SHA256の検証
            if not self.verify_sha256_hash(target_path, model.get("sha256")):
                os.remove(target_path)
                raise ValueError(f"{model_name} のSHA256チェックサムが一致しませんでした。")
                
            return True
        except Exception as e:
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except Exception:
                    pass
            raise RuntimeError(f"モデルのダウンロードに失敗しました: {e}") from e

    def check_all_models_ready(self):
        """生成に必要なすべてのモデルが揃っているか確認する"""
        status_list = self.get_model_status()
        missing = [s for s in status_list if s["status"] == "missing"]
        
        if missing:
            missing_names = ", ".join(m["name"] for m in missing)
            raise RuntimeError(f"ComfyUI必要モデルが不足しています。不足: {missing_names}")
        return True
