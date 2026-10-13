"""固定コメントの自動投稿（OSスケジューラから一括実行する経路）。

方針: Web UI 内では固定コメントの自動投稿は行わない（手動投稿のみ）。
自動投稿は OS のタスクスケジューラ / launchd（core.fixed_comment_task が登録）から
`<exe> --post-fixed-comments` を定期実行し、ここの post_all_pending() を呼ぶ。
"""
import logging

from config import config as _cfg

logger = logging.getLogger(__name__)

# 前回結果の記録名（core.background_task_status）
TASK_NAME = "fixed_comment_auto_post"


def _failure_message(exc: Exception) -> str:
    """利用者向けの失敗文言。スタックトレースや外部APIの生の応答は含めない。"""
    from core.error_codes import AppError, format_error

    if isinstance(exc, AppError):
        return exc.user_message()
    if isinstance(exc, (ValueError, FileNotFoundError)):
        # 投稿前チェックが投げる日本語の理由（video_id なし・固定コメント未設定など）
        return format_error("E-FIXED-COMMENT-AUTO", str(exc), with_fix=True)
    return format_error("E-FIXED-COMMENT-AUTO", type(exc).__name__, with_fix=True)


def post_all_pending(log=None) -> dict:
    """対象プロファイルの未投稿固定コメントを job_manager/runner を介さず直接投稿する。

    Web UI / runner が起動していなくても呼べる（CLI `--post-fixed-comments` から使う）。
    返値: 投稿件数などの要約。
    """
    from core import background_task_status
    from web_app.services.fixed_comment_service import (
        list_fixed_comment_candidates,
        post_fixed_comment_now,
    )

    def _emit(msg: str, tag: str = "info") -> None:
        if log:
            log(msg, tag)
        if tag == "error":
            logger.error(msg)
        else:
            logger.info(msg)

    posted = 0
    failures: list[dict[str, str]] = []
    profiles = 0
    try:
        for profile_id in _target_profile_ids():
            profiles += 1
            candidates = list_fixed_comment_candidates(only_unposted=True, profile_id=profile_id)
            for c in candidates:
                history_name = c["name"]
                try:
                    result = post_fixed_comment_now(
                        history_name, profile_id=profile_id, auto_posted=True, log=log,
                    )
                    if result.get("comment_thread_id"):
                        posted += 1
                        _emit(f"固定コメント投稿: profile={profile_id or 'active'} {history_name}")
                except Exception as exc:
                    logger.exception(
                        "固定コメント直接投稿失敗: profile=%s %s", profile_id or "active", history_name,
                    )
                    failures.append({
                        "target": f"{profile_id or 'active'} / {history_name}",
                        "message": _failure_message(exc),
                    })
    except Exception as exc:
        # 一覧取得など実行全体の失敗も画面へ出してから上位へ伝える
        logger.exception("固定コメント一括投稿が途中で失敗しました")
        failures.append({"target": "一括投稿の実行", "message": _failure_message(exc)})
        background_task_status.record_run(TASK_NAME, succeeded=posted, failures=failures)
        raise
    background_task_status.record_run(TASK_NAME, succeeded=posted, failures=failures)
    failed = len(failures)
    summary = {"posted": posted, "failed": failed, "profiles": profiles}
    _emit(f"固定コメント一括投稿 完了: posted={posted} failed={failed} profiles={profiles}")
    return summary


def _target_profile_ids() -> list[str | None]:
    scope = str(getattr(_cfg, "AUTO_FIXED_COMMENT_PROFILE_SCOPE", "all") or "all").strip().lower()
    if scope == "active":
        return [None]
    if scope != "all":
        raise ValueError(f"未対応の AUTO_FIXED_COMMENT_PROFILE_SCOPE です: {scope}")

    from core.channel_profile import list_profiles
    return [p.profile_id for p in list_profiles()]
