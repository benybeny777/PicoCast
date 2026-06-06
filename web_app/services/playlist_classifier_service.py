"""Ollama再生リスト振り分けを手動実行する独立サービス。"""
from __future__ import annotations

import logging
from typing import Any

from web_app.job_manager import Job, _log, get_job_manager

_logger = logging.getLogger(__name__)


def list_classifier_candidates() -> list[dict[str, Any]]:
    """生成履歴と現在保存されている再生リストカテゴリを返す。"""
    from core.error_codes import AppError
    from core.metadata_db import get_render_info
    from web_app.services.history_service import list_histories

    try:
        candidates: list[dict[str, Any]] = []
        for history in list_histories(include_uploaded=True):
            render_info = get_render_info(history["name"])
            categories = render_info.get("playlist_categories") or []
            if isinstance(categories, str):
                categories = [categories] if categories.strip() else []
            candidates.append({
                "name": history["name"],
                "title": render_info.get("video_title") or history["title"],
                "video_format": render_info.get("video_format") or history["video_format"],
                "playlist_categories": categories,
            })
        return candidates
    except Exception as exc:
        _logger.error(
            "単体再生リスト振り分けの候補一覧取得に失敗しました: code=E-PLAYLIST-TARGET",
            exc_info=True,
        )
        raise AppError(
            "E-PLAYLIST-TARGET",
            detail="候補一覧を取得できませんでした。",
            cause=exc,
        ) from exc


def submit_playlist_classifier_job(
    history_names: list[str],
    *,
    only_unregistered: bool,
) -> str:
    """明示選択された動画の振り分けジョブを登録する。"""
    from core.error_codes import AppError

    names = [str(name).strip() for name in history_names if str(name).strip()]
    if not names:
        raise ValueError("判定対象が選択されていません。")
    try:
        mgr = get_job_manager()
        job = mgr.create_job(
            "playlist_classifier",
            params={"history_names": names, "only_unregistered": only_unregistered},
        )
        _log(job, f"単体再生リスト振り分けを登録: {len(names)}件", "info")
        mgr.submit(job, _run_playlist_classifier, names, only_unregistered)
        return job.job_id
    except Exception as exc:
        _logger.error(
            "単体再生リスト振り分けジョブの登録に失敗しました: code=E-PLAYLIST-SAVE target_count=%s",
            len(names),
            exc_info=True,
        )
        raise AppError(
            "E-PLAYLIST-SAVE",
            detail="判定ジョブを登録できませんでした。",
            cause=exc,
        ) from exc


def _run_playlist_classifier(
    job: Job,
    history_names: list[str],
    only_unregistered: bool,
) -> dict[str, Any]:
    from core.error_codes import AppError
    from core.genre_playlist_classifier import classify_playlist_category
    from core.metadata_db import (
        get_render_info,
        get_script_content,
        update_playlist_categories,
    )
    from core.playlist_resolver import get_standard_categories
    from web_app.security import find_history_dir

    categories = get_standard_categories()
    results: list[dict[str, str]] = []
    skipped = 0
    for history_name in history_names:
        if job.cancel_event.is_set():
            return {"cancelled": True, "results": results, "skipped": skipped}
        stage = "対象確認"
        try:
            if find_history_dir(history_name) is None:
                raise AppError(
                    "E-PLAYLIST-TARGET",
                    detail=f"対象: {history_name}",
                )

            stage = "メタデータ取得"
            render_info = get_render_info(history_name)
            existing = render_info.get("playlist_categories") or []
            if only_unregistered and existing:
                skipped += 1
                _log(job, f"登録済みのためスキップ: {history_name}", "info")
                continue

            stage = "Ollama判定"
            result = classify_playlist_category(
                title=render_info.get("video_title") or history_name,
                description=render_info.get("description") or "",
                script_text=get_script_content(history_name) or "",
                categories=categories,
            )
            category = result["category"]

            stage = "DB保存"
            try:
                update_playlist_categories(history_name, [category])
            except Exception as exc:
                raise AppError(
                    "E-PLAYLIST-SAVE",
                    detail=f"対象: {history_name}",
                    cause=exc,
                ) from exc

            reason = result.get("reason") or ""
            _log(
                job,
                f"判定・保存: {history_name} → {category}" + (f"（{reason}）" if reason else ""),
                "success",
            )
            results.append({
                "history_name": history_name,
                "category": category,
                "reason": reason,
            })
        except AppError as exc:
            _logger.error(
                "単体再生リスト振り分けに失敗しました: code=%s stage=%s history_name=%s",
                exc.code,
                stage,
                history_name,
                exc_info=True,
            )
            _log(job, f"{history_name}: {exc.user_message()}", "error")
            raise
        except Exception as exc:
            wrapped = AppError(
                "E-PLAYLIST-CLASSIFY",
                detail=f"{stage}に失敗しました。対象: {history_name}",
                cause=exc,
            )
            _logger.error(
                "単体再生リスト振り分けに失敗しました: code=%s stage=%s history_name=%s",
                wrapped.code,
                stage,
                history_name,
                exc_info=True,
            )
            _log(job, f"{history_name}: {wrapped.user_message()}", "error")
            raise wrapped from exc
    return {"results": results, "skipped": skipped}
