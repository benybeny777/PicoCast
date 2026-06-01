import os
import time
from google import genai
from config import config
from config import (
    NANOBANANA_FLASH_MODEL,
    NANOBANANA_FHD_IMAGE_SIZE,
    NANOBANANA_PRO_MODEL,
    NANOBANANA_SD_IMAGE_SIZE,
    SD_SIZE_IMAGE_SCALE,
)
# IMAGE_BACKEND は実行時に config から直接参照する（monkeypatch対応）


def _translate_to_english_for_sd(description: str, debug: bool = False) -> str:
    """Ollama を使って日本語の背景描写を SD 向け英語プロンプトに翻訳する。

    失敗時は例外をそのまま伝播させる（サイレントフォールバック禁止）。
    """
    import requests

    ollama_base = config.OLLAMA_BASE_URL.rstrip("/")
    model = config.OLLAMA_TRANSLATE_MODEL

    # Ollama 疎通確認（起動済みでなければ opening_quality.ensure_ollama_server に倣い起動）
    from core.opening_quality import ensure_ollama_server
    ensure_ollama_server()

    system_instruction = (
        "You are an expert Stable Diffusion prompt engineer. "
        "Translate the following Japanese background scene description into a concise English Stable Diffusion prompt. "
        "Output ONLY the translated prompt — no explanations, no labels, no markdown. "
        "Use comma-separated descriptive keywords and short phrases optimized for Stable Diffusion. "
        "Do NOT include character names or dialogue."
    )
    prompt = f"{system_instruction}\n\nJapanese description:\n{description}\n\nEnglish SD prompt:"

    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    with requests.post(f"{ollama_base}/api/generate", json=body, timeout=60) as resp:
        resp.raise_for_status()
        translated = str(resp.json().get("response", "")).strip()

    if not translated:
        raise RuntimeError("Ollama からの翻訳結果が空でした")

    if debug:
        print(f"  [SD翻訳] {description[:40]!r} → {translated[:80]!r}")

    return translated

