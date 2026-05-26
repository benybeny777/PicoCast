"""視聴者維持率データの簡易分析。"""
from __future__ import annotations


def _section(elapsed_ratio: float) -> str:
    if elapsed_ratio < 0.10:
        return "冒頭"
    if elapsed_ratio < 0.30:
        return "序盤"
    if elapsed_ratio < 0.70:
        return "中盤"
    if elapsed_ratio < 0.95:
        return "終盤"
    return "末尾"


def analyze_retention(rows: list[dict]) -> dict:
    """
    維持率データを分析して離脱ポイント・コメントを返す。

    Args:
        rows: fetch_audience_retention() が返すdictのリスト

    Returns:
        {
            "rows": 判定メモ付きの行リスト,
            "drop_points": 離脱ポイントのリスト,
            "loop_points": 見返し/ループ可能性のリスト,
            "summary": 自動コメント文字列,
            "ok": bool (分析可能かどうか)
        }
    """
    if len(rows) < 3:
        return {
            "rows": rows,
            "drop_points": [],
            "loop_points": [],
            "summary": "データ点が少ないため分析できませんでした。",
            "ok": False,
        }

    annotated = []
    drop_points = []
    loop_points = []

    for i, row in enumerate(rows):
        memo = _section(row["elapsed_ratio"])
        if row["audience_watch_ratio"] > 1.0:
            memo += " ★見返し/ループ可能性"
            loop_points.append(row)
        if i > 0:
            prev = rows[i - 1]
            drop = prev["retention_percent"] - row["retention_percent"]
            if drop >= 5.0:
                memo += f" ⚠離脱({drop:.1f}pt↓)"
                drop_points.append({**row, "drop_pt": round(drop, 1)})
        annotated.append({**row, "memo": memo})

    # 自動コメント生成
    comments = []
    early_drops = [d for d in drop_points if d["elapsed_ratio"] < 0.10]
    if early_drops:
        comments.append(
            f"冒頭{early_drops[0]['elapsed_ratio']*100:.0f}%で大きく落ちています。"
            "1行目・最初の背景・冒頭テロップを強化してください。"
        )
    mid_drops = [d for d in drop_points if 0.10 <= d["elapsed_ratio"] < 0.70]
    if mid_drops:
        worst = max(mid_drops, key=lambda d: d["drop_pt"])
        comments.append(
            f"中盤{worst['second']:.0f}秒付近({worst['elapsed_ratio']*100:.0f}%)で"
            f"{worst['drop_pt']:.1f}ptの離脱が発生しています。"
        )
    if loop_points:
        lp = loop_points[0]
        comments.append(
            f"{lp['second']:.0f}秒付近({lp['elapsed_ratio']*100:.0f}%)で"
            "視聴者が見返している可能性があります（audienceWatchRatio>1.0）。"
        )
    if not comments:
        comments.append("全体的に離脱が少なく良好です。")

    return {
        "rows": annotated,
        "drop_points": drop_points,
        "loop_points": loop_points,
        "summary": "\n".join(comments),
        "ok": True,
    }
