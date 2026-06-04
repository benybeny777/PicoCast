import json
import logging
import os
from datetime import date, datetime, timezone, timedelta
from typing import Any

_logger = logging.getLogger(__name__)

SCORE_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1, "未計測": 0, "対象外": -1}
AUDIO_CUTOFF_RISK_DATE = date(2026, 5, 16)
AUDIO_CUTOFF_ACTION_SUFFIX = "音切れ改善候補"
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


def is_audio_cutoff_risk(published_at) -> bool:
    if not published_at:
        return False
    if isinstance(published_at, datetime):
        published_date = published_at.date()
    elif isinstance(published_at, date):
        published_date = published_at
    else:
        text = str(published_at).strip()
        try:
            published_date = date.fromisoformat(text[:10])
        except (TypeError, ValueError):
            return False
    return published_date <= AUDIO_CUTOFF_RISK_DATE


def _append_action_suffix(action: str, suffix: str) -> str:
    action = str(action or "")
    if not action:
        return suffix
    if suffix in action:
        return action
    return f"{action}・{suffix}"


def _should_mark_audio_cutoff_improvement(item: dict[str, Any]) -> bool:
    if item.get("analysis_status") != "analyzable":
        return False
    if item.get("publish_status") != "published":
        return False
    if not item.get("audio_cutoff_risk"):
        return False
    if item.get("video_type") not in ("Shorts", "ShortLong"):
        return False
    return (
        _int(item.get("views")) >= 1000
        or _num(item.get("average_percentage_viewed")) >= 55
        or _num(item.get("like_rate")) >= 1.0
        or _int(item.get("comments")) >= 1
        or _int(item.get("subscribers_net")) >= 1
    )


def apply_audio_cutoff_improvement_action(item: dict[str, Any]) -> dict[str, Any]:
    if _should_mark_audio_cutoff_improvement(item):
        item["action"] = _append_action_suffix(item.get("action"), AUDIO_CUTOFF_ACTION_SUFFIX)
    return item


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
    title_lower = title.lower()
    from config import config as _cfg
    if (
        title_lower.startswith(_cfg.FOLDER_PREFIX_SHORTS.lower())
        or title_lower.startswith(("short_", "shorts_"))
        or "#shorts" in title_lower
        or "ショート" in title
    ):
        return "Shorts"
    return "Long"


def duration_status(item: dict[str, Any]) -> str:
    duration = _num(item.get("duration") or item.get("duration_sec"), None)
    if duration is None or duration <= 0:
        return ""
    video_type = detect_video_type(item)
    if video_type == "Shorts":
        if 42 <= duration <= 48:
            return "ideal"
        if 39 <= duration < 42:
            return "ok_but_short"
        if 48 < duration <= 50:
            return "ok_but_long"
        if 51 <= duration <= 52:
            return "warning"
        return "needs_review"
    if video_type == "ShortLong":
        if 90 <= duration <= 120:
            return "ideal"
        if 61 <= duration < 90:
            return "ok_but_short"
        return "needs_review"
    # Long動画
    if 300 <= duration <= 600:
        return "ideal"
    if 270 <= duration < 300 or 600 < duration <= 660:
        return "warning"
    return "needs_review"


def format_duration_status(status: str) -> str:
    return DURATION_STATUS_LABELS.get(str(status or ""), str(status or ""))


def _detect_avoid_pattern(title: str) -> str:
    """タイトルから失敗ネタ型パターンを推定する。ブラックリスト候補にのみ適用する。"""
    t = str(title or "")
    if any(kw in t for kw in ("歴史", "由来", "発祥", "起源")):
        return "歴史・由来説明型"
    if any(kw in t for kw in ("薬だった", "薬になる", "毒だった", "毒がある", "毒になる")):
        return "有名ネタ消耗型"
    if "本当の理由" in t and not any(kw in t for kw in ("なぜ", "実は", "嫌", "危険", "禁止", "罠", "驚")):
        return "抽象理由型"
    if not any(kw in t for kw in ("実は", "なぜ", "理由", "秘密", "嫌", "危険", "だった", "だけ", "勘違い", "罠", "逆転", "驚", "意外", "禁止", "怒", "苦手")):
        return "驚き不足型"
    return ""


