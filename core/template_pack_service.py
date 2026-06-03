"""テンプレートパックのインポート/エクスポート。"""
from __future__ import annotations

from datetime import datetime, timezone


def export_template_pack(profile_id: str) -> dict:
    from core.prompt_template_store import list_templates

    templates = []
    for tmpl in list_templates(profile_id):
        templates.append({
            "template_name": tmpl.template_name,
            "template_kind": tmpl.template_kind,
            "system_rules": tmpl.system_rules,
            "script_rules": tmpl.script_rules,
            "title_rules": tmpl.title_rules,
            "meeting_rules": tmpl.meeting_rules,
            "ng_rules": tmpl.ng_rules,
            "description": tmpl.description,
            "default_hashtags": tmpl.default_hashtags,
            "default_playlist_category": tmpl.default_playlist_category,
            "template_pack": tmpl.template_pack,
            "visibility": tmpl.visibility,
            "product_bundle": tmpl.product_bundle,
            "is_default": tmpl.is_default,
        })
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "template_count": len(templates),
        "templates": templates,
        "note": "APIキー・OAuth・Analytics実績・ユーザー固有の認証情報は含みません。",
    }


def import_template_pack(profile_id: str, pack_json: dict) -> dict:
    from core.license_manager import assert_template_limit
    from core.prompt_template_store import create_template

    templates = pack_json.get("templates")
    if not isinstance(templates, list):
        raise RuntimeError("templates 配列が必要です")
    assert_template_limit(profile_id, adding=len(templates))
    created = []
    for item in templates:
        if not isinstance(item, dict):
            raise RuntimeError("テンプレート項目が不正です")
        tmpl = create_template(
            profile_id=profile_id,
            template_name=str(item.get("template_name") or "Imported Template"),
            template_kind=str(item.get("template_kind") or ""),
            system_rules=str(item.get("system_rules") or ""),
            script_rules=str(item.get("script_rules") or ""),
            title_rules=item.get("title_rules"),
            meeting_rules=item.get("meeting_rules"),
            ng_rules=item.get("ng_rules"),
            description=item.get("description"),
            default_hashtags=item.get("default_hashtags"),
            default_playlist_category=item.get("default_playlist_category"),
            template_pack=str(item.get("template_pack") or "imported"),
            visibility=str(item.get("visibility") or "private"),
            product_bundle=str(item.get("product_bundle") or ""),
            is_default=bool(item.get("is_default")),
        )
        created.append(tmpl.template_id)
    return {"created": created, "count": len(created)}
