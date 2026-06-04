"""
固定コメント投稿サービス。
metadata.db の youtube_status / video_metadata を正本として扱う。
"""
import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from core.output_paths import get_output_videos_dir, get_uploaded_dir, get_output_root
from core.metadata_db import ManagedConnection, initialize_db
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import is_video_folder, safe_output_path


def list_fixed_comment_candidates(only_unposted: bool = True, profile_id: str | None = None) -> list[dict[str, Any]]:
    context = _fixed_comment_context(profile_id)
    results = []
    # まず候補フォルダを収集（ディレクトリ判定）→ レコードは1クエリで一括取得（N+1回避）
    _cands: list[tuple[str, str, str, bool]] = []  # (relative_name, theme_dir, name, is_uploaded)
    for relative_name, theme_dir in _iter_candidate_dirs(context):
        name = os.path.basename(theme_dir)
        is_uploaded_archive = relative_name.startswith("000_uploaded" + os.sep)
        try:
            _safe_fixed_comment_theme_dir(relative_name, context)
        except Exception:
            continue
        if not os.path.isdir(theme_dir):
            continue
        _cands.append((relative_name, theme_dir, name, is_uploaded_archive))

    records = _fixed_comment_records_bulk([name for _, _, name, _ in _cands], context)
    for relative_name, theme_dir, name, is_uploaded_archive in _cands:
        record = records.get(name)
        if not record:
            continue
        fixed_comment = str(record.get("fixed_comment") or "").strip()
        if not fixed_comment:
            continue

        video_id = str(record.get("video_id") or "").strip()
        if not video_id:
            continue

        publish_status = str(record.get("publish_status") or "").lower()
        if not _is_local_displayable_publish_status(publish_status):
            continue

        comment_thread_id = str(record.get("comment_thread_id") or "").strip()
        already_posted = bool(record.get("fixed_comment_posted") or comment_thread_id)

        if only_unposted and already_posted:
            continue

        results.append({
            "name": relative_name,
            "display_name": name,
            "location": "アップロード済み" if is_uploaded_archive else "出力",
            "title": str(record.get("title") or name),
            "video_id": video_id,
            "publish_status": publish_status,
            "published_at": _published_at_text(record),
            "fixed_comment": fixed_comment,
            "comment_thread_id": comment_thread_id,
            "fixed_comment_posted_at": "DB" if record.get("fixed_comment_posted") else "",
            "fixed_comment_pinned_at": "",
            "already_posted": already_posted,
            "auto_posted": False,
            "auto_submitted_at": "",
        })
    results.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    return _filter_existing_public_videos(results, context)


def submit_fixed_comment_job(history_name: str, auto_posted: bool = False, profile_id: str | None = None) -> str:
    if _is_unsafe_history_name(history_name):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
    context = _fixed_comment_context(profile_id)
    theme_dir = _safe_fixed_comment_theme_dir(history_name, context)
    if not os.path.isdir(theme_dir) or not _is_fixed_comment_folder(theme_dir, context):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    mgr = get_job_manager()
    job = mgr.create_job("fixed_comment")
    profile_note = f" profile={profile_id}" if profile_id else ""
    _log(job, f"固定コメントジョブを登録: {history_name}{profile_note}", "info")
    mgr.submit(job, _run_fixed_comment, history_name, auto_posted, profile_id)
    return job.job_id


def mark_fixed_comment_posted(history_name: str, profile_id: str | None = None) -> dict[str, Any]:
    if _is_unsafe_history_name(history_name):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")

    context = _fixed_comment_context(profile_id)
    theme_dir = _safe_fixed_comment_theme_dir(history_name, context)
    if not os.path.isdir(theme_dir) or not _is_fixed_comment_folder(theme_dir, context):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    local_id = os.path.basename(theme_dir)
    record = _fixed_comment_record(local_id, context)
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="DBに固定コメント対象がありません")

    video_id = str(record.get("video_id") or "")
    if not video_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="video_id がありません")

    fixed_comment = str(record.get("fixed_comment") or "").strip()
    if not fixed_comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="固定コメントが設定されていません")

    recorded_at = _now_local_iso()
    _mark_fixed_comment_db(local_id, comment_thread_id=record.get("comment_thread_id") or None, context=context)

    return {
        "history_name": history_name,
        "video_id": video_id,
        "fixed_comment_posted_at": recorded_at,
    }


