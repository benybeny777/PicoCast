"""
予約投稿スロット時刻到達時の固定コメント自動投稿サービス。
アプリ起動時にデーモンスレッドとして動作し、Webリクエストには一切影響しない。

チェックタイミング: Shorts/Long の公開スロット時刻 (0:00 / 12:00 / 21:00 / 21:00 JST) の
5分後にのみ起動。YouTube API は公開済み未投稿動画がある場合だけ呼ぶ。
"""
import logging
import threading
import time
from datetime import datetime, timedelta

from config import config as _cfg
from core.upload_scheduler import JST, SLOTS, LONG_SLOTS_WEEKDAY, LONG_SLOTS_WEEKEND

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
    """metadata.db と YouTube API から未投稿候補を取得して投稿ジョブを登録する。"""
    from web_app.services.fixed_comment_service import (
        list_fixed_comment_candidates,
        submit_fixed_comment_job,
    )

    for profile_id in _target_profile_ids():
        candidates = list_fixed_comment_candidates(only_unposted=True, profile_id=profile_id)
        for c in candidates:
            history_name = c["name"]

            try:
                job_id = submit_fixed_comment_job(history_name, auto_posted=True, profile_id=profile_id)
                logger.info(
                    "固定コメント自動投稿ジョブ登録: profile=%s %s (job_id=%s)",
                    profile_id or "active",
                    history_name,
                    job_id,
                )
            except Exception:
                logger.exception(
                    "固定コメント自動投稿ジョブ登録失敗: profile=%s %s",
                    profile_id or "active",
                    history_name,
                )


def _target_profile_ids() -> list[str | None]:
    scope = str(getattr(_cfg, "AUTO_FIXED_COMMENT_PROFILE_SCOPE", "all") or "all").strip().lower()
    if scope == "active":
        return [None]
    if scope != "all":
        raise ValueError(f"未対応の AUTO_FIXED_COMMENT_PROFILE_SCOPE です: {scope}")

    from core.channel_profile import list_profiles
    return [p.profile_id for p in list_profiles()]
