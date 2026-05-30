from fastapi import APIRouter, Query, HTTPException
from web_app.services.analytics_service import (
    load_latest_analytics,
    submit_refresh_job,
    get_tsv_text,
    get_ai_copy_text,
    get_shorts_title_prompt,
    get_long_title_prompt,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def api_analytics():
    return {
        "data": load_latest_analytics(),
    }


@router.get("/tsv")
def api_analytics_tsv():
    return {"tsv": get_tsv_text()}


@router.get("/ai-copy")
def api_analytics_ai_copy():
    return {"text": get_ai_copy_text()}


@router.get("/shorts-title-prompt")
def api_analytics_shorts_title_prompt():
    return {"text": get_shorts_title_prompt()}


@router.get("/long-title-prompt")
def api_analytics_long_title_prompt():
    return {"text": get_long_title_prompt()}


@router.post("/refresh")
def api_analytics_refresh():
    job_id = submit_refresh_job()
    return {"job_id": job_id, "status": "queued"}


@router.get("/retention")
def api_analytics_retention(
    video_id: str = Query(...),
    duration: int = Query(..., ge=1),
):
    """指定動画の視聴者維持率を取得して分析結果を返す。"""
    from datetime import datetime, timedelta, timezone
    from core.youtube_analytics import fetch_audience_retention
    from core.retention_analysis import analyze_retention

    jst = timezone(timedelta(hours=9))
    end_date = datetime.now(jst).date().isoformat()
    start_date = (datetime.now(jst).date() - timedelta(days=365)).isoformat()

    try:
        rows = fetch_audience_retention(video_id, start_date, end_date, duration)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube Analytics APIエラー: {e}")

    if not rows:
        return {"ok": False, "message": "維持率データ未取得またはデータ待ちです。", "rows": [], "analysis": None}

    analysis = analyze_retention(rows)
    return {"ok": True, "rows": rows, "analysis": analysis}
