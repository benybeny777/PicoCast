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

    def generate_background(self, description, target_dir=None, force_nanobanana_pro=False, raw=False, reference_image_path=None):
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

            if raw:
                full_prompt = description
            else:
                is_shorts = self.height > self.width
                if is_shorts:
                    layout_rules = (
                        f"【絶対厳守ルール】"
                        f"▼アスペクト比: 縦9:16（ポートレート）で描画すること。"
                        f"▼シーン描画: 背景シーンは画像全体（上から下まで全域）に描くこと。"
                        f"▼人物禁止: 人物・キャラクター・アニメキャラ・シルエットを一切描画しない。"
                        f"▼テキスト配置のみ制限: テキスト・文字・ロゴを描く場合は上部中央（上から20〜35%の範囲・左右20%マージン確保）のみ。テキスト以外のシーン描画はこの制限を受けない。"
                        f"▼テキストスタイル: 白文字・極太黒縁取り・ドロップシャドウ・太ゴシック体で統一。"
                        f"---"
                    )
                else:
                    layout_rules = (
                        f"【絶対厳守ルール】"
                        f"▼アスペクト比: 横16:9（ランドスケープ）で描画すること。"
                        f"▼人物禁止: 人物・キャラクター・アニメキャラ・シルエットを一切描画しない。"
                        f"▼安全領域: テキスト・ロゴ・重要な要素は外周10%を空けた内側に配置すること。"
                        f"▼右半分に空間: キャラクター立ち絵配置のため右側50〜90%エリアに重要な描写を密集させないこと。"
                        f"---"
                    )
                full_prompt = (
                    f"{layout_rules}"
                    f"高品質な漫画風アニメ調背景画像。"
                    f"{description}。"
                    f"マスターピース、精細なデジタルアート、劇的な照明、鮮烈な色彩、映画的構図。"
                )

            if reference_image_path and os.path.exists(reference_image_path):
                from google.genai import types
                with open(reference_image_path, "rb") as f:
                    image_bytes = f.read()
                contents = [
                    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    types.Part.from_text(text=(
                        "この画像のアートスタイル・色調・世界観を完全に踏襲してください。"
                        "同じ画風・同じ色彩設計・同じレンダリングスタイルで、新しいシーンを描いてください。\n\n"
                        + full_prompt
                    )),
                ]
            else:
                contents = full_prompt

            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
            )

            for part in response.parts:
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    local_filename = f"bg_{uuid.uuid4().hex[:8]}.png"
                    saved_path = os.path.join(save_dir, local_filename)
                    with open(saved_path, "wb") as out:
                        out.write(part.inline_data.data)
                    # リサイズして正しいアスペクト比解像度に揃える
                    with Image.open(saved_path) as img:
                        if img.size != (self.width, self.height):
                            img = img.resize((self.width, self.height), Image.LANCZOS)
                            img.save(saved_path)
                    if self.debug:
                        print(f"  [AI] Nano Banana 完了: {local_filename} ({self.width}x{self.height})")
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
