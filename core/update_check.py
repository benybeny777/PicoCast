"""更新確認（任意機能）。

`PRODUCT_UPDATE_CHECK_URL` が設定されている場合のみ、その URL から
最新バージョン情報 JSON を取得して現在のビルドと比較する。
未設定（既定）ではネットワークアクセスを一切行わない。

更新JSONの想定フォーマット:
    {"latest_version": "1.2.0", "url": "https://.../download", "notes": "..."}
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from config import config
from core.gui_support import build_app_version


def is_update_check_enabled() -> bool:
    return bool((config.PRODUCT_UPDATE_CHECK_URL or "").strip())


def check_for_update(timeout: float = 5.0) -> dict:
    """更新確認を実行する。

    戻り値:
      enabled=False                         … 更新確認URL未設定（アクセスしない）
      enabled=True, ok=True, update_available=bool, latest/current/url/notes
      enabled=True, ok=False, error=...     … 取得・解析に失敗
    """
    url = (config.PRODUCT_UPDATE_CHECK_URL or "").strip()
    current = build_app_version()
    if not url:
        return {"enabled": False, "current": current}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NVF-update-check"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
        return {"enabled": True, "ok": False, "current": current, "error": f"更新情報の取得に失敗しました: {e}"}

    latest = str(data.get("latest_version", "")).strip()
    if not latest:
        return {"enabled": True, "ok": False, "current": current, "error": "更新情報に latest_version がありません"}
    return {
        "enabled": True,
        "ok": True,
        "current": current,
        "latest": latest,
        "update_available": latest != current,
        "url": str(data.get("url", "")).strip(),
        "notes": str(data.get("notes", "")).strip(),
    }
