"""
生成済み画像の手動差し替えサービス。
実画像は output/{profile_id} 配下に保存し、差し替え履歴は metadata.db を正本にする。
"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps

from core.metadata_db import (
    get_image_replacement,
    insert_image_replacement,
    list_image_replacements,
)
from core.output_paths import get_backups_dir
from web_app.security import safe_output_path

_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def replace_image(history_name: str, target_key: str, image_bytes: bytes, filename: str, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("confirmed=true が必要です")
    theme_dir, target_path, local_id = _resolve_target(history_name, target_key)
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in _ALLOWED_EXTS:
        raise ValueError("対応形式は png / jpg / jpeg / webp のみです")
    if not os.path.isfile(target_path):
        raise FileNotFoundError(f"対象画像が見つかりません: {target_key}")

    backup_path = _backup_path(local_id, target_key)
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)

    original_size = _image_size(target_path)
    tmp_path = target_path + f".replace.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(target_path, backup_path)
        applied_size = _write_cover_image(image_bytes, target_path, tmp_path, original_size)
        _sync_thumbnail_a(theme_dir, target_key)
        replacement_id = insert_image_replacement({
            "local_id": local_id,
            "target_rel_path": target_key,
            "target_kind": _target_kind(target_key),
            "source_type": "manual_upload",
            "backup_file_path": backup_path,
            "applied_file_path": target_path,
            "original_width": original_size[0],
            "original_height": original_size[1],
            "applied_width": applied_size[0],
            "applied_height": applied_size[1],
            "status": "applied",
            "created_at": _now_iso(),
            "note": f"uploaded_filename={filename}",
        })
    except Exception as e:
        cleanup_errors: list[str] = []
        if os.path.exists(backup_path):
            try:
                shutil.copy2(backup_path, target_path)
            except Exception as rollback_error:
                cleanup_errors.append(f"rollback={rollback_error}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as cleanup_error:
                cleanup_errors.append(f"tmp_cleanup={cleanup_error}")
        if cleanup_errors:
            raise RuntimeError(f"画像差し替えに失敗し、復旧処理にも失敗しました: {', '.join(cleanup_errors)}") from e
        raise

    return {
        "success": True,
        "replacement_id": replacement_id,
        "image": _image_info(target_path, target_key),
        "needs_render": True,
    }


def list_replacements(history_name: str) -> dict[str, Any]:
    _validate_history(history_name)
    local_id = os.path.basename(history_name.replace("\\", "/"))
    return {"history_name": history_name, "replacements": list_image_replacements(local_id)}


def restore_image(history_name: str, replacement_id: int, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("confirmed=true が必要です")
    theme_dir = _validate_history(history_name)
    local_id = os.path.basename(theme_dir)
    record = get_image_replacement(int(replacement_id))
    if not record or record.get("local_id") != local_id:
        raise ValueError("差し替え履歴が見つかりません")
    backup_path = str(record.get("backup_file_path") or "")
    target_key = str(record.get("target_rel_path") or "")
    _, target_path, _ = _resolve_target(history_name, target_key)
    if not os.path.isfile(backup_path):
        raise FileNotFoundError("復元用バックアップ画像が見つかりません")
    if not os.path.isfile(target_path):
        raise FileNotFoundError("復元対象画像が見つかりません")

    before_size = _image_size(target_path)
    shutil.copy2(backup_path, target_path)
    restored_size = _image_size(target_path)
    _sync_thumbnail_a(theme_dir, target_key)
    restore_id = insert_image_replacement({
        "local_id": local_id,
        "target_rel_path": target_key,
        "target_kind": _target_kind(target_key),
        "source_type": "restore",
        "backup_file_path": backup_path,
        "applied_file_path": target_path,
        "original_width": before_size[0],
        "original_height": before_size[1],
        "applied_width": restored_size[0],
        "applied_height": restored_size[1],
        "status": "restored",
        "created_at": _now_iso(),
        "note": f"restore_of={replacement_id}",
    })
    return {
        "success": True,
        "replacement_id": restore_id,
        "restored_from": replacement_id,
        "image": _image_info(target_path, target_key),
    }


def _validate_history(history_name: str) -> str:
    if not history_name or ".." in history_name or "/" in history_name or "\\" in history_name:
        raise ValueError("無効な履歴名です")
    theme_dir = safe_output_path(history_name)
    if not os.path.isdir(theme_dir):
        raise FileNotFoundError("履歴フォルダが見つかりません")
    return theme_dir


def _resolve_target(history_name: str, target_key: str) -> tuple[str, str, str]:
    theme_dir = _validate_history(history_name)
    normalized = str(target_key or "").replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError("無効な画像パスです")
    if not (
        normalized == "thumbnails/thumbnail.png"
        or (normalized.startswith("thumbnails/") and normalized.lower().endswith(".png"))
        or (normalized.startswith("backgrounds/bg_") and normalized.lower().endswith(".png"))
    ):
        raise ValueError("差し替え対象外の画像です")
    target_path = safe_output_path(f"{history_name}/{normalized}")
    return theme_dir, target_path, os.path.basename(theme_dir)


def _backup_path(local_id: str, target_key: str) -> str:
    safe_key = target_key.replace("/", "_").replace("\\", "_")
    name = f"{local_id}_{safe_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
    return os.path.join(get_backups_dir(), "image_replacements", local_id, name)


def _write_cover_image(image_bytes: bytes, target_path: str, tmp_path: str, target_size: tuple[int, int]) -> tuple[int, int]:
    with Image.open(BytesIO(image_bytes)) as src:
        src = ImageOps.exif_transpose(src)
        mode = "RGBA" if src.mode in ("RGBA", "LA") or "transparency" in src.info else "RGB"
        prepared = ImageOps.fit(src.convert(mode), target_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        try:
            save_format = "PNG" if target_path.lower().endswith(".png") else None
            prepared.save(tmp_path, format=save_format)
        finally:
            prepared.close()
    os.replace(tmp_path, target_path)
    return _image_size(target_path)


def _image_size(path: str) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def _image_info(path: str, key: str) -> dict[str, Any]:
    width, height = _image_size(path)
    return {
        "key": key,
        "filename": os.path.basename(path),
        "width": width,
        "height": height,
        "mtime": datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec="seconds"),
    }


def _target_kind(target_key: str) -> str:
    name = os.path.basename(target_key)
    if target_key.startswith("backgrounds/"):
        return "background"
    if name != "thumbnail.png":
        return "thumbnail_ab"
    return "thumbnail"


def _sync_thumbnail_a(theme_dir: str, target_key: str) -> None:
    name = os.path.basename(target_key)
    if not target_key.startswith("thumbnails/") or "_thumbnail_A" not in name:
        return
    src = os.path.join(theme_dir, target_key)
    dst = os.path.join(theme_dir, "thumbnails", "thumbnail.png")
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
