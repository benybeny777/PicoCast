import json
import os
import random
import time
import uuid
from copy import deepcopy
from typing import Any

import httpx
from PIL import Image

import config


class ComfyUIClient:
    """ComfyUI API で背景画像を生成する。自動フォールバック禁止。失敗時は中止する。"""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_sec: float | None = None,
        preset_file: str | None = None,
    ):
        self.base_url = (base_url or config.LOCAL_COMFYUI_URL).rstrip("/")
        self.timeout_sec = float(timeout_sec or config.LOCAL_COMFYUI_TIMEOUT_SEC)
        self.preset_file = preset_file or config.LOCAL_COMFYUI_PRESET_FILE
        self.client_id = uuid.uuid4().hex

    def check_connection(self) -> None:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(f"{self.base_url}/system_stats")
            response.raise_for_status()

    def ensure_running(self) -> None:
        """ComfyUIが起動していなければ COMFYUI_START_COMMAND で自動起動し、準備完了まで待機する。"""
        import logging
        import subprocess
        logger = logging.getLogger(__name__)

        try:
            self.check_connection()
            return
        except Exception:
            pass

        start_cmd = getattr(config, "COMFYUI_START_COMMAND", "").strip()
        if not start_cmd:
            raise RuntimeError(
                f"ComfyUIに接続できません ({self.base_url})。"
                " ComfyUIを起動してください。"
                " 自動起動するには COMFYUI_START_COMMAND を .env に設定してください。"
            )

        logger.info("ComfyUI自動起動: %s", start_cmd)
        subprocess.Popen(start_cmd, shell=True)

        wait_sec = int(getattr(config, "COMFYUI_START_WAIT_SEC", 90))
        for elapsed in range(2, wait_sec + 1, 2):
            time.sleep(2)
            try:
                self.check_connection()
                logger.info("ComfyUI起動確認 (%d秒)", elapsed)
                return
            except Exception:
                pass

        raise RuntimeError(
            f"ComfyUIの起動を {wait_sec} 秒待ちましたが、接続できませんでした ({self.base_url})。"
        )

    def load_presets(self) -> dict[str, dict[str, Any]]:
        with open(self.preset_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise RuntimeError(f"ComfyUIプリセット定義が不正です: {self.preset_file}")
        return data

    def load_preset(self, preset_name: str) -> dict[str, Any]:
        presets = self.load_presets()
        if preset_name not in presets:
            raise RuntimeError(f"ComfyUIプリセットが見つかりません: {preset_name}")
        preset = presets[preset_name]
        if not isinstance(preset, dict):
            raise RuntimeError(f"ComfyUIプリセットが不正です: {preset_name}")
        checkpoint = str(preset.get("checkpoint", "")).strip()
        if not checkpoint:
            raise RuntimeError(f"ComfyUIプリセットのcheckpointが未設定です: {preset_name}")
        workflow_path = self._resolve_path(str(preset.get("workflow_path", "")).strip())
        if not workflow_path or not os.path.isfile(workflow_path):
            raise RuntimeError(f"ComfyUI workflowファイルが見つかりません: {preset.get('workflow_path')}")
        preset = {**preset, "workflow_path": workflow_path}
        return preset

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        preset_name: str,
        negative_prompt: str | None = None,
        width: int | None = None,
        height: int | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_running()
        preset = self.load_preset(preset_name)
        self._validate_checkpoint_available(str(preset["checkpoint"]))
        seed = int(seed if seed is not None else random.randint(1, 2**31 - 1))
        width = int(width or preset.get("width") or config.LOCAL_COMFYUI_OUTPUT_WIDTH)
        height = int(height or preset.get("height") or config.LOCAL_COMFYUI_OUTPUT_HEIGHT)
        negative_prompt = negative_prompt if negative_prompt is not None else str(preset.get("negative_prompt", ""))
        workflow = self._load_workflow(preset["workflow_path"])
        workflow = self._inject(workflow, preset, prompt, negative_prompt, width, height, seed)

        prompt_id = self._queue_prompt(workflow)
        outputs = self._wait_for_outputs(prompt_id)
        image_info = self._first_image_output(outputs)
        self._download_image(image_info, output_path)
        self._validate_image(output_path, width, height)
        return {
            "engine": "local_comfyui",
            "preset_name": preset_name,
            "preset_label": preset.get("label", preset_name),
            "model_type": preset.get("model_type"),
            "checkpoint": preset.get("checkpoint"),
            "workflow_path": preset["workflow_path"],
            "seed": seed,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "status": "success",
            "fallback_used": False,
        }

    def _resolve_path(self, path: str) -> str:
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), path))

    def _load_workflow(self, workflow_path: str) -> dict[str, Any]:
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)
        if not isinstance(workflow, dict):
            raise RuntimeError(f"ComfyUI workflow JSONが不正です: {workflow_path}")
        return workflow

    def _inject(
        self,
        workflow: dict[str, Any],
        preset: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        seed: int,
    ) -> dict[str, Any]:
        result = deepcopy(workflow)
        positive_done = False
        negative_done = False
        for node in result.values():
            inputs = node.get("inputs", {})
            class_type = node.get("class_type", "")
            if "ckpt_name" in inputs:
                inputs["ckpt_name"] = preset["checkpoint"]
            if "seed" in inputs:
                inputs["seed"] = seed
            if "steps" in inputs:
                inputs["steps"] = int(preset.get("steps", inputs["steps"]))
            if "cfg" in inputs:
                inputs["cfg"] = float(preset.get("cfg", inputs["cfg"]))
            if "sampler_name" in inputs:
                sampler_name, scheduler = self._split_sampler(str(preset.get("sampler", inputs["sampler_name"])))
                inputs["sampler_name"] = sampler_name
                if "scheduler" in inputs:
                    inputs["scheduler"] = scheduler
            if class_type == "EmptyLatentImage":
                inputs["width"] = width
                inputs["height"] = height
            if class_type == "CLIPTextEncode" and "text" in inputs:
                if not positive_done:
                    inputs["text"] = prompt
                    positive_done = True
                elif not negative_done:
                    inputs["text"] = negative_prompt
                    negative_done = True
        if not positive_done:
            raise RuntimeError("ComfyUI workflowにCLIPTextEncodeノードが見つかりません")
        return result

    def _split_sampler(self, sampler: str) -> tuple[str, str]:
        if sampler.endswith("_karras"):
            return sampler[:-7], "karras"
        return sampler, "normal"

    def _queue_prompt(self, workflow: dict[str, Any]) -> str:
        payload = {"prompt": workflow, "client_id": self.client_id}
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{self.base_url}/prompt", json=payload)
            response.raise_for_status()
            data = response.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI prompt_idを取得できません: {data}")
        return str(prompt_id)

    def _validate_checkpoint_available(self, checkpoint: str) -> None:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{self.base_url}/object_info/CheckpointLoaderSimple")
            response.raise_for_status()
            data = response.json()
        info = data.get("CheckpointLoaderSimple", data)
        ckpt_spec = info.get("input", {}).get("required", {}).get("ckpt_name", [[]])
        ckpt_names = ckpt_spec[0] if ckpt_spec else []
        if isinstance(ckpt_names, list) and ckpt_names and checkpoint not in ckpt_names:
            raise RuntimeError(f"ComfyUI checkpointが見つかりません: {checkpoint}")

    def _wait_for_outputs(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout_sec
        with httpx.Client(timeout=10.0) as client:
            while time.time() < deadline:
                response = client.get(f"{self.base_url}/history/{prompt_id}")
                response.raise_for_status()
                data = response.json()
                item = data.get(prompt_id) or {}
                status = item.get("status", {})
                if status.get("status_str") == "error":
                    messages = status.get("messages") or []
                    raise RuntimeError(f"ComfyUI workflow実行エラー: {messages}")
                outputs = item.get("outputs")
                if outputs:
                    return outputs
                time.sleep(1.0)
        raise TimeoutError(f"ComfyUI生成がタイムアウトしました: {self.timeout_sec}秒")

    def _first_image_output(self, outputs: dict[str, Any]) -> dict[str, Any]:
        for output in outputs.values():
            images = output.get("images") or []
            if images:
                return images[0]
        raise RuntimeError("ComfyUI出力に画像がありません")

    def _download_image(self, image_info: dict[str, Any], output_path: str) -> None:
        params = {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{self.base_url}/view", params=params)
            response.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(response.content)

    def _validate_image(self, path: str, expected_width: int, expected_height: int) -> None:
        if not os.path.isfile(path):
            raise RuntimeError(f"ComfyUI出力画像が存在しません: {path}")
        if os.path.getsize(path) < 4096:
            raise RuntimeError(f"ComfyUI出力画像のファイルサイズが小さすぎます: {path}")
        with Image.open(path) as img:
            width, height = img.size
        width_diff = abs(width - expected_width) / max(expected_width, 1)
        height_diff = abs(height - expected_height) / max(expected_height, 1)
        if width_diff > 0.25 or height_diff > 0.25:
            raise RuntimeError(
                f"ComfyUI出力画像サイズが期待値から外れています: {width}x{height} / 期待 {expected_width}x{expected_height}"
            )
