from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web_app.services.prompt_service import (
    get_meeting_prompt,
    get_script_generation_prompt,
    get_title_prompt,
    submit_prompt_run,
)

router = APIRouter(prefix="/api/prompt", tags=["prompt"])


@router.get("/script")
def api_script_prompt():
    """台本生成プロンプトを返す（既存タイトル重複回避付き）。"""
    return get_script_generation_prompt()


@router.get("/title")
def api_title_prompt(long_only: bool = False):
    """タイトル案生成プロンプトを返す（実績データ付き）。"""
    return get_title_prompt(long_only=long_only)


@router.get("/meeting")
def api_meeting_prompt():
    """ネタ会議動画の台本生成プロンプトを返す。"""
    return get_meeting_prompt()


class PromptRunRequest(BaseModel):
    kind: str  # script / title / title-long / meeting
    theme: str = ""  # 台本のテーマ（script のみ。タイトル案から選んだもの）


@router.get("/backends")
def api_prompt_backends():
    """文章生成AIの選択肢と利用可否（CLI が見つかるか）。"""
    from core import text_llm
    return {"current": text_llm.current_backend(), "backends": text_llm.available_backends()}


@router.post("/run")
def api_prompt_run(req: PromptRunRequest):
    """プロンプトを設定中の文章生成AIで実行するジョブを登録する。本文は GET /api/jobs/{job_id} の result.text。"""
    try:
        return submit_prompt_run(req.kind, theme=req.theme)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
