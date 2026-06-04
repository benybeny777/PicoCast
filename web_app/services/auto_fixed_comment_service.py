"""固定コメントの自動投稿（OSスケジューラから一括実行する経路）。

方針: Web UI 内では固定コメントの自動投稿は行わない（手動投稿のみ）。
自動投稿は OS のタスクスケジューラ / launchd（core.fixed_comment_task が登録）から
`<exe> --post-fixed-comments` を定期実行し、ここの post_all_pending() を呼ぶ。
"""
import logging

from config import config as _cfg

logger = logging.getLogger(__name__)


def post_all_pending(log=None) -> dict:
    """対象プロファイルの未投稿固定コメントを job_manager/runner を介さず直接投稿する。

    Web UI / runner が起動していなくても呼べる（CLI `--post-fixed-comments` から使う）。
    返値: 投稿件数などの要約。
    """
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
    failed = 0
    profiles = 0
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
            except Exception:
                failed += 1
                logger.exception(
                    "固定コメント直接投稿失敗: profile=%s %s", profile_id or "active", history_name,
                )
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
