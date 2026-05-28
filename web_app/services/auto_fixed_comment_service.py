"""
予約投稿スロット時刻到達時の固定コメント自動投稿サービス。
アプリ起動時にデーモンスレッドとして動作し、Webリクエストには一切影響しない。

チェックタイミング: Shorts/Long の公開スロット時刻 (7:00 / 12:00 / 19:00 / 21:00 JST) の
5分後にのみ起動。YouTube API は公開済み未投稿動画がある場合だけ呼ぶ。
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from config.config import config as _cfg
from core.output_paths import OUTPUT_DIR
from core.upload_scheduler import JST, SLOTS, LONG_SLOTS_WEEKDAY, LONG_SLOTS_WEEKEND
from web_app.security import safe_output_path

logger = logging.getLogger(__name__)

_PUBLISH_BUFFER_SEC = 300   # スロット時刻の何秒後にチェックするか（5分）
_SETTING_POLL_SEC   = 60    # 設定ON/OFF確認の単位スリープ

_watcher_thread: threading.Thread | None = None

# 全スロット時間（重複排除）
_ALL_SLOT_HOURS = sorted(set(SLOTS + LONG_SLOTS_WEEKDAY + LONG_SLOTS_WEEKEND))


def start_auto_watcher() -> None:
    """app.py の lifespan から呼ぶ。二重起動を防ぐ。"""
    global _watcher_thread
    if _watcher_thread and _watcher_thread.is_alive():
        return
    _watcher_thread = threading.Thread(target=_watch_loop, name="auto-fixed-comment", daemon=True)
    _watcher_thread.start()
    logger.info("固定コメント自動投稿ウォッチャー起動 (スロット時刻: %s JST + %d秒後)",
                _ALL_SLOT_HOURS, _PUBLISH_BUFFER_SEC)


def _watch_loop() -> None:
    while True:
        sleep_sec = _seconds_to_next_slot_check()
        _interruptible_sleep(sleep_sec)

        if not _cfg.AUTO_FIXED_COMMENT_ENABLED:
            continue
        try:
            _run_once()
        except Exception:
            logger.exception("固定コメント自動投稿チェックでエラー")


def _seconds_to_next_slot_check() -> float:
    """次のスロット時刻 + バッファまでの待機秒数を返す。"""
    now = datetime.now(JST)
    today = now.date()
    # 今日・明日の全スロット候補を列挙
    candidates: list[datetime] = []
    for offset in (0, 1):
        day = today + timedelta(days=offset)
        for h in _ALL_SLOT_HOURS:
            dt = datetime(day.year, day.month, day.day, h, 0, 0, tzinfo=JST) + timedelta(seconds=_PUBLISH_BUFFER_SEC)
            if dt > now:
                candidates.append(dt)

    if not candidates:
        # 計算上ありえないが念のため1時間後
        return 3600.0

    next_dt = min(candidates)
    return max(0.0, (next_dt - now).total_seconds())


def _interruptible_sleep(total_sec: float) -> None:
    """_SETTING_POLL_SEC 刻みでスリープし、設定変更に応答できるようにする。"""
    remaining = total_sec
    while remaining > 0:
        time.sleep(min(_SETTING_POLL_SEC, remaining))
        remaining -= _SETTING_POLL_SEC


def _run_once() -> None:
    """ローカルで未処理候補があるときだけ YouTube API を呼んで投稿する。"""
    if not _has_local_unsubmitted_candidates():
        return

    from web_app.services.fixed_comment_service import (
        list_fixed_comment_candidates,
        submit_fixed_comment_job,
    )

    candidates = list_fixed_comment_candidates(only_unposted=True)
    for c in candidates:
        history_name = c["name"]
        if c.get("auto_submitted_at"):
            continue

        _mark_auto_submitted(history_name)
        try:
            job_id = submit_fixed_comment_job(history_name, auto_posted=True)
            logger.info("固定コメント自動投稿ジョブ登録: %s (job_id=%s)", history_name, job_id)
        except Exception:
            logger.exception("固定コメント自動投稿ジョブ登録失敗: %s", history_name)


def _has_local_unsubmitted_candidates() -> bool:
    """YouTube API を呼ばずにローカルファイルだけで未処理候補の有無を判定する。"""
    from web_app.services.fixed_comment_service import _iter_candidate_dirs, _safe_json, _first_existing
    try:
        for _relative_name, theme_dir in _iter_candidate_dirs():
            record_path = _first_existing(theme_dir, ("_meta/upload_record.json", "upload_record.json"))
            rec = _safe_json(record_path)
            if not rec.get("video_id"):
                continue
            if rec.get("fixed_comment_thread_id") or rec.get("fixed_comment_posted_at") or rec.get("fixed_comment_pinned_at"):
                continue
            if rec.get("fixed_comment_auto_submitted_at"):
                continue
            return True
    except Exception:
        logger.exception("ローカル候補スキャン失敗")
    return False


def _mark_auto_submitted(history_name: str) -> None:
    """upload_record.json に auto_submitted_at を記録して二重送信を防ぐ。"""
    from web_app.services.fixed_comment_service import _first_existing, _safe_json
    try:
        theme_dir = safe_output_path(history_name, output_base=OUTPUT_DIR)
        record_path = _first_existing(theme_dir, ("_meta/upload_record.json", "upload_record.json"))
        record = _safe_json(record_path)
        if record.get("fixed_comment_auto_submitted_at"):
            return
        record["fixed_comment_auto_submitted_at"] = datetime.now(JST).isoformat(timespec="seconds")
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("auto_submitted_at 記録失敗: %s", history_name)
