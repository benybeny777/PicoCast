"""
台本生成プロンプト・タイトル案プロンプトを組み立てて返すサービス。
Web UIのプロンプト生成ボタンから呼び出す。
"""
import os
from typing import Optional


def _active_genre_profile() -> str:
    """active profile の genre_profile を返す。未設定時は例外。レスポンス dict 用。"""
    from core.channel_profile import require_active_profile
    return require_active_profile().genre_profile


def _get_output_videos_dir() -> str:
    from core.output_paths import get_output_videos_dir
    return get_output_videos_dir()


def _get_uploaded_dir() -> str:
    from core.output_paths import get_uploaded_dir
    return get_uploaded_dir()


def _folder_name_to_title(name: str) -> str:
    from config import config as _cfg
    for prefix in _cfg._LEGACY_FOLDER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name


def _collect_active_titles() -> list[str]:
    """active profile の videos/ フォルダ内の未アップロードフォルダ名からタイトルを収集。"""
    output_dir = _get_output_videos_dir()
    skip = {"000_uploaded", "000_backups", "000_data", "000_legacy"}
    if not os.path.isdir(output_dir):
        return []
    names = sorted(
        (
            d for d in os.listdir(output_dir)
            if os.path.isdir(os.path.join(output_dir, d)) and d not in skip
        ),
        key=lambda d: os.path.getmtime(os.path.join(output_dir, d)),
        reverse=True,
    )
    return [_folder_name_to_title(n) for n in names]


def _collect_uploaded_titles() -> list[str]:
    """active profile の 000_uploaded フォルダからアップロード済みタイトルを収集。"""
    uploaded_dir = _get_uploaded_dir()
    if not os.path.isdir(uploaded_dir):
        return []
    folder_names = sorted(
        (d for d in os.listdir(uploaded_dir) if os.path.isdir(os.path.join(uploaded_dir, d))),
        key=lambda d: os.path.getmtime(os.path.join(uploaded_dir, d)),
        reverse=True,
    )
    return [_folder_name_to_title(n) for n in folder_names]


def _collect_all_titles() -> list[str]:
    """active profile の videos/ + 000_uploaded/ からタイトルを収集。"""
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
