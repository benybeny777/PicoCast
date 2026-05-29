"""
スケジュール管理サービス。
upload_records.json 台帳ベースの設計を維持する。
破壊的操作（公開予定変更・削除・詰め直し）は確認必須。
"""
import json
import os
from typing import Any

from web_app.job_manager import Job, _log, get_job_manager


def list_schedule(
    video_type_filter: str = "all",
    include_published: bool = False,
) -> list[dict[str, Any]]:
    """YouTube API から直接スケジュールを取得して返す。publish_at はJST isoformat で返す。"""
    from datetime import datetime, timedelta, timezone
    from core.youtube_uploader import get_channel_upload_video_statuses

    JST = timezone(timedelta(hours=9))
    now_utc = datetime.now(timezone.utc)

    def _to_jst_iso(raw: str) -> str:
        """YouTube APIのUTC文字列をJST isoformat に変換する。"""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone(JST).isoformat()
        except Exception:
            return raw

    try:
        statuses = get_channel_upload_video_statuses()
    except Exception as e:
        raise RuntimeError(f"YouTube からスケジュール取得に失敗しました: {e}") from e

    result = []
    for video_id, s in statuses.items():
        privacy = str(s.get("privacyStatus") or "").lower()
        raw_publish_at = str(s.get("publishAt") or "").strip()
        publish_at = _to_jst_iso(raw_publish_at) if raw_publish_at else ""
        video_type = str(s.get("video_type") or "").lower()
        title = str(s.get("title") or "")

        is_published = privacy == "public"
        is_scheduled = privacy in ("private", "unlisted") and bool(publish_at) and _is_future(publish_at, now_utc)

        if not is_scheduled and not (include_published and is_published):
            continue

        if video_type_filter == "shorts" and video_type not in ("shorts", "short"):
            continue
        if video_type_filter == "long" and video_type != "long":
            continue

        result.append({
            "video_id": video_id,
            "title": title,
            "video_type": s.get("video_type", ""),
            "publish_at": publish_at,
            "publish_status": "published" if is_published else "scheduled",
            "privacy_status": privacy,
            "is_scheduled": is_scheduled,
            "is_published": is_published,
            "_local_path": "",
        })

    result.sort(key=lambda x: x.get("publish_at") or "")
    return result


def _is_future(publish_at_str: str, now_utc) -> bool:
    """publish_at が現在時刻より未来かどうかを返す。パース失敗時は True（安全側）。"""
    if not publish_at_str:
        return False
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(publish_at_str.replace("Z", "+00:00"))
        return dt > now_utc
    except Exception:
        return True


def submit_sync_job() -> str:
    mgr = get_job_manager()
    job = mgr.create_job("schedule_sync")
    _log(job, "スケジュール同期ジョブを登録しました", "info")
    mgr.submit(job, _run_sync)
    return job.job_id


def _run_sync(job: Job) -> dict[str, Any]:
    _log(job, "YouTube APIからスケジュールを同期中...", "info")
    if job.cancel_event.is_set():
        return {"cancelled": True}
    try:
        from core.upload_scheduler import sync_schedule_from_youtube
        result = sync_schedule_from_youtube()
        _log(job, f"同期完了: {result}", "success")
        return {"result": str(result)}
    except Exception as e:
        _log(job, f"同期エラー: {e}", "error")
        raise


def submit_rebalance_job() -> str:
    """スロット詰め直しの変更案を計算する（YouTube APIへの書き込みなし）。"""
    mgr = get_job_manager()
    job = mgr.create_job("schedule_rebalance")
    _log(job, "スロット詰め直し計算ジョブを登録しました", "info")
    mgr.submit(job, _run_rebalance)
    return job.job_id


def _fmt_jst(iso: str) -> str:
    """JST isoformat を読みやすい表示用文字列に変換する。"""
    try:
        from datetime import datetime, timedelta, timezone
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        jst = dt.astimezone(timezone(timedelta(hours=9)))
        return jst.strftime("%m/%d %H:%M JST")
    except Exception:
        return iso


