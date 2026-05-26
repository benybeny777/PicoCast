import re


_BANNED_WORDS = (
    "人物禁止",
    "人間なし",
    "キャラクターなし",
    "テキストなし",
    "文字なし",
    "ロゴなし",
    "看板文字なし",
    "赤丸なし",
    "矢印なし",
    "注釈なし",
)


def adapt_background_prompt_for_comfyui(text: str) -> str:
    """台本中の日本語背景文を、ローカル背景生成向けの短い指示に整える。"""
    source = re.sub(r"\s+", " ", (text or "").strip())
    source = re.sub(r"【台本】.*", "", source).strip()
    source = source.replace("以下の台本を参考に、", "")
    source = re.sub(r"「(.+?)」のシーンの背景画像を生成してください。?", r"\1", source)
    source = source[:500]
    rules = "、".join(_BANNED_WORDS)
    return (
        f"{source}. 背景のみ。{rules}。"
        "食品・場所・資料要素を中心に、動画背景として使える余白のある構図。"
    )