def _mark_blacklist_candidate(item: dict[str, Any]) -> dict[str, Any]:
    """視聴数・維持率・反応指標でブラックリスト候補を判定し、フラグ・理由・避けるパターンを付与する。"""
    from config import config as _cfg_bl
    item.setdefault("blacklist_candidate", False)
    item.setdefault("weak_reason", "")
    item.setdefault("avoid_pattern", "")
    if item.get("analysis_status") != "analyzable":
        return item

    views = _int(item.get("views"))
    avg_pct = _num(item.get("average_percentage_viewed"))
    subs_net = _int(item.get("subscribers_net"))
    like_rate = _num(item.get("like_rate"))
    comments = _int(item.get("comments"))
    ctr_raw = item.get("ctr")
    video_type = item.get("video_type", "Long")

    is_bl = False
    if video_type in ("Shorts", "ShortLong"):
        if (views >= _cfg_bl.ANALYTICS_BL_MIN_VIEWS_SHORTS
                and avg_pct < _cfg_bl.ANALYTICS_BL_MAX_AVG_PCT_SHORTS
                and subs_net <= 0
                and like_rate < _cfg_bl.ANALYTICS_BL_MAX_LIKE_RATE
                and comments == 0):
            is_bl = True
    else:
        ctr_ok = ctr_raw is None or _num(ctr_raw) < _cfg_bl.ANALYTICS_BL_MAX_CTR_LONG
        if (views >= _cfg_bl.ANALYTICS_BL_MIN_VIEWS_LONG
                and avg_pct < _cfg_bl.ANALYTICS_BL_MAX_AVG_PCT_LONG
                and ctr_ok
                and subs_net <= 0
                and like_rate < _cfg_bl.ANALYTICS_BL_MAX_LIKE_RATE):
            is_bl = True

    item["blacklist_candidate"] = is_bl
    if is_bl:
        item["weak_reason"] = "low_retention_low_reaction"
        item["avoid_pattern"] = _detect_avoid_pattern(item.get("title", ""))
        item["action"] = _append_action_suffix(item.get("action", ""), "ブラックリスト候補")
    return item