def _run_fixed_comment(job: Job, history_name: str, auto_posted: bool = False, profile_id: str | None = None) -> dict[str, Any]:
    """job_manager 経由（Web/runner 上）の固定コメント投稿。中核は post_fixed_comment_now と共有。"""
    return post_fixed_comment_now(
        history_name,
        profile_id=profile_id,
        auto_posted=auto_posted,
        log=lambda msg, tag="info": _log(job, msg, tag),
        is_cancelled=job.cancel_event.is_set,
    )


def post_fixed_comment_now(
    history_name: str,
    profile_id: str | None = None,
    auto_posted: bool = False,
    log=None,
    is_cancelled=None,
) -> dict[str, Any]:
    """固定コメントを YouTube へ直接投稿する（job_manager / runner を介さない）。

    Web UI が起動していなくても呼べる中核処理。`log(msg, tag)` は進捗ログ用コールバック
    （省略時は無出力）、`is_cancelled()` はキャンセル判定（省略時は常に継続）。
    """
    if log is None:
        def log(_msg, _tag="info"):
            return None
    if is_cancelled is None:
        def is_cancelled():
            return False

    context = _fixed_comment_context(profile_id)
    theme_dir = _safe_fixed_comment_theme_dir(history_name, context)
    if not os.path.isdir(theme_dir):
        raise FileNotFoundError(f"履歴フォルダが見つかりません: {history_name}")

    local_id = os.path.basename(theme_dir)
    record = _fixed_comment_record(local_id, context)
    if not record:
        raise ValueError("DBに固定コメント対象がありません")

    video_id = str(record.get("video_id") or "")
    if not video_id:
        raise ValueError("video_id がありません（先にアップロードしてください）")

    fixed_comment = str(record.get("fixed_comment") or "").strip()
    if not fixed_comment:
        raise ValueError("固定コメントが設定されていません")

    already_posted_id = record.get("comment_thread_id") or record.get("fixed_comment_posted")
    if already_posted_id:
        raise ValueError(f"既に投稿済みです (comment_thread_id={already_posted_id})")

    publish_status = str(record.get("publish_status") or "").lower()
    if publish_status not in ("published", "public", "manual_published"):
        log(f"注意: 動画が非公開または予約状態です (status={publish_status})", "warning")

    log(f"固定コメント投稿中: video_id={video_id}", "info")
    if is_cancelled():
        return {"cancelled": True}

    # 二重投稿防止: YouTube API を呼ぶ「前」に DB 上で投稿権を原子的に確保する。
    # SQLite は書き込みを直列化するため、同時実行でも UPDATE が成立するのは1プロセスだけ。
    if not _claim_fixed_comment(local_id, context):
        log("別の処理が投稿中のためスキップしました", "warning")
        return {"skipped": True, "reason": "already_claimed", "video_id": video_id}

    try:
        from core.youtube_uploader import post_comment
        comment_thread_id = post_comment(
            video_id=video_id,
            comment_text=fixed_comment,
            progress_callback=lambda msg: log(msg, "info"),
            profile_id=context.get("profile_id"),
        )
    except Exception as e:
        _release_fixed_comment_claim(local_id, context)  # 失敗したら投稿権を戻して再試行可能にする
        log(f"投稿エラー: {e}", "error")
        raise

    if not comment_thread_id:
        _release_fixed_comment_claim(local_id, context)
        raise Exception("コメント投稿が失敗しました（YouTube API がIDを返しませんでした）")

    log(f"固定コメント投稿完了: comment_thread_id={comment_thread_id}", "success")

    _mark_fixed_comment_db(local_id, comment_thread_id=comment_thread_id, context=context)

    return {"comment_thread_id": comment_thread_id, "video_id": video_id, "auto_posted": auto_posted}


def _iter_candidate_dirs(context: dict[str, Any]) -> Iterable[tuple[str, str]]:
    output_videos_dir = context["videos_dir"]
    try:
        names = sorted(os.listdir(output_videos_dir), reverse=True)
    except OSError:
        names = []

    for name in names:
        if is_video_folder(name):
            path = os.path.join(output_videos_dir, name)
            if os.path.isdir(path):
                yield name, path

    uploaded_dir = context["uploaded_dir"]
    try:
        uploaded_names = sorted(os.listdir(uploaded_dir), reverse=True)
    except OSError:
        return

    for name in uploaded_names:
        path = os.path.join(uploaded_dir, name)
        if os.path.isdir(path):
            yield os.path.join("000_uploaded", name), path


