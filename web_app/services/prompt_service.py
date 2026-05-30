"""
台本生成プロンプト・タイトル案プロンプトを組み立てて返すサービス。
Web UIのプロンプト生成ボタンから呼び出す。
"""
import os
from typing import Optional

from core.output_paths import OUTPUT_DIR, analytics_paths


_NON_FOOD_KEYWORDS = (
    "鬼滅", "ワンピ", "呪術", "スカッと", "こめお", "大喧嘩", "喧嘩", "激論",
    "アニメ", "漫画", "伏線", "考察",
)
_FOOD_KEYWORDS = (
    "食", "飲", "料理", "飯", "味", "お菓子", "菓子", "野菜", "肉", "魚", "寿司", "外食",
    "保存食", "発酵", "調味料", "薬", "毒扱い", "無毒", "給料",
    "人参", "にんじん", "ハチミツ", "蜂蜜", "タピオカ", "フグ", "ふぐ",
    "クロワッサン", "かき氷", "シロップ", "カレー", "コンニャク", "こんにゃく",
    "メロンパン", "マック", "ポテト", "ケチャップ", "トマト", "サーモン",
    "鮭", "ロブスター", "オマール海老", "コーラ", "コカ・コーラ", "ポップコーン",
    "チョコ", "チョコレート", "塩", "フライドポテト", "ポテトフライ",
    "ポテチ", "ポテトチップス",
    "オレンジ", "ミイラ", "カエル", "海のゴキブリ",
)


def _folder_name_to_title(name: str) -> str:
    from config import config as _cfg
    for prefix in _cfg._LEGACY_FOLDER_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name


def _is_food_title(title: str) -> bool:
    if any(kw in title for kw in _NON_FOOD_KEYWORDS):
        return False
    return any(kw in title for kw in _FOOD_KEYWORDS)


def _collect_active_titles() -> list[str]:
    """outputフォルダ内の未アップロードフォルダ名からタイトルを収集。"""
    skip = {"000_uploaded", "000_backups"}
    if not os.path.isdir(OUTPUT_DIR):
        return []
    names = sorted(
        (
            d for d in os.listdir(OUTPUT_DIR)
            if os.path.isdir(os.path.join(OUTPUT_DIR, d)) and d not in skip
        ),
        key=lambda d: os.path.getmtime(os.path.join(OUTPUT_DIR, d)),
        reverse=True,
    )
    return [_folder_name_to_title(n) for n in names]


def _collect_uploaded_titles() -> list[str]:
    """000_uploaded フォルダからアップロード済みタイトルを収集。"""
    uploaded_dir = os.path.join(OUTPUT_DIR, "000_uploaded")
    if not os.path.isdir(uploaded_dir):
        return []
    folder_names = sorted(
        (d for d in os.listdir(uploaded_dir) if os.path.isdir(os.path.join(uploaded_dir, d))),
        key=lambda d: os.path.getmtime(os.path.join(uploaded_dir, d)),
        reverse=True,
    )
    return [_folder_name_to_title(n) for n in folder_names]


def _collect_food_titles() -> list[str]:
    active = _collect_active_titles()
    uploaded = _collect_uploaded_titles()
    all_titles = active + uploaded
    return [t for t in all_titles if _is_food_title(t)]


def _read_latest_analytics_tsv(max_rows: int = 80) -> tuple[str, int]:
    paths = analytics_paths(".tsv")
    if not paths:
        return "", 0
    latest = max(paths, key=os.path.getmtime)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f if line.strip()]
    except OSError:
        return "", 0
    if not lines:
        return "", 0
    header, rows = lines[0], lines[1:max_rows + 1]
    return "\n".join([header] + rows), len(rows)


def _read_latest_analytics_summary() -> str:
    try:
        import json
        from core.analytics_score import build_performance_summary
        paths = analytics_paths(".json")
        if not paths:
            return ""
        latest = max(paths, key=os.path.getmtime)
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items") or []
        if not items:
            return ""
        meta = {
            "generated_at": data.get("generated_at"),
            "days": data.get("days"),
            "start_date": data.get("start_date") or (data.get("summary") or {}).get("start_date"),
            "end_date": data.get("end_date") or (data.get("summary") or {}).get("end_date"),
        }
        return build_performance_summary(items, meta=meta)
    except Exception:
        return ""


def get_script_generation_prompt() -> dict:
    from core.script_prompts import build_script_generation_prompt
    food_titles = _collect_food_titles()
    prompt = build_script_generation_prompt(food_titles)
    return {"prompt": prompt, "title_count": len(food_titles)}


def get_meeting_prompt() -> dict:
    from core.script_prompts import build_meeting_script_prompt
    food_titles = _collect_food_titles()
    tsv, tsv_count = _read_latest_analytics_tsv()
    summary = _read_latest_analytics_summary()
    analytics_tsv = None
    if tsv and summary:
        analytics_tsv = f"{summary}\n\n【動画別TSV】\n{tsv}"
    elif tsv:
        analytics_tsv = tsv
    prompt = build_meeting_script_prompt(food_titles, analytics_tsv=analytics_tsv)
    return {"prompt": prompt, "title_count": len(food_titles)}


def get_title_prompt(long_only: bool = False) -> dict:
    from core.script_prompts import build_title_prompt
    food_titles = _collect_food_titles()
    tsv, tsv_count = _read_latest_analytics_tsv()
    summary = _read_latest_analytics_summary()
    analytics_tsv: Optional[str] = None
    if tsv and summary:
        analytics_tsv = f"{summary}\n\n【動画別TSV】\n{tsv}"
    elif tsv:
        analytics_tsv = tsv
    prompt = build_title_prompt(food_titles, analytics_tsv=analytics_tsv)
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
        "title_count": len(food_titles),
        "analytics_count": tsv_count,
        "long_only": long_only,
    }
