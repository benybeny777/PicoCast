"""
外部サービス（ffmpeg / VOICEVOX / SD WebUI / Ollama）の起動状態と
使用デバイス（GPU / CPU）を確認するユーティリティ。

- log_external_services(): アプリ起動時にコンソール+デバッグログへ出力
- get_service_info_lines(): 処理ログ用に文字列リストを返す
"""
import logging
import subprocess

import requests

from config import config

_logger = logging.getLogger(__name__)


def _ffmpeg_lines() -> list[str]:
    ffmpeg = config.FFMPEG_BIN or "ffmpeg"
    encoder = config.NATIVE_FFMPEG_ENCODER or "libx264"
    try:
        ver_proc = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True, text=True, timeout=5,
        )
        version_line = ver_proc.stdout.splitlines()[0] if ver_proc.stdout else ""
        version = version_line.split(" ")[2] if len(version_line.split(" ")) > 2 else version_line
        version = version.split("-")[0]
    except Exception as e:
        return [f"[外部] ffmpeg - 取得失敗: {e}"]

    try:
        enc_proc = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        enc_list = enc_proc.stdout
    except Exception:
        enc_list = ""

    hw_encoders = [e for e in ("h264_nvenc", "hevc_nvenc", "h264_amf", "h264_qsv") if e in enc_list]
    if "libx264" in enc_list:
        hw_encoders.append("libx264(CPU)")

    encoder_ok = encoder in enc_list
    encoder_label = f"{encoder} ({'利用可' if encoder_ok else '利用不可 → libx264 へフォールバック'})"
    hw_label = " / ".join(hw_encoders) if hw_encoders else "不明"
    return [f"[外部] ffmpeg {version} - エンコーダ: {encoder_label} | HW対応: {hw_label}"]


def _voicevox_lines() -> list[str]:
    base = config.VOICEVOX_URL
    try:
        version = requests.get(f"{base}/version", timeout=2).text.strip('"').strip()
        devices = requests.get(f"{base}/supported_devices", timeout=2).json()
        parts = []
        if devices.get("cuda"):
            parts.append("GPU(CUDA)")
        if devices.get("dml"):
            parts.append("GPU(DirectML)")
        if devices.get("cpu"):
            parts.append("CPU")
        device_str = " / ".join(parts) or "不明"
        return [f"[外部] VOICEVOX {version} - 対応デバイス: {device_str}"]
    except Exception:
        return [f"[外部] VOICEVOX - 未起動または接続不可 ({base})"]


def _sd_webui_lines() -> list[str]:
    base = config.SD_WEBUI_BASE_URL
    try:
        flags = requests.get(f"{base}/sdapi/v1/cmd-flags", timeout=3).json()
        use_cpu = flags.get("use_cpu") or []
        device = flags.get("device") or ""
        if "all" in (use_cpu if isinstance(use_cpu, list) else [use_cpu]):
            device_str = "CPU"
        elif device:
            device_str = f"GPU ({device})"
        else:
            device_str = "GPU"
        try:
            model = requests.get(f"{base}/sdapi/v1/options", timeout=3).json().get("sd_model_checkpoint", "")
        except Exception:
            model = ""
        model_str = f" / モデル: {model}" if model else ""
        return [f"[外部] Stable Diffusion WebUI - デバイス: {device_str}{model_str}"]
    except Exception:
        return [f"[外部] Stable Diffusion WebUI - 未起動または接続不可 ({base})"]


def _ollama_lines() -> list[str]:
    base = config.OLLAMA_BASE_URL
    try:
        version = requests.get(f"{base}/api/version", timeout=2).json().get("version", "?")
        models = requests.get(f"{base}/api/ps", timeout=2).json().get("models", [])
        if models:
            lines = []
            for m in models:
                name = m.get("name", "?")
                size_vram = m.get("size_vram") or 0
                size = m.get("size") or 0
                if size_vram and size:
                    gpu_pct = int(size_vram / size * 100)
                    device_str = f"GPU {gpu_pct}% / CPU {100 - gpu_pct}%"
                elif size_vram:
                    device_str = "GPU"
                else:
                    device_str = "CPU"
                lines.append(f"[外部] Ollama {version} - {name}: {device_str}")
            return lines
        else:
            return [f"[外部] Ollama {version} - 起動中（モデル未ロード）"]
    except Exception:
        return [f"[外部] Ollama - 未起動または接続不可 ({base})"]


def get_service_info_lines() -> list[str]:
    """処理ログ向けに外部サービスのデバイス情報を文字列リストで返す。"""
    lines = []
    lines.extend(_ffmpeg_lines())
    lines.extend(_voicevox_lines())
    if config.IMAGE_BACKEND == "sd_webui":
        lines.extend(_sd_webui_lines())
    lines.extend(_ollama_lines())
    return lines


def log_external_services() -> None:
    """アプリ起動時にコンソールとデバッグログへ外部サービス情報を出力する。"""
    for msg in get_service_info_lines():
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
        _logger.info(msg)
