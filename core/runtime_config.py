"""設定DBの値を現在プロセスへ反映する共通処理。"""
from __future__ import annotations

import logging
import sys
from typing import Any

from config import config as cfg

_logger = logging.getLogger(__name__)


def _coerce_value(key: str, raw_value: object) -> Any:
    current = getattr(cfg, key, None)
    raw = str(raw_value)
    try:
        if isinstance(current, bool):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(current, int) and not isinstance(current, bool):
            return int(raw)
        if isinstance(current, float):
            return float(raw)
        if isinstance(current, tuple):
            return cfg._split_env_choices(raw)
        if isinstance(current, list):
            return list(cfg._split_env_choices(raw))
    except (TypeError, ValueError) as exc:
        _logger.error("設定DBの値を実行時反映できません: key=%s value=%r", key, raw_value, exc_info=True)
        raise RuntimeError(f"{key} の設定値が不正です: {raw_value}") from exc
    if key == "WEB_IMAGE_STYLE_CHOICES":
        return cfg._split_env_choices(raw)
    if key == "WEB_DEFAULT_IMAGE_STYLE":
        return cfg._clean_env_choice(raw)
    return raw


def apply_runtime_settings(updates: dict[str, object]) -> None:
    """設定値を config モジュールと import 済みモジュールへ即時反映する。"""
    for key, raw_value in updates.items():
        if not hasattr(cfg, key):
            continue
        value = _coerce_value(key, raw_value)
        setattr(cfg, key, value)
        for mod in list(sys.modules.values()):
            if mod is None or mod is cfg:
                continue
            if hasattr(mod, key):
                try:
                    setattr(mod, key, value)
                except (AttributeError, TypeError):
                    _logger.warning("設定値のモジュール反映に失敗しました: key=%s module=%s", key, getattr(mod, "__name__", ""), exc_info=True)


def refresh_runtime_settings() -> None:
    """settings.db の保存済み設定を現在プロセスへ読み直す。"""
    from core.settings_store import get_all

    apply_runtime_settings(get_all())
