import csv
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any


SCORE_ORDER = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}


def _num(value, default=0.0):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    return int(_num(value, default))


def detect_video_type(item: dict[str, Any]) -> str:
    video_type = str(item.get("video_type") or "").strip()
    if video_type.lower() in ("shorts", "short", "ショート"):
        return "Shorts"
    if video_type.lower() in ("long", "ロング"):
        return "Long"

    duration = _num(item.get("duration") or item.get("duration_sec"), None)
    if duration is not None and duration <= 60:
        return "Shorts"

    title = str(item.get("title") or "")
    if "[Shorts]" in title or "#shorts" in title.lower() or "ショート" in title:
        return "Shorts"
    return "Long"


def duration_status(item: dict[str, Any]) -> str:
    duration = _num(item.get("duration") or item.get("duration_sec"), None)
    if duration is None or duration <= 0:
        return ""
    video_type = detect_video_type(item)
    if video_type == "Shorts":
        if 38 <= duration <= 50:
            return "ideal"
        if 35 <= duration < 38:
            return "ok_but_short"
        if 50 < duration <= 55:
            return "ok_but_long"
        if 32 <= duration < 35 or 55 < duration <= 58:
            return "warning"
        return "needs_review"
    if 300 <= duration <= 600:
        return "ideal"
    if 270 <= duration < 300 or 600 < duration <= 660:
        return "warning"
    return "needs_review"


def score_item(item: dict[str, Any]) -> dict[str, Any]:
    video_type = detect_video_type(item)
    views = _int(item.get("views"))
    impressions = _int(item.get("impressions"))
    ctr = item.get("ctr")
    ctr_value = _num(ctr, 0.0)
    avg_duration = _num(item.get("average_view_duration"))
    avg_percent = _num(item.get("average_percentage_viewed"))
    likes = _int(item.get("likes"))
    comments = _int(item.get("comments"))
    gained = _int(item.get("subscribers_gained"))
    lost = _int(item.get("subscribers_lost"))

    if video_type == "Shorts":
        if avg_percent >= 90 or avg_duration >= 45:
            score, action = "S", "横展開"
        elif avg_percent >= 80 or avg_duration >= 38:
            score, action = "A", "継続"
        elif avg_percent >= 70 or avg_duration >= 32:
            score, action = "B", "改善して再挑戦"
        elif avg_percent >= 60:
            score, action = "C", "弱い"
        else:
            score, action = "D", "要見直し"
    else:
        if ctr_value >= 8 and avg_percent >= 40:
            score, action = "S", "横展開"
        elif ctr_value >= 5 and avg_percent >= 30:
            score, action = "A", "継続"
        elif ctr_value >= 3 and avg_percent >= 20:
            score, action = "B", "タイトル/中身改善"
        elif avg_percent >= 15:
            score, action = "C", "サムネ/冒頭改善"
        else:
            score, action = "D", "要見直し"

    result = dict(item)
    result.update({
        "title": item.get("title") or "",
        "video_id": item.get("video_id") or "",
        "published_at": item.get("published_at"),
        "duration": _num(item.get("duration") or item.get("duration_sec"), None),
        "duration_status": duration_status(item),
        "video_type": video_type,
        "views": views,
        "impressions": impressions,
        "ctr": None if ctr is None else ctr_value,
        "average_view_duration": avg_duration,
        "average_percentage_viewed": avg_percent,
        "likes": likes,
        "comments": comments,
        "subscribers_gained": gained,
        "subscribers_lost": lost,
        "subscribers_net": gained - lost,
        "score": score,
        "action": action,
    })
    return result


def score_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_item(item) for item in items]
    scored.sort(key=lambda x: (SCORE_ORDER.get(x.get("score"), 0), _int(x.get("views"))), reverse=True)
    return scored


def format_duration(seconds) -> str:
    seconds = int(_num(seconds))
    m, s = divmod(seconds, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def to_tsv(items: list[dict[str, Any]]) -> str:
    cols = [
        "title", "published_at", "video_type", "duration", "duration_status", "views", "impressions", "ctr",
        "average_view_duration", "average_percentage_viewed", "likes",
        "comments", "subscribers_net", "score", "action",
    ]
    lines = ["\t".join(cols)]
    for item in items:
        values = []
        for col in cols:
            value = item.get(col)
            if isinstance(value, float):
                value = f"{value:.2f}"
            values.append("" if value is None else str(value).replace("\t", " "))
        lines.append("\t".join(values))
    return "\n".join(lines)


def save_score_files(items: list[dict[str, Any]], days: int, output_dir="output") -> tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    stamp = now.strftime("%Y%m%d")
    json_path = os.path.join(output_dir, f"analytics_score_{stamp}.json")
    tsv_path = os.path.join(output_dir, f"analytics_score_{stamp}.tsv")
    data = {
        "generated_at": now.isoformat(),
        "days": days,
        "items": items,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(tsv_path, "w", encoding="utf-8", newline="") as f:
        f.write(to_tsv(items))
    return json_path, tsv_path
