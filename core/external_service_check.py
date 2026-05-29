"""
外部サービス（ffmpeg / VOICEVOX / SD WebUI / Ollama）の起動状態と
使用デバイス（GPU / CPU）をログおよびコンソールに出力するユーティリティ。
アプリ起動時の lifespan 内でバックグラウンドスレッドから呼び出す。
"""
import logging
import subprocess

import requests

from config import config

_logger = logging.getLogger(__name__)


def _print_and_log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
    _logger.info(msg)


def _check_ffmpeg() -> None:
    ffmpeg = config.FFMPEG_BIN or "ffmpeg"
    encoder = config.NATIVE_FFMPEG_ENCODER or "libx264"

    try:
        ver_proc = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True, text=True, timeout=5,
        )
        version_line = ver_proc.stdout.splitlines()[0] if ver_proc.stdout else "不明"
        version = version_line.split(" ")[2] if len(version_line.split(" ")) > 2 else version_line
    except Exception as e:
        _print_and_log(f"[外部] ffmpeg -取得失敗: {e}")
        return

    # ハードウェアエンコーダの利用可否を確認
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
    encoder_label = f"{encoder} ({'利用可' if encoder_ok else '⚠ 利用不可 -libx264 へフォールバック'})"

    hw_label = " / ".join(hw_encoders) if hw_encoders else "不明"
    _print_and_log(
        f"[外部] ffmpeg {version} -エンコーダ設定: {encoder_label} | 対応HWエンコーダ: {hw_label}"
    )


def _check_voicevox() -> None:
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
        _print_and_log(f"[外部] VOICEVOX {version} -対応デバイス: {device_str}")
    except Exception:
        _print_and_log(f"[外部] VOICEVOX -未起動または接続不可 ({base})")


def _check_sd_webui() -> None:
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
        _print_and_log(f"[外部] Stable Diffusion WebUI -デバイス: {device_str}{model_str}")
    except Exception:
        _print_and_log(f"[外部] Stable Diffusion WebUI -未起動または接続不可 ({base})")


def _check_ollama() -> None:
    base = config.OLLAMA_BASE_URL
    try:
        version = requests.get(f"{base}/api/version", timeout=2).json().get("version", "?")
        models = requests.get(f"{base}/api/ps", timeout=2).json().get("models", [])
        if models:
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
                _print_and_log(f"[外部] Ollama {version} -{name}: {device_str}")
        else:
            _print_and_log(f"[外部] Ollama {version} -起動中（モデル未ロード）")
    except Exception:
        _print_and_log(f"[外部] Ollama -未起動または接続不可 ({base})")


def log_external_services() -> None:
    """外部サービスの状態とデバイス情報をログ・コンソールに出力する。"""
    _check_ffmpeg()
    _check_voicevox()
    if config.IMAGE_BACKEND == "sd_webui":
        _check_sd_webui()
    _check_ollama()
