"""DBに保存するパス参照と、実行時の実体パス解決を集約する。"""
from __future__ import annotations

import os

from core.runtime_env import app_base_dir, resource_base_dir

ASSET_REF_PREFIX = "asset:"
_LEGACY_ASSET_PREFIXES = (
    "assets/characters/",
    "assets/sd_webui/",
)


def _norm_ref_path(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").lstrip("/")


def _legacy_asset_rel(abs_path: str) -> str:
    normalized = os.path.abspath(abs_path).replace("\\", "/")
    marker = "/assets/"
    index = normalized.lower().rfind(marker)
    if index < 0:
        return ""
    rel = normalized[index + 1:]
    rel_lower = rel.lower()
    if not any(rel_lower.startswith(prefix) for prefix in _LEGACY_ASSET_PREFIXES):
        return ""
    return rel


def asset_ref(relative_path: str) -> str:
    """同梱リソースへの移植可能な参照文字列を作る。"""
    rel = _norm_ref_path(relative_path)
    if not rel:
        return ""
    return f"{ASSET_REF_PREFIX}{rel}"


def resolve_path_ref(value: str, *, base_dir: str | None = None) -> str:
    """DB保存値を実体パスへ解決する。

    - `asset:...`: 同梱リソース基準
    - 相対パス: app_base_dir() 基準
    - 絶対パス: 外部ツールや任意素材としてそのまま
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(ASSET_REF_PREFIX):
        rel = _norm_ref_path(raw[len(ASSET_REF_PREFIX):])
        return os.path.join(resource_base_dir(), *rel.split("/"))
    if os.path.isabs(raw):
        legacy_rel = _legacy_asset_rel(raw)
        if legacy_rel and not os.path.exists(raw):
            return os.path.join(resource_base_dir(), *legacy_rel.split("/"))
        return raw
    rel = _norm_ref_path(raw)
    return os.path.join(base_dir or app_base_dir(), *rel.split("/"))


def to_storable_path_ref(value: str, *, base_dir: str | None = None) -> str:
    """保存向けに、アプリ配下の絶対パスを相対参照へ寄せる。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(ASSET_REF_PREFIX):
        return asset_ref(raw[len(ASSET_REF_PREFIX):])
    if not os.path.isabs(raw):
        return _norm_ref_path(raw)

    abs_path = os.path.abspath(raw)
    resource_root = os.path.abspath(resource_base_dir())
    app_root = os.path.abspath(base_dir or app_base_dir())
    try:
        if os.path.commonpath([abs_path, resource_root]) == resource_root:
            return asset_ref(os.path.relpath(abs_path, resource_root))
    except ValueError:
        pass
    try:
        if os.path.commonpath([abs_path, app_root]) == app_root:
            return _norm_ref_path(os.path.relpath(abs_path, app_root))
    except ValueError:
        pass
    legacy_rel = _legacy_asset_rel(abs_path)
    if legacy_rel and not os.path.exists(abs_path):
        return asset_ref(legacy_rel)
    return raw
