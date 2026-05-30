"""
チャンネルプロファイル管理 API。

GET  /api/channels           - プロファイル一覧
GET  /api/channels/current   - アクティブプロファイル
POST /api/channels           - プロファイル作成
PUT  /api/channels/{id}      - プロファイル更新
POST /api/channels/{id}/activate - アクティブ化
POST /api/channels/{id}/validate - バリデーション
DELETE /api/channels/{id}    - 削除（confirmed=true 必須）
GET  /api/prompt-profiles    - 利用可能な genre_profile 一覧
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.channel_profile import (
    ChannelProfile,
    ChannelProfileError,
    NoActiveProfileError,
    ProfileNotFoundError,
    ProfileValidationError,
    activate_profile,
    delete_profile,
    get_active_profile,
    get_profile,
    list_profiles,
    save_profile,
    validate_profile,
)

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelProfileRequest(BaseModel):
    profile_id: str
    channel_name: str
    channel_handle: str = ""
    genre_profile: str
    output_root: str
    default_hashtags: str = ""
    channel_theme: str = ""
    channel_accent_color: str = ""


class DeleteRequest(BaseModel):
    confirmed: bool = False


def _profile_to_dict(p: ChannelProfile) -> dict:
    return {
        "profile_id": p.profile_id,
        "channel_name": p.channel_name,
        "channel_handle": p.handle_normalized,
        "genre_profile": p.genre_profile,
        "output_root": p.output_root,
        "default_hashtags": p.default_hashtags,
        "channel_theme": p.channel_theme,
        "channel_accent_color": p.channel_accent_color,
        "is_active": p.is_active,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


@router.get("")
def api_list_channels():
    """プロファイル一覧を返す（アクティブが先頭）。"""
    return {"profiles": [_profile_to_dict(p) for p in list_profiles()]}


@router.get("/current")
def api_current_channel():
    """
    アクティブプロファイルを返す。未設定なら null。
    auth フィールドに OAuth token の登録状態（bool）を含める。値は含めない。
    """
    profile = get_active_profile()
    if profile is None:
        return {"profile": None}
    d = _profile_to_dict(profile)
    # OAuth token の登録状態（値は含めない）
    try:
        from core.secret_store import has_secret
        d["auth"] = {
            "upload_oauth":    has_secret("youtube_upload_token",    profile_id=profile.profile_id),
            "analytics_oauth": has_secret("youtube_analytics_token", profile_id=profile.profile_id),
            "client_secrets":  has_secret("youtube_client_secrets",  profile_id=profile.profile_id),
        }
    except Exception:
        d["auth"] = {"upload_oauth": False, "analytics_oauth": False, "client_secrets": False}
    return {"profile": d}


@router.post("")
def api_create_channel(req: ChannelProfileRequest):
    """プロファイルを作成する。"""
    profile = ChannelProfile(
        profile_id=req.profile_id,
        channel_name=req.channel_name,
        channel_handle=req.channel_handle,
        genre_profile=req.genre_profile,
        output_root=req.output_root,
        default_hashtags=req.default_hashtags,
        channel_theme=req.channel_theme,
        channel_accent_color=req.channel_accent_color,
    )
    try:
        save_profile(profile)
    except ProfileValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"saved": req.profile_id}


@router.put("/{profile_id}")
def api_update_channel(profile_id: str, req: ChannelProfileRequest):
    """プロファイルを更新する。"""
    if profile_id != req.profile_id:
        raise HTTPException(status_code=422, detail="URLのprofile_idとリクエストのprofile_idが一致しません")
    existing = get_profile(profile_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"プロファイルが見つかりません: {profile_id}")
    profile = ChannelProfile(
        profile_id=req.profile_id,
        channel_name=req.channel_name,
        channel_handle=req.channel_handle,
        genre_profile=req.genre_profile,
        output_root=req.output_root,
        default_hashtags=req.default_hashtags,
        channel_theme=req.channel_theme,
        channel_accent_color=req.channel_accent_color,
        is_active=existing.is_active,
    )
    try:
        save_profile(profile)
    except ProfileValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"saved": profile_id}


@router.post("/{profile_id}/activate")
def api_activate_channel(profile_id: str):
    """プロファイルをアクティブにする。"""
    try:
        activate_profile(profile_id)
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"activated": profile_id}


@router.post("/{profile_id}/validate")
def api_validate_channel(profile_id: str):
    """プロファイルのバリデーションを実行する。"""
    profile = get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"プロファイルが見つかりません: {profile_id}")
    errors: list[str] = []
    try:
        validate_profile(profile)
    except ProfileValidationError as e:
        errors.append(str(e))

    # genre_profile の存在チェック
    try:
        from core.prompt_profile_loader import validate_genre_profile_exists, list_available_genre_profiles
        validate_genre_profile_exists(profile.genre_profile)
    except Exception as e:
        errors.append(str(e))
        available = list_available_genre_profiles()
        errors.append(f"利用可能な genre_profile: {available}")

    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "errors": []}


@router.delete("/{profile_id}")
def api_delete_channel(profile_id: str, req: DeleteRequest):
    """プロファイルを削除する。confirmed=true 必須。アクティブは削除不可。"""
    try:
        delete_profile(profile_id, confirmed=req.confirmed)
    except ProfileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ChannelProfileError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"deleted": profile_id}


@router.get("/prompt-profiles")
def api_prompt_profiles_redirect():
    """利用可能な genre_profile 一覧（/api/channels エンドポイント内）。"""
    from core.prompt_profile_loader import list_available_genre_profiles
    return {"genre_profiles": list_available_genre_profiles()}
