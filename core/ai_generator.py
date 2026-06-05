import json
import logging
import re
from google import genai
from config import GEMINI_MODEL
from core.ng_words import apply_ng_word_replacements
from core.script_prompts import build_gemini_system_prompt

_logger = logging.getLogger(__name__)

# generate_script() は通常のWeb生成では呼ばれない（通常は pregenerated_script が渡される）。
# __init__ / client は生成・画像プロンプト強化で必要なときに初期化する。
class AIGenerator:
    def __init__(self, debug=False):
        self.debug = debug
        self.client = None
        from core.secret_store import require_current_profile_id, has_secret, load_secret
        profile_id = require_current_profile_id()
        if has_secret("google_api_key", profile_id=profile_id):
            self.client = genai.Client(api_key=load_secret("google_api_key", profile_id=profile_id))

    def close(self):
        if self.client is not None and hasattr(self.client, "close"):
            self.client.close()
        self.client = None

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

        model_to_use = GEMINI_MODEL

        if self.client:
            try:
                print(f"  [AI] Google {model_to_use} で生成を開始します...", flush=True)
                response = self.client.models.generate_content(
                    model=model_to_use,
                    contents=user_prompt,
                    config={
                        'system_instruction': system_prompt,
                        'tools': [{'google_search': {}}]
                    }
                )
                if response and response.text:
                    print(f"  [AI] {model_to_use} での生成が完了しました。", flush=True)
                    return response.text
                raise Exception(f"Google AI ({model_to_use}) が空の応答を返しました。")
            except Exception as e:
                _logger.error("Google AI 台本生成に失敗しました", exc_info=True)
                raise Exception(f"Google AI エラー: {e}")

        from core.error_codes import format_error
        raise RuntimeError(format_error("E-SECRET-MISSING", "Google API キー（設定画面の「認証情報」から登録）"))

    def generate_chapter_markers(self, script_text: str) -> str:
        """ロング台本からYouTube用チャプターマーカーを生成する（1行≒3秒で推定）。"""
        if not self.client:
            return ""
        prompt = f"""以下のゆっくり動画台本から、YouTube概要欄に貼り付けるチャプターマーカーを生成してください。

【推定方法】
- セリフ行（「キャラ名(感情): テキスト」形式）1行を約3秒として累計秒数を計算する
- 背景切り替え行（「背景: 」）はカウントしない
- チャプター区切りは台本内の「チャプター一覧:」または話題の転換点を参考にする
- 1本目は必ず「00:00」から始める

【出力形式（この形式のみ・説明不要）】
00:00 イントロ
01:30 〇〇について
03:00 〇〇の真実
...

【台本】
{script_text}
"""
        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            if response and response.text:
                return apply_ng_word_replacements(response.text.strip())
        except Exception as e:
            _logger.warning("チャプターマーカー生成に失敗しました", exc_info=True)
            print(f"  [AI] チャプターマーカー生成エラー: {e}")
        return ""

    def generate_pinned_comment(self, script_text: str) -> str:
        """台本から固定コメント用テキストを生成する。"""
        if not self.client:
            return ""
        prompt = f"""以下はYouTubeゆっくり動画の台本です。
動画の内容を踏まえて、投稿者がピン留めする固定コメント文を1つ生成してください。

【要件】
- 1文目に動画内容の要約を入れる
- 2文目に視聴者が答えやすい質問を入れる
- 視聴者への問いかけを含む（例:「知ってた？」「どっち派？」「コメントで教えてね！」）
- 動画の主テーマに直結した内容
- 2〜3文以内
- 絵文字を適度に使う（過剰NG）
- チャンネル登録・いいね呼びかけは不要（説明欄にあるため）
- 固定コメント本文のみ出力。前置き・説明・引用符不要

【台本（冒頭部分）】
{script_text[:2000]}
"""
        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            if response and response.text:
                return apply_ng_word_replacements(response.text.strip())
        except Exception as e:
            _logger.warning("固定コメント生成に失敗しました", exc_info=True)
            print(f"  [AI] 固定コメント生成エラー: {e}")
        return ""

    def generate_title_variants(self, script_text: str, base_title: str, thumbnail_text: str = "") -> list[dict]:
        """サムネA/B/Cに対応したLong動画タイトル候補を3件生成する。"""
        if not self.client:
            return []
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
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            text = (response.text or "").strip() if response else ""
            if not text:
                return []
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
            _logger.warning("タイトルA/B/C生成に失敗しました", exc_info=True)
            print(f"  [AI] タイトルA/B/C生成エラー: {e}")
            return []

    def enhance_background_prompts(self, script_text, bg_prompts):
        """台本全体を渡してGeminiに背景プロンプトをインパクト重視で書き直させる。"""
        import re
        if not self.client or not bg_prompts:
            return bg_prompts
        script_text = apply_ng_word_replacements(script_text)
        bg_prompts = [apply_ng_word_replacements(p) for p in bg_prompts]

        prompts_numbered = "\n".join(f"{i+1}. {p}" for i, p in enumerate(bg_prompts))
        request = f"""以下はゆっくり動画の台本です。台本のストーリー・感情・流れを完全に理解したうえで、各シーンの背景画像プロンプトをNano Banana（Gemini画像生成AI）用に最大限インパクトのある内容に書き直してください。

【台本】
{script_text}

【書き直す背景プロンプト（番号順）】
{prompts_numbered}

【書き直しの要件】
- 台本のそのシーンの感情・緊張感・雰囲気を最大限に視覚化する
- 【画像生成ルール】を厳守: 人物禁止・上下左右30%セーフゾーン・テキスト10文字以内
- キャッチコピーは「」で囲んで上部中央に配置するよう明記する
- 特定クリエイター名は含めない
- 日本語で記述する

出力形式（番号＋プロンプトのみ、説明・前置き不要）:
1. （書き直したプロンプト）
2. （書き直したプロンプト）
...
"""
        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=request
            )
            if not response or not response.text:
                return bg_prompts

            enhanced = []
            for line in response.text.strip().split("\n"):
                line = line.strip()
                cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
                if cleaned:
                    enhanced.append(apply_ng_word_replacements(cleaned))

            if len(enhanced) == len(bg_prompts):
                return enhanced
            _logger.warning("背景プロンプト強化の件数が一致しません: enhanced=%s original=%s", len(enhanced), len(bg_prompts))
            print(f"  [AI] プロンプト強化: 件数不一致 ({len(enhanced)} vs {len(bg_prompts)})、元のプロンプトを使用")
            return bg_prompts
        except Exception as e:
            _logger.warning("背景プロンプト強化に失敗しました", exc_info=True)
            print(f"  [AI] プロンプト強化エラー: {e}")
            return bg_prompts
