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


def load_latest_analytics_full() -> dict[str, Any]:
    """items + summary を含む完全データを返す。JSON優先、なければ TSV の items のみ。"""
    files = list_analytics_files()
    for fname in files:
        if fname.endswith(".json"):
            return _load_json_file_full(os.path.join(ANALYTICS_DIR, fname))
        if fname.endswith(".tsv"):
            return {"items": _load_tsv_file(os.path.join(ANALYTICS_DIR, fname)), "summary": {}}
    return {"items": [], "summary": {}}


def _load_json_file(path: str) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", [])
        return []
    except Exception:
        return []


def _load_json_file_full(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {
                "items": data.get("items", []),
                "summary": data.get("summary", {}),
                "days": data.get("days"),
                "start_date": data.get("start_date"),
                "end_date": data.get("end_date"),
                "generated_at": data.get("generated_at"),
            }
        if isinstance(data, list):
            return {"items": data, "summary": {}}
        return {"items": [], "summary": {}}
    except Exception:
        return {"items": [], "summary": {}}


def _coerce_tsv_value(value: str) -> Any:
    if value == "" or value == "None":
        return None
    if value in ("True", "False"):
        return value == "True"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _load_tsv_file(path: str) -> list[dict[str, Any]]:
    try:
        rows = []
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append({k: _coerce_tsv_value(v) for k, v in row.items()})
        return rows
    except Exception:
        return []


def _build_meta(full: dict[str, Any]) -> dict[str, Any]:
    summary = full.get("summary", {})
    return {
        "days": full.get("days") or summary.get("days"),
        "start_date": full.get("start_date") or summary.get("start_date"),
        "end_date": full.get("end_date") or summary.get("end_date"),
        "generated_at": full.get("generated_at"),
        **summary,
    }


def get_ai_copy_text() -> str:
    """AI分析用コピーテキストを生成する。"""
    full = load_latest_analytics_full()
    items = full.get("items", [])
    if not items:
        return "Analyticsデータがありません。"
    from core.analytics_score import build_performance_summary
    return build_performance_summary(items, meta=_build_meta(full))


def get_shorts_title_prompt() -> str:
    """Shortsタイトル案プロンプトを生成する。"""
    full = load_latest_analytics_full()
    items = full.get("items", [])
    if not items:
        return "Analyticsデータがありません。"
    from core.analytics_score import build_shorts_title_prompt
    return build_shorts_title_prompt(items)


def get_long_title_prompt() -> str:
    """Longタイトル案プロンプトを生成する。"""
    full = load_latest_analytics_full()
    items = full.get("items", [])
    if not items:
        return "Analyticsデータがありません。"
    from core.analytics_score import build_long_title_prompt
    return build_long_title_prompt(items)


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
