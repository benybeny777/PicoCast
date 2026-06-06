"""
APIリクエスト / レスポンス用 Pydantic スキーマ。
"""
from pydantic import BaseModel, field_validator
from typing import Any
from config import (
    WEB_DEFAULT_IMAGE_STYLE,
    WEB_DEFAULT_LONG_BUDGET_MODE,
    WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST,
    WEB_DEFAULT_REUSE_BACKGROUNDS,
)


# ── 生成 ─────────────────────────────────────────────
class GenerateRequest(BaseModel):
    script: str
    image_style: str = WEB_DEFAULT_IMAGE_STYLE
    background_engine: str = ""  # "" = IMAGE_BACKEND 設定に従う / "nanobanana" / "sd_webui"
    reuse_backgrounds: bool = WEB_DEFAULT_REUSE_BACKGROUNDS
    reuse_audio: bool = False
    long_thumbnail_ab_test: bool = WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST
    long_budget_mode: bool = WEB_DEFAULT_LONG_BUDGET_MODE
    with_render: bool = True
    bgm_mode: str = "profile_default"  # profile_default / selected / none
    bgm_id: str | None = None
    bgm_volume_db: float | None = None
    setup_test: bool = False

    @field_validator("script")
    @classmethod
    def script_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("台本が空です")
        return v


class BatchGenerateRequest(BaseModel):
    scripts: list[str]
    image_style: str = WEB_DEFAULT_IMAGE_STYLE
    background_engine: str = ""  # "" = IMAGE_BACKEND 設定に従う / "nanobanana" / "sd_webui"
    reuse_backgrounds: bool = WEB_DEFAULT_REUSE_BACKGROUNDS
    reuse_audio: bool = False
    long_thumbnail_ab_test: bool = WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST
    long_budget_mode: bool = WEB_DEFAULT_LONG_BUDGET_MODE
    with_render: bool = True
    bgm_mode: str = "profile_default"  # profile_default / selected / none
    bgm_id: str | None = None
    bgm_volume_db: float | None = None


class HistoryRegenerateRequest(BaseModel):
    history_names: list[str]
    image_style: str = WEB_DEFAULT_IMAGE_STYLE
    background_engine: str = ""  # "" = IMAGE_BACKEND 設定に従う / "nanobanana" / "sd_webui"
    reuse_backgrounds: bool = WEB_DEFAULT_REUSE_BACKGROUNDS
    reuse_audio: bool = False
    long_thumbnail_ab_test: bool = WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST
    long_budget_mode: bool = WEB_DEFAULT_LONG_BUDGET_MODE
    with_render: bool = False
    bgm_mode: str = "profile_default"  # profile_default / selected / none
    bgm_id: str | None = None
    bgm_volume_db: float | None = None
    confirmed: bool = False


class RenderRequest(BaseModel):
    confirmed: bool = False
    bgm_mode: str = "profile_default"  # profile_default / selected / none
    bgm_id: str | None = None
    bgm_volume_db: float | None = None


# ── チェック ─────────────────────────────────────────
class CheckRequest(BaseModel):
    script: str

    @field_validator("script")
    @classmethod
    def script_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("台本が空です")
        return v


# ── 画像再生成 ────────────────────────────────────────
class ImageRegenerateRequest(BaseModel):
    history_name: str
    image_keys: list[str]          # "backgrounds/bg_NNN_001.png" / "thumbnails/..." 等
    prompts: dict[str, str] = {}   # key → テキスト（未保存のプロンプト上書き用）
    background_engine: str = ""    # "" = configデフォルト / "nanobanana" / "sd_webui"


# ── アップロード ──────────────────────────────────────
class UploadRequest(BaseModel):
    history_name: str
    confirmed: bool = False
    playlist_existing_mode: str = "reuse"  # reuse / recreate


class BatchUploadRequest(BaseModel):
    history_names: list[str]
    confirmed: bool = False
    playlist_existing_mode: str = "reuse"  # reuse / recreate


# ── 単体再生リスト振り分け ────────────────────────────
class PlaylistClassifierRequest(BaseModel):
    history_names: list[str]
    only_unregistered: bool = True
    confirmed: bool = False


# ── スケジュール ──────────────────────────────────────
class ScheduleUpdateRequest(BaseModel):
    video_id: str
    publish_at: str  # ISO8601
    confirmed: bool = False


class ScheduleDeleteRequest(BaseModel):
    video_id: str
    confirmed: bool = False


class ConfirmedRequest(BaseModel):
    confirmed: bool = False


# ── 固定コメント ──────────────────────────────────────
class FixedCommentRequest(BaseModel):
    history_name: str
    confirmed: bool = False


class FixedCommentMarkPostedRequest(BaseModel):
    history_name: str
    confirmed: bool = False


class FixedCommentMarkAllPostedRequest(BaseModel):
    confirmed: bool = False


# ── 汎用レスポンス ────────────────────────────────────
class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str = ""


class ErrorResponse(BaseModel):
    error: str
    detail: Any = None
