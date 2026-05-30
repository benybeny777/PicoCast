"""
サービス確認・ダッシュボード状態取得サービス。
秘密値（APIキー本体・トークン内容）は一切返さない。
"""
import os
import subprocess
import shutil
from datetime import datetime, timezone
from typing import Any

import httpx

from config import config
from core.output_paths import get_output_videos_dir, get_analytics_dir

# 起動時にウォームアップし、以降はキャッシュを返す
_settings_status_cache: dict | None = None


def check_voicevox() -> dict[str, Any]:
    try:
        r = httpx.get(f"{config.VOICEVOX_URL}/version", timeout=config.WEB_VOICEVOX_CHECK_TIMEOUT_SEC)
        return {"ok": True, "version": r.text.strip('"')}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_ollama() -> dict[str, Any]:
    try:
        base = config.OLLAMA_BASE_URL.rstrip("/")
        r = httpx.get(f"{base}/api/tags", timeout=config.WEB_VOICEVOX_CHECK_TIMEOUT_SEC)
        if r.status_code == 200:
            models = r.json().get("models", [])
            return {"ok": True, "model_count": len(models)}
        else:
            return {"ok": False, "error": f"Status code: {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_sd_webui() -> dict[str, Any]:
    """Stable Diffusion WebUI Forge / AUTOMATIC1111互換API の疎通確認とモデル情報を返す。"""
    try:
        from core.sd_webui_generator import StableDiffusionWebUIGenerator
        gen = StableDiffusionWebUIGenerator()
        result = gen.check_health()
        # マニフェスト内モデルの導入状況を追加（SD_WEBUI_ROOT 設定時のみ）
        if config.SD_WEBUI_ROOT:
            try:
                from core.sd_model_manager import SDWebUIModelManager
                manager = SDWebUIModelManager()
                statuses = manager.get_model_status()
                result["manifest_total"] = len(statuses)
                result["manifest_installed"] = sum(1 for s in statuses if s["installed"])
            except Exception:
                pass  # フォールバック許可: マニフェスト情報は補助的。取得失敗しても疎通確認結果は返す
        return result
    except Exception as e:
        return {"ok": False, "url": config.SD_WEBUI_BASE_URL, "error": str(e)}


def check_ffmpeg() -> dict[str, Any]:
    bin_path = shutil.which(config.FFMPEG_BIN) or config.FFMPEG_BIN
    try:
        result = subprocess.run(
            [bin_path, "-version"],
            capture_output=True, text=True, timeout=config.WEB_FFMPEG_CHECK_TIMEOUT_SEC
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        ver_short = first_line.split(" Copyright")[0].strip() if " Copyright" in first_line else first_line
        if ver_short.startswith("ffmpeg version "):
            ver_short = ver_short[len("ffmpeg version "):]
        ver_short = ver_short.split("-")[0].strip()

        # 現在の設定エンコーダー
        configured_encoder = str(getattr(config, "NATIVE_FFMPEG_ENCODER", "") or "libx264").strip()

        # GPUエンコーダーのサポート状況チェック
        gpu_supported = False
        try:
            encoders_result = subprocess.run(
                [bin_path, "-encoders"],
                capture_output=True, text=True, timeout=config.WEB_FFMPEG_CHECK_TIMEOUT_SEC
            )
            if encoders_result.returncode == 0:
                encoders_stdout = encoders_result.stdout
                if configured_encoder in encoders_stdout:
                    gpu_supported = True
        except Exception as _e:
            raise RuntimeError(f"Error: {_e}") from _e

        # 動作環境の判定
        if configured_encoder == "libx264":
            running_mode = "CPU (libx264)"
        elif gpu_supported:
            running_mode = f"GPU ({configured_encoder})"
        else:
            running_mode = f"CPU (libx264) ※設定値 {configured_encoder} は未サポートのためフォールバック"

        return {
            "ok": result.returncode == 0,
            "version": ver_short,
            "gpu": running_mode
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def refresh_settings_status() -> dict[str, Any]:
    """サービスチェックを実行してキャッシュを更新して返す。"""
    global _settings_status_cache
    _settings_status_cache = get_settings_status()
    return _settings_status_cache


def get_cached_settings_status() -> dict[str, Any]:
    """キャッシュがあればそれを返す。なければ refresh_settings_status() を呼ぶ。"""
    if _settings_status_cache is not None:
        return _settings_status_cache
    return refresh_settings_status()


def get_settings_status() -> dict[str, Any]:
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_vv     = ex.submit(check_voicevox)
        f_ffmpeg = ex.submit(check_ffmpeg)
        f_ollama = ex.submit(check_ollama)
        f_sd     = ex.submit(check_sd_webui)
        voicevox_result = f_vv.result()
        ffmpeg_result   = f_ffmpeg.result()
        ollama_result   = f_ollama.result()
        sd_webui_result = f_sd.result()

    # 認証情報の登録状態は DB を正本とする（値は返さない）
    from core.secret_store import list_secret_status
    secret_status = list_secret_status()

    return {
        "voicevox": voicevox_result,
        "ffmpeg": ffmpeg_result,
        "ollama": ollama_result,
        "sd_webui": sd_webui_result,
        "image_backend": config.IMAGE_BACKEND,                          # 現在のバックエンド種別
        "google_api_key": secret_status["google_api_key"],              # DB登録状態のみ
        "openai_api_key": secret_status["openai_api_key"],              # DB登録状態のみ
        "hf_token": secret_status["hf_token"],                         # DB登録状態のみ
        "youtube_client_secrets": secret_status["youtube_client_secrets"],
        "youtube_upload_token": secret_status["youtube_upload_token"],
        "youtube_analytics_token": secret_status["youtube_analytics_token"],
        # 旧ファイルの残存状態（参考表示用）
        "legacy_client_secrets_json": os.path.isfile(os.path.join(root, "client_secrets.json")),
        "legacy_token_json": os.path.isfile(os.path.join(root, "token.json")),
        "legacy_token_analytics_json": os.path.isfile(os.path.join(root, "token_analytics.json")),
        "output_dir": get_output_videos_dir(),
        "output_dir_exists": os.path.isdir(get_output_videos_dir()),
        "render_engine": "native",
        "native_shorts_body_voice_speed": config.NATIVE_SHORTS_BODY_VOICE_SPEED,
        "native_shorts_intro_voice_speed": config.NATIVE_SHORTS_INTRO_VOICE_SPEED,
        "native_long_body_voice_speed": config.NATIVE_LONG_BODY_VOICE_SPEED,
        "native_long_intro_voice_speed": config.NATIVE_LONG_INTRO_VOICE_SPEED,
        "max_backgrounds_shorts": config.MAX_BACKGROUNDS_SHORTS,
        "max_backgrounds_long": config.MAX_BACKGROUNDS_LONG,
        "max_backgrounds_long_budget": config.MAX_BACKGROUNDS_LONG_BUDGET,
        "opening_review_use_llm": config.OPENING_REVIEW_USE_LLM,
        "openai_final_review_enabled": config.OPENAI_FINAL_REVIEW_ENABLED,
    }


def get_dashboard_summary() -> dict[str, Any]:
    status = get_cached_settings_status()

    # 直近分析ファイル
    latest_analytics = None
    try:
        files = sorted(
            [f for f in os.listdir(get_analytics_dir()) if f.startswith("analytics_score_")],
            reverse=True,
        )
        latest_analytics = files[0] if files else None
    except OSError:
        pass

    # output/ 配下の履歴数とMP4有無カウント
    from web_app.security import is_video_folder
    history_count = 0
    mp4_count = 0
    try:
        for name in os.listdir(get_output_videos_dir()):
            if not is_video_folder(name):
                continue
            d = os.path.join(get_output_videos_dir(), name)
            if not os.path.isdir(d):
                continue
            history_count += 1
            # *_native.mp4 か video_native.mp4 を探す
            for fname in os.listdir(d):
                if fname.endswith("_native.mp4") or fname == "video_native.mp4":
                    mp4_count += 1
                    break
    except OSError:
        pass

    # 予約中動画数
    scheduled_count = _count_scheduled()

    return {
        **status,
        "history_count": history_count,
        "mp4_count": mp4_count,
        "scheduled_count": scheduled_count,
        "latest_analytics": latest_analytics,
    }


def _count_scheduled() -> int:
    try:
        from core.upload_records import load_upload_records
        records = load_upload_records()
        now_utc = datetime.now(timezone.utc)
        count = 0
        for r in records:
            s = str(r.get("publish_status") or "").lower()
            publish_at = r.get("publish_at") or ""
            if s == "scheduled" and _is_future_publish_at(publish_at, now_utc):
                count += 1
        return count
    except Exception:
        return 0


def _is_future_publish_at(publish_at_str: str, now_utc: datetime) -> bool:
    if not publish_at_str:
        return False
    try:
        dt = datetime.fromisoformat(publish_at_str.replace("Z", "+00:00"))
        return dt > now_utc
    except Exception:
        return False
