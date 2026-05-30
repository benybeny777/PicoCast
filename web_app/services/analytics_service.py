"""
アナリティクスデータ取得・表示サービス。
データは analytics_snapshots テーブル（metadata.db）から取得する。
"""
from typing import Any

from web_app.job_manager import Job, _log, get_job_manager


def load_latest_analytics() -> list[dict[str, Any]]:
    from core.metadata_db import load_latest_analytics_items, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    return load_latest_analytics_items()


def load_latest_analytics_full() -> dict[str, Any]:
    """items + meta を含む完全データを返す。"""
    from core.metadata_db import load_latest_analytics_items, get_latest_analytics_meta, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    items = load_latest_analytics_items()
    meta = get_latest_analytics_meta()
    # start_date / end_date を computed_at + window_days から算出
    start_date = end_date = None
    if meta.get("generated_at") and meta.get("window_days"):
        from core.analytics_score import _analytics_date_range
        start_date, end_date = _analytics_date_range(meta["window_days"], meta.get("generated_at"))
    return {
        "items": items,
        "summary": {},
        "days": meta.get("window_days"),
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": meta.get("generated_at"),
    }


def get_ai_copy_text() -> str:
    full = load_latest_analytics_full()
    items = full.get("items", [])
    if not items:
        return "Analyticsデータがありません。"
    from core.analytics_score import build_performance_summary
    meta = {k: full.get(k) for k in ("days", "start_date", "end_date", "generated_at")}
    return build_performance_summary(items, meta=meta)


def get_shorts_title_prompt() -> str:
    items = load_latest_analytics()
    if not items:
        return "Analyticsデータがありません。"
    from core.analytics_score import build_shorts_title_prompt
    return build_shorts_title_prompt(items)


def get_long_title_prompt() -> str:
    items = load_latest_analytics()
    if not items:
        return "Analyticsデータがありません。"
    from core.analytics_score import build_long_title_prompt
    return build_long_title_prompt(items)


def get_tsv_text() -> str:
    """DB の最新データから TSV テキストを生成して返す（コピー用）。"""
    items = load_latest_analytics()
    if not items:
        return ""
    from core.analytics_score import to_tsv
    return to_tsv(items)


def submit_refresh_job() -> str:
    mgr = get_job_manager()
    job = mgr.create_job("analytics_refresh")
    _log(job, "Analytics取得ジョブを登録しました", "info")
    mgr.submit(job, _run_refresh)
    return job.job_id


def _run_refresh(job: Job) -> dict[str, Any]:
    try:
        from core.youtube_analytics import fetch_video_analytics
        from core.analytics_score import score_items, save_score_files
    except ImportError as e:
        _log(job, f"Analytics モジュールのインポートに失敗: {e}", "error")
        raise

    _log(job, "YouTube Analytics APIからデータを取得中...", "info")
    if job.cancel_event.is_set():
        return {"cancelled": True}

    try:
        data = fetch_video_analytics()
    except Exception as e:
        _log(job, f"Analytics取得エラー: {e}", "error")
        raise

    if job.cancel_event.is_set():
        return {"cancelled": True}

    _log(job, "スコアを計算してDBに保存中...", "info")
    try:
        items = score_items(data.get("items", []))
        summary = data.get("summary", {})
        days = summary.get("days", 28)
        count = save_score_files(items, days, summary=summary)
        _log(job, f"Analytics DB保存完了: {count}件", "success")
        return {"count": count}
    except Exception as e:
        _log(job, f"スコア保存エラー: {e}", "error")
        raise
