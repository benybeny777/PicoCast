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


INTER_DIALOGUE_GAP_SEC = 0.2


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

    try:
        try:
            from core.cta_policy import check_shorts_navigation_ng

            script_text = "\n".join(it.get("text", "") for it in dialogue_items)
            hits = check_shorts_navigation_ng(script_text, "Shorts" if is_shorts else "Long")
            if hits:
                warnings.append(
                    "Shortsでは直接的な他動画誘導・次回予告が含まれています。"
                    f"ループ締めに変更してください: {', '.join(hits)}"
                )
        except Exception:
            pass

        if not meta.get("video_title"):
            errors.append("video_titleがありません")

        thumb_text = meta.get("thumbnail_text", "")
        if thumb_text and len(thumb_text) > 15:
            warnings.append(f"サムネイル文字が長い（{len(thumb_text)}文字）: 「{thumb_text[:20]}」")

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
