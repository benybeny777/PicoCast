import json
import logging
import re

from config import config as cfg
from core import text_llm
from core.ng_words import apply_ng_word_replacements
from core.script_prompts import build_gemini_system_prompt

_logger = logging.getLogger(__name__)


class AIGenerator:
    """台本・タイトル案の文章生成。使う AI は設定 TEXT_LLM_BACKEND（core.text_llm）に従う。

    generate_script() は通常のWeb生成では呼ばれない（通常は pregenerated_script が渡される）。
    """

    def __init__(self, debug=False):
        self.debug = debug
        self.backend = text_llm.current_backend()

    def close(self):
        """互換のため残す。文章生成は呼び出しごとに接続・CLI を開いて閉じる。"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def generate_script(self, topic, reference_script=None, existing_titles=None):
        ref_rule = ""
        if reference_script:
            ref_rule = f"""
## ベース台本（最優先事項）:
以下のテキストを動画のベースとして使用してください。
---
{reference_script}
---
"""

        system_prompt = build_gemini_system_prompt(existing_titles=existing_titles)
        user_prompt = (
            f"テーマ: {topic}\n{ref_rule}\n\n"
            f"**重要: すべての「背景: 」タグの中に、必ず10文字以内の日本語キャッチコピーを「」で囲んで含めてください。文字なしの背景は絶対に出力しないでください。**"
        )
        label = text_llm.BACKEND_LABELS[self.backend]
        print(f"  [AI] {label} で台本生成を開始します...", flush=True)
        text = text_llm.generate(
            user_prompt, system=system_prompt, web_search=cfg.TEXT_LLM_WEB_SEARCH,
        )
        print(f"  [AI] {label} での台本生成が完了しました。", flush=True)
        return text

    def generate_title_variants(self, script_text: str, base_title: str, thumbnail_text: str = "") -> list[dict]:
        """サムネA/B/Cに対応したLong動画タイトル候補を3件生成する。"""
        prompt = f"""以下のYouTubeロング動画について、サムネイルA/B/Cに対応するタイトル案を3つ作ってください。

目的:
- クリック率を上げる
- ただし内容とズレる釣りタイトルは禁止
- 食べ物雑学だと一瞬で分かる
- A/B/Cで明確に切り口を変える

共通ルール:
- 日本語
- 18〜45文字
- ハッシュタグなし
- 絵文字なし
- 句読点は少なめ
- 過度な断定や不安煽りは禁止

A案:
- 食べ物どアップ・クリック重視
- 今の既定タイトルに近い自然な強さ

B案:
- 昔ヤバい型
- 歴史感・意外性重視

C案:
- 比較ギャップ型
- 昔と今、名前と実物、勘違いと真実などの差を見せる

既定タイトル:
{base_title}

サムネ文字:
{thumbnail_text}

台本:
{script_text[:3500]}

出力はJSONのみ:
{{
  "title_variants": [
    {{"variant": "A", "title": "...", "concept": "food_closeup_click"}},
    {{"variant": "B", "title": "...", "concept": "old_history_surprise"}},
    {{"variant": "C", "title": "...", "concept": "before_after_gap"}}
  ]
}}
"""
        try:
            text = text_llm.generate(prompt)
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
            data = json.loads(text)
            variants = data.get("title_variants", [])
            result = []
            for item in variants:
                variant = str(item.get("variant", "")).strip().upper()
                title = apply_ng_word_replacements(str(item.get("title", "")).strip())
                concept = str(item.get("concept", "")).strip()
                if variant in {"A", "B", "C"} and title:
                    result.append({"variant": variant, "title": title, "concept": concept})
            return result
        except Exception as e:
            # 呼び出し側（workers/main.py）は不足分を既定のタイトル案で埋めて生成を続ける既存仕様。
            _logger.warning("タイトルA/B/C生成に失敗しました: backend=%s", self.backend, exc_info=True)
            print(f"  [AI] タイトルA/B/C生成エラー: {e}")
            return []
