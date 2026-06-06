"""
Ollama を使って動画内容から再生リストカテゴリを判定する。

独立した手動ツールから明示実行された場合にだけ使う。
候補カテゴリは active profile の playlist_categories.md を正本にし、
Ollama の出力は候補名と完全一致したものだけ採用する。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from config import config as cfg
from core.error_codes import AppError

_logger = logging.getLogger(__name__)


def classify_playlist_category(
    *,
    title: str,
    description: str = "",
    script_text: str = "",
    categories: list[str] | tuple[str, ...],
) -> dict[str, str]:
    """動画内容から playlist_categories.md 内のカテゴリを1つ選ぶ。"""
    choices = [str(c).strip() for c in categories if str(c).strip()]
    if not choices:
        _logger.error("単体再生リスト判定の候補カテゴリが空です")
        raise AppError("E-PLAYLIST-CONFIG", detail="playlist_categories.md にカテゴリを追加してください。")

    prompt = _build_prompt(
        title=title,
        description=description,
        script_text=script_text,
        categories=choices,
    )
    try:
        from core.opening_quality import ensure_ollama_server
        ensure_ollama_server()
    except Exception as exc:
        _logger.error(
            "再生リスト判定用Ollamaの起動確認に失敗しました: model=%s url=%s",
            cfg.OLLAMA_PLAYLIST_MODEL,
            cfg.OLLAMA_BASE_URL,
            exc_info=True,
        )
        raise AppError("E-OLLAMA-DOWN", detail="再生リスト判定でOllamaが必要です。", cause=exc) from exc

    try:
        body = {
            "model": cfg.OLLAMA_PLAYLIST_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "temperature": 0.0,
                "num_predict": cfg.OLLAMA_PLAYLIST_NUM_PREDICT,
            },
        }
        with requests.post(
            f"{cfg.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json=body,
            timeout=cfg.OLLAMA_PLAYLIST_TIMEOUT_SEC,
        ) as response:
            response.raise_for_status()
            payload = response.json()
    except requests.exceptions.ConnectionError as exc:
        _logger.error(
            "再生リスト判定用Ollamaに接続できません: model=%s url=%s",
            cfg.OLLAMA_PLAYLIST_MODEL,
            cfg.OLLAMA_BASE_URL,
            exc_info=True,
        )
        raise AppError("E-OLLAMA-DOWN", detail="再生リスト判定でOllamaが必要です。", cause=exc) from exc
    except requests.exceptions.Timeout as exc:
        _logger.error(
            "Ollama再生リスト判定がタイムアウトしました: model=%s url=%s timeout_sec=%s num_predict=%s",
            cfg.OLLAMA_PLAYLIST_MODEL,
            cfg.OLLAMA_BASE_URL,
            cfg.OLLAMA_PLAYLIST_TIMEOUT_SEC,
            cfg.OLLAMA_PLAYLIST_NUM_PREDICT,
            exc_info=True,
        )
        raise AppError(
            "E-PLAYLIST-CLASSIFY",
            detail=f"Ollama の応答が {cfg.OLLAMA_PLAYLIST_TIMEOUT_SEC:g} 秒以内に完了しませんでした。",
            cause=exc,
        ) from exc
    except AppError:
        raise
    except Exception as exc:
        _logger.error(
            "Ollama再生リスト判定APIに失敗しました: model=%s url=%s",
            cfg.OLLAMA_PLAYLIST_MODEL,
            cfg.OLLAMA_BASE_URL,
            exc_info=True,
        )
        raise AppError("E-PLAYLIST-CLASSIFY", detail="Ollama API 呼び出しに失敗しました。", cause=exc) from exc

    raw = str(payload.get("response") or "").strip()
    data = _parse_json_object(raw)
    category = str(data.get("category") or "").strip()
    reason = str(data.get("reason") or "").strip()
    if category not in choices:
        _logger.error(
            "Ollama再生リスト判定が候補外カテゴリを返しました: category=%r choices=%s raw=%r",
            category,
            choices,
            raw[:500],
        )
        raise AppError("E-PLAYLIST-CLASSIFY", detail=f"Ollama の判定結果が候補外です: {category or '空'}")
    return {"category": category, "reason": reason}


def _build_prompt(
    *,
    title: str,
    description: str,
    script_text: str,
    categories: list[str],
) -> str:
    script = str(script_text or "").strip()
    max_chars = max(0, int(cfg.PLAYLIST_CLASSIFIER_SCRIPT_CHARS))
    if max_chars and len(script) > max_chars:
        script = script[:max_chars] + "\n..."
    return "\n".join([
        "あなたはYouTubeチャンネルの再生リスト分類担当です。",
        "動画内容を読み、候補カテゴリから最も近いものを1つだけ選んでください。",
        "候補カテゴリにない名前は絶対に作らないでください。",
        "返答はJSONのみ。形式: {\"category\":\"候補カテゴリ名\", \"reason\":\"短い理由\"}",
        "",
        "候補カテゴリ:",
        *[f"- {cat}" for cat in categories],
        "",
        f"動画タイトル: {str(title or '').strip()}",
        f"説明文: {str(description or '').strip()}",
        "台本:",
        script,
    ])


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            _logger.error("Ollama再生リスト判定レスポンスにJSONがありません: raw=%r", text[:500])
            raise AppError("E-PLAYLIST-CLASSIFY", detail="Ollama の返答にJSONがありません。")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            _logger.error("Ollama再生リスト判定JSONの解析に失敗しました: raw=%r", text[:500], exc_info=True)
            raise AppError("E-PLAYLIST-CLASSIFY", detail="Ollama のJSON返答を解析できません。", cause=exc) from exc
    if not isinstance(data, dict):
        _logger.error("Ollama再生リスト判定JSONがオブジェクトではありません: data=%r", data)
        raise AppError("E-PLAYLIST-CLASSIFY", detail="Ollama のJSON返答形式が不正です。")
    return data