def score_item(item: dict[str, Any]) -> dict[str, Any]:
    video_type = detect_video_type(item)
    audio_cutoff_risk = is_audio_cutoff_risk(item.get("published_at"))
    views = _int(item.get("views"))
    impressions = _int(item.get("impressions"))
    ctr = item.get("ctr")
    ctr_value = _num(ctr, 0.0)
    avg_duration = _num(item.get("average_view_duration"))
    avg_percent = _num(item.get("average_percentage_viewed"))
    likes = _int(item.get("likes"))
    dislikes = _int(item.get("dislikes"))
    like_dislike_total = likes + dislikes
    dislike_rate = dislikes / max(like_dislike_total, 1) * 100 if like_dislike_total > 0 else None
    from config import config as _cfg_score
    dislike_rate_provisional = like_dislike_total < _cfg_score.ANALYTICS_DISLIKE_RATE_MIN_REACTIONS
    comments = _int(item.get("comments"))
    gained_raw = item.get("subscribers_gained")
    lost_raw = item.get("subscribers_lost")
    gained = _int(gained_raw)
    lost = _int(lost_raw)
    if gained_raw is None and lost_raw is None and item.get("subscribers_net") is not None:
        subscribers_net = _int(item.get("subscribers_net"))
    else:
        subscribers_net = gained - lost
    like_rate = (likes / views * 100) if views > 0 else 0.0

    publish_status = str(item.get("publish_status") or "published")
    analytics_available = bool(item.get("analytics_available", True))

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
            "audio_cutoff_risk": audio_cutoff_risk,
            "is_topic_exclusion_target": False,
            "is_provisional": False,
            "views": views, "impressions": impressions, "ctr": None,
            "average_view_duration": avg_duration, "average_percentage_viewed": avg_percent,
            "likes": likes, "like_rate": like_rate,
            "dislikes": dislikes, "like_dislike_total": like_dislike_total,
            "dislike_rate": dislike_rate, "dislike_rate_provisional": dislike_rate_provisional,
            "comments": comments,
            "subscribers_gained": gained, "subscribers_lost": lost, "subscribers_net": subscribers_net,
            "score": "対象外", "action": "対象外",
            "blacklist_candidate": False, "weak_reason": "", "avoid_pattern": "",
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
            "audio_cutoff_risk": audio_cutoff_risk,
            "is_topic_exclusion_target": True,
            "is_provisional": False,
            "views": 0, "impressions": 0, "ctr": None,
            "average_view_duration": 0, "average_percentage_viewed": 0,
            "likes": 0, "like_rate": 0.0,
            "dislikes": 0, "like_dislike_total": 0,
            "dislike_rate": None, "dislike_rate_provisional": True,
            "comments": 0,
            "subscribers_gained": 0, "subscribers_lost": 0, "subscribers_net": 0,
            "score": "未計測", "action": "予約中",
            "blacklist_candidate": False, "weak_reason": "", "avoid_pattern": "",
        })
        return result

    # ルール1: Analyticsの平均視聴率などが未取得、または views == 0 はデータ待ち
    if not analytics_available or views == 0:
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
            "audio_cutoff_risk": audio_cutoff_risk,
            "is_topic_exclusion_target": True,
            "is_provisional": False,
            "analytics_available": analytics_available,
            "views": views, "impressions": impressions, "ctr": None,
            "average_view_duration": 0, "average_percentage_viewed": 0,
            "likes": likes, "like_rate": like_rate,
            "dislikes": dislikes, "like_dislike_total": like_dislike_total,
            "dislike_rate": dislike_rate, "dislike_rate_provisional": dislike_rate_provisional,
            "comments": comments,
            "subscribers_gained": gained, "subscribers_lost": lost, "subscribers_net": subscribers_net,
            "score": "未計測", "action": "データ待ち",
            "blacklist_candidate": False, "weak_reason": "", "avoid_pattern": "",
        })
        return result

    # ルール2: views < ANALYTICS_MIN_VIEWS_FOR_SCORE → 配布不足・判定保留
    from config import config as _cfg_score
    if views < _cfg_score.ANALYTICS_MIN_VIEWS_FOR_SCORE:
        has_strong_reaction = (
            like_rate >= _cfg_score.ANALYTICS_REACTION_STRONG_LIKE_RATE
            or likes >= _cfg_score.ANALYTICS_REACTION_STRONG_MIN_LIKES
        )
        has_reaction = (
            likes >= _cfg_score.ANALYTICS_REACTION_MIN_LIKES
            or comments >= 1
            or subscribers_net >= 1
        )
        if has_strong_reaction:
            ud_action = "配布不足・反応強い"
        elif has_reaction:
            ud_action = "配布不足・判定保留・反応あり"
        else:
            ud_action = "配布不足・判定保留"
        result = dict(item)
        result.update({
            "title": item.get("title") or "",
            "video_id": item.get("video_id") or "",
            "published_at": item.get("published_at"),
            "duration": _num(item.get("duration") or item.get("duration_sec"), None),
            "duration_status": duration_status(item),
            "video_type": video_type,
            "publish_status": publish_status,
            "analysis_status": "underdistributed",
            "audio_cutoff_risk": audio_cutoff_risk,
            "is_topic_exclusion_target": False,
            "is_provisional": False,
            "views": views, "impressions": impressions, "ctr": None,
            "average_view_duration": avg_duration, "average_percentage_viewed": avg_percent,
            "likes": likes, "like_rate": like_rate,
            "dislikes": dislikes, "like_dislike_total": like_dislike_total,
            "dislike_rate": dislike_rate, "dislike_rate_provisional": dislike_rate_provisional,
            "comments": comments,
            "subscribers_gained": gained, "subscribers_lost": lost, "subscribers_net": subscribers_net,
            "score": "未計測", "action": ud_action,
            "blacklist_candidate": False, "weak_reason": "", "avoid_pattern": "",
        })
        return result

    # 本判定の最低要件: views >= 500 かつ公開後24時間経過
    # どちらか一方でも満たせば本判定可
    is_provisional = False
    if views < 500:
        pub_val = item.get("published_at")
        if pub_val:
            try:
                pub_dt = datetime.fromisoformat(str(pub_val).replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                hours_since = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
                if hours_since < 24:
                    is_provisional = True
            except Exception:
                pass  # フォールバック許可: 日付パース失敗時は本判定とする

    # 横展開の最低視聴率ライン（viewsだけ・avg_percentだけで横展開しない）
    if video_type == "Shorts":
        min_pct_expansion = 45.0
    elif video_type == "ShortLong":
        min_pct_expansion = 50.0
    else:
        min_pct_expansion = 40.0  # Long は CTR >= 8 と平均視聴率 40%以上で横展開
    above_expansion_min = avg_percent >= min_pct_expansion
    long_expansion_ready = video_type == "Long" and ctr_value >= 8 and avg_percent >= 40

    # ルール2: 動画種別ごとのベーススコア
    if video_type == "Shorts":
        if avg_percent >= 90 or avg_duration >= 45:
            score, action = "A", "横展開"
        elif avg_percent >= 80 or avg_duration >= 38:
            score, action = "B", "継続"
        elif avg_percent >= 70 or avg_duration >= 32:
            score, action = "C", "改善して再挑戦"
        elif avg_percent >= 60:
            score, action = "D", "弱い"
        else:
            score, action = "E", "要見直し"
    elif video_type == "ShortLong":
        # 61〜120秒の短尺Long。Shortsより長いのでしきい値を緩める
        if avg_percent >= 75 or avg_duration >= 70:
            score, action = "A", "横展開"
        elif avg_percent >= 60 or avg_duration >= 50:
            score, action = "B", "継続"
        elif avg_percent >= 40 or avg_duration >= 35:
            score, action = "C", "改善して再挑戦"
        elif avg_percent >= 25:
            score, action = "D", "弱い"
        else:
            score, action = "E", "要見直し"
    else:
        # Long（180秒+）
        if ctr_value >= 8 and avg_percent >= 40:
            score, action = "A", "横展開"
        elif ctr_value >= 5 and avg_percent >= 30:
            score, action = "B", "継続"
        elif ctr_value >= 3 and avg_percent >= 20:
            score, action = "C", "タイトル/中身改善"
        elif avg_percent >= 15:
            score, action = "D", "サムネ/冒頭改善"
        else:
            score, action = "E", "要見直し"

    # ルール3: 最低視聴率ラインを下回る横展開を抑制
    if action == "横展開" and not above_expansion_min:
        action = "テーマ有望・構成改善"

    # ルール4: 登録者純増 >= 2 → 強い横展開候補（最低でも B）
    if subscribers_net >= 2:
        if SCORE_ORDER.get(score, 0) < SCORE_ORDER["C"]:
            score = "C"
            action = "登録者増・改善候補"
        if video_type != "Long" and above_expansion_min and action != "横展開":
            action = "横展開"
        elif video_type == "Long" and long_expansion_ready and action != "横展開":
            action = "横展開"
        elif video_type == "Long" and action != "横展開":
            action = "登録者増・構成改善"
    # 登録者純増 >= 1 → 登録導線あり（弱いスコアへの補足）
    elif subscribers_net >= 1 and action in ("弱い", "要見直し", "改善して再挑戦"):
        action = f"{action}・登録導線あり"

    # ルール5: like率 >= 1.5% → テーマ有望（視聴率ライン未達または C/D スコア）
    if like_rate >= 1.5 and action != "横展開":
        if not above_expansion_min:
            # 高エンゲージメントだが低視聴率 → テーマ有望・構成改善
            action = "テーマ有望・構成改善"
        elif score in ("D", "E"):
            action = "テーマ有望・冒頭/構成改善"

    # ルール6: コメント反応あり（弱いスコアの補足）
    if comments >= 1 and action in ("弱い", "要見直し"):
        action = f"{action}・反応あり"

    # ルール7: 本判定保留（views < 500 かつ公開24時間未満）
    if is_provisional and "横展開" in action:
        action = f"{action}(判定保留)"

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
        "audio_cutoff_risk": audio_cutoff_risk,
        "is_topic_exclusion_target": True,
        "is_provisional": is_provisional,
        "views": views,
        "impressions": impressions,
        "ctr": None if ctr is None else ctr_value,
        "average_view_duration": avg_duration,
        "average_percentage_viewed": avg_percent,
        "likes": likes,
        "like_rate": like_rate,
        "dislikes": dislikes,
        "like_dislike_total": like_dislike_total,
        "dislike_rate": dislike_rate,
        "dislike_rate_provisional": dislike_rate_provisional,
        "comments": comments,
        "subscribers_gained": gained,
        "subscribers_lost": lost,
        "subscribers_net": subscribers_net,
        "score": score,
        "action": action,
        "blacklist_candidate": False, "weak_reason": "", "avoid_pattern": "",
    })
    return apply_audio_cutoff_improvement_action(result)


