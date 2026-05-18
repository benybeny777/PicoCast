import os
import re
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
CLIENT_SECRETS = os.path.join(ROOT_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(ROOT_DIR, "token_analytics.json")


def _get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def _parse_iso_duration(value: str) -> int | None:
    if not value:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not m:
        return None
    h = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + minutes * 60 + s


def _chunks(values, size=50):
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _video_metadata(youtube, video_ids):
    result = {}
    for ids in _chunks(video_ids):
        response = youtube.videos().list(
            part="snippet,contentDetails",
            id=",".join(ids),
            maxResults=50,
        ).execute()
        for item in response.get("items", []):
            vid = item.get("id")
            snippet = item.get("snippet", {})
            details = item.get("contentDetails", {})
            duration = _parse_iso_duration(details.get("duration"))
            title = snippet.get("title", "")
            result[vid] = {
                "title": title,
                "published_at": snippet.get("publishedAt"),
                "duration": duration,
                "video_type": "Shorts" if duration is not None and duration <= 60 else "Long",
            }
    return result


def _query_report(analytics, start_date, end_date, metrics):
    return analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics=",".join(metrics),
        dimensions="video",
        sort="-views",
        maxResults=200,
    ).execute()


def fetch_video_analytics(days=28):
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)

    jst = timezone(timedelta(hours=9))
    end = datetime.now(jst).date()
    start = end - timedelta(days=int(days))
    start_date = start.isoformat()
    end_date = end.isoformat()

    metrics = [
        "views",
        "estimatedMinutesWatched",
        "averageViewDuration",
        "averageViewPercentage",
        "likes",
        "comments",
        "subscribersGained",
        "subscribersLost",
        "impressions",
        "impressionClickThroughRate",
    ]
    try:
        report = _query_report(analytics, start_date, end_date, metrics)
    except Exception:
        metrics = metrics[:-2]
        report = _query_report(analytics, start_date, end_date, metrics)

    headers = [h.get("name") for h in report.get("columnHeaders", [])]
    rows = report.get("rows", [])
    video_ids = [row[0] for row in rows if row]
    meta = _video_metadata(youtube, video_ids)

    items = []
    for row in rows:
        data = dict(zip(headers, row))
        video_id = data.get("video")
        m = meta.get(video_id, {})
        ctr = data.get("impressionClickThroughRate")
        items.append({
            "video_id": video_id,
            "title": m.get("title") or video_id,
            "published_at": m.get("published_at"),
            "duration": m.get("duration"),
            "video_type": m.get("video_type"),
            "views": data.get("views", 0),
            "impressions": data.get("impressions", 0),
            "ctr": ctr,
            "average_view_duration": data.get("averageViewDuration", 0),
            "average_percentage_viewed": data.get("averageViewPercentage", 0),
            "likes": data.get("likes", 0),
            "comments": data.get("comments", 0),
            "subscribers_gained": data.get("subscribersGained", 0),
            "subscribers_lost": data.get("subscribersLost", 0),
        })

    summary = {
        "days": days,
        "start_date": start_date,
        "end_date": end_date,
        "video_count": len(items),
        "views": sum(int(float(item.get("views") or 0)) for item in items),
    }
    return {"summary": summary, "items": items}