class ImageGenerator:
    def __init__(
        self,
        width=1920,
        height=1080,
        debug=False,
        image_style="通常",
        sd_size_mode=False,
        background_engine=None,
    ):
        self.width = width
        self.height = height
        self.debug = debug
        self.image_style = image_style
        self.sd_size_mode = sd_size_mode

        # バックエンド解決順:
        #   1. 明示的に渡された background_engine 引数を最優先
        #   2. config.IMAGE_BACKEND == "sd_webui" → sd_webui
        #   3. config.IMAGE_BACKEND == "gemini" → nanobanana 固定
        #   4. config.IMAGE_BACKEND が未対応値 → ValueError
        # ※ config.IMAGE_BACKEND は実行時参照（monkeypatch / .env 再ロード対応）
        if background_engine and background_engine.strip():
            effective_engine = background_engine.strip().lower()
        elif config.IMAGE_BACKEND == "sd_webui":
            effective_engine = "sd_webui"
        elif config.IMAGE_BACKEND == "gemini":
            effective_engine = "nanobanana"
        else:
            raise ValueError(
                f"未対応の IMAGE_BACKEND です: '{config.IMAGE_BACKEND}'。"
                f"有効な値: 'gemini', 'sd_webui'"
            )
        self.background_engine = effective_engine

        scale = max(0.1, min(1.0, float(SD_SIZE_IMAGE_SCALE or 0.5)))
        self.request_width = max(64, int(round(self.width * scale))) if sd_size_mode else self.width
        self.request_height = max(64, int(round(self.height * scale))) if sd_size_mode else self.height

        self.client = None
        if self.background_engine == "nanobanana":
            from core.secret_store import current_profile_id_or_default, has_secret, load_secret
            profile_id = current_profile_id_or_default()
            if not has_secret("google_api_key", profile_id=profile_id):
                raise RuntimeError(
                    "Google API キーが未登録です。設定画面の「認証情報」から登録してください。"
                )
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

    def _image_generation_config(self):
        from google.genai import types
        aspect_ratio = "9:16" if self.height > self.width else "16:9"
        return types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio, image_size=self.nanobanana_image_size()),
        )

    def nanobanana_image_size(self):
        return NANOBANANA_SD_IMAGE_SIZE if self.sd_size_mode else NANOBANANA_FHD_IMAGE_SIZE

    def nanobanana_request_label(self):
        return "SD" if self.sd_size_mode else "FHD"

    def nanobanana_request_summary(self):
        # SD（縮小生成）は「縮小して生成 → 最終解像度へ拡大保存」を矢印表示。
        # FHD（高画質生成）は生成＝保存なので単体表示。
        if self.sd_size_mode:
            return (
                f"Google送信設定: Nano Banana {self.request_width}x{self.request_height} (SD)"
                f" → 保存 {self.width}x{self.height} (FHD)"
            )
        return f"Google送信設定: Nano Banana {self.width}x{self.height} (FHD)"

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
            if img.size != (self.width, self.height):
                resized = img.resize((self.width, self.height), Image.LANCZOS)
                try:
                    resized.save(path)
                finally:
                    resized.close()
        return fname

    def _meta_path_for_dir(self, save_dir):
        return ""

    def _write_image_generation_meta(self, save_dir, entry):
        return None

    def _resize_image_file(self, path, size):
        from PIL import Image
        with Image.open(path) as img:
            if img.size == size:
                return
            resized = img.resize(size, Image.LANCZOS)
            try:
                resized.save(path)
            finally:
                resized.close()

    def _prepare_sd_webui_model(self) -> None:
        """SD_WEBUI_MODEL が設定されている場合、インストール確認・ダウンロード・モデル切り替えを行う。

        SD_WEBUI_MODEL が空文字のときは何もしない（Forge の現在ロード済みモデルをそのまま使う）。
        モデルが未インストールかつ AUTO_DOWNLOAD_SD_MODELS=False のときは RuntimeError を送出する。
        フォールバック禁止: 指定モデルが使用不可な場合は中止する。
        """
        model_name = config.SD_WEBUI_MODEL.strip()
        if not model_name:
            return  # SD_WEBUI_MODEL 未設定: 現在ロード済みモデルをそのまま使用

        from core.sd_model_manager import SDWebUIModelManager
        from core.sd_webui_generator import StableDiffusionWebUIGenerator

        manager = SDWebUIModelManager()

        # マニフェストから該当モデルを探す
        # マニフェスト読み込み失敗は処理を中止する（サイレントスキップ禁止）
        matched = None
        statuses = manager.get_model_status()
        for s in statuses:
            hint = s.get("api_match_hint", "").lower()
            fname_lower = s["filename"].lower()
            name_lower = model_name.lower()
            if (
                fname_lower == name_lower
                or (hint and hint in name_lower)
                or name_lower in fname_lower
            ):
                matched = s
                break

        if matched is not None and not matched["installed"]:
            # requires_auth=true のモデルは自動ダウンロード不可
            if matched.get("requires_auth"):
                raise RuntimeError(
                    f"Stable Diffusion WebUI モデル '{matched['filename']}' のダウンロードには"
                    f" HF_TOKEN が必要です。\n"
                    f"設定画面の「APIキー設定」タブで HF_TOKEN を保存し、\n"
                    f"配布元ページでライセンス同意済みか確認してください。\n"
                    f"SDモデル管理画面: /sd-models"
                )
            if config.AUTO_DOWNLOAD_SD_MODELS:
                def _progress(filename, downloaded, total):
                    if total > 0:
                        pct = downloaded * 100 // total
                        print(
                            f"  [Stable Diffusion] ダウンロード中: {filename} "
                            f"{downloaded // 1024 // 1024}MB/{total // 1024 // 1024}MB ({pct}%)"
                        )
                    else:
                        print(f"  [Stable Diffusion] ダウンロード中: {filename} {downloaded // 1024 // 1024}MB")

                print(f"  [Stable Diffusion] モデルをダウンロードします: {matched['filename']}")
                manager.download_model(matched["id"], progress_callback=_progress)
                # ダウンロード後に Stable Diffusion WebUI へ再スキャンを依頼
                with StableDiffusionWebUIGenerator() as _gen:
                    _gen.rescan_models()
            else:
                raise RuntimeError(
                    f"Stable Diffusion WebUI モデル '{matched['filename']}' が未導入です。\n"
                    f"SDモデル管理画面 (/sd-models) からダウンロードしてください。\n"
                    f"または AUTO_DOWNLOAD_SD_MODELS=1 を設定すると生成前に自動ダウンロードします。"
                )

        # モデル切り替え（SD WebUI API 経由）
        with StableDiffusionWebUIGenerator() as gen:
            gen.set_active_model(model_name)

    def _generate_background_sd_webui(self, description, save_dir, fname, *, is_thumbnail=False):
        """Stable Diffusion WebUI Forge / AUTOMATIC1111互換API で背景画像を生成する。"""
        from core.sd_webui_generator import (
            StableDiffusionWebUIGenerator,
            _BG_PROMPT_SUFFIX,
            _THUMB_PROMPT_SUFFIX,
        )

        if not fname:
            existing_nums = []
            for f in os.listdir(save_dir):
                if f.lower().endswith(".png") and f.lower().startswith("bg_"):
                    try:
                        existing_nums.append(int(f[3:6]))
                    except ValueError:
                        pass
            next_num = max(existing_nums, default=0) + 1
            fname = f"bg_{next_num:03d}_001.png"
        output_path = os.path.join(save_dir, fname)

        # SD_WEBUI_MODEL 設定時: インストール確認 → 必要に応じてダウンロード → モデル切り替え
        self._prepare_sd_webui_model()

        # Shorts の場合は縦長サイズに切り替え
        is_shorts = self.height > self.width
        if is_shorts:
            final_width = self.height   # Shorts: 縦長のため幅・高さを入れ替え
            final_height = self.width
        else:
            final_width = self.width
            final_height = self.height

        if self.sd_size_mode:
            scale = max(0.1, min(1.0, float(SD_SIZE_IMAGE_SCALE or 0.5)))
            gen_width = max(64, int(round(final_width * scale)))
            gen_height = max(64, int(round(final_height * scale)))
        else:
            gen_width = final_width
            gen_height = final_height

        prompt_suffix = _THUMB_PROMPT_SUFFIX if is_thumbnail else _BG_PROMPT_SUFFIX

        # 日本語プロンプトを Ollama で英語に翻訳してから SD WebUI に渡す
        en_prompt = _translate_to_english_for_sd(description, debug=self.debug)

        if self.debug:
            print(
                f"  [AI] SD WebUI ({config.SD_WEBUI_BASE_URL}) "
                f"{gen_width}x{gen_height} で生成開始: {en_prompt[:60]}..."
            )

        with StableDiffusionWebUIGenerator(width=gen_width, height=gen_height) as gen:
            try:
                gen.generate_image(en_prompt, output_path, prompt_suffix=prompt_suffix)
                if self.sd_size_mode:
                    self._resize_image_file(output_path, (final_width, final_height))
            except Exception as e:
                print(f"❌ SD WebUI 背景生成に失敗しました。自動フォールバックは行いません。")
                print(f"❌ エラー詳細: {e}")
                raise

        if self.debug:
            print(f"  [AI] SD WebUI 完了: {fname}")
        return fname

    def generate_background(self, description, target_dir=None, force_nanobanana_pro=False, raw=False, reference_image_path=None, reference_image_paths=None, fname=None, is_thumbnail=False):
        if self.background_engine == "sd_webui":
            save_dir = target_dir or "output/backgrounds"
            os.makedirs(save_dir, exist_ok=True)
            # 自動フォールバック禁止。失敗時は中止する。
            return self._generate_background_sd_webui(description, save_dir, fname, is_thumbnail=is_thumbnail)
        if self.background_engine != "nanobanana":
            raise RuntimeError(f"未対応の背景生成エンジンです: {self.background_engine}")

        if not self.client:
            raise RuntimeError(
                "Google API クライアントが初期化されていません。"
                " 設定画面の「認証情報」から Google API キーを登録してください。"
            )

        save_dir = target_dir or "output/backgrounds"
        os.makedirs(save_dir, exist_ok=True)

        model_name = NANOBANANA_PRO_MODEL if (force_nanobanana_pro or "pro" in self.image_style) else NANOBANANA_FLASH_MODEL

        if self.debug:
            size_note = f" {self.nanobanana_request_label()}生成→{self.width}x{self.height}"
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
                if is_thumbnail:
                    char_instruction = (
                        "上記はキャラクターの参照画像です。"
                        "これらのキャラクターを必ずサムネイルに登場させてください。"
                        "以下の台本と参照画像をもとに、YouTubeサムネイルを生成してください。\n\n"
                    )
                else:
                    char_instruction = (
                        "上記の画像はキャラクターの立ち絵です。これらのキャラクターが自然に映えるよう、"
                        "背景・構図・色調を設計してください。\n\n"
                    )
                parts.append(types.Part.from_text(text=(char_instruction + full_prompt)))
                contents = parts
            else:
                contents = full_prompt

            response = self.client.models.generate_content(
                model=model_name,
                contents=contents,
                config=self._image_generation_config(),
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
        aspect_ratio = "9:16" if self.height > self.width else "16:9"
        image_size = self.nanobanana_image_size()
        for req in requests_list:
            prompt = self._build_full_prompt(req["description"], req.get("raw", False))
            inline_requests.append({
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "config": {
                    "response_modalities": ["IMAGE"],
                    "image_config": {"aspect_ratio": aspect_ratio, "image_size": image_size},
                },
            })
            batch_prompts.append(prompt)

        if self.debug:
            print(f"  [Batch] {len(inline_requests)}件を送信: {model_name} / Nano Banana {self.nanobanana_request_label()}")

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

        inline_requests = None
        batch_prompts = None
        batch_job = None
        return results