def score_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_item(item) for item in items]

    # views 上位20% かつ avg_percent >= 65 → action = 横展開・微改善
    # viewsだけで横展開しない: 最低視聴率ライン(Shorts:45% / ShortLong:50%)も必須
    # 判定保留(is_provisional)は昇格しない
    analyzable_views = sorted(
        _int(item.get("views")) for item in scored
        if item.get("analysis_status") == "analyzable"
    )
    _EXPANSION_MIN = {"Shorts": 45.0, "ShortLong": 50.0}
    if analyzable_views:
        top20_threshold = analyzable_views[max(0, int(len(analyzable_views) * 0.8))]
        for item in scored:
            vtype = item.get("video_type", "Long")
            min_pct = _EXPANSION_MIN.get(vtype, 0.0)
            if (
                item.get("analysis_status") == "analyzable"
                and not item.get("is_provisional")
                and _int(item.get("views")) >= top20_threshold
                and _num(item.get("average_percentage_viewed")) >= max(65, min_pct)
                and item.get("action") != "横展開"
            ):
                item["action"] = "横展開・微改善"

    for item in scored:
        apply_audio_cutoff_improvement_action(item)
        _mark_blacklist_candidate(item)

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
        "publish_status", "analysis_status", "is_provisional", "audio_cutoff_risk",
        "generation_kind", "source_video_title", "generation_purpose",
        "character_pattern", "genre_group", "topic_request_cta", "topic_request_cta_reason",
        "final_cta_type", "render_engine",
        "views", "impressions", "ctr",
        "average_view_duration", "average_percentage_viewed",
        "likes", "like_rate",
        "dislikes", "like_dislike_total", "dislike_rate", "dislike_rate_provisional",
        "comments", "subscribers_net", "score", "action",
        "blacklist_candidate", "weak_reason", "avoid_pattern",
    ]
    lines = ["\t".join(cols)]
    for item in items:
        values = []
        for col in cols:
            value = item.get(col)
            if col == "published_at" and value is not None:
                value = str(value)[:16].replace("T", " ")
            elif isinstance(value, float):
                value = f"{value:.2f}"
            values.append("" if value is None else str(value).replace("\t", " "))
        lines.append("\t".join(values))
    return "\n".join(lines)


