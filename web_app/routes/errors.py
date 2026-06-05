"""Web API 例外変換ヘルパー。"""
from __future__ import annotations

import logging

from fastapi import HTTPException

_logger = logging.getLogger(__name__)


def raise_api_error(exc: Exception, *, status_code: int = 400, action: str = "API処理") -> None:
    """例外をログへ残して HTTPException として送出する。"""
    _logger.error("%sに失敗しました", action, exc_info=True)
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def error_payload(exc: Exception, *, action: str = "API処理") -> dict[str, str]:
    """既存互換の {status, message} レスポンス用に、ログ付きエラー payload を返す。"""
    _logger.error("%sに失敗しました", action, exc_info=True)
    return {"status": "error", "message": str(exc)}
