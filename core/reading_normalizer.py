"""
VOICEVOXの誤読を防ぐため、Ollamaでよみがなを生成してからTTSに渡す。
字幕には元テキストをそのまま使用する。
"""
import json
import re
import requests
import config as _cfg

_PROMPT_HEADER = (
    "以下のVOICEVOX音声合成用セリフ一覧を変換してください。\n"
    "誤読しやすい漢字・固有名詞・専門用語・数字表現はひらがなに変換し、"
    "読みが自然な一般的な漢字はそのまま残してください。\n"
    "句読点（。！？、）・文体・語調は変えないでください。\n"
    "JSON形式のみで返答してください: {\"1\": \"変換後\", \"2\": \"変換後\", ...}\n\n"
)


class ReadingNormalizer:
    def __init__(self):
        self._cache: dict[str, str] = {}
        self._available = False
        if not _cfg.VOICE_READING_NORMALIZE_ENABLED:
            return
        try:
            res = requests.get(f"{_cfg.VOICE_READING_NORMALIZE_OLLAMA_URL}/api/tags", timeout=_cfg.READING_NORMALIZE_CHECK_TIMEOUT_SEC)
            self._available = res.status_code == 200
        except Exception:
            pass

    def normalize_batch(self, texts: list[str]) -> dict[str, str]:
        """複数テキストを一括でよみがな正規化する。失敗時は元テキストにフォールバック。"""
        if not self._available:
            return {t: t for t in texts}

        uncached = [t for t in texts if t not in self._cache]
        if not uncached:
            return {t: self._cache.get(t, t) for t in texts}

        numbered = "\n".join(f"{i + 1}: {t}" for i, t in enumerate(uncached))
        prompt = _PROMPT_HEADER + numbered

        try:
            res = requests.post(
                f"{_cfg.VOICE_READING_NORMALIZE_OLLAMA_URL}/api/chat",
                json={
                    "model": _cfg.VOICE_READING_NORMALIZE_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=_cfg.READING_NORMALIZE_CHAT_TIMEOUT_SEC,
            )
            res.raise_for_status()
            content = res.json()["message"]["content"].strip()
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                result = json.loads(m.group())
                for i, original in enumerate(uncached):
                    normalized = result.get(str(i + 1), original)
                    self._cache[original] = normalized if isinstance(normalized, str) else original
        except Exception:
            pass

        for t in uncached:
            if t not in self._cache:
                self._cache[t] = t

        return {t: self._cache.get(t, t) for t in texts}

    def load_cache(self, saved: dict[str, str]) -> None:
        self._cache.update(saved)

    def normalize(self, text: str) -> str:
        if text in self._cache:
            return self._cache[text]
        return self.normalize_batch([text]).get(text, text)

