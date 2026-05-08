import os
import uuid
from google import genai
from config import GOOGLE_API_KEY, NANOBANANA_PRO_MODEL, NANOBANANA_FLASH_MODEL

class ImageGenerator:
    def __init__(self, width=1920, height=1080, debug=False, image_style="通常"):
        self.width = width
        self.height = height
        self.debug = debug
        self.image_style = image_style

        self.client = None
        if GOOGLE_API_KEY:
            try:
                self.client = genai.Client(api_key=GOOGLE_API_KEY)
            except Exception as e:
                print(f"  [Warning] Failed to initialize Google GenAI Client: {e}")

    def generate_background(self, description, target_dir=None, force_nanobanana_pro=False):
        if not self.client:
            print("  [Error] Google API キーが未設定です")
            return None

        save_dir = target_dir or "output/backgrounds"
        os.makedirs(save_dir, exist_ok=True)

        model_name = NANOBANANA_PRO_MODEL if (force_nanobanana_pro or "pro" in self.image_style) else NANOBANANA_FLASH_MODEL

        if self.debug:
            print(f"  [AI] Google {model_name} (Nano Banana) で描画を開始します: {description[:40]}...")

        try:
            from PIL import Image
            import io

            w, h = self.width, self.height
            ratio_str = f"{w}:{h}"
            safe_left   = round(w * 0.20)
            safe_right  = round(w * 0.80)
            safe_top    = round(h * 0.20)
            safe_bottom = round(h * 0.50)
            is_shorts = h > w
            if is_shorts:
                layout_rules = (
                    f"【絶対厳守ルール】"
                    f"▼シーン描画: 背景シーンは画像全体（{w}x{h}px）に描画すること。上から下まで全域にシーンを描くこと。"
                    f"▼人物禁止: 人物・キャラクター・アニメキャラ・シルエットを一切描画しない。"
                    f"▼テキスト配置のみ制限: テキスト・文字・ロゴを描く場合は必ず上部中央（y={safe_top}px〜{round(h*0.35)}px・x={safe_left}px〜{safe_right}px）のみ。テキスト以外のシーン描画はこの制限を受けない。"
                    f"▼テキストスタイル: 白文字・極太黒縁取り・ドロップシャドウ・太ゴシック体で統一。"
                    f"---"
                )
            else:
                layout_rules = (
                    f"人物・キャラクター・アニメキャラを一切描画しないこと。---"
                )
            full_prompt = (
                f"{layout_rules}"
                f"画像サイズ {w}x{h}px・アスペクト比{ratio_str}。高品質な漫画風アニメ調背景画像。"
                f"{description}。"
                f"マスターピース、精細なデジタルアート、劇的な照明、鮮烈な色彩、映画的構図。"
            )

            response = self.client.models.generate_content(
                model=model_name,
                contents=full_prompt,
            )

            for part in response.parts:
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    local_filename = f"bg_{uuid.uuid4().hex[:8]}.png"
                    with open(os.path.join(save_dir, local_filename), "wb") as out:
                        out.write(part.inline_data.data)
                    if self.debug:
                        print(f"  [AI] Nano Banana 完了: {local_filename}")
                    return local_filename

            raise Exception("No image part found in response.")

        except Exception as e:
            print(f"  [AI] Nano Banana エラー: {e}")
            raise Exception(f"Nano Banana ({model_name}) が失敗しました: {e}")

    def _apply_bottom_gradient(self, img):
        """キャラクター立ち絵エリア確保のため下部をグラデーションで暗くする。"""
        from PIL import Image, ImageDraw
        fade_start_ratio = 0.50 if self.height > self.width else 0.60
        start_y = int(self.height * fade_start_ratio)
        overlay = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(start_y, self.height):
            progress = (y - start_y) / (self.height - start_y)
            alpha = int(210 * progress)
            draw.line([(0, y), (self.width, y)], fill=(0, 0, 0, alpha))
        result = Image.alpha_composite(img.convert('RGBA'), overlay)
        return result.convert('RGB')
