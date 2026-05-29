import logging
import os
import re
import time
from logging.handlers import TimedRotatingFileHandler

from config import config


_CONFIGURED = False


class _SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(str(record.getMessage()))
        record.args = ()
        return True


def setup_debug_logging() -> str | None:
    """アプリ全体のデバッグログを日次ローテーションで出力する。"""
    global _CONFIGURED
    if not config.DEBUG_LOG_ENABLED:
        return None

    os.makedirs(config.DEBUG_LOG_DIR, exist_ok=True)
    log_path = os.path.join(config.DEBUG_LOG_DIR, "app_debug.log")
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.DEBUG_LOG_LEVEL, logging.DEBUG))

    if not _CONFIGURED:
        handler = TimedRotatingFileHandler(
            log_path,
            when="midnight",
            interval=1,
            backupCount=max(1, config.DEBUG_LOG_RETENTION_DAYS),
            encoding="utf-8",
        )
        handler.setLevel(getattr(logging, config.DEBUG_LOG_LEVEL, logging.DEBUG))
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(process)d] %(name)s: %(message)s"
        ))
        handler.addFilter(_SecretRedactingFilter())
        root.addHandler(handler)
        # サードパーティライブラリのノイズを抑制
        for _noisy in (
            "watchfiles",       # ファイル変更検知ループ防止
            "httpcore",         # HTTP接続の内部詳細
            "httpx",            # 同上
            "asyncio",          # Python内部ループ
            "googleapiclient",  # Google API ディスカバリ
            "urllib3",          # HTTP低レベル
            "PIL",              # Pillow内部
        ):
            logging.getLogger(_noisy).setLevel(logging.WARNING)
        _CONFIGURED = True

    cleanup_old_debug_logs()
    logging.getLogger(__name__).debug("デバッグログ初期化: %s", log_path)
    return log_path


def cleanup_old_debug_logs() -> None:
    if not os.path.isdir(config.DEBUG_LOG_DIR):
        return
    keep_days = max(1, config.DEBUG_LOG_RETENTION_DAYS)
    threshold = time.time() - (keep_days * 24 * 60 * 60)
    for name in os.listdir(config.DEBUG_LOG_DIR):
        if not name.startswith("app_debug.log."):
            continue
        path = os.path.join(config.DEBUG_LOG_DIR, name)
        if os.path.isfile(path) and os.path.getmtime(path) < threshold:
            os.remove(path)


def _redact(message: str) -> str:
    redacted = message
    for secret in (config.GOOGLE_API_KEY, config.OPENAI_API_KEY):
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "sk-[REDACTED]", redacted)
    redacted = re.sub(r"AIza[A-Za-z0-9_-]{20,}", "AIza[REDACTED]", redacted)
    return redacted
