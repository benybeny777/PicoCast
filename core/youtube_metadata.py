import re


CHANNEL_DEFAULT_TAGS = [
    "ずんだもん",
    "ゆっくり解説",
    "VOICEVOX",
    "食べ物 雑学",
    "雑学 ショート",
    "ゆっくり解説 食べ物",
    "料理の歴史",
]

# Safe default: sushi-specific tags are added by build_topic_tags() only.
VIDEO_DEFAULT_TAGS = [
    "ずんだもん",
    "ゆっくり解説",
    "VOICEVOX",
    "雑学",
    "雑学 ショート",
    "食べ物 雑学",
    "食べ物 雑学 ショート",
    "食べ物雑学",
    "食べ物の歴史",
    "ゆっくり解説 食べ物",
    "ずんだもん解説",
    "四国めたん",
    "VOICEVOX解説",
    "トリビア",
    "ショート",
    "Shorts",
]

EXCLUDED_TAGS = [
    "食べ物 豆知識",
    "食べ物豆知識",
    "アニメ雑学",
    "漫画雑学",
    "ゲーム雑学",
    "都市伝説",
    "怖い話",
    "2ch",
    "なんJ",
]

LOW_PRIORITY_TAGS = [
    "豆知識",
]

# Backward-compatible name used by older tests/imports.
DEFAULT_YOUTUBE_TAGS = VIDEO_DEFAULT_TAGS

DEFAULT_HASHTAGS = [
    "#ずんだもん",
    "#ゆっくり解説",
    "#食べ物雑学",
    "#食べ物の歴史",
    "#VOICEVOX",
    "#雑学ショート",
]

SEO_DESCRIPTION_SENTENCE_SHORTS = (
    "ずんだもんと四国めたんが、身近な食べ物雑学や食べ物の歴史を"
    "ゆっくり解説する雑学ショートです。"
)

SEO_DESCRIPTION_SENTENCE_LONG = (
    "ずんだもんと四国めたんが、身近な食べ物雑学や食べ物の歴史を"
    "ゆっくり解説します。"
)

TAG_POLICY = {
    "source": "vidIQ keyword analysis",
    "force_keywords_into_title": False,
    "excluded_tags": EXCLUDED_TAGS,
    "low_priority_tags": LOW_PRIORITY_TAGS,
}


def split_tags(tags) -> list[str]:
    if isinstance(tags, (list, tuple, set)):
        raw = [str(tag) for tag in tags]
    else:
        raw = re.split(r"[,、\n]", str(tags or ""))
    return [tag.strip() for tag in raw if tag and tag.strip()]


def strip_hashtags(text: str) -> str:
    return re.sub(r"#\S+", "", str(text or "")).strip()


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def normalize_tags(tags: list[str]) -> list[str]:
    normalized = []
    seen = set()

    for tag in tags:
        if not tag:
            continue

        tag = str(tag).strip()
        tag = tag.lstrip("#").strip()
        tag = " ".join(tag.split())

        if not tag or tag in EXCLUDED_TAGS:
            continue

        key = tag.lower()
        if key in seen:
            continue

        seen.add(key)
        normalized.append(tag)

    return normalized


def trim_tags_to_500_chars(tags: list[str], max_chars: int = 500) -> list[str]:
    result = []
    total = 0

    for tag in tags:
        add_len = len(tag) if not result else len(tag) + 1
        if total + add_len > max_chars:
            break
        result.append(tag)
        total += add_len

    return result


