"""
台本の「再生リスト」カテゴリ名と動画形式から
YouTube上の実際の再生リスト名を解決するモジュール。
"""

STANDARD_CATEGORIES = (
    "なんで？食べ物の形・容器・袋の秘密",
    "昔は捨ててたのに今は高級品！食べ物の大逆転",
    "実は薬・毒扱いだった！食べ物の黒歴史",
    "実は日本生まれ！その名前、騙されてます",
    "海外では信じられない！ニッポン食のギャップ",
    "毎日使うのに知らない！調味料の意外すぎる秘密",
    "コンビニ・スナック・チェーンの開発秘話",
)

_SHORTS_SUFFIX = " Shorts"
_LONG_SUFFIX = "【じっくり解説】"
_NETA_KAIGI_SHORTS = "ずんだもんとめたんのネタ会議 Shorts"
_NETA_KAIGI_LONG = "ずんだもんとめたんのネタ会議【じっくり版】"


def normalize_category(name: str) -> str:
    """前後空白・全角スペースを除去して正規化する。"""
    return str(name or "").strip().replace("　", " ")


def parse_playlist_categories(raw: str) -> list[str]:
    """台本の「再生リスト:」の値をカテゴリリストに変換する。カンマ区切りを許容。"""
    if not raw:
        return []
    return [c for c in (normalize_category(p) for p in raw.split(",")) if c]


def _is_neta_kaigi_long(video_format: str, screen_format: str) -> bool:
    vf = (video_format or "").strip()
    sf = (screen_format or "").strip()
    if "ネタ会議" in vf and ("long" in vf.lower() or "ロング" in vf):
        return True
    if "ネタ会議" in vf and sf in ("横", "landscape"):
        return True
    return False


def resolve_video_type(video_format: str, screen_format: str) -> str:
    """動画形式・画面形式から "shorts" または "long" を返す。"""
    vf = (video_format or "").strip()
    sf = (screen_format or "").strip()
    vf_lower = vf.lower()
    if "short" in vf_lower:
        return "shorts"
    if "ネタ会議" in vf:
        return "long" if ("long" in vf_lower or sf in ("横", "landscape")) else "shorts"
    return "shorts" if not vf_lower or "long" not in vf_lower else "long"


def resolve_playlist_title(
    category: str,
    video_format: str,
    screen_format: str,
) -> str | None:
    """
    カテゴリ名・動画形式・画面形式から YouTube 上の実際の再生リスト名を解決する。

    ネタ会議系は category 引数を無視して固定名を返す。
    判定不能な動画形式の場合は None を返す（自動フォールバック禁止）。
    """
    vf = (video_format or "").strip()
    sf = (screen_format or "").strip()
    vf_lower = vf.lower()

    if "ネタ会議" in vf:
        return _NETA_KAIGI_LONG if _is_neta_kaigi_long(vf, sf) else _NETA_KAIGI_SHORTS

    cat = normalize_category(category)
    is_shorts = "short" in vf_lower or sf in ("縦", "portrait")
    is_long = "long" in vf_lower or sf in ("横", "landscape")

    if is_shorts:
        return f"{cat}{_SHORTS_SUFFIX}"
    if is_long:
        return f"{cat}{_LONG_SUFFIX}"
    return None
