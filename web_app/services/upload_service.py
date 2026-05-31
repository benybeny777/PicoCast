"""
YouTubeアップロードサービス。
二重アップロード防止チェックを行い、ジョブとして実行する。
"""
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from core.output_paths import get_output_videos_dir, get_uploaded_dir, get_backups_dir
from web_app.job_manager import Job, _log, get_job_manager
from web_app.security import is_video_folder, safe_output_path

_JST = timezone(timedelta(hours=9))
_slot_lock = threading.Lock()  # スロット割り当ての同時実行を防ぐ


def list_upload_candidates() -> list[dict[str, Any]]:
    """videos/ 配下でMP4がある動画を返す。"""
    candidates = []
    seen: set[str] = set()

    # output/ 直下のみ走査（000_uploaded/ は表示しない）
    search_dirs = [
        (get_output_videos_dir(), ""),
    ]

    for search_dir, prefix in search_dirs:
        try:
            names = sorted(os.listdir(search_dir), reverse=True)
        except OSError:
            continue

        for name in names:
            if not is_video_folder(name):
                continue
            if name in seen:
                continue
            seen.add(name)
            rel = prefix + name
            try:
                theme_dir = safe_output_path(rel, output_base=get_output_videos_dir())
            except Exception:
                continue
            if not os.path.isdir(theme_dir):
                continue

            mp4_path = _find_mp4(theme_dir)
            if not mp4_path:
                continue

            local_id = os.path.basename(theme_dir)
            from core.metadata_db import get_render_info, ManagedConnection
            ri = get_render_info(local_id)
            publish_at = ""
            with ManagedConnection() as _conn:
                _row = _conn.execute(
                    "SELECT publish_at FROM youtube_status WHERE local_id=?", (local_id,)
                ).fetchone()
                if _row:
                    publish_at = _row["publish_at"] or ""

            candidates.append({
                "name": rel,
                "mp4_path": mp4_path,
                "mp4_filename": os.path.basename(mp4_path),
                "title": ri.get("video_title") or name,
                "video_format": ri.get("video_format", ""),
                "publish_at": publish_at,
            })
    return candidates


def submit_upload_job(history_name: str) -> str:
    if ".." in history_name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="無効な履歴名です")
    theme_dir = safe_output_path(history_name, output_base=get_output_videos_dir())
    if not os.path.isdir(theme_dir) or not is_video_folder(os.path.basename(theme_dir)):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="履歴フォルダが見つかりません")

    mgr = get_job_manager()
    job = mgr.create_job("upload")
    _log(job, f"アップロードジョブを登録: {history_name}", "info")
    mgr.submit(job, _run_upload, history_name)
    return job.job_id


