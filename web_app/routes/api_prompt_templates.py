"""
プロンプトテンプレート管理 API。

テンプレートの使用可否は active profile の profile_id で絞り込む。
別 profile のテンプレートは一覧にも返さない。

GET    /api/prompt-templates              - active profile のテンプレート一覧
POST   /api/prompt-templates             - active profile にテンプレート作成
PUT    /api/prompt-templates/{id}        - active profile 所属のみ更新可
POST   /api/prompt-templates/{id}/set-default - デフォルト設定
POST   /api/prompt-templates/{id}/clone  - 別 profile へ複製
DELETE /api/prompt-templates/{id}        - active profile 所属のみ削除可
POST   /api/prompt-templates/seed        - 未投入の profile にファイルから seed
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.channel_profile import require_active_profile
from core.prompt_template_store import (
    TEMPLATE_KINDS,
    clone_template,
    create_template,
    delete_template,
    get_template,
    list_templates,
    set_default,
    update_template,
)
from web_app.routes.errors import raise_api_error

router = APIRouter(prefix="/api/prompt-templates", tags=["prompt-templates"])


def _active_profile_id() -> str:
    return require_active_profile().profile_id


def _check_ownership(template_id: str, profile_id: str) -> None:
    """テンプレートが active profile 所属でなければ 403/404 を返す。"""
    tmpl = get_template(template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="テンプレートが見つかりません")
    if tmpl.profile_id != profile_id:
        raise HTTPException(status_code=403, detail="別 profile のテンプレートは操作できません")


# ─────────────────────────────────────────────────────────────────────────────
# リクエストモデル
# ─────────────────────────────────────────────────────────────────────────────

class CreateTemplateRequest(BaseModel):
    template_name: str
    template_kind: str
    system_rules: str = ""
    script_rules: str = ""
    title_rules: str | None = None
    meeting_rules: str | None = None
    ng_rules: str | None = None
    description: str | None = None
    default_hashtags: str | None = None
    default_playlist_category: str | None = None
    is_default: bool = False


class UpdateTemplateRequest(BaseModel):
    template_name: str | None = None
    system_rules: str | None = None
    script_rules: str | None = None
    title_rules: str | None = None
    meeting_rules: str | None = None
    ng_rules: str | None = None
    description: str | None = None
    default_hashtags: str | None = None
    default_playlist_category: str | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None


class CloneRequest(BaseModel):
    target_profile_id: str
    new_name: str


class ImportPackRequest(BaseModel):
    pack_json: dict
    confirmed: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# エンドポイント
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def api_list_templates(kind: str | None = Query(default=None)):
    """active profile のテンプレート一覧。kind で絞り込み可能。"""
    profile_id = _active_profile_id()
    if kind and kind not in TEMPLATE_KINDS:
        raise HTTPException(status_code=422, detail=f"kind は {TEMPLATE_KINDS} のいずれかで指定してください")
    templates = list_templates(profile_id, kind=kind)
    return [_tmpl_to_dict(t) for t in templates]


@router.post("")
def api_create_template(req: CreateTemplateRequest):
    """active profile にテンプレートを作成する。"""
    profile_id = _active_profile_id()
    try:
        from core.license_manager import assert_template_limit
        assert_template_limit(profile_id, adding=1)
    except RuntimeError as e:
        raise_api_error(e, status_code=403, action="プロンプトテンプレート上限確認")
    if req.template_kind not in TEMPLATE_KINDS:
        raise HTTPException(status_code=422, detail=f"template_kind は {TEMPLATE_KINDS} のいずれかで指定してください")
    if not req.template_name.strip():
        raise HTTPException(status_code=422, detail="template_name は必須です")
    try:
        tmpl = create_template(
            profile_id=profile_id,
            template_name=req.template_name.strip(),
            template_kind=req.template_kind,
            system_rules=req.system_rules,
            script_rules=req.script_rules,
            title_rules=req.title_rules,
            meeting_rules=req.meeting_rules,
            ng_rules=req.ng_rules,
            description=req.description,
            default_hashtags=req.default_hashtags,
            default_playlist_category=req.default_playlist_category,
            is_default=req.is_default,
        )
        return _tmpl_to_dict(tmpl)
    except Exception as e:
        raise_api_error(e, status_code=422, action="プロンプトテンプレート作成")


@router.post("/seed")
def api_seed():
    """
    ファイルから全 channel profile へのテンプレート seed を実行する。
    既にテンプレートがある profile はスキップする。
    """
    from core.prompt_template_seeder import seed_all_profiles
    results = seed_all_profiles()
    return {"results": results}


@router.get("/export")
def api_export_templates():
    """active profile のテンプレートパックを秘密情報なしでエクスポートする。"""
    from core.template_pack_service import export_template_pack
    profile_id = _active_profile_id()
    return export_template_pack(profile_id)


@router.post("/import")
def api_import_templates(req: ImportPackRequest):
    """テンプレートパックを active profile へインポートする。"""
    if not req.confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    from core.template_pack_service import import_template_pack
    profile_id = _active_profile_id()
    try:
        return import_template_pack(profile_id, req.pack_json)
    except Exception as e:
        raise_api_error(e, status_code=422, action="プロンプトテンプレートインポート")


@router.get("/{template_id}")
def api_get_template(template_id: str):
    """テンプレートを1件取得する（active profile 所属のみ）。"""
    profile_id = _active_profile_id()
    _check_ownership(template_id, profile_id)
    tmpl = get_template(template_id)
    return _tmpl_to_dict(tmpl)


@router.put("/{template_id}")
def api_update_template(template_id: str, req: UpdateTemplateRequest):
    """active profile 所属のテンプレートを更新する。"""
    profile_id = _active_profile_id()
    _check_ownership(template_id, profile_id)
    try:
        tmpl = update_template(
            template_id,
            profile_id,
            template_name=req.template_name,
            system_rules=req.system_rules,
            script_rules=req.script_rules,
            title_rules=req.title_rules,
            meeting_rules=req.meeting_rules,
            ng_rules=req.ng_rules,
            description=req.description,
            default_hashtags=req.default_hashtags,
            default_playlist_category=req.default_playlist_category,
            is_enabled=req.is_enabled,
        )
        if req.is_default:
            set_default(template_id, profile_id)
            tmpl = get_template(template_id)
        return _tmpl_to_dict(tmpl)
    except PermissionError as e:
        raise_api_error(e, status_code=403, action="プロンプトテンプレート更新権限確認")
    except Exception as e:
        raise_api_error(e, status_code=422, action="プロンプトテンプレート更新")


@router.post("/{template_id}/set-default")
def api_set_default(template_id: str):
    """指定テンプレートを同 kind のデフォルトに設定する。"""
    profile_id = _active_profile_id()
    _check_ownership(template_id, profile_id)
    try:
        set_default(template_id, profile_id)
        return {"ok": True, "template_id": template_id}
    except PermissionError as e:
        raise_api_error(e, status_code=403, action="プロンプトテンプレート既定設定")


@router.post("/{template_id}/clone")
def api_clone_template(template_id: str, req: CloneRequest):
    """
    テンプレートを別 profile へ複製する（明示操作のみ許可）。
    複製後は新しい template_id として保存される。
    """
    profile_id = _active_profile_id()
    _check_ownership(template_id, profile_id)
    if not req.new_name.strip():
        raise HTTPException(status_code=422, detail="new_name は必須です")
    try:
        cloned = clone_template(template_id, req.target_profile_id, req.new_name.strip())
        return {
            "ok": True,
            "cloned": _tmpl_to_dict(cloned),
            "warning": "複製後はチャンネル固有の文言・ハッシュタグ・再生リストカテゴリを必ず見直してください",
        }
    except Exception as e:
        raise_api_error(e, status_code=422, action="プロンプトテンプレート複製")


@router.delete("/{template_id}")
def api_delete_template(template_id: str):
    """active profile 所属のテンプレートを削除する。"""
    profile_id = _active_profile_id()
    _check_ownership(template_id, profile_id)
    try:
        delete_template(template_id, profile_id)
        return {"ok": True, "deleted": template_id}
    except PermissionError as e:
        raise_api_error(e, status_code=403, action="プロンプトテンプレート削除権限確認")
    except Exception as e:
        raise_api_error(e, status_code=422, action="プロンプトテンプレート削除")


# ─────────────────────────────────────────────────────────────────────────────
# シリアライズ
# ─────────────────────────────────────────────────────────────────────────────

def _tmpl_to_dict(tmpl) -> dict:
    return {
        "template_id": tmpl.template_id,
        "profile_id": tmpl.profile_id,
        "template_name": tmpl.template_name,
        "template_kind": tmpl.template_kind,
        "genre_profile": tmpl.genre_profile,
        "is_default": tmpl.is_default,
        "is_enabled": tmpl.is_enabled,
        "system_rules": tmpl.system_rules,
        "script_rules": tmpl.script_rules,
        "title_rules": tmpl.title_rules,
        "meeting_rules": tmpl.meeting_rules,
        "ng_rules": tmpl.ng_rules,
        "description": tmpl.description,
        "default_hashtags": tmpl.default_hashtags,
        "default_playlist_category": tmpl.default_playlist_category,
        "template_pack": getattr(tmpl, "template_pack", None),
        "visibility": getattr(tmpl, "visibility", None),
        "product_bundle": getattr(tmpl, "product_bundle", None),
        "created_at": tmpl.created_at,
        "updated_at": tmpl.updated_at,
    }
