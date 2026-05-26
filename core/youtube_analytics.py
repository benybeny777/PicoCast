import json
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


def _close_google_resource(resource):
    if resource is not None and hasattr(resource, "close"):
        resource.close()


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


def _local_upload_records_by_video_id() -> dict:
    records = {}
    try:
        from core.upload_records import load_upload_records
        for record in load_upload_records():
            video_id = record.get("video_id")
            if video_id:
                records[video_id] = dict(record)
    except Exception:
        pass
    uploaded_dir = os.path.join(ROOT_DIR, "output", "000_uploaded")
    if not os.path.isdir(uploaded_dir):
        return records
    for root, _dirs, files in os.walk(uploaded_dir):
        if "upload_record.json" not in files:
            continue
        path = os.path.join(root, "upload_record.json")
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            continue
        video_id = record.get("video_id")
        if video_id:
            policy_path = os.path.join(root, "cta_policy.json") if os.path.basename(root) == "_meta" else os.path.join(root, "_meta", "cta_policy.json")
            script_path = os.path.join(os.path.dirname(root), "script.txt") if os.path.basename(root) == "_meta" else os.path.join(root, "script.txt")
            if os.path.exists(script_path):
                try:
                    from core.parser import ScriptParser
                    script_meta = {
                        it["type"]: it["text"]
                        for it in ScriptParser.parse(script_path)
                        if it["type"] in ScriptParser.META_TYPES
                    }
                    record.setdefault("generation_kind", script_meta.get("generation_kind", ""))
                    record.setdefault("source_video_title", script_meta.get("source_video_title", ""))
                    record.setdefault("generation_purpose", script_meta.get("generation_purpose", ""))
                    record.setdefault("character_pattern", script_meta.get("character_pattern", ""))
                    record.setdefault("genre_group", script_meta.get("genre_group", ""))
                    record.setdefault("topic_request_cta", script_meta.get("topic_request_cta", ""))
                    record.setdefault("topic_request_cta_reason", script_meta.get("topic_request_cta_reason", ""))
                except Exception:
                    pass
            if os.path.exists(policy_path):
                try:
                    with open(policy_path, "r", encoding="utf-8") as f:
                        policy = json.load(f).get("cta_policy", {})
                    topic_state = str(policy.get("topic_request_cta", ""))
                    if topic_state == "allowed":
                        record["topic_request_cta"] = "許可"
                    elif topic_state == "blocked":
                        record["topic_request_cta"] = "禁止"
                    record.setdefault("topic_request_cta_reason", policy.get("topic_request_cta_reason", ""))
                    record.setdefault("final_cta_type", policy.get("final_cta_type", ""))
                except Exception:
                    pass
            merged = dict(records.get(video_id, {}))
            merged.update(record)
            records[video_id] = merged
    return records


def _video_metadata(youtube, video_ids):
    result = {}
    now_utc = datetime.now(timezone.utc)
    for ids in _chunks(video_ids):
        response = youtube.videos().list(
            part="snippet,contentDetails,status,statistics",
            id=",".join(ids),
            maxResults=50,
        ).execute()
        for item in response.get("items", []):
            vid = item.get("id")
            snippet = item.get("snippet", {})
            details = item.get("contentDetails", {})
            status = item.get("status", {})
            stats = item.get("statistics", {})
            duration = _parse_iso_duration(details.get("duration"))
            privacy = status.get("privacyStatus", "unknown")
            publish_at_str = status.get("publishAt")

            if privacy == "public":
                publish_status = "published"
            elif privacy == "private" and publish_at_str:
                try:
                    scheduled_dt = datetime.fromisoformat(publish_at_str.replace("Z", "+00:00"))
                    publish_status = "scheduled" if scheduled_dt > now_utc else "published"
                except Exception:
                    publish_status = "private"
            elif privacy == "unlisted":
                publish_status = "unlisted"
            else:
                publish_status = privacy  # "private" / "unknown"

            result[vid] = {
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt"),
                "duration": duration,
                "video_type": "Shorts" if duration is not None and duration <= 60 else "Long",
                "publish_status": publish_status,
                "stats_views": int(stats.get("viewCount", 0) or 0),
                "stats_likes": int(stats.get("likeCount", 0) or 0),
                "stats_comments": int(stats.get("commentCount", 0) or 0),
            }
    return result


