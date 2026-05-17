import json
import os
import re
from typing import Any

import requests

from config import (
    OPENAI_API_KEY,
    OPENAI_FINAL_REVIEW_MODEL,
    OPENAI_FINAL_REVIEW_ENABLED,
    OPENING_REVIEW_USE_LLM,
    OLLAMA_BASE_URL,
    OLLAMA_REVIEW_MODEL,
    OLLAMA_REWRITE_MODEL,
    OPENING_REVIEW_MAX_LLM_RETRIES,
    OPENING_REVIEW_AUTO_REWRITE,
    SHORT_FULL_SCRIPT_REVIEW,
    LONG_FULL_SCRIPT_REVIEW,
)


SURPRISE_WORDS = (
    "昔", "実は", "だった", "毒扱い", "日本生まれ", "禁止", "薬", "高級品",
    "貧乏飯", "真逆", "ヤバい", "意外", "知ら", "別物", "勘違い", "衝撃",
    "もともと", "海外", "庶民", "贅沢", "偽物", "危険",
)
CONCLUSION_WORDS = ("つまり", "結論", "正体", "理由は", "答えは")
FOOD_HINT_WORDS = (
    "パン", "米", "肉", "魚", "卵", "牛乳", "チーズ", "カレー", "ラーメン",
    "寿司", "そば", "うどん", "お菓子", "チョコ", "メロン", "じゃがいも",
    "トマト", "ナポリタン", "コーヒー", "コーラ", "マヨネーズ", "うなぎ",
    "牛丼", "天ぷら", "餃子", "焼肉", "味噌", "醤油", "バター",
)