def _analytics_date_range(days: int, generated_at: str | None = None) -> tuple[str, str]:
    if generated_at:
        try:
            end = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).date()
        except Exception:
            _logger.warning("Analytics期間のgenerated_at解析に失敗しました: generated_at=%s", generated_at, exc_info=True)
            end = datetime.now(timezone(timedelta(hours=9))).date()
    else:
        end = datetime.now(timezone(timedelta(hours=9))).date()
    start = end - timedelta(days=int(days))
    return start.isoformat(), end.isoformat()


def analytics_period_label(days: int | None = None, start_date: str | None = None, end_date: str | None = None, generated_at: str | None = None) -> str:
    days = int(days or 28)
    if not start_date or not end_date:
        start_date, end_date = _analytics_date_range(days, generated_at)
    generated_text = f" / 取得日時: {generated_at}" if generated_at else ""
    return f"対象期間: {start_date}〜{end_date} ({days}日){generated_text}"


def build_performance_summary(items: list[dict[str, Any]], limit: int = 5, meta: dict[str, Any] | None = None) -> str:
    if not items:
        return "実績データが空です。"

    def _fmt_title(item):
        title = str(item.get("title") or "").strip()
        return title[:42] + ("..." if len(title) > 42 else "")

    # 実績ありのみ分析対象（予約中・データ待ち・対象外は除外）
    scored = [item for item in items if item.get("analysis_status") == "analyzable"]
    data_wait = [item for item in items if item.get("analysis_status") == "data_wait"]
    strong = [
        item for item in scored
        if item.get("score") in ("A", "B") or _num(item.get("average_percentage_viewed")) >= 70
    ]
    top_views = sorted(scored, key=lambda x: _int(x.get("views")), reverse=True)[:limit]
    top_retention = sorted(scored, key=lambda x: _num(x.get("average_percentage_viewed")), reverse=True)[:limit]
    top_like_rate = sorted(
        [item for item in scored if _int(item.get("views")) >= 50],
        key=lambda x: _num(x.get("like_rate")),
        reverse=True,
    )[:limit]
    data_wait_notable = sorted(
        [
            item for item in data_wait
            if (
                _int(item.get("views")) >= 1000
                or _int(item.get("likes")) >= 10
                or _num(item.get("like_rate")) >= 1.0
                or _int(item.get("comments")) >= 1
            )
        ],
        key=lambda x: (_int(x.get("views")), _int(x.get("likes")), _int(x.get("comments"))),
        reverse=True,
    )[:limit]

    lines = ["今回の実績データから見える優先横展開:"]
    if meta:
        lines.append("・" + analytics_period_label(
            days=meta.get("days"),
            start_date=meta.get("start_date"),
            end_date=meta.get("end_date"),
            generated_at=meta.get("generated_at"),
        ))
        ch_gained = meta.get("channel_subscribers_gained")
        ch_lost = meta.get("channel_subscribers_lost")
        ch_net = meta.get("channel_subscribers_net")
        if ch_gained is not None:
            from config import ANALYTICS_CHANNEL_LEGACY_NOTE, ANALYTICS_CHANNEL_REMAKE_DATE
            lines.append(f"・チャンネル登録者増減: +{ch_gained} -{ch_lost} 純増{ch_net}")
            lines.append(f"・注記: {ANALYTICS_CHANNEL_LEGACY_NOTE}（リメイク開始: {ANALYTICS_CHANNEL_REMAKE_DATE}）")
    lines.append(f"・対象動画: {len(scored)}件 / 強い候補: {len(strong)}件 / データ待ち: {len(data_wait)}件")
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
    if data_wait_notable:
        lines.append("・data_wait注目: " + " / ".join(
            f"{_fmt_title(item)} views{_int(item.get('views'))} likes{_int(item.get('likes'))} comments{_int(item.get('comments'))}"
            for item in data_wait_notable[:3]
        ))
    lines.append("・viewsだけで判断せず、平均視聴率、平均視聴時間、登録者増減、高評価率を合わせて横展開する。")
    lines.append("・data_waitは平均視聴率未取得のため暫定扱いにし、views / likes / like_rate / comments が強い動画には必ず短いコメントを付ける。")
    lines.append("・views 1000未満は配布不足扱いで評価対象外。ネタ失敗と誤判定しないこと。")

    # 弱い動画ランキング（views>=1000、analyzable）
    weak_candidates = sorted(
        [item for item in scored if not item.get("is_provisional")],
        key=lambda x: (
            _num(x.get("average_percentage_viewed")),
            _num(x.get("average_view_duration")),
            _num(x.get("like_rate")),
        ),
    )[:limit]
    if weak_candidates:
        lines.append("\n【弱い動画ランキング（平均視聴率昇順）】")
        for item in weak_candidates:
            lines.append(
                f"・{_fmt_title(item)} "
                f"views{_int(item.get('views'))} "
                f"avg_pct{_num(item.get('average_percentage_viewed')):.1f}% "
                f"avg_dur{_num(item.get('average_view_duration')):.0f}s "
                f"like_rate{_num(item.get('like_rate')):.2f}% "
                f"subs{_int(item.get('subscribers_net')):+d} "
                f"[{item.get('video_type','')}]"
            )

    # ブラックリスト候補と避けるべきネタ型
    blacklist = [item for item in scored if item.get("blacklist_candidate")]
    if blacklist:
        lines.append("\n【避けるべきネタ型候補（ブラックリスト）】")
        for item in blacklist:
            pattern = item.get("avoid_pattern") or "パターン不明"
            lines.append(
                f"・{_fmt_title(item)} "
                f"views{_int(item.get('views'))} "
                f"avg_pct{_num(item.get('average_percentage_viewed')):.1f}% "
                f"→ 型: {pattern}"
            )
        lines.append("※ スワイプ率データ未取得のため入口診断はスキップ（視聴維持率・反応指標で判定）")

    return "\n".join(lines)


