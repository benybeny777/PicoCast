"""音声生成バックエンド共通処理。

VOICEVOX と AquesTalk 系ゆっくり音声を、生成パイプラインから同じ
「backend を見て WAV を作る」単位で扱うための薄い層。
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import wave
from dataclasses import dataclass

from config import config
from core.path_refs import resolve_path_ref

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioSpeaker:
    backend: str
    speaker: str
    speaker_id: int | None = None
    voice_type: str = ""
    speed: int | None = None
    pitch: int | None = None
    volume: int | None = None
    character_name: str = ""


def resolve_audio_speaker(profile_id: str | None, character_name: str, emotion: str = "ノーマル") -> AudioSpeaker:
    """キャラクター設定から音声バックエンド設定を解決する。"""
    from core.character_profile_store import resolve_character_voice_settings

    settings = resolve_character_voice_settings(profile_id, character_name, emotion)
    backend = str(settings["backend"] or "").strip().lower()
    if backend not in {"voicevox", "aquestalk"}:
        _logger.error("未対応の音声バックエンドです: backend=%s character=%s", backend, character_name)
        raise RuntimeError(f"未対応の音声バックエンドです: {backend}")
    return AudioSpeaker(
        backend=backend,
        speaker=str(settings.get("speaker") or ""),
        speaker_id=settings.get("speaker_id"),
        voice_type=str(settings.get("voice_type") or ""),
        speed=settings.get("speed"),
        pitch=settings.get("pitch"),
        volume=settings.get("volume"),
        character_name=str(settings.get("character_name") or character_name),
    )


def _require_aquestalk_ready(profile_id: str | None = None) -> str:
    if not config.AQUESTALK_ENABLED:
        _logger.error("AquesTalkが無効です")
        raise RuntimeError("AquesTalkが無効です。設定画面で AQUESTALK_ENABLED を有効にしてください。")
    configured_engine = str(config.AQUESTALK_ENGINE_PATH or "").strip()
    if not configured_engine:
        _logger.error("AquesTalkエンジンパスが未設定です")
        raise RuntimeError("AquesTalkエンジンパスが未設定です。")
    engine = resolve_path_ref(configured_engine)
    if not os.path.isfile(engine):
        _logger.error("AquesTalkエンジンが見つかりません: path=%s", engine)
        raise RuntimeError("AquesTalkエンジンが見つかりません。AQUESTALK_ENGINE_PATH を確認してください。")
    return engine


def _load_aquestalk_license_key(profile_id: str | None) -> str:
    from core.secret_store import SecretNotFoundError, load_secret

    try:
        return load_secret("aquestalk_license_key", profile_id=profile_id).strip()
    except SecretNotFoundError:
        _logger.warning("AquesTalkライセンスキーが未登録です: profile_id=%s", profile_id)
        return ""
    except Exception:
        _logger.error("AquesTalkライセンスキーの読み込みに失敗しました", exc_info=True)
        raise


def _validate_wav(path: str) -> None:
    if not os.path.isfile(path):
        _logger.error("音声生成後のWAVが存在しません: path=%s", path)
        raise RuntimeError("音声生成後のWAVが存在しません。")
    try:
        with wave.open(path, "rb") as wr:
            if wr.getnframes() <= 0:
                raise RuntimeError("WAVフレーム数が0です")
    except Exception as exc:
        _logger.error("WAV形式の検証に失敗しました: path=%s", path, exc_info=True)
        raise RuntimeError("生成されたWAVが不正です。") from exc


def generate_aquestalk_audio(
    *,
    text: str,
    speaker: AudioSpeaker,
    output_path: str,
    profile_id: str | None = None,
    speed_scale: float = 1.0,
) -> str:
    """AquesTalk系エンジン/ラッパーCLIで WAV を生成する。"""
    engine = _require_aquestalk_ready(profile_id)
    license_key = _load_aquestalk_license_key(profile_id)
    template = str(config.AQUESTALK_COMMAND_TEMPLATE or "").strip()
    if not template:
        _logger.error("AquesTalkコマンドテンプレートが未設定です")
        raise RuntimeError("AquesTalkコマンドテンプレートが未設定です。")
    if not config.AQUESTALK_LICENSE_CONFIRMED and not license_key:
        _logger.error("AquesTalkライセンスキー未登録かつライセンス確認済みフラグも未設定です")
        raise RuntimeError("AquesTalkライセンスが未設定です。ライセンスキー登録または確認済みフラグを設定してください。")
    if "{license_key}" in template and not license_key:
        _logger.error("AquesTalkコマンドテンプレートがライセンスキーを要求していますが未登録です")
        raise RuntimeError("AquesTalkライセンスキーが未登録です。")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    speed = int(round((speaker.speed or config.AQUESTALK_DEFAULT_SPEED) * float(speed_scale or 1.0)))
    values = {
        "engine": engine,
        "text": text,
        "output": output_path,
        "voice": speaker.voice_type or speaker.speaker,
        "speaker": speaker.speaker,
        "speed": speed,
        "pitch": speaker.pitch if speaker.pitch is not None else config.AQUESTALK_DEFAULT_PITCH,
        "volume": speaker.volume if speaker.volume is not None else config.AQUESTALK_DEFAULT_VOLUME,
        "license_key": license_key,
    }
    try:
        command_line = template.format(**values)
        command = shlex.split(command_line, posix=True)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=config.AQUESTALK_TIMEOUT_SEC,
        )
    except Exception as exc:
        _logger.error("AquesTalk音声生成コマンドの実行に失敗しました", exc_info=True)
        raise RuntimeError("AquesTalk音声生成コマンドの実行に失敗しました。") from exc
    if result.returncode != 0:
        _logger.error(
            "AquesTalk音声生成が失敗しました: returncode=%s stderr=%s",
            result.returncode,
            (result.stderr or "").strip()[:500],
        )
        raise RuntimeError("AquesTalk音声生成が失敗しました。エンジン設定とライセンスを確認してください。")
    _validate_wav(output_path)
    return output_path


def check_aquestalk(profile_id: str | None = None) -> dict:
    """AquesTalk設定と短い生成テストを確認する。"""
    if not config.AQUESTALK_ENABLED:
        return {"ok": True, "enabled": False, "note": "AquesTalkは無効です"}
    try:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            speaker = AudioSpeaker(
                backend="aquestalk",
                speaker="yukkuri_reimu",
                voice_type="yukkuri_reimu",
                speed=config.AQUESTALK_DEFAULT_SPEED,
                pitch=config.AQUESTALK_DEFAULT_PITCH,
                volume=config.AQUESTALK_DEFAULT_VOLUME,
                character_name="霊夢",
            )
            out = os.path.join(tmp, "aquestalk_check.wav")
            generate_aquestalk_audio(
                text=config.AQUESTALK_TEST_TEXT,
                speaker=speaker,
                output_path=out,
                profile_id=profile_id,
                speed_scale=1.0,
            )
        return {"ok": True, "enabled": True, "engine_path": config.AQUESTALK_ENGINE_PATH}
    except Exception as exc:
        _logger.error("AquesTalkサービスチェックに失敗しました", exc_info=True)
        return {"ok": False, "enabled": True, "error": str(exc)}
