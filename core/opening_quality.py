import json
import os
import re
import subprocess
import time
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
    OPENING_SCORE_ABORT_THRESHOLD,
    OPENING_SCORE_HARD_ABORT_THRESHOLD,
    SHORT_FULL_SCRIPT_REVIEW,
    LONG_FULL_SCRIPT_REVIEW,
)


SURPRISE_WORDS = (
    "昔", "実は", "だった", "毒扱い", "日本生まれ", "禁止", "薬", "高級品",
    "貧乏飯", "真逆", "ヤバい", "意外", "知ら", "別物", "勘違い", "衝撃",
    "もともと", "海外", "庶民", "贅沢", "偽物", "危険", "実の外", "薬屋",
    "作戦", "代用品", "王族", "名前だけ", "外側", "手間", "メロンなし",
)
CONCLUSION_WORDS = ("つまり", "結論", "正体", "理由は", "答えは")
FOOD_HINT_WORDS = (
    "パン", "米", "肉", "魚", "卵", "牛乳", "チーズ", "カレー", "ラーメン",
    "寿司", "そば", "うどん", "お菓子", "チョコ", "メロン", "じゃがいも",
    "トマト", "ナポリタン", "コーヒー", "コーラ", "マヨネーズ", "うなぎ",
    "牛丼", "天ぷら", "餃子", "焼肉", "味噌", "醤油", "バター", "ケチャップ",
    "カシューナッツ", "紅茶", "アイス", "バナナ",
)

_OLLAMA_START_ATTEMPTED = False


