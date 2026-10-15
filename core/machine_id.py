"""生の端末IDを保存・公開せず、製品別の端末コードを計算する。"""
from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import sys

from config import config as cfg
from core.error_codes import AppError

_logger = logging.getLogger(__name__)


def _raw_machine_id() -> str:
    """OSの端末IDを読む。呼び出し元は例外を含む生情報を外へ出さない。"""
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            raw_id, _ = winreg.QueryValueEx(key, "MachineGuid")
    elif sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"\r\n]+)"', result.stdout)
        raw_id = match.group(1) if match else ""
    else:
        raise ValueError("対応していないOSです")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ValueError("端末IDが取得できませんでした")
    return raw_id.strip()


def machine_code() -> str:
    """SHA-256の先頭32桁を返す。取得失敗は明示エラーで停止する。"""
    try:
        try:
            raw_id = _raw_machine_id()
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ValueError("端末IDが取得できませんでした")
            return hashlib.sha256(f"{cfg.PRODUCT_ID}:{raw_id}".encode("utf-8")).hexdigest()[:32]
        except Exception as exc:
            # OS例外の本文やsubprocess出力に生IDが含まれ得るため、型だけを残す。
            raise AppError("E-LICENSE-MACHINE", f"端末情報の取得失敗（{type(exc).__name__}）") from None
    except AppError:
        _logger.error("端末コード取得に失敗しました code=E-LICENSE-MACHINE", exc_info=True)
        raise
