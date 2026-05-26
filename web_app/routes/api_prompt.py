from fastapi import APIRouter
from web_app.services.prompt_service import get_script_generation_prompt, get_title_prompt

router = APIRouter(prefix="/api/prompt", tags=["prompt"])


@router.get("/script")
def api_script_prompt():
    """台本生成プロンプトを返す（既存タイトル重複回避付き）。"""
    return get_script_generation_prompt()


@router.get("/title")
def api_title_prompt(long_only: bool = False):
    """タイトル案生成プロンプトを返す（実績データ付き）。"""
    return get_title_prompt(long_only=long_only)