def _truthy_env(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _speaker(item: dict[str, Any]) -> str:
    return str(item.get("speaker") or item.get("character") or item.get("name") or "")


def _dialogue_text(item: dict[str, Any]) -> str:
    return str(item.get("text", "")).strip()


def _extract_keywords(title: str, thumbnail_text: str = "") -> list[str]:
    source = f"{title} {thumbnail_text}"
    tokens = [word for word in FOOD_HINT_WORDS if word in source]
    for candidate in _food_candidates(title):
        if candidate not in tokens:
            tokens.append(candidate)
    chunks = re.findall(r"[一-龯ぁ-んァ-ヶーA-Za-z0-9]{2,}", source)
    skip_words = ("動画", "タイトル", "サムネ", "文字", "Shorts", "Long", "雑学", "解説")
    for chunk in chunks:
        if chunk not in tokens and not any(skip in chunk for skip in skip_words):
            tokens.append(chunk)
    return tokens[:8]


def _food_candidates(title: str) -> list[str]:
    title = (title or "").strip()
    candidates = []
    for sep in ("は", "が", "に", "を", "も", "で"):
        if sep in title:
            head = title.split(sep, 1)[0].strip()
            if 2 <= len(head) <= 12:
                candidates.append(head)
            break
    if "の" in title:
        head = title.split("の", 1)[0].strip()
        if 2 <= len(head) <= 12 and head not in candidates:
            candidates.append(head)
    return candidates


def _is_incomplete_opening_line(text: str) -> bool:
    text = (text or "").strip()
    if len(text) < 4:
        return True
    return bool(re.search(r"(?:は|が|を|に|で|と|の|も|へ|から|より)$", text))


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


def opening_score_tag(score: int, critical_errors: list | None = None) -> str:
    """Return log tag for a given opening score and critical error list."""
    has_errors = bool(critical_errors)
    if score >= OPENING_SCORE_ABORT_THRESHOLD and not has_errors:
        return "score_ok"
    if score >= OPENING_SCORE_HARD_ABORT_THRESHOLD and not has_errors:
        return "score_warn"
    return "score"


def local_opening_review(items, title: str, thumbnail_text: str, is_shorts: bool, render_engine: str = "ymm4") -> dict[str, Any]:
    dialogue_items = [item for item in items if item.get("type") == "dialogue"]
    opening = dialogue_items[:_opening_limit(is_shorts)]
    opening_text = "\n".join(_dialogue_text(item) for item in opening)
    speakers = [_speaker(item) for item in opening]
    all_speakers = [_speaker(item) for item in dialogue_items]
    keywords = _extract_keywords(title, thumbnail_text)
    food_keywords = [word for word in keywords if word in FOOD_HINT_WORDS or word in _food_candidates(title)]
    first_line = _dialogue_text(opening[0]) if opening else ""

    score = 100
    issues = []
    critical_errors = []
    checks = {}

    has_food = bool(keywords and any(keyword in opening_text for keyword in keywords))
    # タイトル由来 food_keywords に加え、FOOD_HINT_WORDS が直接 first_line にあればOK
    # （「コーヒーは口臭を招くのよ」のようにタイトルが抽象的でも食材名が初行にある場合を拾う）
    first_line_has_food = (
        bool(food_keywords and any(keyword in first_line for keyword in food_keywords))
        or any(word in first_line for word in FOOD_HINT_WORDS)
    )
    # N選型（「〇〇3選」「5選」等）は代表食材1つが冒頭にあればOK
    is_n_sen = bool(re.search(r"[2-9][選]|[2-9０-９][〜~]?[0-9０-９]*選", str(title or "")))
    checks["food_keyword_in_opening"] = has_food
    checks["food_keyword_in_first_line"] = first_line_has_food
    checks["is_n_sen"] = is_n_sen
    checks["keywords"] = keywords
    checks["food_keywords"] = food_keywords
    if not has_food:
        score -= 20
        issues.append("冒頭にタイトル/食べ物名との接続が弱い")
    if not first_line_has_food:
        if is_n_sen:
            issues.append("N選型: 冒頭1行目に代表食材の言及が弱い")
        else:
            critical_errors.append("冒頭1行目に食べ物名がない")

    has_thumbnail_text = bool(thumbnail_text and thumbnail_text in opening_text)
    checks["thumbnail_text_in_opening"] = has_thumbnail_text
    if thumbnail_text and not has_thumbnail_text:
        score -= 8
        issues.append("サムネ文字との接続が弱い")

    has_surprise = any(word in opening_text for word in SURPRISE_WORDS)
    first_line_has_surprise = any(word in first_line for word in SURPRISE_WORDS)
    checks["surprise_word_in_opening"] = has_surprise
    checks["surprise_word_in_first_line"] = first_line_has_surprise
    if not has_surprise:
        score -= 25
        issues.append("冒頭の意外性ワードが弱い")
    if not first_line_has_surprise:
        critical_errors.append("冒頭1行目に意外性がない")

    has_both_speakers = len({s for s in speakers if s}) >= 2
    checks["both_speakers_present"] = has_both_speakers
    if not has_both_speakers:
        score -= 12
        issues.append("掛け合いになっていない")

    same_run = _max_same_speaker_run(all_speakers)
    checks["max_same_speaker_run"] = same_run
    if same_run >= 4:
        score -= 10
        issues.append("同じ話者が4連続以上")
        critical_errors.append("同じ話者が4連続以上")

    dialogue_count = len(dialogue_items)
    checks["dialogue_count"] = dialogue_count
    if is_shorts:
        if render_engine == "native":
            from config import NATIVE_SHORTS_LINES_MUST_FIX, NATIVE_SHORTS_LINES_WARNING
            if dialogue_count >= NATIVE_SHORTS_LINES_MUST_FIX:
                critical_errors.append(f"Shorts(native)のセリフ数が{NATIVE_SHORTS_LINES_MUST_FIX}行以上")
            elif dialogue_count >= NATIVE_SHORTS_LINES_WARNING:
                issues.append(f"Shorts(native)のセリフ数が{dialogue_count}行（{NATIVE_SHORTS_LINES_WARNING}行以上は多め）")
        else:
            if dialogue_count >= 21:
                critical_errors.append("Shortsのセリフ数が21行以上")

    incomplete_first_line = _is_incomplete_opening_line(first_line)
    checks["first_line_complete"] = not incomplete_first_line
    if incomplete_first_line:
        critical_errors.append("冒頭1行目だけで意味が完結していない")

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
    # 80点以上は通過、70-79点は重大エラーがなければ警告通過、69点以下はリライト対象。
    status = (
        "pass" if score >= 80 and not critical_errors
        else "warning" if score >= OPENING_SCORE_HARD_ABORT_THRESHOLD and not critical_errors
        else "llm_review_required"
    )
    return {
        "mode": "local",
        "score": score,
        "status": status,
        "llm_review_required": score < OPENING_SCORE_HARD_ABORT_THRESHOLD or bool(critical_errors),
        "rewrite_needed": score < OPENING_SCORE_HARD_ABORT_THRESHOLD or bool(critical_errors),
        "issues": issues,
        "critical_errors": critical_errors,
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


def _ollama_is_ready(timeout=1.5) -> bool:
    try:
        with requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=timeout) as response:
            return response.ok
    except requests.RequestException:
        return False


def ensure_ollama_server(wait_seconds=10) -> None:
    global _OLLAMA_START_ATTEMPTED
    if _ollama_is_ready():
        return

    if not _OLLAMA_START_ATTEMPTED:
        _OLLAMA_START_ATTEMPTED = True
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
        except Exception as exc:
            raise RuntimeError(f"Ollama自動起動に失敗しました: {exc}") from exc

    deadline = time.time() + max(1, wait_seconds)
    while time.time() < deadline:
        if _ollama_is_ready(timeout=1.0):
            return
        time.sleep(0.5)
    raise RuntimeError("Ollamaを自動起動しましたが、APIが応答しませんでした")


def _post_ollama(prompt: str, model: str, *, json_only: bool = False) -> str:
    ensure_ollama_server()
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if json_only:
        body["format"] = "json"
    with requests.post(f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate", json=body, timeout=120) as response:
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
- サムネ文字の衝撃ワードを冒頭5秒以内に回収しているか
- タイトルは理由・経緯・疑問、サムネは一番強い事実という役割分担ができているか
- タイトルとサムネが同じ文章の繰り返しになっていないか
- 「衝撃の秘密」「知られざる真実」「意外な歴史」「ヤバすぎる理由」など抽象ワードだけに逃げていないか
- 3秒以内に続きを見たくなるか
- 15秒以内に理由が見えるか
- Longの場合、冒頭30秒以内に「衝撃事実」「視聴者の疑問」「昔と今のギャップ」「答えの予告」が入っているか
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
    critical_errors = [str(i) for i in result.get("critical_errors", [])[:5]] if isinstance(result.get("critical_errors", []), list) else []
    return {
        "mode": "llm",
        "provider": provider,
        "model": model,
        "score": max(0, min(100, score)),
        "status": "pass" if score >= 80 and not critical_errors else "warning" if score >= OPENING_SCORE_HARD_ABORT_THRESHOLD and not critical_errors else "llm_review_required",
        "rewrite_needed": bool(result.get("rewrite_recommended") or result.get("rewrite_needed")) or score < OPENING_SCORE_HARD_ABORT_THRESHOLD or bool(critical_errors),
        "publish_ok": result.get("publish_ok"),
        "must_fix": [str(i) for i in must_fix[:5]],
        "warnings": [str(i) for i in warnings[:5]],
        "issues": issues,
        "critical_errors": critical_errors,
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
    critical_errors = review.get("critical_errors") or []
    scores = review.get("scores") or {}
    hook_score = scores.get("hook", 100)
    loop_score = scores.get("loop", 100)
    cta_score = scores.get("cta", 100)
    # must_fix があれば点数に関係なく修正
    if must_fix or critical_errors:
        return True
    # 項目別しきい値
    if hook_score < 75 or loop_score < 70 or cta_score < 70:
        return True
    # 69点以下はリライト。70-79点は重大エラーがなければ警告通過。
    return score < OPENING_SCORE_HARD_ABORT_THRESHOLD


def rewrite_opening_with_ollama(
    review: dict[str, Any],
    title: str,
    thumbnail_text: str,
    video_type: str,
    model: str | None = None,
) -> str | None:
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
- サムネ文字の衝撃ワードを冒頭5秒以内に回収する
- タイトルとサムネの同じ文章を繰り返さない
- 昔と今の価値観ギャップを前面に出す
- ずんだもん/四国めたんの形式で返す
"""
    text = _post_ollama(prompt, model or OLLAMA_REWRITE_MODEL, json_only=False)
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
        if 38 <= total_sec <= 50:
            status = "ideal"
        elif 35 <= total_sec < 38:
            status = "ok_but_short"
        elif 50 < total_sec <= 55:
            status = "ok_but_long"
        elif 55 < total_sec <= 58:
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


def duration_status_label(status: str) -> str:
    labels = {
        "ideal": "理想",
        "ok": "OK",
        "ok_but_short": "やや短いがOK",
        "ok_but_long": "OKだが長め",
        "warning": "注意",
        "needs_review": "要確認",
        "unknown": "不明",
    }
    return labels.get(str(status or ""), str(status or ""))


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
    render_engine: str = "native",
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
    return f"""You are the pre-generation reviewer for a Japanese YouTube food trivia script.
Return JSON only. No markdown. No explanation outside JSON. Do not rewrite the script.

title: {title}
thumbnail_text: {thumbnail_text}
fixed_comment: {fixed_comment}
video_type: {"Shorts" if is_shorts else "Long"}
render_engine: {render_engine if is_shorts else "ymm4"}
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
- estimated duration risk
- serious mismatch only

Stop the pipeline only for must_fix-level problems:
- estimated Shorts duration under 39 seconds or over 52 seconds (53s or more is error-level)
- native Shorts dialogue count 31 or more (29-30 is warning only; 22-28 is acceptable; 24-27 is ideal — do NOT flag must_fix for dialogue_count 28 or under)
- first dialogue lacks the food name (drinks like coffee/cola/milk also count as food for this channel)
- first dialogue is incomplete or split mid-phrase
- factual error or risky unsupported assertion
- unhandled YouTube NG wording
- same speaker 4 times in a row

Use nice_to_fix only for minor issues:
- weak title
- weak thumbnail connection
- weak surprise wording
- slightly weak CTA
- slightly abstract telop

Scoring policy:
- 80 or higher: publish_ok should usually be true unless must_fix exists.
- 70-79: publish_ok can be true if must_fix is empty.
- 69 or lower: publish_ok should be false.
- Do not fail a script only because the title/thumbnail/telop are not exact matches if the meaning is aligned.

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


def _filter_obsolete_dialogue_must_fix(must_fix: list[str], dialogue_count: int) -> list[str]:
    """native Shorts で dialogue_count <= 28 の場合、YMM4時代の '21行以上' 系 must_fix を除去する。"""
    OLD_PATTERNS = ("21以上", "21行以上", "対話数が21", "Shorts dialogue count", "dialogue_count: 2")
    return [
        item for item in must_fix
        if not any(pat in str(item) for pat in OLD_PATTERNS)
    ] if dialogue_count <= 28 else must_fix


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
    render_engine: str = "native",
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
        render_engine=render_engine,
    )
    body = {
        "model": OPENAI_FINAL_REVIEW_MODEL,
        "input": prompt,
        "text": {"format": {"type": "json_object"}},
    }
    with requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body),
        timeout=60,
    ) as response:
        response.raise_for_status()
        text = _extract_openai_response_text(response.json())
    result = json.loads(_strip_json_text(text))
    result["model"] = OPENAI_FINAL_REVIEW_MODEL
    # native Shorts かつ dialogue_count <= 28 の場合、旧 YMM4 基準由来の誤 must_fix を除去
    if is_shorts and render_engine == "native":
        dialogue_count = int((local_review.get("checks") or {}).get("dialogue_count") or 0)
        if dialogue_count <= 28 and dialogue_count > 0:
            must_fix = result.get("must_fix") or []
            result["must_fix"] = _filter_obsolete_dialogue_must_fix(must_fix, dialogue_count)
    return result


def save_final_review(theme_dir: str, review: dict[str, Any] | None) -> str:
    path = os.path.join(_meta_dir(theme_dir), "final_review.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(review or {"skipped": True}, f, ensure_ascii=False, indent=2)
    return path
