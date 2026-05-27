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
    WEB_DEFAULT_SD_SIZE_MODE,
)


# ── 生成 ─────────────────────────────────────────────
class GenerateRequest(BaseModel):
    script: str
    image_style: str = WEB_DEFAULT_IMAGE_STYLE
    background_engine: str = "nanobanana"
    reuse_backgrounds: bool = WEB_DEFAULT_REUSE_BACKGROUNDS
    long_thumbnail_ab_test: bool = WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST
    long_budget_mode: bool = WEB_DEFAULT_LONG_BUDGET_MODE
    sd_size_mode: bool = WEB_DEFAULT_SD_SIZE_MODE

    @field_validator("script")
    @classmethod
    def script_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("台本が空です")
        return v


class BatchGenerateRequest(BaseModel):
    scripts: list[str]
    image_style: str = WEB_DEFAULT_IMAGE_STYLE
    background_engine: str = "nanobanana"
    reuse_backgrounds: bool = WEB_DEFAULT_REUSE_BACKGROUNDS
    long_thumbnail_ab_test: bool = WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST
    long_budget_mode: bool = WEB_DEFAULT_LONG_BUDGET_MODE
    sd_size_mode: bool = WEB_DEFAULT_SD_SIZE_MODE


class HistoryRegenerateRequest(BaseModel):
    history_names: list[str]
    image_style: str = WEB_DEFAULT_IMAGE_STYLE
    background_engine: str = "nanobanana"
    reuse_backgrounds: bool = WEB_DEFAULT_REUSE_BACKGROUNDS
    long_thumbnail_ab_test: bool = WEB_DEFAULT_LONG_THUMBNAIL_AB_TEST
    long_budget_mode: bool = WEB_DEFAULT_LONG_BUDGET_MODE
    sd_size_mode: bool = WEB_DEFAULT_SD_SIZE_MODE
    with_render: bool = False
    confirmed: bool = False


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
    sd_size_mode: bool = False     # True: SD生成サイズで生成して最終サイズにリサイズ（高速化）


# ── アップロード ──────────────────────────────────────
class UploadRequest(BaseModel):
    history_name: str
    confirmed: bool = False


class BatchUploadRequest(BaseModel):
    history_names: list[str]
    confirmed: bool = False


# ── スケジュール ──────────────────────────────────────
class ScheduleUpdateRequest(BaseModel):
    video_id: str
    publish_at: str  # ISO8601
    confirmed: bool = False


class ScheduleDeleteRequest(BaseModel):
    video_id: str
    confirmed: bool = False


# ── 固定コメント ──────────────────────────────────────
class FixedCommentRequest(BaseModel):
    history_name: str
    confirmed: bool = False


class FixedCommentMarkPostedRequest(BaseModel):
    history_name: str
    confirmed: bool = False


# ── 汎用レスポンス ────────────────────────────────────
class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str = ""


class ErrorResponse(BaseModel):
    error: str
    detail: Any = None
