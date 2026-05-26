"""
アナリティクスデータ取得・表示サービス。
"""
import csv
import json
import os
from typing import Any

from core.output_paths import ANALYTICS_DIR
from web_app.job_manager import Job, _log, get_job_manager


def list_analytics_files() -> list[str]:
    try:
        files = sorted(
            [f for f in os.listdir(ANALYTICS_DIR) if f.startswith("analytics_score_")],
            reverse=True,
        )
        return files
    except OSError:
        return []


def load_latest_analytics() -> list[dict[str, Any]]:
    files = list_analytics_files()
    for fname in files:
        if fname.endswith(".json"):
            return _load_json_file(os.path.join(ANALYTICS_DIR, fname))
        if fname.endswith(".tsv"):
            return _load_tsv_file(os.path.join(ANALYTICS_DIR, fname))
    return []


def _load_json_file(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _load_tsv_file(path: str) -> list[dict[str, Any]]:
    try:
        rows = []
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(dict(row))
        return rows
    except Exception:
        return []


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

    _log(job, "スコアを計算して保存中...", "info")
    try:
        items = score_items(data.get("items", []))
        summary = data.get("summary", {})
        days = summary.get("days", 28)
        json_path, tsv_path = save_score_files(items, days, summary=summary)
        _log(job, f"Analytics保存完了: {json_path}", "success")
        return {"json_path": json_path, "tsv_path": tsv_path, "count": len(items)}
    except Exception as e:
        _log(job, f"スコア保存エラー: {e}", "error")
        raise


def get_tsv_text() -> str:
    """TSVテキストをそのまま返す（コピー用）。"""
    files = [f for f in list_analytics_files() if f.endswith(".tsv")]
    if not files:
        return ""
    path = os.path.join(ANALYTICS_DIR, files[0])
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
