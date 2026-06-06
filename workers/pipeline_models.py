"""動画生成パイプラインの状態モデルと既定バリアント。"""
from __future__ import annotations

from dataclasses import dataclass

LONG_THUMBNAIL_VARIANTS = [
    {
        "variant": "A",
        "concept": "food_closeup_click",
        "text": "default thumbnail candidate",
        "prompt": (
            "Variant A: food close-up, click-focused composition. "
            "Make the food very large in the center, bright, high contrast, glossy and appetizing. "
            "The viewer should instantly understand this is food trivia."
        ),
    },
    {
        "variant": "B",
        "concept": "old_history_surprise",
        "text": "history/surprise candidate",
        "prompt": (
            "Variant B: old history and surprise composition. "
            "Use an old dining table, vintage shop, old document, or historical atmosphere. "
            "Prioritize unexpected food history and curiosity."
        ),
    },
    {
        "variant": "C",
        "concept": "before_after_gap",
        "text": "comparison/gap candidate",
        "prompt": (
            "Variant C: comparison gap composition. "
            "Split the image left and right to compare past and present. "
            "Show a clear contrast between old treatment and the modern food appearance."
        ),
    },
]


@dataclass
class GenerationReport:
    """動画生成1件分の集計結果。"""

    voices_generated: int = 0
    voices_failed: int = 0
    backgrounds_generated: int = 0
    backgrounds_failed: int = 0
    elapsed_sec: float = 0.0
    native_render_used: bool = False
    theme_dir: str = ""

    def summary(self) -> str:
        minutes, seconds = divmod(int(self.elapsed_sec), 60)
        elapsed = f"{minutes}分{seconds}秒" if minutes else f"{seconds}秒"
        return (
            f"⏱  所要時間: {elapsed}\n"
            f"🎤 音声: 生成={self.voices_generated} / 失敗={self.voices_failed}\n"
            f"🖼  背景: 生成={self.backgrounds_generated} / 失敗={self.backgrounds_failed}"
        )


def fallback_title_variants(base_title: str | None) -> list[dict[str, str]]:
    """AI生成失敗時に使うLongタイトルA/B/C案を返す。"""
    base = (base_title or "").strip() or "食べ物の意外な話"
    fallback = [
        ("A", base, "food_closeup_click"),
        ("B", f"{base}に隠れた意外な歴史", "old_history_surprise"),
        ("C", f"{base}は昔と今で何が違うのか", "before_after_gap"),
    ]
    result = []
    for variant, title, concept in fallback:
        if len(title) > 45:
            title = title[:44] + "…"
        result.append({"variant": variant, "title": title, "concept": concept})
    return result
