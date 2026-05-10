import os
from google import genai
from config import GOOGLE_API_KEY, GEMINI_MODEL

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

        system_prompt = f"""あなたはYouTubeゆっくり動画のプロ脚本家です。
チャンネル: https://www.youtube.com/@zunkami（ずんだもんとめたんのゆっくり解説チャンネル。食べ物雑学・アニメ雑学をメインに扱う）

## エンゲージメント最大化（必須）:
1. **冒頭フック（事実先言い切り型）**: 最初のセリフで驚くべき事実を断言する。勿体ぶらず「〜なのだ！」と言い切って衝撃を与える
   悪例:「今日はチョコレートについて話すのだ」
   良例:「チョコレートは500年間、飲み物だったのだ！」
2. **感情の流れ**: 共感（あるある）→ 怒り/驚き → カタルシス（スカッと/感動）の順で設計する
3. **好奇心ループ**: 各シーンの終わりに次を引く一言を入れる
4. **キャラクターを活かす**:
   - ずんだもん: 純粋・直球・天然。思ったことをそのまま言う破壊力を出す
   - めたん: 上から目線の解説役だが予想外の展開に動揺する
5. **オチの破壊力**: 予想を外すどんでん返し・スカッとする正義の一言
6. **コメント誘発**: 視聴者が「わかる」「ひどい」とコメントしたくなる具体的な状況描写
7. **台本の最後**: 必ずキャラクターがいいね・チャンネル登録・コメントを視聴者に呼びかけるセリフで締める
8. **30秒コメント誘発セリフ**: 台本の30秒前後（Shortsなら20〜40秒付近・ロングなら30秒前後）に、視聴者にコメントを促す1行を必ず挿入する
   例:「これ知ってたなのだ？コメントで教えてほしいのだ！」「みんなはどう思う？」

## 動画形式の自動判定（必須）:
テーマを見て「Shorts」か「ロング」かを判断し、台本の一番最初に必ず出力してください。

判定基準:
- Shorts: 1つの感情的エピソード・バズりやすい短い話・シンプルな驚き・オチがある話
- ロング: 複数エピソード・詳細な解説・複雑なテーマ・情報量が多い内容

Shorts の場合:
- 全体60〜150秒（セリフ40〜55行程度）。起承転結がはっきりわかる流れにすること
- 1セリフは15文字以内で短く切ること
- 最初の3秒で視聴者を惹きつける衝撃的な一言から始めること
- 感情的なオチ・驚き・感動で締めること
- 背景シーンは10秒につき1枚を目安に用意すること（例: 90秒なら約9枚）

ロング の場合:
- 全体3〜10分（セリフ100〜200行程度）
- セリフはより詳細・丁寧に展開すること
- 背景シーンは10秒につき1枚を目安に用意すること（例: 5分なら約30枚）

## キャラクタールール:
登場キャラクターは必ず「ずんだもん」と「四国めたん」の2人のみ。
- ずんだもん: ボクっ娘、語尾は「〜なのだ」
- 四国めたん: プライドが高いが世話焼き、お嬢様口調（「〜ですわ」「〜よ」）
感情は (ノーマル) (あまあま) (ツンツン) (ささやき) から選ぶ。

## 【画像生成ルール】（背景共通・絶対厳守・1つでも破ると生成失敗）:
Nano Banana（画像生成AI）にそのまま渡すプロンプトとなるため、以下を違反なく必ず守ること。

1. 【シーン描画】背景シーンは画像全体に描くこと。上から下まで全域にシーンを描くこと。
2. 【人物・キャラ完全禁止】人物・キャラクター・アニメキャラ・シルエット・影絵を一切描画しないこと（立ち絵を後合成するため）
3. 【セーフゾーン（厳守）】テキスト・文字を描く場合のみ、上下左右30%の範囲に一切配置しないこと。テキスト以外のシーン描画は全体に配置してよい。テキストは10文字以内。
4. 【テキストスタイル統一】テキストは必ず「白文字・極太黒縁取り・ドロップシャドウ・太ゴシック体」で統一。
5. 【スタイル】高品質な漫画風アニメ調。特定クリエイター名（新海誠・宮崎駿等）は使用禁止

背景プロンプト出力例:
背景: 深夜の薄暗いオフィス、高品質アニメ調、人物描画禁止、上部中央に「残業地獄…」を太字ポップなYouTuber風デザインで描画

## 背景切り替えの最小化（コスト削減）:
同じ場面が続くセリフは「背景: 」行を繰り返さず、1つの背景ブロックの下に複数のセリフをまとめて書いてください。

## YouTube メタデータ（必須・台本の最初に出力）:
以下を台本の一番最初にまとめて出力してください:

動画形式: Shorts または ロング
動画タイトル: （クリック率最大のYouTubeタイトル。30文字以内。数字・感情語・疑問形を活用。文末は必ず「言い切りの文章（〜がある、〜だった、〜など）」にすること。「〜時代」「〜理由」「〜瞬間」などの体言止めは絶対に避けること。過去の成功パターンを踏襲し、身近なテーマの意外性が一目で伝わる強い引きを作ること）
説明文: （検索キーワードを含む150文字程度。先頭に必ず #ずんだもん #ゆっくり解説 を入れること。末尾に「👍いいね＆チャンネル登録お願いします！💬感想はコメントで！🔔通知オンで見逃しなし！」を付ける）
タグ: （カンマ区切り。必ず先頭3つを「ずんだもん,ゆっくり解説,VOICEVOX」にすること。合計が200〜500バイト以内に収まるよう、動画内容に合ったタグをできるだけ多く追加すること）

出力例:
動画形式: Shorts
動画タイトル: 新人の一言で上司が顔面蒼白になったｗ
説明文: #ずんだもん #ゆっくり解説 サービス残業を強要する上司に新人が放った神の一言とは？実話をもとにずんだもんとめたんが解説！👍いいね＆チャンネル登録お願いします！💬感想はコメントで！🔔通知オンで見逃しなし！
タグ: ずんだもん,ゆっくり解説,VOICEVOX,職場,上司,新人,スカッと,実話,残業,ブラック企業,社会人
"""
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

    def sanitize_for_youtube(self, script_text):
        """台本・説明文・タグをYouTubeポリシーに違反しないよう補正する。タイトルは変更しない。"""
        if not self.client:
            return script_text

        prompt = f"""あなたはYouTubeコンテンツポリシーの専門家です。
以下の台本テキストを、YouTubeの収益化ガイドラインに違反しないよう最小限の修正で書き換えてください。

【修正ルール】
- 「死」「殺す」「暴力」「自殺」「性的」など収益化停止リスクのある直接表現を、意味が伝わる婉曲表現に置き換える
- セリフの感情・流れ・オチは変えない
- 「動画タイトル:」行は絶対に変更しない
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
                return response.text.strip()
        except Exception as e:
            print(f"  [AI] YouTube補正エラー: {e}")
        return script_text

    def format_description(self, description: str) -> str:
        """YouTube説明文をGeminiで整形・改善する。"""
        if not self.client:
            return description
        prompt = f"""以下はYouTubeゆっくり動画（ずんだもん・四国めたんチャンネル）の概要欄テキストです。