def _fixed_comment_record(local_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or _fixed_comment_context(None)
    db_path = context["db_path"]
    if not os.path.isfile(db_path):
        if context.get("profile_id"):
            return {}
        initialize_db()
    conn, manager = _open_metadata_connection(context)
    try:
        row = conn.execute(
            """
            SELECT v.local_id,
                   COALESCE(ri.video_title, v.title, v.local_id) AS title,
                   vm.fixed_comment,
                   ys.youtube_video_id AS video_id,
                   ys.publish_status,
                   ys.publish_at,
                   ys.uploaded_at,
                   ys.published_at,
                   ys.fixed_comment_posted,
                   ys.fixed_comment_id AS comment_thread_id
            FROM videos v
            LEFT JOIN render_info ri ON ri.local_id = v.local_id
            LEFT JOIN video_metadata vm ON vm.local_id = v.local_id
            LEFT JOIN youtube_status ys ON ys.local_id = v.local_id
            WHERE v.local_id=?
            """,
            (local_id,),
        ).fetchone()
    finally:
        _close_metadata_connection(conn, manager)
    return dict(row) if row else {}


def _fixed_comment_records_bulk(local_ids: list[str], context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """候補一覧用: 複数 local_id のレコードを1クエリで取得する（N+1回避）。"""
    if not local_ids:
        return {}
    db_path = context["db_path"]
    if not os.path.isfile(db_path):
        if context.get("profile_id"):
            return {}
        initialize_db()
    placeholders = ",".join("?" * len(local_ids))
    conn, manager = _open_metadata_connection(context)
    try:
        rows = conn.execute(
            f"""
            SELECT v.local_id,
                   COALESCE(ri.video_title, v.title, v.local_id) AS title,
                   vm.fixed_comment,
                   ys.youtube_video_id AS video_id,
                   ys.publish_status,
                   ys.publish_at,
                   ys.uploaded_at,
                   ys.published_at,
                   ys.fixed_comment_posted,
                   ys.fixed_comment_id AS comment_thread_id
            FROM videos v
            LEFT JOIN render_info ri ON ri.local_id = v.local_id
            LEFT JOIN video_metadata vm ON vm.local_id = v.local_id
            LEFT JOIN youtube_status ys ON ys.local_id = v.local_id
            WHERE v.local_id IN ({placeholders})
            """,
            local_ids,
        ).fetchall()
    finally:
        _close_metadata_connection(conn, manager)
    return {r["local_id"]: dict(r) for r in rows}


def _mark_fixed_comment_db(local_id: str, comment_thread_id: str | None = None, context: dict[str, Any] | None = None) -> None:
    context = context or _fixed_comment_context(None)
    db_path = context["db_path"]
    if not os.path.isfile(db_path):
        if context.get("profile_id"):
            return
        initialize_db()
    conn, manager = _open_metadata_connection(context)
    try:
        conn.execute(
            """
            UPDATE youtube_status
            SET fixed_comment_posted=1,
                fixed_comment_id=COALESCE(?, fixed_comment_id)
            WHERE local_id=?
            """,
            (comment_thread_id, local_id),
        )
        conn.commit()
    finally:
        _close_metadata_connection(conn, manager)


def _claim_fixed_comment(local_id: str, context: dict[str, Any]) -> bool:
    """投稿前に DB 上で原子的に投稿権を確保する。確保できたら True。

    `fixed_comment_posted` を 0→1 へ条件付き UPDATE する。複数プロセス（手動投稿と
    OSタスクなど）が同時に同じ動画を処理しても、UPDATE が成立するのは1プロセスだけなので
    YouTube API を呼ぶ前に排他でき、二重投稿を防げる。投稿失敗時は _release で戻す。
    """
    conn, manager = _open_metadata_connection(context)
    try:
        cur = conn.execute(
            """
            UPDATE youtube_status
            SET fixed_comment_posted=1
            WHERE local_id=?
              AND COALESCE(fixed_comment_posted,0)=0
              AND COALESCE(fixed_comment_id,'')=''
            """,
            (local_id,),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        _close_metadata_connection(conn, manager)


def _release_fixed_comment_claim(local_id: str, context: dict[str, Any]) -> None:
    """投稿に失敗したときに、確保した投稿権（fixed_comment_posted）を戻して再試行可能にする。"""
    conn, manager = _open_metadata_connection(context)
    try:
        conn.execute(
            "UPDATE youtube_status SET fixed_comment_posted=0 "
            "WHERE local_id=? AND COALESCE(fixed_comment_id,'')=''",
            (local_id,),
        )
        conn.commit()
    finally:
        _close_metadata_connection(conn, manager)


def _is_local_displayable_publish_status(publish_status: str) -> bool:
    # YouTube API による実公開確認 (_filter_existing_public_videos) が最終フィルター。
    # 予約投稿は公開後もDB側に scheduled/reserved が残ることがあるため、ローカル状態だけでは除外しない。
    return True


def _published_at_text(upload_record: dict) -> str:
    return str(
        upload_record.get("published_at")
        or upload_record.get("uploaded_at")
        or upload_record.get("publish_at")
        or ""
    ).strip()


def _filter_existing_public_videos(candidates: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    video_ids = sorted({str(item.get("video_id") or "").strip() for item in candidates if item.get("video_id")})
    statuses = (
        _fetch_youtube_statuses(video_ids, context)
        if context.get("profile_id")
        else _fetch_youtube_statuses(video_ids)
    )
    if statuses is None:
        return candidates

    filtered = []
    for item in candidates:
        video_id = str(item.get("video_id") or "").strip()
        status = statuses.get(video_id)
        if not status:
            continue

        privacy = str(status.get("privacyStatus") or "").lower()
        if privacy != "public":
            continue

        item = dict(item)
        item["publish_status"] = "public"
        item["published_at"] = status.get("publishedAt") or item.get("published_at", "")
        item["title"] = status.get("title") or item.get("title", "")
        filtered.append(item)
    return filtered


def _fetch_youtube_statuses(video_ids: list[str], context: dict[str, Any] | None = None) -> dict[str, dict] | None:
    if not video_ids:
        return {}
    from core.youtube_uploader import get_video_statuses
    return get_video_statuses(video_ids, profile_id=(context or {}).get("profile_id"))


def _is_unsafe_history_name(history_name: str) -> bool:
    normalized = history_name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    return (
        not history_name
        or os.path.isabs(history_name)
        or ".." in parts
        or normalized.startswith("/")
        or (len(parts) > 2)
        or (len(parts) == 2 and parts[0] != "000_uploaded")
    )


def _safe_fixed_comment_theme_dir(history_name: str, context: dict[str, Any] | None = None) -> str:
    context = context or _fixed_comment_context(None)
    normalized = history_name.replace("\\", "/")
    if context.get("profile_id"):
        if normalized.startswith("000_uploaded/"):
            return _safe_join(context["output_root"], *normalized.split("/"))
        return _safe_join(context["videos_dir"], *normalized.split("/"))
    if normalized.startswith("000_uploaded/"):
        return safe_output_path(normalized, output_base=get_output_root())
    return safe_output_path(normalized, output_base=get_output_videos_dir())


def _is_fixed_comment_folder(theme_dir: str, context: dict[str, Any] | None = None) -> bool:
    basename = os.path.basename(theme_dir)
    record = _fixed_comment_record(basename, context)
    return bool(record.get("video_id") and record.get("fixed_comment"))


def _fixed_comment_context(profile_id: str | None) -> dict[str, Any]:
    if profile_id:
        from core.channel_profile import get_profile
        profile = get_profile(profile_id)
        if profile is None:
            raise ValueError(f"チャンネルプロファイルが見つかりません: {profile_id}")
        output_root = profile.output_root_abs
        return {
            "profile_id": profile.profile_id,
            "output_root": output_root,
            "videos_dir": os.path.join(output_root, "videos"),
            "uploaded_dir": os.path.join(output_root, "000_uploaded"),
            "db_path": os.path.join(output_root, "000_data", "metadata.db"),
        }

    output_root = get_output_root()
    return {
        "profile_id": None,
        "output_root": output_root,
        "videos_dir": get_output_videos_dir(),
        "uploaded_dir": get_uploaded_dir(),
        "db_path": os.path.join(output_root, "000_data", "metadata.db"),
    }


def _safe_join(base: str, *parts: str) -> str:
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *parts))
    if os.path.commonpath([base_abs, target]) != base_abs:
        raise ValueError("出力フォルダ外へのアクセスは許可されていません")
    return target


def _open_metadata_connection(context: dict[str, Any]) -> tuple[sqlite3.Connection, ManagedConnection | None]:
    if context.get("profile_id"):
        conn = sqlite3.connect(context["db_path"])
        conn.row_factory = sqlite3.Row
        return conn, None
    manager = ManagedConnection()
    return manager.__enter__(), manager


def _close_metadata_connection(conn: sqlite3.Connection, manager: ManagedConnection | None) -> None:
    if manager is not None:
        manager.__exit__(None, None, None)
    else:
        conn.close()


def _now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
