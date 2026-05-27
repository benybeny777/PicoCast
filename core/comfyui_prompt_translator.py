"""
ComfyUI背景プロンプト変換モジュール。
日本語の背景説明をOllamaで英語のpositive / negativeプロンプトに変換する。

失敗時はRuntimeErrorを上位に伝播する。フォールバック禁止。
"""

import json
import re

import httpx
import config


_REQUIRED_POSITIVE = [
    "background art only",
    "empty scene",
    "no people",
    "no characters",
    "no humanoid subject",
    "manga style background illustration",
    "clean composition",
]

_REQUIRED_NEGATIVE = [
    "person", "people", "human", "girl", "woman", "man", "anime girl",
    "character", "face", "eyes", "hair", "body", "portrait", "full body",
    "hands", "clothes", "horns", "creature", "text", "watermark", "logo",
]

_SYSTEM_PROMPT = (
    "You are a Stable Diffusion / ComfyUI prompt specialist.\n"
    "Convert the given Japanese background description into English positive and negative prompts "
    "optimized for anime-style background art generation.\n\n"
    "Rules:\n"
    "1. Output ONLY a valid JSON object with exactly two keys: \"positive\" and \"negative\".\n"
    "2. The image must be a BACKGROUND SCENE ONLY — absolutely no people, characters, or humanoids.\n"
    "3. The positive prompt MUST start with: "
    "\"background art only, empty scene, no people, no characters, no humanoid subject, "
    "manga style background illustration, clean composition\"\n"
    "4. The negative prompt MUST include: "
    "\"person, people, human, girl, woman, man, anime girl, character, face, eyes, hair, "
    "body, portrait, full body, hands, clothes, horns, creature, text, watermark, logo\"\n"
    "5. Do NOT include any text, signs, labels, or Japanese characters in positive — "
    "text is rendered separately by the video compositor.\n"
    "6. Describe only scene / location / atmosphere / lighting / environment.\n"
    "7. Keep the positive prompt concise (under 200 tokens).\n"
    "8. Return ONLY the JSON object. No markdown code fences. No explanation.\n\n"
    "Example output:\n"
    "{\"positive\": \"background art only, empty scene, no people, no characters, "
    "no humanoid subject, manga style background illustration, clean composition, "
    "ancient Japanese castle interior, tatami floor, shoji sliding doors, warm candlelight\", "
    "\"negative\": \"person, people, human, girl, woman, man, anime girl, character, face, eyes, "
    "hair, body, portrait, full body, hands, clothes, horns, creature, text, watermark, logo\"}"
)


def _extract_scene(description: str) -> str:
    """台本ヘッダーを除去して背景シーン説明だけを抽出する。"""
    text = re.sub(r"\s+", " ", (description or "").strip())
    text = re.sub(r"【台本】.*", "", text, flags=re.DOTALL).strip()
    text = text.replace("以下の台本を参考に、", "")
    text = re.sub(r"「(.+?)」のシーンの背景画像を生成してください。?", r"\1", text)
    return text[:500]


def translate_background_prompt(description: str) -> dict[str, str]:
    """
    日本語の背景説明をComfyUI向けのpositive/negativeプロンプトに変換する。

    Returns:
        {
            "positive": "...",
            "negative": "...",
            "model": "...",
            "original_scene": "...",
        }

    Raises:
        RuntimeError: LLM呼び出し失敗 / JSON解析失敗 / 必須フィールド欠落
    """
    model = config.COMFYUI_PROMPT_TRANSLATE_MODEL
    ollama_url = config.COMFYUI_PROMPT_TRANSLATE_OLLAMA_URL.rstrip("/")
    timeout = float(config.COMFYUI_PROMPT_TRANSLATE_TIMEOUT_SEC)

    scene = _extract_scene(description)
    if not scene:
        raise RuntimeError("ComfyUIプロンプト変換: 背景説明が空です")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Japanese background description: {scene}"},
        ],
        "stream": False,
        "format": "json",
    }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{ollama_url}/api/chat", json=payload)
        response.raise_for_status()

    data = response.json()
    content = data.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(
            f"ComfyUIプロンプト変換: LLMの応答が空です (model={model})"
        )

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"ComfyUIプロンプト変換: JSON解析失敗 — {e}\n応答: {content[:300]}"
        )

    if not isinstance(result, dict):
        raise RuntimeError(
            f"ComfyUIプロンプト変換: 応答がJSONオブジェクトではありません: {content[:300]}"
        )

    positive = str(result.get("positive", "")).strip()
    negative = str(result.get("negative", "")).strip()

    if not positive:
        raise RuntimeError(
            f"ComfyUIプロンプト変換: positive が空です (model={model})\n応答: {content[:300]}"
        )
    if not negative:
        raise RuntimeError(
            f"ComfyUIプロンプト変換: negative が空です (model={model})\n応答: {content[:300]}"
        )

    # 必須要素が欠落していた場合は先頭に補完する（LLMの省略への安全策）
    pos_lower = positive.lower()
    missing_pos = [t for t in _REQUIRED_POSITIVE if t not in pos_lower]
    if missing_pos:
        positive = ", ".join(missing_pos) + ", " + positive

    neg_terms = {t.strip().lower() for t in negative.split(",")}
    missing_neg = [t for t in _REQUIRED_NEGATIVE if t not in neg_terms]
    if missing_neg:
        negative = ", ".join(missing_neg) + ", " + negative

    return {
        "positive": positive,
        "negative": negative,
        "model": model,
        "original_scene": scene,
    }