_ANALYTICS_RULES_TEXT = """\
━━━━━━━━━━━━━━━━━━
Analytics/vidIQ実績ルール（最新）
━━━━━━━━━━━━━━━━━━

【穴シリーズ優先横展開】
バウムクーヘン・マカロニ・ベーグルで成立確認済み。穴・空洞・形状の理由系は高優先横展開候補。
ただし「○○に穴がある本当の理由」の連発は避け、タイトル表現を変える。
次候補: ちくわ、ドーナツ、れんこん、アイスの棒、ストロー菓子など。

【配布不足・反応強い動画の扱い】
views < 1000 でも like_rate >= 2.5% または likes >= 20 の動画は失敗扱いにしない。
action に「反応強い」が付いている動画は横展開起点として優先検討する。
例: ジンジャーエール → 薬っぽい飲み物シリーズの起点候補。

【腐らない・長持ち系の採用基準】
ハチミツのような一般食材単体は既知感・科学説明化で弱くなりやすい。
マックポテトのように、自分も食べている身近な商品・ブランド・店に紐づく場合は優先度を上げる。
腐らない系は「外食チェーン・コンビニ・日常購入品」に寄せて採用すること。

【昔は違った系の採用基準】
現在のイメージとの落差が大きいものだけ採用する。
・サーモン型（優先）: 現在の人気・高級感が強く、昔の低評価とのギャップが大きいもの
・トロ型（優先度下げ）: 既知情報になりやすいものは優先度を下げる
次候補: ロブスター・カニカマ・チキン・タコ・サーモン系横展開。

【弱動画の分類（即ブラックリストにしない）】
・ハチミツ: 有名ネタ・科学説明型 → リベンジは歴史エピソード型で切り口を変える
・人参: 反応は強いので入口改善候補。ネタ自体は捨てない
・納豆フィルム: 自分事化できなければブラックリスト候補
・プリン: 具体エピソード化すれば改善余地あり
・メロンパン: 有名すぎる名前ネタ消耗型。通常切り口は避ける

【次回タイトル案 優先候補】
以下を最優先候補として扱う（既存タイトルと重複しないか確認すること）:
・ちくわに穴がないと作れない理由
・オムライスは日本生まれだった
・昔のロブスターは貧乏人の食べ物だった
・ドクターペッパーが薬っぽく作られた理由
・ドーナツに穴がある本当の理由
"""


