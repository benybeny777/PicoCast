import atexit
import logging
import os
import queue
import re
import time
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler

from config import config


_CONFIGURED_ROLE: str | None = None
_LISTENER: QueueListener | None = None


class _SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(str(record.getMessage()))
        record.args = ()
        return True


def setup_debug_logging(role: str = "web") -> str | None:
    """role 別のデバッグログを QueueListener 経由で日次ローテーション出力する。"""
    global _CONFIGURED_ROLE, _LISTENER
    if not config.DEBUG_LOG_ENABLED:
        return None

    role = re.sub(r"[^A-Za-z0-9_-]+", "_", role or "web")
    os.makedirs(config.DEBUG_LOG_DIR, exist_ok=True)
    log_path = os.path.join(config.DEBUG_LOG_DIR, f"app_debug_{role}.log")
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.DEBUG_LOG_LEVEL, logging.DEBUG))

    if _CONFIGURED_ROLE != role:
        if _LISTENER is not None:
            _LISTENER.stop()
        for handler in list(root.handlers):
            if isinstance(handler, QueueHandler):
                root.removeHandler(handler)
        log_queue: queue.Queue = queue.Queue()
        queue_handler = QueueHandler(log_queue)
        queue_handler.addFilter(_SecretRedactingFilter())
        root.addHandler(queue_handler)

        file_handler = TimedRotatingFileHandler(
            log_path,
            when="midnight",
            interval=1,
            backupCount=max(1, config.DEBUG_LOG_RETENTION_DAYS),
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, config.DEBUG_LOG_LEVEL, logging.DEBUG))
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(process)d] %(name)s %(funcName)s:%(lineno)d: %(message)s"
        ))
        _LISTENER = QueueListener(log_queue, file_handler, respect_handler_level=True)
        _LISTENER.start()
        atexit.register(_stop_listener)

        for _noisy in (
            "watchfiles",
            "httpcore",
            "httpx",
            "asyncio",
            "googleapiclient",
            "urllib3",
            "PIL",
        ):
            logging.getLogger(_noisy).setLevel(logging.WARNING)
        _CONFIGURED_ROLE = role

    cleanup_old_debug_logs()
    _logger = logging.getLogger(__name__)
    sep = "=" * 72
    _logger.warning(sep)
    _logger.warning("  ★ APP STARTUP role=%s PID=%s LOG=%s", role, os.getpid(), log_path)
    _logger.warning(sep)
    return log_path


def _stop_listener() -> None:
    global _LISTENER
    if _LISTENER is not None:
        _LISTENER.stop()
        _LISTENER = None


def cleanup_old_debug_logs() -> None:
    if not os.path.isdir(config.DEBUG_LOG_DIR):
        return
    keep_days = max(1, config.DEBUG_LOG_RETENTION_DAYS)
    threshold = time.time() - (keep_days * 24 * 60 * 60)
    for name in os.listdir(config.DEBUG_LOG_DIR):
        if not name.startswith("app_debug_") or ".log." not in name:
            continue
        path = os.path.join(config.DEBUG_LOG_DIR, name)
        if os.path.isfile(path) and os.path.getmtime(path) < threshold:
            os.remove(path)


def _redact(message: str) -> str:
    redacted = message
    redacted = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "sk-[REDACTED]", redacted)
    redacted = re.sub(r"AIza[A-Za-z0-9_-]{20,}", "AIza[REDACTED]", redacted)
    return redacted