def _run_rebalance(job: Job) -> dict[str, Any]:
    """YouTube APIから予約状態を取得してスロット詰め直し変更案を計算する。書き込みは行わない。"""
    _log(job, "スロット詰め直しを計算中（YouTube APIへの書き込みなし）...", "info")
    try:
        from core.upload_scheduler import rebalance_slots
        shorts_changes = rebalance_slots("shorts")
        long_changes = rebalance_slots("long")
        total = len(shorts_changes) + len(long_changes)

        _log(job, f"Shorts 変更案: {len(shorts_changes)}件", "info")
        for old, new, title in shorts_changes:
            _log(job, f"  {title}: {_fmt_jst(old)} → {_fmt_jst(new)}", "info")

        _log(job, f"Long 変更案: {len(long_changes)}件", "info")
        for old, new, title in long_changes:
            _log(job, f"  {title}: {_fmt_jst(old)} → {_fmt_jst(new)}", "info")

        _log(job, f"計算完了: 変更案 {total}件（YouTube未適用）", "success")
        return {
            "dry_run": True,
            "shorts_changes": [{"old": o, "new": n, "title": t} for o, n, t in shorts_changes],
            "long_changes": [{"old": o, "new": n, "title": t} for o, n, t in long_changes],
        }
    except Exception as e:
        _log(job, f"計算エラー: {e}", "error")
        raise


def submit_update_job(video_id: str, publish_at: str) -> dict[str, Any]:
    """公開予定変更をジョブとして登録する。"""
    mgr = get_job_manager()
    job = mgr.create_job("schedule_update")
    _log(job, f"公開予定変更ジョブを登録: {video_id}", "info")
    mgr.submit(job, _run_update_schedule, video_id, publish_at)
    return {"job_id": job.job_id, "status": "queued"}


def _run_update_schedule(job: Job, video_id: str, publish_at: str) -> dict[str, Any]:
    from datetime import datetime, timedelta, timezone
    from core.youtube_uploader import update_video_publish_time

    # publish_at をJST isoformat に正規化（フォームからはタイムゾーンなしで来る場合がある）
    _JST = timezone(timedelta(hours=9))
    try:
        dt = datetime.fromisoformat(publish_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_JST)
        publish_at_jst = dt.astimezone(_JST).isoformat()
    except Exception:
        publish_at_jst = publish_at

    _log(job, f"公開予定変更中: {video_id} → {publish_at_jst}", "info")
    ok = update_video_publish_time(
        video_id,
        publish_at_jst,
        progress_callback=lambda msg: _log(job, msg, "info"),
    )
    if not ok:
        raise Exception("YouTube API での公開予定変更に失敗しました")

    _update_local_record(video_id, publish_at_jst)
    _log(job, f"公開予定変更完了 (JST): {publish_at_jst}", "success")
    return {"video_id": video_id, "publish_at": publish_at_jst}


def _update_local_record(video_id: str, new_publish_at: str) -> None:
    """各動画の _meta/upload_record.json の publish_at を更新する。"""
    from core.upload_records import load_upload_records

    for rec in load_upload_records():
        if rec.get("video_id") == video_id:
            local_path = rec.get("_local_path")
            if local_path and os.path.isfile(local_path):
                rec["publish_at"] = new_publish_at
                rec_to_save = {k: v for k, v in rec.items() if k != "_local_path"}
                try:
                    with open(local_path, "w", encoding="utf-8") as f:
                        json.dump(rec_to_save, f, ensure_ascii=False, indent=2)
                except Exception as _e:
                    raise RuntimeError(f"Error: {_e}") from _e
            break


def update_schedule(video_id: str, publish_at: str) -> dict[str, Any]:
    """確認済み後に呼ばれる。ジョブとして公開予定変更を実行する。"""
    return submit_update_job(video_id, publish_at)


def delete_schedule(video_id: str) -> dict[str, Any]:
    """
    [DISABLED] YouTube Data API に動画削除エンドポイントはあるが、
    不可逆操作のため Web UI からは提供しない。YouTube Studio から手動で操作すること。
    """
    return {
        "disabled": True,
        "reason": "スケジュール削除は YouTube Studio から手動で行ってください。",
        "video_id": video_id,
    }