def _build_title_prompt_base(items: list[dict[str, Any]], video_type_filter: str | None = None) -> str:
    """Shorts/Longタイトル案プロンプトの共通ベース部分を生成する。"""
    scored = [
        item for item in items
        if item.get("analysis_status") == "analyzable"
        and (video_type_filter is None or item.get("video_type") == video_type_filter)
    ]

    def _fmt(item):
        title = str(item.get("title") or "").strip()
        return title[:50] + ("..." if len(title) > 50 else "")

    strong = sorted(
        [item for item in scored if item.get("score") in ("A", "B")],
        key=lambda x: _num(x.get("average_percentage_viewed")),
        reverse=True,
    )[:5]
    blacklist = [item for item in scored if item.get("blacklist_candidate")]

    lines = []
    if strong:
        lines.append("【横展開できる強い動画】")
        for item in strong:
            lines.append(
                f"・{_fmt(item)} "
                f"avg_pct{_num(item.get('average_percentage_viewed')):.1f}% "
                f"views{_int(item.get('views'))}"
            )
    if blacklist:
        lines.append("\n【避けるべきネタ型（ブラックリスト）】")
        for item in blacklist:
            pattern = item.get("avoid_pattern") or "パターン不明"
            lines.append(f"・{_fmt(item)} → 型: {pattern}")
        lines.append("\n【タイトル生成NG例】")
        lines.append("NG: 「○○の歴史」「○○の由来」「○○の秘密」「○○だった」（有名事実の繰り返し）")
        lines.append("改善: 「○○は昔、嫌われていた」「○○が実は日本生まれの理由」「○○の袋だけパンパンな理由」")
        lines.append("   → 常識逆転・具体物の違和感・冒頭1秒で結論断言 を入れること")
    return "\n".join(lines)