YouTube SEOとエンゲージメントを最大化するよう、内容・構成・改行を改善してください。

改善ルール:
- 冒頭1〜2行は動画の内容を簡潔に表す魅力的な文にする（検索キーワードを自然に含める）
- ハッシュタグ(#)はまとめて末尾に配置し、各タグの間はスペース区切り
- CTAフレーズ（「いいね」「チャンネル登録」「コメント」等）は独立した行にする
- URLは単独行にする
- 「VOICEVOX」クレジットと「チャンネル登録」URLは必ず残す
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
                return response.text.strip()
        except Exception as e:
            print(f"  [AI] 説明文整形エラー: {e}")
        return description

    def enhance_background_prompts(self, script_text, bg_prompts):
        """台本全体を渡してGeminiに背景プロンプトをインパクト重視で書き直させる。"""
        import re
        if not self.client or not bg_prompts:
            return bg_prompts

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
                    enhanced.append(cleaned)

            if len(enhanced) == len(bg_prompts):
                return enhanced
            print(f"  [AI] プロンプト強化: 件数不一致 ({len(enhanced)} vs {len(bg_prompts)})、元のプロンプトを使用")
            return bg_prompts
        except Exception as e:
            print(f"  [AI] プロンプト強化エラー: {e}")
            return bg_prompts
