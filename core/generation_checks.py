import logging

from config import (
    NATIVE_LONG_BODY_VOICE_SPEED,
    NATIVE_LONG_INTRO_VOICE_SPEED,
    NATIVE_SHORTS_BODY_VOICE_SPEED,
    NATIVE_SHORTS_ESTIMATE_BASE_CPS,
    NATIVE_SHORTS_INTRO_VOICE_SPEED,
    TRANSITION_SEC,
    VOICE_INTRO_FAST_LINES,
    VOICE_TAIL_SAFETY_SEC,
)

_logger = logging.getLogger(__name__)

INTER_DIALOGUE_GAP_SEC = 0.2

_KAIDAN_ASSERTION_NG = (
    "これは実際に起きた",
    "本当に起きた事件",
    "本当に死んだ",
    "実在する呪われた場所",
    "この場所は呪われている",
    "ここに行くと死ぬ",
    "ここに行くと危険",
    "この地域では本当に出る",
    "犯人は",
)

_KAIDAN_UNCERTAINTY_MARKERS = (
    "実話として語ら",
    "真偽は不明",
    "真偽不明",
    "怪談として",
    "噂として",
    "そう信じられて",
    "記録と噂",
)


def _check_kaidan_safety(meta: dict[str, str], dialogue_items: list[dict]) -> list[str]:
    """怪談チャンネルだけに断定表現と真偽不明表現を検査する。"""
    from core.channel_profile import get_active_profile

    profile = get_active_profile()
    if profile is None or profile.genre_profile != "zundamon_kowai":
        return []
    text = "\n".join([*meta.values(), *(it.get("text", "") for it in dialogue_items)])
    errors = [
        f"怪談の断定表現は禁止です。「真偽不明」「噂として語られている」へ修正してください: {phrase}"
        for phrase in _KAIDAN_ASSERTION_NG
        if phrase in text
    ]
    if not any(marker in text for marker in _KAIDAN_UNCERTAINTY_MARKERS):
        errors.append("怪談台本に真偽不明・噂・怪談としての語り方がありません")
    return errors


