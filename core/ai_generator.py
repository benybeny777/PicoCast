import os
from google import genai
from config import GOOGLE_API_KEY, GEMINI_MODEL
from core.ng_words import NG_WORD_PROMPT, apply_ng_word_replacements
from core.script_prompts import build_gemini_system_prompt

class AIGenerator:
    def __init__(self, debug=False):
        self.debug = debug
        self.client = None
        if GOOGLE_API_KEY:
            self.client = genai.Client(api_key=GOOGLE_API_KEY)

    def generate_script(self, topic, reference_script=None):
        ref_rule = ""
        if reference_script:
            ref_rule = f"""
## ベース台本（最優先事項）:
以下のテキストを動画のベースとして使用してください。
---
{reference_script}
---
"""

        system_prompt = build_gemini_system_prompt()
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
                raise Exception(f"Google AI エラー: {e}")

        return "Error: Google API キーが未設定です。"

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
            print(f"  [AI] チャプターマーカー生成エラー: {e}")
        return ""

    def sanitize_for_youtube(self, script_text):
        """台本・説明文・タグをYouTubeポリシーに違反しないよう補正する。タイトルは変更しない。"""
        script_text = apply_ng_word_replacements(script_text)
        if not self.client:
            return script_text

        prompt = f"""あなたはYouTubeコンテンツポリシーの専門家です。
以下の台本テキストを、YouTubeの収益化ガイドラインに違反しないよう最小限の修正で書き換えてください。

{NG_WORD_PROMPT}

【修正ルール】
- 「死」「殺す」「暴力」「自殺」「性的」など収益化停止リスクのある直接表現を、意味が伝わる婉曲表現に置き換える
- セリフの感情・流れ・オチは変えない
- 「動画タイトル:」行も、NGワードや直接的すぎる表現があればクリック率を保ったまま言い換える
- 「タグ:」行のリスクワードも同様に置き換える
- 「説明文:」もリスク表現があれば修正する
- 問題のない行はそのまま出力する
- フォーマット（背景: / キャラ名(感情): / タグ: 等）は一切変えない
- 余計なコメントや説明は不要。修正後のテキストのみ出力する

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
            print(f"  [AI] YouTube補正エラー: {e}")
        return script_text

    def format_description(self, description: str) -> str:
        """YouTube説明文をGeminiで整形・改善する。"""
        description = apply_ng_word_replacements(description)
        if not self.client:
            return description
        prompt = f"""以下はYouTubeゆっくり動画（ずんだもん・四国めたんチャンネル）の概要欄テキストです。
YouTube SEOとエンゲージメントを最大化するよう、内容・構成・改行を改善してください。

{NG_WORD_PROMPT}

改善ルール:
- 冒頭1〜2行は動画の内容を簡潔に表す魅力的な文にする（検索キーワードを自然に含める）
- ハッシュタグ(#)はまとめて末尾に配置し、各タグの間はスペース区切り
- CTAフレーズ（「いいね」「チャンネル登録」「コメント」等）は独立した行にする
- URLは単独行にする
- 「VOICEVOX」クレジット・「使用音声」・「チャンネル登録」URLは削除する（後から自動付与される）
- 段落間は空行を1行入れる
- 整形後のテキストのみ出力。説明や前置きは不要

【説明文】
{description}
"""
        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            if response and response.text:
                return apply_ng_word_replacements(response.text.strip())
        except Exception as e:
            print(f"  [AI] 説明文整形エラー: {e}")
        return description

    def generate_pinned_comment(self, script_text: str) -> str:
        """台本から固定コメント用テキストを生成する。"""
        if not self.client:
            return ""
        prompt = f"""以下はYouTubeゆっくり動画の台本です。
動画の内容を踏まえて、投稿者がピン留めする固定コメント文を1つ生成してください。

【要件】
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
            print(f"  [AI] 固定コメント生成エラー: {e}")
        return ""

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
            print(f"  [AI] プロンプト強化: 件数不一致 ({len(enhanced)} vs {len(bg_prompts)})、元のプロンプトを使用")
            return bg_prompts
        except Exception as e:
            print(f"  [AI] プロンプト強化エラー: {e}")
            return bg_prompts
