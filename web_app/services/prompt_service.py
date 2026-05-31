"""
台本生成プロンプト・タイトル案プロンプトを組み立てて返すサービス。
Web UIのプロンプト生成ボタンから呼び出す。
"""
from typing import Optional


def _active_genre_profile() -> str:
    """active profile の genre_profile を返す。未設定時は例外。レスポンス dict 用。"""
    from core.channel_profile import require_active_profile
    return require_active_profile().genre_profile


def _collect_active_titles() -> list[str]:
    """metadata.db から未アップロードタイトルを収集。"""
    from core.metadata_db import ManagedConnection, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        rows = conn.execute(
            """
            SELECT v.title
            FROM videos v
            LEFT JOIN youtube_status ys ON ys.local_id = v.local_id
            WHERE ys.youtube_video_id IS NULL OR ys.youtube_video_id = ''
            ORDER BY COALESCE(v.updated_at, v.created_at, v.local_id) DESC
            LIMIT 200
            """
        ).fetchall()
    return [str(r["title"] or "").strip() for r in rows if str(r["title"] or "").strip()]


def _collect_uploaded_titles() -> list[str]:
    """metadata.db からアップロード済みタイトルを収集。"""
    from core.metadata_db import ManagedConnection, initialize_db, is_initialized
    if not is_initialized():
        initialize_db()
    with ManagedConnection() as conn:
        rows = conn.execute(
            """
            SELECT v.title
            FROM videos v
            JOIN youtube_status ys ON ys.local_id = v.local_id
            WHERE ys.youtube_video_id IS NOT NULL AND ys.youtube_video_id != ''
            ORDER BY COALESCE(v.updated_at, v.created_at, v.local_id) DESC
            LIMIT 200
            """
        ).fetchall()
    return [str(r["title"] or "").strip() for r in rows if str(r["title"] or "").strip()]


def _collect_all_titles() -> list[str]:
    """metadata.db から生成済みタイトルを収集。"""
    return _collect_active_titles() + _collect_uploaded_titles()


def _read_latest_analytics_tsv(max_rows: int = 80) -> tuple[str, int]:
    from core.analytics_score import to_tsv
    from web_app.services.analytics_service import load_latest_analytics
    items = load_latest_analytics()
    if not items:
        return "", 0
    lines = to_tsv(items[:max_rows]).splitlines()
    if len(lines) < 2:
        return "", 0
    return "\n".join(lines), len(lines) - 1


def _read_latest_analytics_summary() -> str:
    try:
        from core.analytics_score import build_performance_summary
        from web_app.services.analytics_service import load_latest_analytics_full
        full = load_latest_analytics_full()
        items = full.get("items") or []
        if not items:
            return ""
        meta = {k: full.get(k) for k in ("generated_at", "days", "start_date", "end_date")}
        return build_performance_summary(items, meta=meta)
    except Exception:
        return ""


def get_script_generation_prompt() -> dict:
    genre_profile = _active_genre_profile()
    all_titles = _collect_all_titles()
    from core.script_prompts import build_script_generation_prompt
    prompt = build_script_generation_prompt(all_titles)
    return {
        "prompt": prompt,
        "title_count": len(all_titles),
        "genre_profile": genre_profile,
    }


def get_meeting_prompt() -> dict:
    genre_profile = _active_genre_profile()
    all_titles = _collect_all_titles()
    tsv, tsv_count = _read_latest_analytics_tsv()
    summary = _read_latest_analytics_summary()
    analytics_tsv = None
    if tsv and summary:
        analytics_tsv = f"{summary}\n\n【動画別TSV】\n{tsv}"
    elif tsv:
        analytics_tsv = tsv
    from core.script_prompts import build_meeting_script_prompt
    prompt = build_meeting_script_prompt(all_titles, analytics_tsv=analytics_tsv)
    return {
        "prompt": prompt,
        "title_count": len(all_titles),
        "genre_profile": genre_profile,
    }


def get_title_prompt(long_only: bool = False) -> dict:
    genre_profile = _active_genre_profile()
    all_titles = _collect_all_titles()
    tsv, tsv_count = _read_latest_analytics_tsv()
    summary = _read_latest_analytics_summary()
    analytics_tsv: Optional[str] = None
    if tsv and summary:
        analytics_tsv = f"{summary}\n\n【動画別TSV】\n{tsv}"
    elif tsv:
        analytics_tsv = tsv
    from core.script_prompts import build_title_prompt
    prompt = build_title_prompt(all_titles, analytics_tsv=analytics_tsv)
    if long_only:
        prompt += (
            "\n\n今回の生成条件:\n"
            "・ロング候補として20案を出す\n"
            "・Shorts候補は出さない\n"
            "・すべてLong候補の出力形式を使う\n"
            "・Long TOP5を出す\n"
        )
    return {
        "prompt": prompt,
        "title_count": len(all_titles),
        "analytics_count": tsv_count,
        "long_only": long_only,
        "genre_profile": genre_profile,
    }
