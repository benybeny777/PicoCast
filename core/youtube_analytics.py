"""YouTube Analytics API wrapper."""
from datetime import date, timedelta
from googleapiclient.discovery import build
from core.youtube_uploader import get_youtube_client


def _analytics_client():
    creds = get_youtube_client()._http.credentials
    return build("youtubeAnalytics", "v2", credentials=creds)


def _youtube_client():
    return get_youtube_client()


def fetch_video_analytics(days: int = 28) -> list[dict]:
    """動画単位のアナリティクスを取得して返す。

    Returns list of dicts with keys:
        video_id, title, views, watch_time_min, avg_duration_sec,
        avg_view_pct, impressions, ctr, likes, comments, subscribers_gained
    """
    end = date.today()
    start = end - timedelta(days=days)

    youtube = _youtube_client()
    analytics = _analytics_client()

    # Analytics: 動画単位の指標
    report = analytics.reports().query(
        ids="channel==MINE",
        startDate=start.isoformat(),
        endDate=end.isoformat(),
        dimensions="video",
        metrics=(
            "views,estimatedWatchTime,averageViewDuration,"
            "averageViewPercentage,impressions,impressionClickThroughRate,"
            "likes,comments,subscribersGained"
        ),
        sort="-views",
        maxResults=50,
    ).execute()

    rows = report.get("rows", [])
    if not rows:
        return []

    # 動画タイトルを一括取得
    video_ids = [r[0] for r in rows]
    titles = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="snippet",
            id=",".join(chunk),
        ).execute()
        for item in resp.get("items", []):
            titles[item["id"]] = item["snippet"]["title"]

    result = []
    for row in rows:
        vid = row[0]
        result.append({
            "video_id":            vid,
            "title":               titles.get(vid, vid),
            "views":               int(row[1]),
            "watch_time_min":      round(row[2], 1),
            "avg_duration_sec":    round(row[3], 1),
            "avg_view_pct":        round(row[4], 1),
            "impressions":         int(row[5]),
            "ctr":                 round(row[6] * 100, 1),
            "likes":               int(row[7]),
            "comments":            int(row[8]),
            "subscribers_gained":  int(row[9]),
        })
    return result


def fetch_channel_summary(days: int = 28) -> dict:
    """チャンネル全体の集計を返す。"""
    end = date.today()
    start = end - timedelta(days=days)

    analytics = _analytics_client()
    report = analytics.reports().query(
        ids="channel==MINE",
        startDate=start.isoformat(),
        endDate=end.isoformat(),
        metrics=(
            "views,estimatedWatchTime,impressions,"
            "impressionClickThroughRate,subscribersGained,subscribersLost"
        ),
    ).execute()

    rows = report.get("rows", [])
    if not rows:
        return {}
    r = rows[0]
    return {
        "views":              int(r[0]),
        "watch_time_min":     round(r[1], 1),
        "impressions":        int(r[2]),
        "ctr":                round(r[3] * 100, 1),
        "subscribers_gained": int(r[4]),
        "subscribers_lost":   int(r[5]),
    }
