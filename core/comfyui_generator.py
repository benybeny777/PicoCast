"""ComfyUI（ローカル）で画像を生成する。

利用者が起動した ComfyUI（既定 http://127.0.0.1:8188）の API へワークフローを送り、
完成画像を受け取る。内蔵ワークフローは PicoAgent（character-maker/sidecar/media/generate.py）で
RTX 5060 Laptop 8GB・RAM 34GB の実機生成を確認した Krea 2 Turbo NVFP4 の構成と同じ。
Krea 2 のテキストエンコーダーは Qwen3-VL のため、日本語のプロンプトをそのまま渡せる
（Stable Diffusion WebUI のような Ollama での英訳は不要）。

失敗時に別のバックエンドへ切り替えない（フォールバック禁止）。
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import uuid

import requests

from config import config as cfg

_logger = logging.getLogger(__name__)

class ComfyUIError(RuntimeError):
    """ComfyUI 側が生成に失敗した（キュー投入拒否・実行エラー・出力なし）。"""


def generation_size(final_width: int, final_height: int) -> tuple[int, int]:
    """生成解像度。最終解像度と同じ向きで、設定の長辺・短辺（16の倍数）を使う。"""
    long_edge = cfg.COMFYUI_GEN_LONG_EDGE // 16 * 16
    short_edge = cfg.COMFYUI_GEN_SHORT_EDGE // 16 * 16
    return (short_edge, long_edge) if final_height > final_width else (long_edge, short_edge)


def krea2_workflow(prompt: str, *, width: int, height: int, seed: int, steps: int) -> dict:
    """Krea 2 Turbo の文章→画像ワークフロー（ComfyUI API 形式）。"""
    def node(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    tile = cfg.COMFYUI_VAE_TILE_SIZE
    return {
        "1": node("UNETLoader", unet_name=cfg.COMFYUI_KREA_UNET, weight_dtype="default"),
        "2": node("CLIPLoader", clip_name=cfg.COMFYUI_KREA_TEXT_ENCODER, type="krea2", device="default"),
        "3": node("VAELoader", vae_name=cfg.COMFYUI_KREA_VAE),
        "4": node("CLIPTextEncode", clip=["2", 0], text=prompt),
        "5": node("ConditioningZeroOut", conditioning=["4", 0]),
        "6": node("EmptyLatentImage", width=width, height=height, batch_size=1),
        "7": node("KSampler", model=["1", 0], positive=["4", 0], negative=["5", 0], latent_image=["6", 0],
                  seed=seed, steps=steps, cfg=1, sampler_name="euler", scheduler="simple", denoise=1),
        "8": node("VAEDecodeTiled", samples=["7", 0], vae=["3", 0], tile_size=tile, overlap=64,
                  temporal_size=16, temporal_overlap=4),
        "9": node("SaveImage", images=["8", 0], filename_prefix="yukkurijidou/bg"),
    }


def custom_workflow(path: str, prompt: str, *, width: int, height: int, seed: int, steps: int) -> dict:
    """利用者のワークフロー（ComfyUI の「API形式で保存」した JSON）へ値を差し込む。

    入力値がちょうど {{PROMPT}} / {{WIDTH}} / {{HEIGHT}} / {{SEED}} / {{STEPS}} の箇所を置き換える。
    {{PROMPT}} が無いワークフローはプロンプトが反映されないため拒否する。
    """
    with open(path, encoding="utf-8") as f:
        workflow = json.load(f)
    values = {"{{PROMPT}}": prompt, "{{WIDTH}}": width, "{{HEIGHT}}": height, "{{SEED}}": seed, "{{STEPS}}": steps}
    found = set()
    for node in workflow.values():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        for key, value in list(inputs.items()):
            if isinstance(value, str) and value in values:
                inputs[key] = values[value]
                found.add(value)
    if "{{PROMPT}}" not in found:
        raise ComfyUIError(f"ワークフローに {{{{PROMPT}}}} の入力がありません: {path}")
    return workflow


class ComfyUIGenerator:
    def __init__(self, base_url: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or cfg.COMFYUI_BASE_URL).rstrip("/")
        self.timeout = timeout or cfg.COMFYUI_TIMEOUT_SEC
        self.session = requests.Session()

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ComfyUIGenerator":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def check_health(self) -> dict:
        """ComfyUI が応答するか。応答しなければ requests の例外を上位へ伝える。"""
        with self.session.get(f"{self.base_url}/system_stats", timeout=5) as res:
            res.raise_for_status()
            return res.json()

    def build_workflow(self, prompt: str, *, width: int, height: int, seed: int | None = None) -> tuple[dict, int]:
        seed = secrets.randbelow(2**31) if seed is None else seed
        steps = cfg.COMFYUI_STEPS
        if cfg.COMFYUI_WORKFLOW_PATH:
            workflow = custom_workflow(cfg.COMFYUI_WORKFLOW_PATH, prompt, width=width, height=height, seed=seed, steps=steps)
        else:
            workflow = krea2_workflow(prompt, width=width, height=height, seed=seed, steps=steps)
        return workflow, seed

    def generate_png(self, prompt: str, *, width: int, height: int, seed: int | None = None) -> tuple[bytes, int]:
        """1枚生成して PNG のバイト列と使ったシード値を返す。"""
        workflow, seed = self.build_workflow(prompt, width=width, height=height, seed=seed)
        with self.session.post(
            f"{self.base_url}/prompt", json={"prompt": workflow, "client_id": uuid.uuid4().hex}, timeout=30,
        ) as res:
            if res.status_code >= 400:
                # ComfyUI はノード不足・モデル未導入をここで 400 と理由付きで返す
                _logger.error("ComfyUI がワークフローを受け付けませんでした: status=%s body=%s", res.status_code, res.text[:2000])
                raise ComfyUIError(f"ComfyUI がワークフローを受け付けませんでした（HTTP {res.status_code}）。モデルファイル名とカスタムノードを確認してください")
            prompt_id = res.json()["prompt_id"]
        image_ref = self._wait_output(prompt_id)
        with self.session.get(f"{self.base_url}/view", params=image_ref, timeout=60) as res:
            res.raise_for_status()
            return res.content, seed

    def _wait_output(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            with self.session.get(f"{self.base_url}/history/{prompt_id}", timeout=30) as res:
                res.raise_for_status()
                history = res.json()
            record = history.get(prompt_id)
            if record:
                return _image_ref(record)
            time.sleep(1.0)
        self._interrupt()
        raise ComfyUIError(f"ComfyUI の生成が {self.timeout} 秒以内に終わりませんでした")

    def _interrupt(self) -> None:
        """時間切れの生成を止め、次の生成が GPU を待たないようにする。"""
        try:
            with self.session.post(f"{self.base_url}/interrupt", timeout=10) as res:
                res.raise_for_status()
        except requests.RequestException:
            _logger.error("ComfyUI の生成中断を送れませんでした", exc_info=True)


def _image_ref(record: dict) -> dict:
    """/history の1件から出力画像の参照（filename/subfolder/type）を取り出す。"""
    status = record.get("status", {})
    if status.get("status_str") == "error":
        details = [
            str(message[1].get("exception_message", message[1]))
            for message in status.get("messages", [])
            if isinstance(message, (list, tuple)) and len(message) > 1
            and message[0] in ("execution_error", "execution_interrupted") and isinstance(message[1], dict)
        ]
        _logger.error("ComfyUI の実行に失敗しました: %s", details)
        raise ComfyUIError("ComfyUI の生成に失敗しました: " + ("; ".join(details)[:300] or "詳細なし"))
    for node in record.get("outputs", {}).values():
        images = node.get("images", [])
        if images:
            image = images[0]
            return {"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")}
    raise ComfyUIError("ComfyUI の出力に画像がありません（SaveImage ノードを確認してください）")
