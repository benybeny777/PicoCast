import os
import logging
import re
from google import genai
from config import config
from config import (
    NANOBANANA_FLASH_MODEL,
    NANOBANANA_PRO_MODEL,
)
# IMAGE_BACKEND は実行時に config から直接参照する（monkeypatch対応）

_logger = logging.getLogger(__name__)


class ImageGenerationError(Exception):
    """画像生成APIの失敗。HTTPステータスとカテゴリを保持する（自動フォールバックはしない）。

    category:
      "auth"     … 401/403 認証・権限
      "quota"    … 429 レート制限・クォータ
      "api_busy" … 503 API混雑（後で再実行推奨。台本/プロンプトの問題ではない）
      "generic"  … その他
    """

    def __init__(self, message, *, category="generic", status_code=None, model=None, backend=None):
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.model = model
        self.backend = backend

    @property
    def code(self) -> str:
        """中央カタログのエラーコード（E-IMG-BUSY など）。"""
        from core.error_codes import image_error_code
        return image_error_code(self.category)

    @property
    def retry_recommended(self) -> bool:
        # 混雑(503)・レート制限(429)は時間を置いた再実行で回復する見込みがある
        return self.category in ("api_busy", "quota")


def classify_image_api_error(exc: Exception) -> tuple[str, int | None]:
    """画像生成APIの例外から (category, http_status) を判定する。"""
    status = getattr(exc, "code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        m = re.search(r"\b(400|401|403|404|429|500|503)\b", str(exc))
        status = int(m.group(1)) if m else None
    if status in (401, 403):
        return "auth", status
    if status == 429:
        return "quota", status
    if status == 503:
        return "api_busy", status
    return "generic", status


def _translate_to_english_for_sd(description: str, debug: bool = False) -> str:
    """Ollama を使って日本語の背景描写を Stable Diffusion WebUI 向け英語プロンプトに翻訳する。

    Stable Diffusion WebUI バックエンドでは Ollama を必須とする。接続不可・
    タイムアウト時は対処手順つきの E-OLLAMA-DOWN を送出する（サイレントフォールバック禁止）。
    """
    import requests
    from core.error_codes import AppError

    ollama_base = config.OLLAMA_BASE_URL.rstrip("/")
    model = config.OLLAMA_TRANSLATE_MODEL

    # Ollama 疎通確認（起動済みでなければ opening_quality.ensure_ollama_server に倣い起動）。
    # Stable Diffusion WebUI 画像生成では英訳に Ollama が必須なので、起動できなければ明確に止める。
    from core.opening_quality import ensure_ollama_server
    try:
        ensure_ollama_server()
    except Exception as e:
        _logger.error("Ollamaサーバーの起動確認に失敗しました", exc_info=True)
        raise AppError("E-OLLAMA-DOWN", detail="Stable Diffusion WebUI 画像の英語プロンプト変換に必要です", cause=e)

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
    try:
        with requests.post(f"{ollama_base}/api/generate", json=body, timeout=60) as resp:
            resp.raise_for_status()
            translated = str(resp.json().get("response", "")).strip()
    except (requests.ConnectionError, requests.Timeout) as e:
        _logger.error("Ollamaプロンプト翻訳APIへ接続できません", exc_info=True)
        raise AppError("E-OLLAMA-DOWN", detail="Stable Diffusion WebUI 画像の英語プロンプト変換に必要です", cause=e)

    if not translated:
        raise RuntimeError("Ollama からの翻訳結果が空でした")

    if debug:
        print(f"  [プロンプト英訳] {description[:40]!r} → {translated[:80]!r}")

    return translated

class ImageGenerator:
    def __init__(
        self,
        width=1920,
        height=1080,
        debug=False,
        image_style="通常",
        background_engine=None,
    ):
        self.width = width
        self.height = height
        self.debug = debug
        self.image_style = image_style

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

        self.client = None
        if self.background_engine == "nanobanana":
            from core.secret_store import current_profile_id_or_default, has_secret, load_secret
            profile_id = current_profile_id_or_default()
            if not has_secret("google_api_key", profile_id=profile_id):
                from core.error_codes import format_error
                raise RuntimeError(format_error("E-SECRET-MISSING", "Google API キー（設定画面の「認証情報」から登録）"))
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
        # image_size は送らない（API 既定サイズで生成し、保存時に最終解像度へリサイズする）。
        return types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        )

    def nanobanana_request_summary(self):
        return f"Google送信設定: Nano Banana {self.width}x{self.height}"

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
                        _logger.warning("背景画像ファイル名の番号解析に失敗しました: file=%s", f, exc_info=True)
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

    def _prepare_sd_webui_model(self) -> None:
        """SD_WEBUI_MODEL が設定されている場合、インストール確認・ダウンロード・モデル切り替えを行う。

        SD_WEBUI_MODEL が空文字のときは何もしない（Stable Diffusion WebUI の現在ロード済みモデルをそのまま使う）。
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

        # モデル切り替え（Stable Diffusion WebUI API 経由）
        with StableDiffusionWebUIGenerator() as gen:
            gen.set_active_model(model_name)

    def _generate_background_sd_webui(self, description, save_dir, fname, *, is_thumbnail=False):
        """Stable Diffusion WebUI / AUTOMATIC1111互換API で背景画像を生成する。"""
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
                        _logger.warning("背景画像ファイル名の番号解析に失敗しました: file=%s", f, exc_info=True)
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

        gen_width = final_width
        gen_height = final_height

        prompt_suffix = _THUMB_PROMPT_SUFFIX if is_thumbnail else _BG_PROMPT_SUFFIX

        # 日本語プロンプトを Ollama で英語に翻訳してから Stable Diffusion WebUI に渡す
        en_prompt = _translate_to_english_for_sd(description, debug=self.debug)

        if self.debug:
            print(
                f"  [AI] Stable Diffusion WebUI ({config.SD_WEBUI_BASE_URL}) "
                f"{gen_width}x{gen_height} で生成開始: {en_prompt[:60]}..."
            )

        with StableDiffusionWebUIGenerator(width=gen_width, height=gen_height) as gen:
            try:
                gen.generate_image(en_prompt, output_path, prompt_suffix=prompt_suffix)
            except ImageGenerationError:
                raise  # 既に分類済み
            except Exception as e:
                # 自動フォールバック禁止。HTTPステータスで分類してコード付き例外にする。
                category, status = classify_image_api_error(e)
                _logger.error(
                    "Stable Diffusion WebUI 背景生成に失敗しました: category=%s status=%s",
                    category,
                    status,
                    exc_info=True,
                )
                print(f"❌ Stable Diffusion WebUI 背景生成に失敗しました（category={category} / status={status}）。自動フォールバックは行いません。")
                print(f"❌ エラー詳細: {e}")
                raise ImageGenerationError(
                    f"Stable Diffusion WebUI が失敗しました: {e}",
                    category=category, status_code=status, model="sd_webui", backend="sd_webui",
                ) from e

        if self.debug:
            print(f"  [AI] Stable Diffusion WebUI 完了: {fname}")
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
            print(f"  [AI] Google {model_name} (Nano Banana) {self.width}x{self.height} で描画を開始します: {description[:40]}...")

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

        except ImageGenerationError:
            raise  # 既に分類済み（二重ラップしない）
        except Exception as e:
            category, status = classify_image_api_error(e)
            _logger.error(
                "Nano Banana 背景生成に失敗しました: category=%s status=%s model=%s",
                category,
                status,
                model_name,
                exc_info=True,
            )
            print(f"  [AI] Nano Banana エラー(category={category} / status={status}): {e}")
            # 自動フォールバック禁止: 別モデル・別バックエンド・ローカル生成へ切り替えない。
            raise ImageGenerationError(
                f"Nano Banana ({model_name}) が失敗しました: {e}",
                category=category, status_code=status, model=model_name, backend="nanobanana",
            ) from e
        finally:
            response = None
            parts = None
