"""
Stable Diffusion WebUI Forge / AUTOMATIC1111互換API クライアント。

画像生成失敗時は自動フォールバックせず、例外を上位に伝播させる。
API未起動・HTTPエラー・レスポンス異常はすべて RuntimeError として明示する。
"""
import base64
import logging
import os

import httpx

from config import config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# SD向けプロンプト品質補助サフィックス（英語固定ルール）
# ─────────────────────────────────────────────
# 背景画像用: 人物なし・16:9・漫画風を強調
_BG_PROMPT_SUFFIX = (
    ", anime style background, colorful manga illustration, clean composition, "
    "no people, no human characters, high detail, 16:9 composition"
)

# サムネイル用: 大きな余白・ドラマチック照明・YouTubeサムネイルらしさを強調
_THUMB_PROMPT_SUFFIX = (
    ", bold Japanese YouTube thumbnail style, manga illustration, dramatic lighting, "
    "high contrast, large empty space for text, 16:9 composition"
)


class StableDiffusionWebUIGenerator:
    """Stable Diffusion WebUI Forge / AUTOMATIC1111互換API経由で画像を生成する。"""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        model: str | None = None,
        sampler_name: str | None = None,
        steps: int | None = None,
        cfg_scale: float | None = None,
        width: int | None = None,
        height: int | None = None,
        negative_prompt: str | None = None,
    ):
        self.base_url = (base_url or config.SD_WEBUI_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else config.SD_WEBUI_TIMEOUT_SEC
        self.model = model if model is not None else config.SD_WEBUI_MODEL
        self.sampler_name = sampler_name or config.SD_WEBUI_SAMPLER
        self.steps = steps if steps is not None else config.SD_WEBUI_STEPS
        self.cfg_scale = cfg_scale if cfg_scale is not None else config.SD_WEBUI_CFG_SCALE
        self.width = width if width is not None else config.SD_WEBUI_WIDTH
        self.height = height if height is not None else config.SD_WEBUI_HEIGHT
        self.negative_prompt = (
            negative_prompt if negative_prompt is not None else config.SD_WEBUI_NEGATIVE_PROMPT
        )
        self._client = httpx.Client()

    def close(self) -> None:
        """httpx クライアントを明示的に閉じる。with 文を使うか、呼び出し後に必ず呼ぶこと。"""
        self._client.close()

    def __enter__(self) -> "StableDiffusionWebUIGenerator":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ─────────────────────────────────────────
    # 公開API
    # ─────────────────────────────────────────

    def _check_connection(self) -> bool:
        """疎通確認のみ。成功時 True、失敗時 False を返す（例外を外に出さない）。"""
        try:
            r = self._client.get(f"{self.base_url}/sdapi/v1/options", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def check_health(self) -> dict:
        """SD WebUI APIの疎通確認と現在ロード中のモデル名を返す。

        Returns:
            {"ok": True, "url": str, "model": str}

        Raises:
            RuntimeError: APIに接続できない、またはHTTPエラーが発生した場合。
        """
        url = f"{self.base_url}/sdapi/v1/options"
        try:
            r = self._client.get(url, timeout=10)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"SD WebUI API に接続できません ({self.base_url})。"
                f"Forge/AUTOMATIC1111 が --api オプション付きで起動していることを確認してください。"
                f"詳細: {e}"
            ) from e
        if r.status_code != 200:
            raise RuntimeError(
                f"SD WebUI API エラー (GET /sdapi/v1/options): "
                f"status={r.status_code}, body={r.text[:300]}"
            )
        data = r.json()
        return {
            "ok": True,
            "url": self.base_url,
            "model": data.get("sd_model_checkpoint", ""),
        }

    def generate_image(
        self,
        prompt: str,
        output_path: str,
        *,
        negative_prompt: str | None = None,
        width: int | None = None,
        height: int | None = None,
        steps: int | None = None,
        cfg_scale: float | None = None,
        sampler_name: str | None = None,
        seed: int = -1,
        prompt_suffix: str = "",
    ) -> str:
        """txt2img で画像を生成して PNG として保存する。保存パスを返す。

        Args:
            prompt: 生成プロンプト（英語を想定。呼び出し側で Ollama による日→英翻訳済みを渡すこと）
            output_path: 保存先ファイルパス（.png）
            negative_prompt: ネガティブプロンプト（None=設定値を使用）
            width / height: 出力解像度（None=設定値）
            steps / cfg_scale / sampler_name: 生成パラメータ（None=設定値）
            seed: シード値（-1=ランダム）
            prompt_suffix: プロンプト末尾に付加する英語品質補助文字列

        Returns:
            保存した output_path

        Raises:
            RuntimeError: API未起動・HTTPエラー・レスポンス異常のいずれか。
        """
        effective_neg = negative_prompt if negative_prompt is not None else self.negative_prompt
        effective_width = width if width is not None else self.width
        effective_height = height if height is not None else self.height
        effective_steps = steps if steps is not None else self.steps
        effective_cfg = cfg_scale if cfg_scale is not None else self.cfg_scale
        effective_sampler = sampler_name or self.sampler_name
        effective_prompt = prompt + prompt_suffix

        payload: dict = {
            "prompt": effective_prompt,
            "negative_prompt": effective_neg,
            "width": effective_width,
            "height": effective_height,
            "steps": effective_steps,
            "cfg_scale": effective_cfg,
            "sampler_name": effective_sampler,
            "seed": seed,
            "batch_size": 1,
            "n_iter": 1,
        }

        # モデル指定がある場合は override_settings で切り替え（生成後は元に戻さない）
        if self.model:
            payload["override_settings"] = {"sd_model_checkpoint": self.model}
            payload["override_settings_restore_afterwards"] = False

        url = f"{self.base_url}/sdapi/v1/txt2img"
        logger.debug(
            "SD WebUI txt2img: prompt=%s... (size=%dx%d, steps=%d, cfg=%.1f)",
            effective_prompt[:60],
            effective_width,
            effective_height,
            effective_steps,
            effective_cfg,
        )

        try:
            r = self._client.post(url, json=payload, timeout=self.timeout)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"SD WebUI API に接続できません ({self.base_url})。"
                f"Forge/AUTOMATIC1111 が --api オプション付きで起動していることを確認してください。"
                f"詳細: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise RuntimeError(
                f"SD WebUI API がタイムアウトしました ({self.timeout}秒)。"
                f"SD_WEBUI_TIMEOUT_SEC を増やすか、生成ステップ数を減らしてください。詳細: {e}"
            ) from e

        if r.status_code != 200:
            raise RuntimeError(
                f"SD WebUI txt2img エラー: status={r.status_code}, body={r.text[:400]}"
            )

        data = r.json()
        images = data.get("images")
        if not images:
            raise RuntimeError(
                "SD WebUI txt2img レスポンスに画像データがありません。"
                "APIのレスポンス構造を確認してください。"
            )

        # 出力ディレクトリを作成（なければ）
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        # 一時ファイルに書き出して成功後に rename する（失敗時にゴミファイルを残さない）
        tmp_path = output_path + ".tmp"
        try:
            img_bytes = base64.b64decode(images[0])
            with open(tmp_path, "wb") as f:
                f.write(img_bytes)
            os.replace(tmp_path, output_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

        logger.debug("SD WebUI 保存完了: %s", output_path)
        return output_path

    # ─────────────────────────────────────────
    # モデル管理API
    # ─────────────────────────────────────────

    def get_options(self) -> dict:
        """SD WebUI の現在の全オプション設定を返す。

        Returns:
            SD WebUI /sdapi/v1/options のレスポンスそのまま。

        Raises:
            RuntimeError: API未接続・HTTPエラー。
        """
        url = f"{self.base_url}/sdapi/v1/options"
        try:
            r = self._client.get(url, timeout=10)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"SD WebUI API に接続できません ({self.base_url}): {e}"
            ) from e
        if r.status_code != 200:
            raise RuntimeError(
                f"SD WebUI API エラー (GET /sdapi/v1/options): "
                f"status={r.status_code}, body={r.text[:300]}"
            )
        return r.json()

    def get_current_model(self) -> str:
        """現在ロードされているチェックポイントモデル名を返す。

        Returns:
            sd_model_checkpoint の文字列（例: "v1-5-pruned-emaonly.safetensors [...]"）

        Raises:
            RuntimeError: API未接続・HTTPエラー。
        """
        opts = self.get_options()
        return opts.get("sd_model_checkpoint", "")

    def get_models(self) -> list[dict]:
        """SD WebUI にインストールされているモデルの一覧を返す。

        Returns:
            /sdapi/v1/sd-models のリスト（各要素は title, model_name, hash, sha256, filename など）

        Raises:
            RuntimeError: API未接続・HTTPエラー。
        """
        url = f"{self.base_url}/sdapi/v1/sd-models"
        try:
            r = self._client.get(url, timeout=30)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"SD WebUI API に接続できません ({self.base_url}): {e}"
            ) from e
        if r.status_code != 200:
            raise RuntimeError(
                f"SD WebUI API エラー (GET /sdapi/v1/sd-models): "
                f"status={r.status_code}, body={r.text[:300]}"
            )
        return r.json()

    def set_active_model(self, model_name: str) -> None:
        """SD WebUI のアクティブモデルを切り替える。

        Args:
            model_name: タイトル文字列またはファイル名で指定（部分一致で解決する）。

        Raises:
            RuntimeError: モデルが見つからない・API未接続・HTTPエラー。
        """
        # インストール済みモデル一覧から一致するものを探す
        models = self.get_models()
        matched_title = _find_model_title(models, model_name)
        if matched_title is None:
            available = [m.get("title", m.get("model_name", "?")) for m in models]
            raise RuntimeError(
                f"SD WebUI に '{model_name}' が見つかりません。"
                f"rescan を実行してモデルを再検出してください。"
                f"利用可能: {available}"
            )

        url = f"{self.base_url}/sdapi/v1/options"
        payload = {"sd_model_checkpoint": matched_title}
        try:
            r = self._client.post(url, json=payload, timeout=60)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"SD WebUI API に接続できません ({self.base_url}): {e}"
            ) from e
        if r.status_code != 200:
            raise RuntimeError(
                f"SD WebUI モデル切替エラー (POST /sdapi/v1/options): "
                f"status={r.status_code}, body={r.text[:300]}"
            )
        logger.info("SD WebUI アクティブモデル切替完了: %s", matched_title)

    def rescan_models(self) -> None:
        """SD WebUI にモデル一覧の再スキャンを依頼する。

        Raises:
            RuntimeError: API未接続・HTTPエラー。
        """
        url = f"{self.base_url}/sdapi/v1/refresh-checkpoints"
        try:
            r = self._client.post(url, timeout=60)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"SD WebUI API に接続できません ({self.base_url}): {e}"
            ) from e
        if r.status_code != 200:
            raise RuntimeError(
                f"SD WebUI rescan エラー (POST /sdapi/v1/refresh-checkpoints): "
                f"status={r.status_code}, body={r.text[:300]}"
            )
        logger.info("SD WebUI モデル再スキャン完了")


# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def _find_model_title(models: list[dict], name: str) -> str | None:
    """インストール済みモデルリストから name に一致する title を探す。

    完全一致（title / model_name / filename） → 部分一致（name が title/filename に含まれる）
    の順で検索する。

    Args:
        models: /sdapi/v1/sd-models のリスト
        name: 検索対象の文字列

    Returns:
        見つかった場合は title 文字列、見つからない場合は None。
    """
    name_lower = name.lower()
    # 完全一致
    for m in models:
        if (
            m.get("title", "").lower() == name_lower
            or m.get("model_name", "").lower() == name_lower
            or os.path.basename(m.get("filename", "")).lower() == name_lower
        ):
            return m.get("title") or m.get("model_name")
    # 部分一致
    for m in models:
        title = m.get("title", "")
        filename = os.path.basename(m.get("filename", ""))
        if name_lower in title.lower() or name_lower in filename.lower():
            return title or m.get("model_name")
    return None
