import os
import time
from google import genai
from config import GOOGLE_API_KEY, NANOBANANA_PRO_MODEL, NANOBANANA_FLASH_MODEL, SD_SIZE_IMAGE_SCALE

class ImageGenerator:
    def __init__(self, width=1920, height=1080, debug=False, image_style="通常", sd_size_mode=False):
        self.width = width
        self.height = height
        self.debug = debug
        self.image_style = image_style
        self.sd_size_mode = sd_size_mode
        scale = max(0.1, min(1.0, float(SD_SIZE_IMAGE_SCALE or 0.5)))
        self.request_width = max(64, int(round(self.width * scale))) if sd_size_mode else self.width
        self.request_height = max(64, int(round(self.height * scale))) if sd_size_mode else self.height

        self.client = None
        if GOOGLE_API_KEY:
            try:
                self.client = genai.Client(api_key=GOOGLE_API_KEY)
            except Exception as e:
                print(f"  [Warning] Failed to initialize Google GenAI Client: {e}")

    def _build_full_prompt(self, description, raw=False):
        if raw:
            return description
        is_shorts = self.height > self.width
        if is_shorts:
            layout_rules = (
                "【絶対厳守ルール】"
                "▼アスペクト比: 縦9:16（ポートレート）で描画すること。"
                "▼シーン描画: 背景シーンは画像全体（上から下まで全域）に描くこと。"
                "▼人物禁止: 人物・キャラクター・シルエット・影絵を一切描画しない。ずんだもん・四国めたんを含むいかなるキャラクターも描画禁止。"
                "▼セーフゾーン（厳守）: 上下左右30%の範囲にはテキスト・文字・重要な要素を一切配置しないこと。テキスト以外のシーン描画はこの制限を受けない。"
                "▼テキストスタイル: 白文字・極太黒縁取り・ドロップシャドウ・太ゴシック体で統一。"
                "---"
            )
        else:
            layout_rules = (
                "【絶対厳守ルール】"
                "▼アスペクト比: 横16:9（ランドスケープ）で描画すること。"
                "▼人物禁止: 人物・キャラクター・シルエット・影絵を一切描画しない。ずんだもん・四国めたんを含むいかなるキャラクターも描画禁止。"
                "▼セーフゾーン（厳守）: 上下左右30%の範囲にはテキスト・文字・重要な要素を一切配置しないこと。テキスト以外のシーン描画はこの制限を受けない。"
                "▼右半分に空間: キャラクター立ち絵配置のため右側50〜90%エリアに重要な描写を密集させないこと。"
                "---"
            )
        return (
            f"{layout_rules}"
            f"高品質な漫画風イラスト調背景画像。"
            f"{description}。"
            f"マスターピース、精細なデジタルアート、劇的な照明、鮮烈な色彩、映画的構図。"
        )

    def _save_prompt_log(self, save_dir, fname, prompt):
        log_path = os.path.join(save_dir, "image_prompts.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"=== {fname} ===\n{prompt}\n\n")

    def _save_image_part(self, part, save_dir, fname=None):
        """inline_data part を PNG として保存・リサイズし、ファイル名を返す。"""
        from PIL import Image
        if fname is None:
            existing_nums = []
            for f in os.listdir(save_dir):
                if f.lower().endswith(".png") and f.lower().startswith("bg_"):
                    try:
                        existing_nums.append(int(f[3:6]))
                    except ValueError:
                        pass
            next_num = max(existing_nums, default=0) + 1
            fname = f"bg_{next_num:03d}_001.png"
        path = os.path.join(save_dir, fname)
        with open(path, "wb") as f:
            f.write(part.inline_data.data)
        with Image.open(path) as img:
            if self.sd_size_mode:
                small = img.resize((self.request_width, self.request_height), Image.LANCZOS)
                resized = small.resize((self.width, self.height), Image.LANCZOS)
                try:
                    resized.save(path)
                finally:
                    small.close()
                    resized.close()
            elif img.size != (self.width, self.height):
                resized = img.resize((self.width, self.height), Image.LANCZOS)
                try:
                    resized.save(path)
                finally:
                    resized.close()
        return fname

    def generate_background(self, description, target_dir=None, force_nanobanana_pro=False, raw=False, reference_image_path=None, reference_image_paths=None, fname=None):
        if not self.client:
            print("  [Error] Google API キーが未設定です")
            return None

        save_dir = target_dir or "output/backgrounds"
        os.makedirs(save_dir, exist_ok=True)

        model_name = NANOBANANA_PRO_MODEL if (force_nanobanana_pro or "pro" in self.image_style) else NANOBANANA_FLASH_MODEL

        if self.debug:
            size_note = f" SDサイズ生成({self.request_width}x{self.request_height}→{self.width}x{self.height})" if self.sd_size_mode else f" {self.width}x{self.height}"
            print(f"  [AI] Google {model_name} (Nano Banana){size_note} で描画を開始します: {description[:40]}...")

        try:
            full_prompt = self._build_full_prompt(description, raw)

            # 複数リファレンス画像の統合
            all_refs = list(reference_image_paths or [])
            if reference_image_path:
                all_refs = [reference_image_path] + all_refs
            all_refs = [p for p in all_refs if p and os.path.exists(p)]

            response = None
            parts = None
            if all_refs:
                from google.genai import types
                parts = []
                for ref_path in all_refs:
                    with open(ref_path, "rb") as f:
                        parts.append(types.Part.from_bytes(data=f.read(), mime_type="image/png"))
                parts.append(types.Part.from_text(text=(
                    "上記の画像はキャラクターの立ち絵です。これらのキャラクターが自然に映えるよう、"
                    "背景・構図・色調を設計してください。\n\n"
                    + full_prompt
                )))
                contents = parts
            else:
                contents = full_prompt

            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
            )

            for part in response.parts:
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    generated_name = self._save_image_part(part, save_dir, fname=fname)
                    if self.debug:
                        print(f"  [AI] Nano Banana 完了: {generated_name} ({self.width}x{self.height})")
                        self._save_prompt_log(save_dir, generated_name, full_prompt)
                    return generated_name

            raise Exception("No image part found in response.")

        except Exception as e:
            print(f"  [AI] Nano Banana エラー: {e}")
            raise Exception(f"Nano Banana ({model_name}) が失敗しました: {e}")
        finally:
            response = None
            parts = None

    def generate_backgrounds_batch(self, requests_list, target_dir=None, fnames=None):
        """Google Batch API で複数背景を一括生成する。
        requests_list: [{"description": str, "raw": bool}, ...]
        戻り値: 同順のファイル名リスト（失敗は None）
        注意: スタイル参照（1枚目を基準にする機能）はバッチモードでは無効。
        """
        if not self.client:
            raise Exception("Google API キーが未設定です")

        save_dir = target_dir or "output/backgrounds"
        os.makedirs(save_dir, exist_ok=True)

        model_name = NANOBANANA_PRO_MODEL if "pro" in self.image_style else NANOBANANA_FLASH_MODEL

        # inline リクエストを組み立て
        inline_requests = []
        batch_prompts = []
        batch_job = None
        for req in requests_list:
            prompt = self._build_full_prompt(req["description"], req.get("raw", False))
            inline_requests.append({
                "contents": [{"role": "user", "parts": [{"text": prompt}]}]
            })
            batch_prompts.append(prompt)

        if self.debug:
            print(f"  [Batch] {len(inline_requests)}件を送信: {model_name}")

        batch_job = self.client.batches.create(model=model_name, src=inline_requests)
        if self.debug:
            print(f"  [Batch] ジョブ名: {batch_job.name}  初期状態: {batch_job.state}")

        # 完了までポーリング（30秒間隔）
        terminal = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED"}
        while str(batch_job.state) not in terminal:
            time.sleep(30)
            batch_job = self.client.batches.get(name=batch_job.name)
            if self.debug:
                print(f"  [Batch] 状態: {batch_job.state}")

        if str(batch_job.state) != "JOB_STATE_SUCCEEDED":
            raise Exception(f"Batch APIジョブ失敗: {batch_job.state}")

        # 結果を保存
        results = [None] * len(requests_list)
        for i, result in enumerate(self.client.batches.list_job_results(name=batch_job.name)):
            if i >= len(results):
                break
            try:
                # response が GenerateContentResponse 相当
                response = result.response
                parts = getattr(response, 'parts', None)
                if parts is None and hasattr(response, 'candidates') and response.candidates:
                    parts = response.candidates[0].content.parts
                for part in (parts or []):
                    if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                        target_fname = fnames[i] if fnames and i < len(fnames) else None
                        fname = self._save_image_part(part, save_dir, fname=target_fname)
                        results[i] = fname
                        if self.debug:
                            print(f"  [Batch] 結果[{i+1}]: {fname}")
                            self._save_prompt_log(save_dir, fname, batch_prompts[i])
                        break
            except Exception as e:
                if self.debug:
                    print(f"  [Batch] 結果[{i}]処理エラー: {e}")

        return results
