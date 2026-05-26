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

import config
from core.output_paths import OUTPUT_DIR, ANALYTICS_DIR


def check_voicevox() -> dict[str, Any]:
    try:
        r = httpx.get(f"{config.VOICEVOX_URL}/version", timeout=config.WEB_VOICEVOX_CHECK_TIMEOUT_SEC)
        return {"ok": True, "version": r.text.strip('"')}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_ffmpeg() -> dict[str, Any]:
    bin_path = shutil.which(config.FFMPEG_BIN) or config.FFMPEG_BIN
    try:
        result = subprocess.run(
            [bin_path, "-version"],
            capture_output=True, text=True, timeout=config.WEB_FFMPEG_CHECK_TIMEOUT_SEC
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        return {"ok": result.returncode == 0, "version": first_line}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_settings_status() -> dict[str, Any]:
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    return {
        "voicevox": check_voicevox(),
        "ffmpeg": check_ffmpeg(),
        "google_api_key": bool(config.GOOGLE_API_KEY),
        "openai_api_key": bool(config.OPENAI_API_KEY),
        "client_secrets_json": os.path.isfile(os.path.join(root, "client_secrets.json")),
        "token_json": os.path.isfile(os.path.join(root, "token.json")),
        "token_analytics_json": os.path.isfile(os.path.join(root, "token_analytics.json")),
        "output_dir": OUTPUT_DIR,
        "output_dir_exists": os.path.isdir(OUTPUT_DIR),
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
    status = get_settings_status()

    # 直近分析ファイル
    latest_analytics = None
    try:
        files = sorted(
            [f for f in os.listdir(ANALYTICS_DIR) if f.startswith("analytics_score_")],
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
        for name in os.listdir(OUTPUT_DIR):
            if not is_video_folder(name):
                continue
            d = os.path.join(OUTPUT_DIR, name)
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