def build_shorts_title_prompt(items: list[dict[str, Any]]) -> str:
    """Shortsタイトル案生成用コピー用テキストを生成する。"""
    base = _build_title_prompt_base(items, video_type_filter="Shorts")
    header = (
        "以下の実績データをもとに、ずんだもんとめたんの食べ物雑学ショート動画タイトル案を5〜10個考えてください。\n"
        "主KPI: 平均視聴率（維持率）。ブラックリスト候補と同じネタ型・切り口は原則NGです。\n"
        "改善再挑戦は切り口を明確に変える場合のみ最大2案まで許可。\n\n"
    )
    return header + _ANALYTICS_RULES_TEXT + "\n" + (base if base else "（実績データなし）")


def build_long_title_prompt(items: list[dict[str, Any]]) -> str:
    """Longタイトル案生成用コピー用テキストを生成する。"""
    base = _build_title_prompt_base(items, video_type_filter="Long")
    header = (
        "以下の実績データをもとに、ずんだもんとめたんの食べ物雑学Long動画タイトル案を3〜5個考えてください。\n"
        "主KPI: CTR × 平均視聴率。ブラックリスト候補と同じネタ型・切り口は原則NGです。\n\n"
    )
    return header + _ANALYTICS_RULES_TEXT + "\n" + (base if base else "（実績データなし）")


def save_score_files(items: list[dict[str, Any]], days: int, output_dir=None, summary: dict[str, Any] | None = None) -> int:
    """analytics データを DB に保存する。JSON/TSV ファイルへの書き込みは廃止済み。返値: 保存件数。"""
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    collected_at = now.strftime("%Y-%m-%d")  # 同日の重複防止
    count = 0
    try:
        from core.metadata_db import insert_analytics_snapshot, is_initialized, initialize_db
        if not is_initialized():
            initialize_db()
        for item in items:
            vid = item.get("video_id")
            if not vid:
                continue
            insert_analytics_snapshot(vid, collected_at, int(days), item)
            count += 1
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).error("[SQLite] analytics DB書き込み失敗: %s", e)
        raise
    return count
