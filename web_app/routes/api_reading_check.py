"""読み違いの可能性（VOICEVOX の読みと辞書の読みの食い違い）の確認・登録 API。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/reading-check", tags=["reading_check"])


class ScriptCheckRequest(BaseModel):
    script: str


class AcceptRequest(BaseModel):
    word: str
    reading: str  # 正しい読み（ひらがな）


class DismissRequest(BaseModel):
    word: str
    voicevox_reading: str


@router.post("")
def api_check_script(req: ScriptCheckRequest):
    """台本の読みを VOICEVOX で確認するジョブを登録する（合成はしない）。結果は GET /api/jobs/{job_id} の result。"""
    from web_app.services.reading_check_service import submit_script_check
    try:
        return {"job_id": submit_script_check(req.script)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/findings")
def api_list_findings():
    """未対応の読み違いの可能性（生成時・生成前チェックで見つかったもの）。"""
    from core import reading_dictionary_store
    return {"findings": reading_dictionary_store.list_findings()}


@router.post("/findings/accept")
def api_accept_finding(req: AcceptRequest):
    """正しい読みを辞書へ登録し、その語の項目を片付ける。"""
    from core import reading_dictionary_store
    word, reading = req.word.strip(), req.reading.strip()
    if not word or not reading:
        raise HTTPException(status_code=422, detail="word と reading は必須です")
    reading_dictionary_store.accept_finding(word, reading)
    return {"saved": word, "reading": reading}


@router.post("/findings/dismiss")
def api_dismiss_finding(req: DismissRequest):
    """今の読みのままでよい語として、同じ組み合わせを今後表示しない。"""
    from core import reading_dictionary_store
    if not reading_dictionary_store.dismiss_finding(req.word, req.voicevox_reading):
        raise HTTPException(status_code=404, detail=f"'{req.word}' は一覧にありません")
    return {"dismissed": req.word}