def _truthy_env(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _speaker(item: dict[str, Any]) -> str:
    return str(item.get("speaker") or item.get("character") or item.get("name") or "")


def _dialogue_text(item: dict[str, Any]) -> str:
    return str(item.get("text", "")).strip()


def _extract_keywords(title: str, thumbnail_text: str = "") -> list[str]:
    source = f"{title} {thumbnail_text}"
    tokens = [word for word in FOOD_HINT_WORDS if word in source]
    chunks = re.findall(r"[一-龯ぁ-んァ-ヶーA-Za-z0-9]{2,}", source)
    skip_words = ("動画", "タイトル", "サムネ", "文字", "Shorts", "Long", "雑学", "解説")
    for chunk in chunks:
        if chunk not in tokens and not any(skip in chunk for skip in skip_words):
            tokens.append(chunk)
    return tokens[:8]


def _max_same_speaker_run(speakers: list[str]) -> int:
    max_run = 0
    current = None
    run = 0
    for speaker in speakers:
        if speaker and speaker == current:
            run += 1
        else:
            current = speaker
            run = 1 if speaker else 0
        max_run = max(max_run, run)
    return max_run


def _opening_limit(is_shorts: bool) -> int:
    return 12 if is_shorts else 20


def local_opening_review(items, title: str, thumbnail_text: str, is_shorts: bool) -> dict[str, Any]:
    dialogue_items = [item for item in items if item.get("type") == "dialogue"]
    opening = dialogue_items[:_opening_limit(is_shorts)]
    opening_text = "\n".join(_dialogue_text(item) for item in opening)
    speakers = [_speaker(item) for item in opening]
    keywords = _extract_keywords(title, thumbnail_text)

    score = 100
    issues = []
    checks = {}

    has_food = bool(keywords and any(keyword in opening_text for keyword in keywords))
    checks["food_keyword_in_opening"] = has_food
    checks["keywords"] = keywords
    if not has_food:
        score -= 20
        issues.append("冒頭にタイトル/食べ物名との接続が弱い")

    has_thumbnail_text = bool(thumbnail_text and thumbnail_text in opening_text)
    checks["thumbnail_text_in_opening"] = has_thumbnail_text
    if thumbnail_text and not has_thumbnail_text:
        score -= 8
        issues.append("サムネ文字との接続が弱い")

    has_surprise = any(word in opening_text for word in SURPRISE_WORDS)
    checks["surprise_word_in_opening"] = has_surprise
    if not has_surprise:
        score -= 25
        issues.append("冒頭の意外性ワードが弱い")

    has_both_speakers = len({s for s in speakers if s}) >= 2
    checks["both_speakers_present"] = has_both_speakers
    if not has_both_speakers:
        score -= 12
        issues.append("掛け合いになっていない")

    same_run = _max_same_speaker_run(speakers)
    checks["max_same_speaker_run"] = same_run
    if same_run >= 4:
        score -= 10
        issues.append("同じ話者が4連続以上")

    long_lines = [_dialogue_text(item) for item in opening if len(_dialogue_text(item)) > 15]
    checks["long_dialogue_count"] = len(long_lines)
    if long_lines:
        score -= min(15, len(long_lines) * 3)
        issues.append("15文字超えのセリフが多い")

    first_two = "\n".join(_dialogue_text(item) for item in opening[:2])
    early_conclusion = any(word in first_two for word in CONCLUSION_WORDS)
    checks["early_conclusion_risk"] = early_conclusion
    if early_conclusion:
        score -= 8
        issues.append("冒頭1-2セリフで結論が早すぎる可能性")

    score = max(0, min(100, score))
    # ローカル項目別スコア（ルールベースで算出できる範囲のみ）
    local_scores = {
        "hook": max(0, 100
                    - (25 if not has_surprise else 0)
                    - (10 if not has_food else 0)
                    - (8 if early_conclusion else 0)),
        "title_match": max(0, 100
                           - (15 if not has_food else 0)
                           - (8 if thumbnail_text and not has_thumbnail_text else 0)),
        "tempo": max(0, 100
                     - (12 if not has_both_speakers else 0)
                     - (10 if same_run >= 4 else 0)
                     - min(15, len(long_lines) * 3)),
        "clarity": max(0, 100 - min(20, len(long_lines) * 4)),
    }
    # pass>=85 / warning>=75 / llm_review_required<75（ローカルLLMが甘いためしきい値を引き上げ）
    status = "pass" if score >= 85 else "warning" if score >= 75 else "llm_review_required"
    return {
        "mode": "local",
        "score": score,
        "status": status,
        "llm_review_required": score < 75,
        "rewrite_needed": score < 80,
        "issues": issues,
        "checks": checks,
        "scores": local_scores,
        "opening_lines": [
            {"speaker": _speaker(item), "text": _dialogue_text(item)}
            for item in opening
        ],
    }


def _strip_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        return text[start:end + 1]
    return text


def _post_ollama(prompt: str, model: str, *, json_only: bool = False) -> str:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if json_only:
        body["format"] = "json"
    response = requests.post(f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate", json=body, timeout=120)
    response.raise_for_status()
    return str(response.json().get("response", "")).strip()


def _build_opening_review_prompt(local_review: dict[str, Any], title: str, thumbnail_text: str, video_type: str, target_duration: str) -> str:
    opening_lines = "\n".join(
        f"{line.get('speaker', '')}: {line.get('text', '')}"
        for line in local_review.get("opening_lines", [])
    )
    local_issues = "\n".join(f"- {i}" for i in local_review.get("issues", []))
    local_scores_str = json.dumps(local_review.get("scores", {}), ensure_ascii=False)
    return f"""あなたはYouTube Shortsの厳しい編集者です。
評価は甘くしないでください。平均的な出来は60点です。
80点以上は「かなり良い」場合だけです。90点以上はほぼ完成品だけです。
出力はJSONのみ。説明・markdown・コードブロック・前置きは禁止。

動画形式: {video_type}
タイトル: {title}
サムネ文字: {thumbnail_text}
目標尺: {target_duration}
ルールベース事前チェック（参考）: {local_scores_str}
{f"事前検出の問題点:{chr(10)}{local_issues}" if local_issues else ""}

冒頭セリフ:
{opening_lines}

以下を厳しく評価してください。問題がある場合は必ず warnings に入れてください:
- 冒頭1秒で食べ物名と意外性が出るか
- タイトルとサムネの期待に合うか
- 3秒以内に続きを見たくなるか
- 15秒以内に理由が見えるか
- 会話テンポが落ちていないか
- 同じ情報を繰り返していないか
- ラストが冒頭へ自然に戻るか（ループ構成か）
- CTAが長すぎないか
- 1セリフ15文字以内か

採点基準:
90-100: そのまま出せる強い台本
80-89: 出せるが軽微な改善あり
70-79: 弱点あり、修正推奨
60-69: 伸びにくい、修正必須
59以下: 作り直し候補

返答形式（JSONのみ）:
{{"overall_score":78,"publish_ok":true,"rewrite_recommended":true,"must_fix":[],"warnings":["冒頭の意外性はあるが3秒以内の引きがやや弱い"],"scores":{{"hook":82,"title_match":90,"tempo":76,"clarity":85,"loop":72,"cta":70}},"fix_target":"hook"}}
"""


def _normalize_review_result(result: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    # 新スキーマ: overall_score / 旧スキーマ: score にフォールバック
    score = int(result.get("overall_score") or result.get("score") or 0)
    # warnings + must_fix を issues に統合（後方互換）
    warnings = result.get("warnings") or []
    must_fix = result.get("must_fix") or []
    legacy_issues = result.get("issues") or []
    if not isinstance(legacy_issues, list):
        legacy_issues = [str(legacy_issues)]
    issues = [str(i) for i in (must_fix + warnings + legacy_issues)][:8]
    scores = result.get("scores") or {}
    return {
        "mode": "llm",
        "provider": provider,
        "model": model,
        "score": max(0, min(100, score)),
        # pass>=85 / warning>=75（ローカルLLMが甘いためしきい値を引き上げ）
        "status": "pass" if score >= 85 else "warning" if score >= 75 else "llm_review_required",
        "rewrite_needed": bool(result.get("rewrite_recommended") or result.get("rewrite_needed")) or score < 80,
        "publish_ok": result.get("publish_ok"),
        "must_fix": [str(i) for i in must_fix[:5]],
        "warnings": [str(i) for i in warnings[:5]],
        "issues": issues,
        "scores": scores,
        "fix_target": result.get("fix_target"),
        "suggested_opening": result.get("suggested_opening"),
    }


def ollama_opening_review(local_review: dict[str, Any], title: str, thumbnail_text: str, video_type: str, target_duration: str) -> dict[str, Any] | None:
    prompt = _build_opening_review_prompt(local_review, title, thumbnail_text, video_type, target_duration)
    last_error = None
    for attempt in range(OPENING_REVIEW_MAX_LLM_RETRIES + 1):
        try:
            text = _post_ollama(prompt, OLLAMA_REVIEW_MODEL, json_only=True)
            result = json.loads(_strip_json_text(text))
            return _normalize_review_result(result, "ollama", OLLAMA_REVIEW_MODEL)
        except Exception as exc:
            last_error = exc
            prompt = (
                "前回の出力はJSONとして不正でした。次はJSONだけ返してください。\n"
                "形式: {\"score\":82,\"rewrite_needed\":false,\"issues\":[],\"suggested_opening\":null}\n\n"
                + prompt
            )
    return {
        "mode": "llm",
        "provider": "ollama",
        "model": OLLAMA_REVIEW_MODEL,
        "score": local_review.get("score", 0),
        "status": local_review.get("status", "warning"),
        "rewrite_needed": local_review.get("rewrite_needed", False),
        "publish_ok": None,
        "must_fix": [],
        "warnings": [f"Ollamaレビュー失敗: {last_error}"],
        "issues": [f"Ollamaレビュー失敗: {last_error}"],
        "scores": local_review.get("scores", {}),
        "fix_target": None,
        "suggested_opening": None,
        "fallback_to_local": True,
    }


def llm_opening_review(local_review: dict[str, Any], title: str, thumbnail_text: str, video_type: str, target_duration: str) -> dict[str, Any] | None:
    if not OPENING_REVIEW_USE_LLM:
        return None
    return ollama_opening_review(local_review, title, thumbnail_text, video_type, target_duration)


def should_auto_rewrite_opening(review: dict[str, Any]) -> bool:
    if not OPENING_REVIEW_AUTO_REWRITE:
        return False
    score = int(review.get("score", 0) or 0)
    must_fix = review.get("must_fix") or []
    scores = review.get("scores") or {}
    hook_score = scores.get("hook", 100)
    loop_score = scores.get("loop", 100)
    cta_score = scores.get("cta", 100)
    # must_fix があれば点数に関係なく修正
    if must_fix:
        return True
    # 項目別しきい値
    if hook_score < 75 or loop_score < 70 or cta_score < 70:
        return True
    # 総合スコアで80未満は修正候補（ローカルLLMは甘いため旧75→80に引き上げ）
    return score < 80


def rewrite_opening_with_ollama(review: dict[str, Any], title: str, thumbnail_text: str, video_type: str) -> str | None:
    opening_lines = "\n".join(
        f"{line.get('speaker', '')}: {line.get('text', '')}"
        for line in review.get("opening_lines", [])
    )
    issues = "\n".join(f"- {issue}" for issue in review.get("issues", []))
    prompt = f"""以下のYouTube台本の冒頭だけを修正してください。
全文は書かない。Scene 1〜2相当のセリフだけを返す。
説明、markdown、コードブロックは禁止。

動画形式: {video_type}
タイトル: {title}
サムネ文字: {thumbnail_text}

問題点:
{issues}

元の冒頭:
{opening_lines}

制約:
- 1セリフ15文字以内
- 食べ物名を冒頭に入れる
- 意外性を1秒以内に出す
- タイトルとサムネに一致させる
- ずんだもん/四国めたんの形式で返す
"""
    text = _post_ollama(prompt, OLLAMA_REWRITE_MODEL, json_only=False)
    text = re.sub(r"^```(?:text)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    return text or None


def apply_opening_rewrite_to_script(script_content: str, rewrite_text: str, is_shorts: bool) -> str:
    rewrite_lines = [
        line.strip()
        for line in rewrite_text.splitlines()
        if line.strip() and ":" in line.replace("：", ":")
    ]
    if not rewrite_lines:
        return script_content

    line_re = re.compile(r"^([^:：\n]{1,30})(?:[（(][^）)]*[）)])?\s*[:：]\s*(.+)$")
    original_lines = script_content.splitlines()
    skip_prefixes = (
        "title:", "thumbnail:", "description:", "tags:", "format:", "pinnedcomment:",
        "動画形式:", "動画タイトル:", "サムネ文字:", "サムネイル:", "説明文:", "タグ:",
        "固定コメント:", "背景:", "シーン:", "scene:", "background:", "telop:", "テロップ:",
    )
    dialogue_indexes = []
    for idx, line in enumerate(original_lines):
        stripped = line.strip()
        normalized = stripped.replace("：", ":").lower()
        if normalized.startswith(skip_prefixes):
            continue
        if line_re.match(stripped):
            dialogue_indexes.append(idx)
    if not dialogue_indexes:
        return script_content

    max_replace = min(len(dialogue_indexes), _opening_limit(is_shorts), len(rewrite_lines))
    for i in range(max_replace):
        original_lines[dialogue_indexes[i]] = rewrite_lines[i]

    extra = rewrite_lines[max_replace:_opening_limit(is_shorts)]
    if extra and max_replace:
        insert_at = dialogue_indexes[max_replace - 1] + 1
        original_lines[insert_at:insert_at] = extra

    return "\n".join(original_lines) + ("\n" if script_content.endswith("\n") else "")


def _meta_dir(theme_dir: str) -> str:
    path = os.path.join(theme_dir, "_meta")
    os.makedirs(path, exist_ok=True)
    return path


def save_opening_review(theme_dir: str, local_review: dict[str, Any], llm_review: dict[str, Any] | None = None, rewrite_text: str | None = None) -> str:
    meta = _meta_dir(theme_dir)
    path = os.path.join(meta, "opening_review.json")
    final_review = local_review if rewrite_text else (llm_review or local_review)
    data = {
        "local_review": local_review,
        "llm_review": llm_review,
        "rewrite_suggestion": rewrite_text,
        "final_score": final_review.get("score"),
        "final_status": final_review.get("status"),
        "rewrite_needed": final_review.get("rewrite_needed", False),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if rewrite_text:
        with open(os.path.join(meta, "opening_rewrite_suggestion.txt"), "w", encoding="utf-8") as f:
            f.write(rewrite_text)
    return path


def duration_review(total_sec: float, is_shorts: bool) -> dict[str, Any]:
    if is_shorts:
        if 35 <= total_sec <= 55:
            status = "ok"
        elif 32 <= total_sec <= 34 or 56 <= total_sec <= 58:
            status = "warning"
        else:
            status = "needs_review"
        return {
            "video_type": "Shorts",
            "seconds": round(total_sec, 2),
            "ideal": "38-50秒",
            "acceptable": "35-55秒",
            "status": status,
        }
    if 270 <= total_sec <= 600:
        status = "ok"
    elif total_sec < 240 or total_sec > 660:
        status = "warning"
    else:
        status = "ok"
    return {
        "video_type": "Long",
        "seconds": round(total_sec, 2),
        "ideal": "5-8分",
        "acceptable": "4分30秒-10分",
        "status": status,
    }


def save_duration_review(theme_dir: str, review: dict[str, Any]) -> str:
    path = os.path.join(_meta_dir(theme_dir), "duration_review.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(review, f, ensure_ascii=False, indent=2)
    return path


def _scene_summaries(items, limit: int = 12) -> list[dict[str, Any]]:
    scenes = []
    current = None
    dialogue_count = 0
    sample = []
    for item in items:
        if item.get("type") == "background":
            if current:
                current["dialogue_count"] = dialogue_count
                current["sample_lines"] = sample[:3]
                scenes.append(current)
            current = {"scene": item.get("text", "")}
            dialogue_count = 0
            sample = []
        elif item.get("type") == "dialogue":
            dialogue_count += 1
            if len(sample) < 3:
                sample.append(_dialogue_text(item))
    if current:
        current["dialogue_count"] = dialogue_count
        current["sample_lines"] = sample[:3]
        scenes.append(current)
    return scenes[:limit]


def _build_final_review_prompt(
    *,
    title: str,
    thumbnail_text: str,
    fixed_comment: str,
    script_content: str,
    items,
    is_shorts: bool,
    estimated_duration: float,
    local_review: dict[str, Any],
    ollama_review: dict[str, Any] | None,
    duration_result: dict[str, Any],
) -> str:
    opening_lines = "\n".join(
        f"{line.get('speaker', '')}: {line.get('text', '')}"
        for line in local_review.get("opening_lines", [])
    )
    if is_shorts and SHORT_FULL_SCRIPT_REVIEW:
        script_block = f"full_script:\n{script_content}"
    elif (not is_shorts) and LONG_FULL_SCRIPT_REVIEW:
        script_block = f"full_script:\n{script_content}"
    else:
        script_block = "scene_summaries:\n" + json.dumps(_scene_summaries(items), ensure_ascii=False)
    return f"""You are the final reviewer for a Japanese YouTube food trivia script.
Return JSON only. No markdown. No explanation outside JSON. Do not rewrite the script.

title: {title}
thumbnail_text: {thumbnail_text}
fixed_comment: {fixed_comment}
video_type: {"Shorts" if is_shorts else "Long"}
estimated_duration_sec: {estimated_duration:.2f}
duration_check: {json.dumps(duration_result, ensure_ascii=False)}
local_opening_review: {json.dumps(local_review, ensure_ascii=False)}
ollama_opening_review: {json.dumps(ollama_review, ensure_ascii=False)}

opening_lines:
{opening_lines}

{script_block}

Check:
- opening hook
- title/thumbnail consistency
- pacing
- duration risk
- serious mismatch only

Return:
{{"final_score":86,"publish_ok":true,"risk":"low","must_fix":[],"nice_to_fix":[]}}
"""


def _extract_openai_response_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    parts = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                parts.append(str(content.get("text", "")))
    return "\n".join(parts).strip()


def final_chatgpt_review(
    *,
    title: str,
    thumbnail_text: str,
    fixed_comment: str,
    script_content: str,
    items,
    is_shorts: bool,
    estimated_duration: float,
    local_review: dict[str, Any],
    ollama_review: dict[str, Any] | None,
    duration_result: dict[str, Any],
) -> dict[str, Any] | None:
    if not OPENAI_FINAL_REVIEW_ENABLED:
        return None
    if not OPENAI_API_KEY:
        return {
            "skipped": True,
            "reason": "OPENAI_API_KEY is not set",
            "model": OPENAI_FINAL_REVIEW_MODEL,
        }
    prompt = _build_final_review_prompt(
        title=title,
        thumbnail_text=thumbnail_text,
        fixed_comment=fixed_comment,
        script_content=script_content,
        items=items,
        is_shorts=is_shorts,
        estimated_duration=estimated_duration,
        local_review=local_review,
        ollama_review=ollama_review,
        duration_result=duration_result,
    )
    body = {
        "model": OPENAI_FINAL_REVIEW_MODEL,
        "input": prompt,
        "text": {"format": {"type": "json_object"}},
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body),
        timeout=60,
    )
    response.raise_for_status()
    text = _extract_openai_response_text(response.json())
    result = json.loads(_strip_json_text(text))
    result["model"] = OPENAI_FINAL_REVIEW_MODEL
    return result


def save_final_review(theme_dir: str, review: dict[str, Any] | None) -> str:
    path = os.path.join(_meta_dir(theme_dir), "final_review.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(review or {"skipped": True}, f, ensure_ascii=False, indent=2)
    return path