def _all_channel_video_ids(youtube) -> list:
    """チャンネルのアップロード済み全動画IDを返す。"""
    ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = (
        ch_resp.get("items", [{}])[0]
        .get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not uploads_id:
        return []

    video_ids = []
    next_page = None
    while True:
        kwargs = dict(part="contentDetails", playlistId=uploads_id, maxResults=50)
        if next_page:
            kwargs["pageToken"] = next_page
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        next_page = resp.get("nextPageToken")
        if not next_page:
            break
    return video_ids


def _fetch_channel_subscriber_totals(analytics, start_date: str, end_date: str) -> dict | None:
    """チャンネル全体の登録者増減をdimension無しで取得する。"""
    try:
        result = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="subscribersGained,subscribersLost",
        ).execute()
        headers = [h.get("name") for h in result.get("columnHeaders", [])]
        rows = result.get("rows", [])
        if rows:
            data = dict(zip(headers, rows[0]))
            gained = int(float(data.get("subscribersGained", 0) or 0))
            lost = int(float(data.get("subscribersLost", 0) or 0))
            return {"gained": gained, "lost": lost}
    except Exception:
        pass
    return None


def _query_report(analytics, start_date, end_date, metrics):
    all_rows = []
    headers = None
    start_index = 1
    while True:
        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics=",".join(metrics),
            dimensions="video",
            sort="-views",
            maxResults=200,
            startIndex=start_index,
        ).execute()
        if headers is None:
            headers = response.get("columnHeaders", [])
        rows = response.get("rows", [])
        all_rows.extend(rows)
        if len(rows) < 200:
            break
        start_index += 200
    return {"columnHeaders": headers, "rows": all_rows}


def fetch_video_analytics(days=28):
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)

    try:
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

        # Analytics期間内にアクティブだった動画のデータを組み立て
        analytics_map = {}
        for row in rows:
            data = dict(zip(headers, row))
            video_id = data.get("video")
            if video_id:
                analytics_map[video_id] = data

        # チャンネルの全動画IDを取得してメタデータを補完
        all_ids = _all_channel_video_ids(youtube)
        # analyticsにあるがall_idsにないIDも含める（削除済み等の例外対応）
        combined_ids = list(dict.fromkeys(all_ids + list(analytics_map.keys())))
        meta = _video_metadata(youtube, combined_ids)
        local_records = _local_upload_records_by_video_id()

        items = []
        for video_id in combined_ids:
            m = meta.get(video_id, {})
            data = analytics_map.get(video_id, {})
            local_record = local_records.get(video_id, {})
            analytics_available = video_id in analytics_map
            ctr = data.get("impressionClickThroughRate")
            items.append({
                "video_id": video_id,
                "title": m.get("title") or video_id,
                "published_at": m.get("published_at"),
                "duration": m.get("duration"),
                "video_type": m.get("video_type"),
                "publish_status": m.get("publish_status", "published"),
                "analytics_available": analytics_available,
                "views": data.get("views", m.get("stats_views", 0)),
                "impressions": data.get("impressions", 0),
                "ctr": ctr,
                "average_view_duration": data.get("averageViewDuration", 0),
                "average_percentage_viewed": data.get("averageViewPercentage", 0),
                "likes": data.get("likes", m.get("stats_likes", 0)),
                "comments": data.get("comments", m.get("stats_comments", 0)),
                "subscribers_gained": data.get("subscribersGained", 0),
                "subscribers_lost": data.get("subscribersLost", 0),
                "generation_kind": local_record.get("generation_kind", ""),
                "source_video_title": local_record.get("source_video_title", ""),
                "generation_purpose": local_record.get("generation_purpose", ""),
                "character_pattern": local_record.get("character_pattern", ""),
                "genre_group": local_record.get("genre_group", ""),
                "topic_request_cta": local_record.get("topic_request_cta", ""),
                "topic_request_cta_reason": local_record.get("topic_request_cta_reason", ""),
                "final_cta_type": local_record.get("final_cta_type", ""),
            })

        ch_subs = _fetch_channel_subscriber_totals(analytics, start_date, end_date)
        summary = {
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
            "video_count": len(items),
            "views": sum(int(float(item.get("views") or 0)) for item in items),
            "channel_subscribers_gained": ch_subs["gained"] if ch_subs else None,
            "channel_subscribers_lost": ch_subs["lost"] if ch_subs else None,
            "channel_subscribers_net": (ch_subs["gained"] - ch_subs["lost"]) if ch_subs else None,
        }
        return {"summary": summary, "items": items}
    finally:
        _close_google_resource(analytics)
        _close_google_resource(youtube)
