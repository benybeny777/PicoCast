"""Ollama再生リスト振り分けを手動実行する独立サービス。"""
from __future__ import annotations

import logging
from typing import Any, NoReturn, Sequence

from web_app.job_manager import Job, _log, get_job_manager

_logger = logging.getLogger(__name__)
_JOB_TYPE = "playlist_classifier"


def _normalize_history_names(history_names: Sequence[str]) -> list[str]:
    """空値と重複を除き、入力順を維持した対象名一覧を返す。"""
    return list(dict.fromkeys(
        name
        for raw_name in history_names
        if (name := str(raw_name).strip())
    ))


def _normalize_playlist_categories(raw: Any) -> list[str]:
    """DB由来のカテゴリ値を表示・判定用の文字列リストへ統一する。"""
    if isinstance(raw, str):
        value = raw.strip()
        return [value] if value else []
    if isinstance(raw, (list, tuple)):
        return [value for item in raw if (value := str(item).strip())]
    return []


def _candidate_from_history(history: dict[str, Any], render_info: dict[str, Any]) -> dict[str, Any]:
    """履歴とレンダー情報から画面表示用候補を作る。"""
    return {
        "name": history["name"],
        "title": render_info.get("video_title") or history["title"],
        "video_format": render_info.get("video_format") or history["video_format"],
        "playlist_categories": _normalize_playlist_categories(
            render_info.get("playlist_categories")
        ),
    }


def list_classifier_candidates() -> list[dict[str, Any]]:
    """生成履歴と現在保存されている再生リストカテゴリを返す。"""
    from core.error_codes import AppError
    from core.metadata_db import get_render_info
    from web_app.services.history_service import list_histories

    try:
        candidates: list[dict[str, Any]] = []
        for history in list_histories(include_uploaded=True):
            render_info = get_render_info(history["name"])
            candidates.append(_candidate_from_history(history, render_info))
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

    names = _normalize_history_names(history_names)
    if not names:
        _logger.error(
            "単体再生リスト振り分けの対象が空です: code=E-PLAYLIST-TARGET"
        )
        raise AppError(
            "E-PLAYLIST-TARGET",
            detail="判定対象が選択されていません。",
        )
    try:
        mgr = get_job_manager()
        job = mgr.create_job(
            _JOB_TYPE,
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


def _raise_classification_failure(
    *,
    history_name: str,
    stage: str,
    exc: Exception,
) -> NoReturn:
    """失敗をデバッグログと処理ログへ一度だけ記録し、AppErrorとして再送出する。"""
    from core.error_codes import AppError

    error = exc if isinstance(exc, AppError) else AppError(
        "E-PLAYLIST-CLASSIFY",
        detail=f"{stage}に失敗しました。対象: {history_name}",
        cause=exc,
    )
    _logger.error(
        "単体再生リスト振り分けに失敗しました: code=%s stage=%s history_name=%s",
        error.code,
        stage,
        history_name,
        exc_info=True,
    )
    if error is exc:
        raise error
    raise error from exc


def _classify_history(
    job: Job,
    *,
    history_name: str,
    categories: Sequence[str],
    only_unregistered: bool,
) -> dict[str, str] | None:
    """1動画を判定してDBへ保存する。登録済みスキップ時はNoneを返す。"""
    from core.error_codes import AppError
    from core.genre_playlist_classifier import classify_playlist_category
    from core.metadata_db import (
        get_render_info,
        get_script_content,
        update_playlist_categories,
    )
    from web_app.security import find_history_dir

    stage = "対象確認"
    try:
        if find_history_dir(history_name) is None:
            raise AppError("E-PLAYLIST-TARGET", detail=f"対象: {history_name}")

        stage = "メタデータ取得"
        render_info = get_render_info(history_name)
        existing = _normalize_playlist_categories(
            render_info.get("playlist_categories")
        )
        if only_unregistered and existing:
            _log(job, f"登録済みのためスキップ: {history_name}", "info")
            return None

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
        return {
            "history_name": history_name,
            "category": category,
            "reason": reason,
        }
    except Exception as exc:
        _raise_classification_failure(
            history_name=history_name,
            stage=stage,
            exc=exc,
        )


def _run_playlist_classifier(
    job: Job,
    history_names: list[str],
    only_unregistered: bool,
) -> dict[str, Any]:
    from core.playlist_resolver import get_standard_categories

    categories = get_standard_categories()
    results: list[dict[str, str]] = []
    skipped = 0
    for history_name in history_names:
        if job.cancel_event.is_set():
            return {"cancelled": True, "results": results, "skipped": skipped}
        result = _classify_history(
            job,
            history_name=history_name,
            categories=categories,
            only_unregistered=only_unregistered,
        )
        if result is None:
            skipped += 1
        else:
            results.append(result)
    return {"results": results, "skipped": skipped}