def build_topic_tags(title: str, script_text: str = "") -> list[str]:
    text = f"{title}\n{script_text}"
    tags: list[str] = []

    rules = [
        (
            ["寿司", "サーモン", "回転寿司", "なれずし", "江戸前"],
            ["寿司 雑学", "寿司", "日本食", "なれずし", "保存食", "発酵食品"],
        ),
        (
            ["アイス", "ソフトクリーム", "棒アイス", "自販機アイス", "ガリガリ"],
            ["アイス 雑学", "お菓子 雑学", "アイス", "棒アイス", "自販機アイス"],
        ),
        (
            ["コーラ", "トニックウォーター", "炭酸", "ジュース", "飲み物"],
            ["飲み物 雑学", "コーラ 雑学", "炭酸飲料", "飲み物", "食文化"],
        ),
        (
            ["お菓子", "チョコ", "ポテトチップス", "プリン", "ドーナツ", "スナック", "グミ"],
            ["お菓子 雑学", "スナック菓子", "ポテチ", "ポテトチップス", "お菓子"],
        ),
        (
            ["マヨネーズ", "ソース", "調味料", "醤油", "みそ", "ケチャップ", "柚子胡椒"],
            ["調味料 雑学", "調味料", "マヨネーズ", "柚子胡椒", "食文化"],
        ),
        (
            ["コンビニ", "ファミチキ", "セブン", "ローソン", "ファミリーマート"],
            ["コンビニ", "コンビニ 雑学", "コンビニ飯", "ファストフード"],
        ),
        (
            ["マック", "マクドナルド", "ポテト", "ハンバーガー"],
            ["マクドナルド", "マック", "ファストフード", "ポテト", "食べ物 雑学"],
        ),
        (
            ["トマト", "ジャガイモ", "毒", "危険"],
            ["トマト", "野菜の歴史", "食べ物の歴史", "食文化"],
        ),
        (
            ["カレー", "ナポリタン", "ラーメン"],
            ["日本の食文化", "食文化", "食べ物 雑学"],
        ),
        (
            ["ドリア", "洋食", "ファミレス", "ホテル料理"],
            ["ドリア", "洋食", "日本生まれ", "ファミレス", "ホテル料理"],
        ),
    ]

    for keywords, add_tags in rules:
        if any(keyword in text for keyword in keywords):
            tags.extend(add_tags)

    return tags


def build_youtube_tags(
    title: str,
    script_text: str = "",
    extra_tags: list[str] | None = None,
) -> list[str]:
    tags: list[str] = []
    tags.extend(VIDEO_DEFAULT_TAGS)
    tags.extend(build_topic_tags(title, script_text))
    if extra_tags:
        tags.extend(extra_tags)

    tags = normalize_tags(tags)
    return trim_tags_to_500_chars(tags)


def optimize_tags(tags, title: str = "", description: str = "", script_text: str = "") -> str:
    youtube_tags = build_youtube_tags(
        title=title,
        script_text=script_text or description,
        extra_tags=split_tags(tags),
    )
    return ",".join(youtube_tags)


def ensure_seo_description_sentence(description: str, is_shorts: bool | None = None) -> str:
    desc = str(description or "").strip()
    if not desc:
        return desc
    body_without_hashtags = strip_hashtags(desc)
    if _has_any(body_without_hashtags, ("雑学ショート", "食べ物雑学", "ゆっくり解説 食べ物", "食べ物の歴史")):
        return desc
    sentence = SEO_DESCRIPTION_SENTENCE_SHORTS if is_shorts is not False else SEO_DESCRIPTION_SENTENCE_LONG
    return f"{sentence}\n\n{desc}"


def ensure_fixed_hashtags(description: str) -> str:
    desc = str(description or "").rstrip()
    existing = set(re.findall(r"#\S+", desc))
    missing = [tag for tag in DEFAULT_HASHTAGS if tag not in existing]
    if not missing:
        return desc

    lines = desc.splitlines()
    for i, line in enumerate(lines):
        if "#ずんだもん" in line and "#ゆっくり解説" in line and "#食べ物雑学" in line:
            lines[i] = (line.rstrip() + " " + " ".join(missing)).strip()
            return "\n".join(lines).rstrip()

    return (desc + "\n\n" + " ".join(DEFAULT_HASHTAGS)).strip()


def optimize_description(description: str, is_shorts: bool | None = None, keep_hashtags: bool = True) -> str:
    desc = ensure_seo_description_sentence(description, is_shorts=is_shorts)
    if keep_hashtags:
        return ensure_fixed_hashtags(desc)
    return desc


def optimize_upload_metadata(
    title: str,
    description: str,
    tags,
    is_shorts: bool | None = None,
    script_text: str = "",
) -> tuple[str, str, str]:
    """Return title unchanged while improving description and YouTube tags."""
    clean_title = str(title or "").strip()
    optimized_description = optimize_description(description, is_shorts=is_shorts, keep_hashtags=True)
    optimized_tags = optimize_tags(
        tags,
        title=clean_title,
        description=optimized_description,
        script_text=script_text,
    )
    return clean_title, optimized_description, optimized_tags
