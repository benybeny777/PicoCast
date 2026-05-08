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
            ratio_str = f"{h}:{w}" if h > w else f"{w}:{h}"
            safe_left   = round(w * 0.20)
            safe_right  = round(w * 0.80)
            safe_top    = round(h * 0.20)
            safe_bottom = round(h * 0.50)
            full_prompt = (
                f"画像サイズ {w}x{h}px・アスペクト比{ratio_str}で生成すること。"
                f"高品質な漫画風アニメ調背景画像を生成してください。{description}。"
                f"マスターピース、精細なデジタルアート、劇的な照明、鮮烈な色彩、映画的構図。"
                f"【厳守レイアウトルール】"
                f"テキスト・文字・ロゴは必ずセーフゾーン内（左{safe_left}px〜右{safe_right}px・上{safe_top}px〜下{safe_bottom}px）に収めること。"
                f"上下左右各20%のマージン（{round(w*0.2)}px/{round(h*0.2)}px）にはテキストも重要オブジェクトも一切配置禁止。"
                f"画像下部50%（{safe_bottom}px以下）はキャラクター立ち絵と字幕のために完全に空白にすること。"
            )

            response = self.client.models.generate_content(
                model=model_name,
                contents=full_prompt,
            )

            for part in response.parts:
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    bio = io.BytesIO(part.inline_data.data)
                    img = Image.open(bio)
                    try:
                        img = img.convert("RGB")
                        if img.size != (self.width, self.height):
                            scale = max(self.width / img.width, self.height / img.height)
                            new_w = round(img.width * scale)
                            new_h = round(img.height * scale)
                            img = img.resize((new_w, new_h), Image.LANCZOS)
                            left = (new_w - self.width) // 2
                            top = (new_h - self.height) // 2
                            img = img.crop((left, top, left + self.width, top + self.height))
                        img = self._apply_bottom_gradient(img)
                        local_filename = f"bg_{uuid.uuid4().hex[:8]}.png"
                        img.save(os.path.join(save_dir, local_filename))
                    finally:
                        img.close()
                        bio.close()
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