def _run_upload(job: Job, history_name: str) -> dict[str, Any]:
    from core.channel_info import get_channel_info, log_channel_info
    from core.youtube_uploader import upload_video

    # アップロード直前チャンネル確認ログ
    log_channel_info()
    ch = get_channel_info()
    _log(job, f"[CHANNEL] name={ch['name'] or ''}", "info")
    _log(job, f"[CHANNEL] handle={ch['handle'] or ''}", "info")
    _log(job, f"[CHANNEL] theme={ch['theme'] or ''}", "info")
    if not ch["upload_allowed"]:
        missing = [w["message"] for w in ch["warnings"] if w["level"] == "error"]
        raise RuntimeError("チャンネル設定不足のためアップロード中止: " + "、".join(missing))

    theme_dir = safe_output_path(history_name, output_base=get_output_videos_dir())
    if not os.path.isdir(theme_dir):
        raise FileNotFoundError(f"履歴フォルダが見つかりません: {history_name}")

    mp4_path = _find_mp4(theme_dir)
    if not mp4_path:
        raise FileNotFoundError(f"MP4ファイルが見つかりません: {history_name}")

    from core.metadata_db import get_render_info
    local_id = os.path.basename(theme_dir)
    render_info = get_render_info(local_id)
    _log(job, f"アップロード開始: {mp4_path}", "info")

    if job.cancel_event.is_set():
        return {"cancelled": True}

    # サムネイルパスを探す
    thumbnail_path = os.path.join(theme_dir, "thumbnails", "thumbnail.png")
    if not os.path.exists(thumbnail_path):
        thumbnail_path = None

    try:
        video_id = upload_video(
            mp4_path=mp4_path,
            title=render_info.get("video_title", history_name),
            description=render_info.get("description", ""),
            tags=render_info.get("tags", []),
            thumbnail_path=thumbnail_path,
            progress_callback=lambda msg, tag="info": _log(job, msg, tag),
        )
    except Exception as e:
        _log(job, f"アップロードエラー: {e}", "error")
        raise

    _log(job, f"アップロード完了: video_id={video_id}", "success")

    # スロットを取得して YouTube でスケジュール設定
    # 複数本同時アップロード時の競合を防ぐためロックで直列化する
    from core.playlist_resolver import resolve_video_type
    video_format = str(render_info.get("video_format") or "").strip()
    screen_format = str(render_info.get("screen_format") or "").strip()
    video_type = resolve_video_type(video_format, screen_format)
    publish_at_iso: str | None = None
    with _slot_lock:
        try:
            from core.upload_scheduler import assign_slots_from_youtube
            from core.youtube_uploader import update_video_publish_time
            slots = assign_slots_from_youtube(1, video_type)
            if slots:
                slot_dt = slots[0]
                _log(job, f"スロット割り当て: {slot_dt.isoformat()}", "info")
                ok = update_video_publish_time(
                    video_id, slot_dt,
                    progress_callback=lambda msg: _log(job, msg, "info"),
                )
                if ok:
                    publish_at_iso = slot_dt.isoformat()
                    _log(job, f"公開予定を設定しました: {publish_at_iso}", "success")
                else:
                    _log(job, "公開予定の設定に失敗しました。非公開のままです。", "warning")
            else:
                _log(job, "空きスロットが見つかりませんでした。非公開のままです。", "warning")
        except Exception as e:
            _log(job, f"スロット設定エラー（非公開のまま続行）: {e}", "warning")

    # 再生リストへ追加
    playlist_categories: list[str] = render_info.get("playlist_categories") or []
    playlist_assignments: list[dict] = []
    if playlist_categories:
        # 新仕様: 台本の「再生リスト:」に従い形式別名へ解決して登録
        from core.playlist_resolver import resolve_playlist_title
        from core.youtube_uploader import create_playlist, add_video_to_playlist_by_name
        video_format = render_info.get("video_format", "")
        screen_format = render_info.get("screen_format", "")
        for cat in playlist_categories:
            resolved = resolve_playlist_title(cat, video_format, screen_format)
            entry: dict = {"category": cat, "resolved": resolved, "ok": False, "reason": ""}
            if resolved is None:
                entry["reason"] = f"動画形式が不明なため再生リストを特定できません（video_format={video_format!r}, screen_format={screen_format!r}）"
                _log(job, f"再生リスト解決不能: {entry['reason']}", "warning")
                playlist_assignments.append(entry)
                continue
            create_result = create_playlist(resolved)
            if not create_result["ok"]:
                entry["reason"] = f"再生リスト作成失敗: {create_result['reason']}"
                _log(job, f"再生リスト作成失敗: {resolved} — {create_result['reason']}", "error")
                playlist_assignments.append(entry)
                continue
            add_result = add_video_to_playlist_by_name(
                video_id, resolved,
                progress_callback=lambda msg: _log(job, msg, "info"),
            )
            entry["ok"] = add_result["ok"]
            entry["reason"] = add_result["reason"]
            if add_result["ok"]:
                if add_result.get("skipped"):
                    _log(job, f"再生リスト登録済み: {resolved}", "info")
                else:
                    _log(job, f"再生リスト追加: {resolved}", "success")
                # DB に再生リスト登録状態を保存
                try:
                    from core.metadata_db import upsert_playlist_registration, is_initialized, initialize_db
                    if not is_initialized():
                        initialize_db()
                    local_id = os.path.basename(theme_dir)
                    upsert_playlist_registration(
                        local_id, video_id, resolved,
                        create_result.get("id"), status="registered")
                except Exception as _pl_e:
                    _log(job, f"⚠ 再生リストDB同期失敗: {_pl_e}", "warning")
            else:
                _log(job, f"再生リスト追加失敗: {resolved} — {add_result['reason']}", "error")
            playlist_assignments.append(entry)
    else:
        # 後方互換: 台本に「再生リスト:」なし → Long のみ LONG_UPLOAD_PLAYLIST_NAME へ追加
        if video_type == "long":
            try:
                from config import config as _cfg
                from core.youtube_uploader import add_video_to_playlist_by_name
                playlist_name = _cfg.LONG_UPLOAD_PLAYLIST_NAME
                if playlist_name:
                    result = add_video_to_playlist_by_name(
                        video_id, playlist_name,
                        progress_callback=lambda msg: _log(job, msg, "info"),
                    )
                    if result["ok"] and not result.get("skipped"):
                        _log(job, f"再生リスト追加: {playlist_name}", "success")
                    elif result.get("skipped"):
                        _log(job, f"再生リスト追加済み: {playlist_name}", "info")
                    else:
                        _log(job, f"再生リスト追加スキップ: {result.get('reason', '不明')}", "warning")
            except Exception as e:
                _log(job, f"再生リスト追加エラー（続行）: {e}", "warning")

    # youtube_status を DB に直接書き込む
    uploaded_at = datetime.now(_JST).isoformat()
    upload_record = {
        "video_id": video_id,
        "title": render_info.get("video_title", history_name),
        "video_type": video_type,
        "uploaded_at": uploaded_at,
        "publish_status": "scheduled" if publish_at_iso else "private",
        "publish_at": publish_at_iso,
    }
    try:
        from core.metadata_db import upsert_youtube_status, ManagedConnection, initialize_db, is_initialized
        if not is_initialized():
            initialize_db()
        with ManagedConnection() as _conn:
            upsert_youtube_status(_conn, local_id, upload_record)
            _conn.commit()
        _log(job, "youtube_status を DB に保存しました", "info")
    except Exception as _db_e:
        _log(job, f"⚠ DB保存失敗（続行）: {_db_e}", "warning")

    # 000_uploaded/ へフォルダ移動（既に移動済みの場合はスキップ）
    folder_name = os.path.basename(theme_dir)
    uploaded_dir = get_uploaded_dir()
    dest = os.path.join(uploaded_dir, folder_name)
    if os.path.realpath(theme_dir) != os.path.realpath(dest):
        os.makedirs(uploaded_dir, exist_ok=True)
        shutil.move(theme_dir, dest)
        _log(job, f"フォルダを移動しました → 000_uploaded/{folder_name}", "info")
    else:
        _log(job, f"フォルダは既に 000_uploaded/{folder_name} にあります", "info")

    # 000_backups/ から同テーマのバックアップを削除
    backups_dir = get_backups_dir()
    prefix = f"{folder_name}_"
    removed = 0
    if os.path.isdir(backups_dir):
        for entry in os.listdir(backups_dir):
            entry_path = os.path.join(backups_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry == folder_name or entry.startswith(prefix):
                shutil.rmtree(entry_path)
                removed += 1
    if removed:
        _log(job, f"バックアップを削除しました: {removed}件", "info")

    return {"video_id": video_id, "message": f"video_id={video_id}"}


def _find_mp4(theme_dir: str) -> str | None:
    try:
        for fname in sorted(os.listdir(theme_dir)):
            if fname.endswith("_native.mp4") or fname == "video_native.mp4":
                return os.path.join(theme_dir, fname)
    except OSError:
        pass
    return None

