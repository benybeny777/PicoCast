"""秘密情報を含めない診断パッケージ作成サービス。"""
from __future__ import annotations

import json
import platform
import sys
import zipfile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.settings_store import get_all

from core.runtime_env import app_base_dir as _app_base_dir
_ROOT = Path(_app_base_dir())  # 永続データの基準。exe(onefile)では exe と同じフォルダ
_DIAG_DIR = _ROOT / "output" / "_diagnostics"
_SECRET_PATTERNS = (
    "key",
    "token",
    "secret",
    "oauth",
    "client_secrets",
    "credential",
    "password",
    "license_id",
    "buyer",
    "purchaser",
    "email",
)
_SECRET_VALUE_RE = re.compile(r"(?i)(api[_-]?key|token|secret|oauth|password|credential)(\s*[:=]\s*)([^\s,;]+)")


def _mask_settings(settings: dict[str, str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in settings.items():
        lower = key.lower()
        if any(pattern in lower for pattern in _SECRET_PATTERNS):
            masked[key] = "***MASKED***" if value else ""
        else:
            masked[key] = value
    return masked


def _safe_job(job: dict[str, Any]) -> dict[str, Any]:
    logs = []
    for row in (job.get("logs") or [])[-80:]:
        safe = dict(row)
        msg = str(safe.get("message", ""))
        safe["message"] = _SECRET_VALUE_RE.sub(r"\1\2***MASKED***", msg)
        logs.append(safe)
    return {
        "job_id": job.get("job_id"),
        "type": job.get("type") or job.get("job_type"),
        "profile_id": job.get("profile_id"),
        "status": job.get("status"),
        "progress_text": _SECRET_VALUE_RE.sub(r"\1\2***MASKED***", str(job.get("progress_text") or "")),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "error": _SECRET_VALUE_RE.sub(r"\1\2***MASKED***", str(job.get("error") or "")),
        "cancel_requested": bool(job.get("cancel_requested")),
        "logs": logs,
    }


def _gpu_info() -> dict[str, Any]:
    """nvidia-smi で GPU を診断する。未検出やエラーは状態として記録する（秘密情報は含まない）。"""
    import shutil
    import subprocess
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {"detected": False, "reason": "nvidia-smi が見つかりません"}
    try:
        proc = subprocess.run(
            [smi, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        # 診断データ収集なので、プローブ失敗は状態として記録する（パッケージ全体は止めない）
        return {"detected": False, "reason": f"nvidia-smi 実行エラー: {type(exc).__name__}"}
    if proc.returncode != 0:
        return {"detected": False, "reason": f"nvidia-smi 失敗 (code={proc.returncode})"}
    gpus = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return {"detected": bool(gpus), "gpus": gpus}


def _schema_versions() -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        from core.metadata_db import SCHEMA_VERSION
        result["metadata_schema_version"] = SCHEMA_VERSION
    except Exception as exc:
        result["metadata_schema_error"] = str(exc)
    return result


def _error_catalog() -> list[dict[str, Any]]:
    from core.error_codes import ERROR_CATALOG
    return [
        {
            "code": item.code,
            "message": item.message,
            "category": item.category,
            "retry_recommended": item.retry_recommended,
            "remediation": item.remediation,
        }
        for item in ERROR_CATALOG.values()
    ]


def create_diagnostics_package() -> dict[str, str]:
    from core.gui_support import build_app_version
    from web_app.job_manager import get_job_manager
    from web_app.services.status_service import get_settings_status

    _DIAG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = _DIAG_DIR / f"diagnostics_{stamp}.zip"
    jobs = get_job_manager().list_jobs()
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]

    payloads = {
        "version.json": {
            "app_version": build_app_version(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "environment.json": {
            "os": platform.platform(),
            "python": sys.version,
            "executable": sys.executable,
            "gpu": _gpu_info(),
        },
        "service_status.json": get_settings_status(),
        "settings_masked.json": _mask_settings(get_all()),
        "jobs_latest.json": [_safe_job(job) for job in jobs[:30]],
        "failed_jobs_latest.json": [_safe_job(job) for job in failed_jobs[:10]],
        "error_codes.json": _error_catalog(),
        "schema.json": _schema_versions(),
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in payloads.items():
            zf.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2))

    return {"path": str(zip_path), "filename": zip_path.name}
