import hashlib
import io
import os
import re
import subprocess

import requests

from config import FFMPEG_BIN, NATIVE_FFMPEG_ENCODER, NATIVE_FFMPEG_PRESET


APP_VERSION_BASE = "2026.05.19"


def build_app_version() -> str:
    # ビルド時に焼き込んだバージョンを最優先（exe では git が使えないため）
    try:
        from core._build_version import BUILD_VERSION  # ビルド時生成・gitignore
        if BUILD_VERSION:
            return BUILD_VERSION
    except Exception:
        pass  # フォールバック許可: 焼き込みが無ければ git / 既定へ
    try:
        repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_dir,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        short_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty = subprocess.run(
            ["git", "diff", "--quiet"],
            cwd=repo_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode != 0
        version = f"{APP_VERSION_BASE}.{count}-{short_hash}"
        return version + ("-dirty" if dirty else "")
    except Exception:
        return APP_VERSION_BASE


def split_input_scripts(raw_scripts: str) -> list[str]:
    """貼り付けられた台本をバッチ区切り文字で分割する。"""
    raw_scripts = raw_scripts.strip()
    if not raw_scripts:
        return []

    # 純粋ハイフン行（---アンケート設定案--- のような名前付き行は分割しない）
    scripts = [s.strip() for s in re.split(r"(?m)^-{3,}$", raw_scripts) if s.strip()]
    if len(scripts) > 1:
        return scripts

    heading_re = re.compile(r"^\s*━+\s*動画\s*\d+[^。\n]*━+\s*$", re.MULTILINE)
    if heading_re.search(raw_scripts):
        chunks = []
        current = []
        for line in raw_scripts.splitlines():
            if heading_re.match(line):
                if current and any(part.strip() for part in current):
                    chunks.append("\n".join(current).strip())
                current = []
                continue
            current.append(line)
        if current and any(part.strip() for part in current):
            chunks.append("\n".join(current).strip())
        if len(chunks) > 1:
            return chunks

    starts = [m.start() for m in re.finditer(r"(?m)^動画形式[:：]", raw_scripts)]
    if len(starts) > 1:
        starts.append(len(raw_scripts))
        return [raw_scripts[starts[i]:starts[i + 1]].strip() for i in range(len(starts) - 1)]

    return [raw_scripts]


def unified_check(name: str, primary_url: str, path: str) -> dict:
    file_ok = os.path.exists(path)
    found_url = None
    urls_to_try = [primary_url]
    if "8188" in primary_url or "8000" in primary_url:
        for port in ["8188", "8000", "8189"]:
            alt = primary_url.replace("8188", port).replace("8000", port)
            if alt not in urls_to_try:
                urls_to_try.append(alt)
    for url in urls_to_try:
        try:
            with requests.get(url, timeout=0.8):
                found_url = url
                break
        except Exception:
            continue
    return {
        "name": name,
        "connected": found_url is not None,
        "url": found_url if found_url else primary_url,
        "file_ok": file_ok,
        "path": path,
    }


def ffmpeg_native_status() -> dict:
    configured = str(NATIVE_FFMPEG_ENCODER or "libx264").strip() or "libx264"
    preset = str(NATIVE_FFMPEG_PRESET or "").strip()
    result = {
        "bin": FFMPEG_BIN,
        "configured": configured,
        "preset": preset,
        "available": False,
        "gpu": configured not in ("", "libx264"),
        "hw_encoders": [],
        "error": "",
    }
    try:
        proc = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for enc in ("h264_nvenc", "hevc_nvenc", "av1_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf"):
            if enc in text:
                result["hw_encoders"].append(enc)
        result["available"] = configured == "libx264" or configured in text
        if proc.returncode != 0 and not result["available"]:
            result["error"] = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
            result["error"] = result["error"][0] if result["error"] else f"exit {proc.returncode}"
    except Exception as e:
        result["error"] = str(e)
    return result


def file_digest(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def load_image_copy(path: str, image_module):
    with open(path, "rb") as f:
        data = f.read()
    with image_module.open(io.BytesIO(data)) as src:
        return src.copy()
