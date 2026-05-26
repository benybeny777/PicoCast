from fastapi import APIRouter, Query, HTTPException
from web_app.services.analytics_service import (
    load_latest_analytics,
    list_analytics_files,
    submit_refresh_job,
    get_tsv_text,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def api_analytics():
    return {
        "files": list_analytics_files(),
        "data": load_latest_analytics(),
    }


@router.get("/tsv")
def api_analytics_tsv():
    return {"tsv": get_tsv_text()}


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