def pre_generate_check(items: list[dict], is_shorts: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    meta_types = {
        "video_title", "thumbnail_text", "description", "tags", "hashtags",
        "fixed_comment", "generation_kind", "source_video_title", "generation_purpose",
    }
    meta = {it["type"]: it["text"] for it in items if it["type"] in meta_types}
    dialogue_items = [it for it in items if it["type"] == "dialogue"]
    bg_items = [it for it in items if it["type"] == "background"]

    video_format = next((it["text"] for it in items if it["type"] == "video_format"), "").strip()
    is_netakaigi = "ネタ会議" in video_format

    try:
        try:
            from core.cta_policy import check_shorts_navigation_ng

            if not is_netakaigi:
                script_text = "\n".join(it.get("text", "") for it in dialogue_items)
                hits = check_shorts_navigation_ng(script_text, "Shorts" if is_shorts else "Long")
                if hits:
                    warnings.append(
                        "Shortsでは直接的な他動画誘導・次回予告が含まれています。"
                        f"ループ締めに変更してください: {', '.join(hits)}"
                    )
        except Exception:
            raise

        if not meta.get("video_title"):
            errors.append("video_titleがありません")

        errors.extend(_check_kaidan_safety(meta, dialogue_items))

        thumb_text = meta.get("thumbnail_text", "")
        if thumb_text and len(thumb_text) > 15:
            warnings.append(f"サムネイル文字が長い（{len(thumb_text)}文字）: 「{thumb_text[:20]}」")

        # ネタ会議専用チェック
        if is_netakaigi:
            screen_fmt = next((it["text"] for it in items if it["type"] == "screen_format"), "").strip()
            is_long_variant = (
                "Long" in video_format or "ロング" in video_format
                or "横" in screen_fmt or "wide" in screen_fmt.lower()
            )
            dc = len(dialogue_items)
            if len(bg_items) < 1:
                errors.append("ネタ会議: 背景が1件もありません")
            if is_long_variant:
                # ネタ会議Long（横）: 55〜120行
                if dc < 30:
                    errors.append(f"ネタ会議Long: セリフ数不足（{dc}行 / 最低30行以上）")
                elif dc < 55:
                    warnings.append(f"ネタ会議Long: セリフ数がやや少なめです（{dc}行 / 理想55〜120行）")
                elif dc > 120:
                    errors.append(f"ネタ会議Long: セリフ数過多（{dc}行 / 120行以下推奨）")
            else:
                # ネタ会議Shorts（縦・デフォルト）: 35〜65行
                if dc < 20:
                    errors.append(f"ネタ会議Shorts: セリフ数不足（{dc}行 / 最低20行以上）")
                elif dc < 35:
                    warnings.append(f"ネタ会議Shorts: セリフ数がやや少なめです（{dc}行 / 理想35〜65行）")
                elif dc > 85:
                    errors.append(f"ネタ会議Shorts: セリフ数過多（{dc}行 / 85行以下推奨）")
                elif dc > 65:
                    warnings.append(f"ネタ会議Shorts: セリフ数がやや多めです（{dc}行 / 理想35〜65行）")
            return errors, warnings

        min_bg = 4 if is_shorts else 3
        if len(bg_items) < min_bg:
            warnings.append(f"背景数が少ない（{len(bg_items)}箇所、推奨{min_bg}以上）")

        if dialogue_items:
            first_text = dialogue_items[0].get("text", "")
            if len(first_text) < 8:
                warnings.append(f"冒頭セリフが短すぎます（{len(first_text)}文字）: 「{first_text}」")
            if is_shorts:
                from config import (
                    NATIVE_SHORTS_AVG_CHARS_MIN,
                    NATIVE_SHORTS_CHARS_MUST_FIX_MIN,
                    NATIVE_SHORTS_LINES_IDEAL_MAX,
                    NATIVE_SHORTS_LINES_IDEAL_MIN,
                    NATIVE_SHORTS_LINES_MUST_FIX,
                    NATIVE_SHORTS_LINES_TARGET_MAX,
                    NATIVE_SHORTS_LINES_TARGET_MIN,
                    NATIVE_SHORTS_SHORT_LINE_MAX,
                    NATIVE_SHORTS_TARGET_CHARS_MIN,
                )

                dialogue_count = len(dialogue_items)
                total_dialogue_chars = sum(len(it.get("text", "")) for it in dialogue_items)
                avg_dialogue_chars = total_dialogue_chars / dialogue_count if dialogue_count else 0.0
                if dialogue_count < NATIVE_SHORTS_LINES_IDEAL_MIN:
                    errors.append(
                        f"Shorts台本量不足（{dialogue_count}行 / 理想{NATIVE_SHORTS_LINES_IDEAL_MIN}行以上）"
                    )
                if dialogue_count >= NATIVE_SHORTS_LINES_MUST_FIX:
                    errors.append(f"Shortsセリフ数過多（{dialogue_count}行 / 31行以上は禁止）")
                if total_dialogue_chars < NATIVE_SHORTS_CHARS_MUST_FIX_MIN:
                    missing = NATIVE_SHORTS_TARGET_CHARS_MIN - total_dialogue_chars
                    errors.append(
                        f"Shorts本文文字数不足（セリフ本文{total_dialogue_chars}文字 / 最低{NATIVE_SHORTS_CHARS_MUST_FIX_MIN}文字以上）"
                        f"。目標{NATIVE_SHORTS_TARGET_CHARS_MIN}文字まであと{missing}文字"
                    )
                if avg_dialogue_chars < NATIVE_SHORTS_AVG_CHARS_MIN:
                    errors.append(
                        f"Shorts平均文字数不足（平均{avg_dialogue_chars:.1f}文字 / 必須{NATIVE_SHORTS_AVG_CHARS_MIN:.1f}文字以上）"
                    )
                short_line_count = sum(1 for it in dialogue_items if len(it.get("text", "")) <= 10)
                very_short_line_count = sum(1 for it in dialogue_items if len(it.get("text", "")) <= 7)
                if short_line_count > NATIVE_SHORTS_SHORT_LINE_MAX:
                    errors.append(
                        f"Shorts短文セリフ過多（10文字以下が{short_line_count}行 / 最大{NATIVE_SHORTS_SHORT_LINE_MAX}行）"
                    )
                if very_short_line_count:
                    warnings.append(f"7文字以下の短文セリフがあります（{very_short_line_count}行）。原則11〜15文字に伸ばしてください")
                if NATIVE_SHORTS_LINES_IDEAL_MIN <= dialogue_count <= NATIVE_SHORTS_LINES_IDEAL_MAX and not (
                    NATIVE_SHORTS_LINES_TARGET_MIN <= dialogue_count <= NATIVE_SHORTS_LINES_TARGET_MAX
                ):
                    warnings.append(
                        f"Shortsセリフ数は許容内ですが、安定目標は{NATIVE_SHORTS_LINES_TARGET_MIN}〜{NATIVE_SHORTS_LINES_TARGET_MAX}行です"
                    )
    except Exception as exc:
        _logger.error("生成前チェックに失敗しました", exc_info=True)
        errors.append(f"生成前チェック失敗: {exc}")

    return errors, warnings


def estimate_duration(items: list[dict], is_shorts: bool) -> tuple[float | None, int, float]:
    dialogue_items = [it for it in items if it["type"] == "dialogue"]
    if not dialogue_items:
        return None, 0, 0.0
    line_count = len(dialogue_items)
    total_chars = sum(len(it.get("text", "")) for it in dialogue_items)
    avg_chars = total_chars / line_count if line_count else 0.0

    elapsed = 0.0
    if is_shorts:
        for idx, item in enumerate(dialogue_items):
            chars = len(item.get("text", ""))
            speed = NATIVE_SHORTS_INTRO_VOICE_SPEED if idx < VOICE_INTRO_FAST_LINES else NATIVE_SHORTS_BODY_VOICE_SPEED
            elapsed += chars / (NATIVE_SHORTS_ESTIMATE_BASE_CPS * speed) + 0.1 * speed
    else:
        additional = TRANSITION_SEC + VOICE_TAIL_SAFETY_SEC + INTER_DIALOGUE_GAP_SEC
        for idx, item in enumerate(dialogue_items):
            chars = len(item.get("text", ""))
            speed = NATIVE_LONG_INTRO_VOICE_SPEED if idx < VOICE_INTRO_FAST_LINES else NATIVE_LONG_BODY_VOICE_SPEED
            elapsed += chars / (5.4 * speed) + 0.1 * speed + additional
    return elapsed, line_count, avg_chars


def duration_tag(status: str) -> str:
    if status in ("ideal", "ok_but_short", "ok_but_long"):
        return "success" if status == "ideal" else "warning"
    if status in ("warning", "needs_review"):
        return "warning"
    return "duration"
