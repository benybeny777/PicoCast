"""
APIリクエスト / レスポンス用 Pydantic スキーマ。
"""
from pydantic import BaseModel, field_validator
from typing import Any


# ── 生成 ─────────────────────────────────────────────
class GenerateRequest(BaseModel):
    script: str
    image_style: str = "通常"
    reuse_backgrounds: bool = False

    @field_validator("script")
    @classmethod
    def script_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("台本が空です")
        return v


class BatchGenerateRequest(BaseModel):
    scripts: list[str]
    image_style: str = "通常"
    reuse_backgrounds: bool = False


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


# ── 汎用レスポンス ────────────────────────────────────
class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str = ""


class ErrorResponse(BaseModel):
    error: str
    detail: Any = None
