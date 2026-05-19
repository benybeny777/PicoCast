import csv
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any


SCORE_ORDER = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "未計測": 0, "対象外": -1}
DURATION_STATUS_LABELS = {
    "ideal": "理想",
    "ok": "OK",
    "ok_but_short": "やや短いがOK",
    "ok_but_long": "OKだが長め",
    "warning": "注意",
    "needs_review": "要確認",
}


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
    # duration が取得できている場合は秒数で分類（API側の video_type より優先）
    duration = _num(item.get("duration") or item.get("duration_sec"), None)
    if duration is not None:
        if duration <= 60:
            return "Shorts"
        if duration <= 120:
            return "ShortLong"
        return "Long"

    # duration なし → フィールドとタイトルで判定
    video_type = str(item.get("video_type") or "").strip().lower()
    if video_type in ("shorts", "short", "ショート"):
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
    if video_type == "ShortLong":
        if 90 <= duration <= 120:
            return "ideal"
        if 61 <= duration < 90:
            return "ok_but_short"
        return "needs_review"
    # Long
    if 300 <= duration <= 600:
        return "ideal"
    if 270 <= duration < 300 or 600 < duration <= 660:
        return "warning"
    return "needs_review"


def format_duration_status(status: str) -> str:
    return DURATION_STATUS_LABELS.get(str(status or ""), str(status or ""))


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
    subscribers_net = gained - lost
    like_rate = (likes / views * 100) if views > 0 else 0.0

    publish_status = str(item.get("publish_status") or "published")

    # 非公開・限定公開 → 対象外
    if publish_status in ("private", "unlisted", "unknown"):
        result = dict(item)
        result.update({
            "title": item.get("title") or "",
            "video_id": item.get("video_id") or "",
            "published_at": item.get("published_at"),
            "duration": _num(item.get("duration") or item.get("duration_sec"), None),
            "duration_status": duration_status(item),
            "video_type": video_type,
            "publish_status": publish_status,
            "analysis_status": "excluded",
            "is_topic_exclusion_target": False,
            "views": views, "impressions": impressions, "ctr": None,
            "average_view_duration": avg_duration, "average_percentage_viewed": avg_percent,
            "likes": likes, "like_rate": like_rate, "comments": comments,
            "subscribers_gained": gained, "subscribers_lost": lost, "subscribers_net": subscribers_net,
            "score": "対象外", "action": "対象外",
        })
        return result

    # 予約投稿 → 重複除外対象だが分析対象外
    if publish_status == "scheduled":
        result = dict(item)
        result.update({
            "title": item.get("title") or "",
            "video_id": item.get("video_id") or "",
            "published_at": item.get("published_at"),
            "duration": _num(item.get("duration") or item.get("duration_sec"), None),
            "duration_status": duration_status(item),
            "video_type": video_type,
            "publish_status": publish_status,
            "analysis_status": "scheduled",
            "is_topic_exclusion_target": True,
            "views": 0, "impressions": 0, "ctr": None,
            "average_view_duration": 0, "average_percentage_viewed": 0,
            "likes": 0, "like_rate": 0.0, "comments": 0,
            "subscribers_gained": 0, "subscribers_lost": 0, "subscribers_net": 0,
            "score": "未計測", "action": "予約中",
        })
        return result

    # Rule 1: views == 0 はデータ待ち
    if views == 0:
        result = dict(item)
        result.update({
            "title": item.get("title") or "",
            "video_id": item.get("video_id") or "",
            "published_at": item.get("published_at"),
            "duration": _num(item.get("duration") or item.get("duration_sec"), None),
            "duration_status": duration_status(item),
            "video_type": video_type,
            "publish_status": publish_status,
            "analysis_status": "data_wait",
            "is_topic_exclusion_target": True,
            "views": 0, "impressions": 0, "ctr": None,
            "average_view_duration": 0, "average_percentage_viewed": 0,
            "likes": 0, "like_rate": 0.0, "comments": 0,
            "subscribers_gained": gained, "subscribers_lost": lost, "subscribers_net": subscribers_net,
            "score": "未計測", "action": "データ待ち",
        })
        return result

    # Rule 2: 動画種別ごとのベーススコア
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
    elif video_type == "ShortLong":
        # 61〜120秒の短尺Long。Shortsより長いのでしきい値を緩める
        if avg_percent >= 75 or avg_duration >= 70:
            score, action = "S", "横展開"
        elif avg_percent >= 60 or avg_duration >= 50:
            score, action = "A", "継続"
        elif avg_percent >= 40 or avg_duration >= 35:
            score, action = "B", "改善して再挑戦"
        elif avg_percent >= 25:
            score, action = "C", "弱い"
        else:
            score, action = "D", "要見直し"
    else:
        # Long (180秒+)
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

    # Rule 3: 登録者純増 >= 2 は最低でも B、視聴率 >= 60 なら横展開
    if subscribers_net >= 2:
        if SCORE_ORDER.get(score, 0) < SCORE_ORDER["B"]:
            score = "B"
            action = "登録者増・改善候補"
        if avg_percent >= 60:
            action = "横展開"

    # Rule 4: like率 >= 1.5% かつ視聴率が低い → テーマは有望
    if like_rate >= 1.5 and score in ("C", "D"):
        action = "テーマ有望・冒頭/構成改善"

    result = dict(item)
    result.update({
        "title": item.get("title") or "",
        "video_id": item.get("video_id") or "",
        "published_at": item.get("published_at"),
        "duration": _num(item.get("duration") or item.get("duration_sec"), None),
        "duration_status": duration_status(item),
        "video_type": video_type,
        "publish_status": publish_status,
        "analysis_status": "analyzable",
        "is_topic_exclusion_target": True,
        "views": views,
        "impressions": impressions,
        "ctr": None if ctr is None else ctr_value,
        "average_view_duration": avg_duration,
        "average_percentage_viewed": avg_percent,
        "likes": likes,
        "like_rate": like_rate,
        "comments": comments,
        "subscribers_gained": gained,
        "subscribers_lost": lost,
        "subscribers_net": subscribers_net,
        "score": score,
        "action": action,
    })
    return result


