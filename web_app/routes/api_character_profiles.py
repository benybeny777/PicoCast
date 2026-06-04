"""キャラクター設定（character_profiles）管理 API。

active profile のキャラクター設定を一覧・編集・有効/無効切替する。
別 profile のキャラ設定は触れない（profile_id を active に固定）。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/character-profiles", tags=["character-profiles"])


def _active_profile_id() -> str:
    from core.channel_profile import require_active_profile
    return require_active_profile().profile_id


def _to_dict(c) -> dict:
    return {
        "character_id": c.character_id,
        "profile_id": c.profile_id,
        "character_key": c.character_key,
        "display_name": c.display_name,
        "character_name": c.character_name,
        "role": c.role,
        "tone_style": c.tone_style,
        "speaking_rules": c.speaking_rules,
        "forbidden_phrases": c.forbidden_phrases,
        "dialogue_rules": c.dialogue_rules,
        "voice_backend": c.voice_backend,
        "voice_speaker": c.voice_speaker,
        "voice_speaker_id": c.voice_speaker_id,
        "voice_styles": c.voice_styles or {},
        "portrait_png_path": c.portrait_png_path,
        "credit_required": c.credit_required,
        "credit_text": c.credit_text,
        "enabled": c.enabled,
        "sort_order": c.sort_order,
    }


@router.get("")
def list_character_profiles():
    """active profile のキャラクター設定一覧を返す。"""
    from core.character_profile_store import list_characters
    profile_id = _active_profile_id()
    return {"profile_id": profile_id, "characters": [_to_dict(c) for c in list_characters(profile_id)]}


class CharacterUpdateRequest(BaseModel):
    display_name: str | None = None
    character_name: str | None = None
    role: str | None = None
    tone_style: str | None = None
    speaking_rules: str | None = None
    forbidden_phrases: str | None = None
    dialogue_rules: str | None = None
    voice_backend: str | None = None
    voice_speaker: str | None = None
    voice_speaker_id: int | None = None
    voice_styles: dict[str, int] | None = None
    portrait_png_path: str | None = None
    credit_required: bool | None = None
    credit_text: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class CharacterCreateRequest(BaseModel):
    character_key: str
    display_name: str
    character_name: str
    role: str = ""
    tone_style: str = ""
    speaking_rules: str = ""
    forbidden_phrases: str = ""
    dialogue_rules: str = ""
    voice_backend: str = "voicevox"
    voice_speaker: str = ""
    voice_speaker_id: int | None = None
    voice_styles: dict[str, int] = Field(default_factory=dict)
    portrait_png_path: str = ""
    credit_required: bool = True
    credit_text: str = ""
    enabled: bool = True
    sort_order: int = 0


def _assert_owned(character_id: str, profile_id: str):
    """character_id が active profile のものか確認する（別 profile 改変を防ぐ）。"""
    from core.character_profile_store import list_characters
    if not any(c.character_id == character_id for c in list_characters(profile_id)):
        raise HTTPException(status_code=404, detail="このチャンネルのキャラクター設定が見つかりません")


@router.patch("/{character_id}")
def update_character_profile(character_id: str, req: CharacterUpdateRequest):
    """キャラクター設定を更新する（active profile のもののみ）。"""
    from core.character_profile_store import enable_character_exclusive, update_character
    profile_id = _active_profile_id()
    _assert_owned(character_id, profile_id)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        if fields.get("enabled") is True:
            fields.pop("enabled")
            enable_character_exclusive(character_id, **fields)
            fields["enabled"] = True
        else:
            update_character(character_id, **fields)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"updated": character_id, "fields": list(fields.keys())}


@router.post("")
def create_character_profile(req: CharacterCreateRequest):
    """キャラクター設定を追加する（active profile）。"""
    from core.character_profile_store import create_character
    profile_id = _active_profile_id()
    try:
        character_id = create_character(
            profile_id=profile_id,
            character_key=req.character_key,
            display_name=req.display_name,
            character_name=req.character_name,
            role=req.role,
            tone_style=req.tone_style,
            speaking_rules=req.speaking_rules,
            forbidden_phrases=req.forbidden_phrases,
            dialogue_rules=req.dialogue_rules,
            voice_backend=req.voice_backend,
            voice_speaker=req.voice_speaker,
            voice_speaker_id=req.voice_speaker_id,
            voice_styles=req.voice_styles,
            portrait_png_path=req.portrait_png_path,
            credit_required=req.credit_required,
            credit_text=req.credit_text,
            enabled=req.enabled,
            sort_order=req.sort_order,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"created": character_id}


@router.delete("/{character_id}")
def delete_character_profile(character_id: str, confirmed: bool = False):
    """キャラクター設定を削除する（active profile のもののみ、confirmed=true 必須）。"""
    if not confirmed:
        raise HTTPException(status_code=422, detail="confirmed=true が必要です")
    from core.character_profile_store import delete_character
    profile_id = _active_profile_id()
    _assert_owned(character_id, profile_id)
    delete_character(character_id)
    return {"deleted": character_id}
