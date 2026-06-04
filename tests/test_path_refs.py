"""移植可能なパス参照のテスト。"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_asset_ref_uses_forward_slashes():
    from core.path_refs import asset_ref

    assert asset_ref(r"assets\characters\reimu.png") == "asset:assets/characters/reimu.png"


def test_asset_ref_resolves_from_resource_base(tmp_path, monkeypatch):
    import core.path_refs as refs

    monkeypatch.setattr(refs, "resource_base_dir", lambda: str(tmp_path / "bundle"))

    assert refs.resolve_path_ref("asset:assets/characters/reimu.png") == str(
        tmp_path / "bundle" / "assets" / "characters" / "reimu.png"
    )


def test_absolute_resource_path_is_stored_as_asset_ref(tmp_path, monkeypatch):
    import core.path_refs as refs

    resource_root = tmp_path / "bundle"
    app_root = tmp_path / "app"
    portrait = resource_root / "assets" / "characters" / "reimu.png"
    monkeypatch.setattr(refs, "resource_base_dir", lambda: str(resource_root))
    monkeypatch.setattr(refs, "app_base_dir", lambda: str(app_root))

    assert refs.to_storable_path_ref(str(portrait)) == "asset:assets/characters/reimu.png"


def test_absolute_app_path_is_stored_as_relative_path(tmp_path, monkeypatch):
    import core.path_refs as refs

    app_root = tmp_path / "app"
    engine = app_root / "tools" / "aquestalk" / "engine.exe"
    monkeypatch.setattr(refs, "resource_base_dir", lambda: str(tmp_path / "bundle"))
    monkeypatch.setattr(refs, "app_base_dir", lambda: str(app_root))

    assert refs.to_storable_path_ref(str(engine)) == "tools/aquestalk/engine.exe"


def test_stale_absolute_asset_path_resolves_to_current_resource_root(tmp_path, monkeypatch):
    import core.path_refs as refs

    old_path = tmp_path / "old-extract" / "assets" / "characters" / "zundamon.png"
    resource_root = tmp_path / "new-extract"
    monkeypatch.setattr(refs, "resource_base_dir", lambda: str(resource_root))

    assert refs.resolve_path_ref(str(old_path)) == str(
        resource_root / "assets" / "characters" / "zundamon.png"
    )


def test_unrelated_assets_path_is_not_rewritten(tmp_path, monkeypatch):
    import core.path_refs as refs

    external = tmp_path / "other" / "assets" / "documents" / "manual.pdf"
    monkeypatch.setattr(refs, "resource_base_dir", lambda: str(tmp_path / "bundle"))

    assert refs.resolve_path_ref(str(external)) == str(external)
    assert refs.to_storable_path_ref(str(external)) == str(external)