def score_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_item(item) for item in items]

    # views 上位20% かつ avg_percent >= 65 → action = 横展開・微改善
    # （"横展開" はそのまま維持）
    analyzable_views = sorted(
        _int(item.get("views")) for item in scored
        if item.get("analysis_status") == "analyzable"
    )
    if analyzable_views:
        top20_threshold = analyzable_views[max(0, int(len(analyzable_views) * 0.8))]
        for item in scored:
            if (
                item.get("analysis_status") == "analyzable"
                and _int(item.get("views")) >= top20_threshold
                and _num(item.get("average_percentage_viewed")) >= 65
                and item.get("action") != "横展開"
            ):
                item["action"] = "横展開・微改善"

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
        "title", "published_at", "video_type", "duration", "duration_status",
        "publish_status", "analysis_status",
        "views", "impressions", "ctr",
        "average_view_duration", "average_percentage_viewed", "likes", "like_rate",
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


def build_performance_summary(items: list[dict[str, Any]], limit: int = 5) -> str:
    if not items:
        return "実績データが空です。"

    def _fmt_title(item):
        title = str(item.get("title") or "").strip()
        return title[:42] + ("..." if len(title) > 42 else "")

    # 実績ありのみ分析対象（予約中・データ待ち・対象外は除外）
    scored = [item for item in items if item.get("analysis_status") == "analyzable"]
    strong = [
        item for item in scored
        if item.get("score") in ("S", "A") or _num(item.get("average_percentage_viewed")) >= 70
    ]
    top_views = sorted(scored, key=lambda x: _int(x.get("views")), reverse=True)[:limit]
    top_retention = sorted(scored, key=lambda x: _num(x.get("average_percentage_viewed")), reverse=True)[:limit]
    top_like_rate = sorted(
        [item for item in scored if _int(item.get("views")) >= 50],
        key=lambda x: _num(x.get("like_rate")),
        reverse=True,
    )[:limit]

    lines = [
        "今回の実績データから見える優先横展開:",
        f"・対象動画: {len(scored)}件 / 強い候補: {len(strong)}件",
    ]
    if top_views:
        lines.append("・再生数上位: " + " / ".join(
            f"{_fmt_title(item)} views{_int(item.get('views'))}" for item in top_views[:3]
        ))
    if top_retention:
        lines.append("・平均視聴率上位: " + " / ".join(
            f"{_fmt_title(item)} {_num(item.get('average_percentage_viewed')):.1f}%" for item in top_retention[:3]
        ))
    if top_like_rate:
        lines.append("・高評価率上位: " + " / ".join(
            f"{_fmt_title(item)} {_num(item.get('like_rate')):.2f}%" for item in top_like_rate[:3]
        ))
    lines.append("・viewsだけで判断せず、平均視聴率、平均視聴時間、登録者増減、高評価率を合わせて横展開する。")
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
