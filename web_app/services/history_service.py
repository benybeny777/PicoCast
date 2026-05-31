"""
生成履歴一覧・詳細取得サービス。
output/ 配下の生成物を走査し、メタ情報は metadata.db から取得する。
"""
import os
from typing import Any

from core.output_paths import get_output_videos_dir, get_uploaded_dir, get_output_root
from core.metadata_db import ManagedConnection
from web_app.security import is_video_folder, safe_output_path

def _is_management(name: str) -> bool:
    """[Shorts]/[Long] プレフィックスがないフォルダは管理用として扱う。"""
    return not is_video_folder(name)


def _find_mp4(theme_dir: str) -> str | None:
    try:
        for name in sorted(os.listdir(theme_dir)):
            if name.endswith("_native.mp4") or name == "video_native.mp4":
                return name
    except OSError:
        pass
    return None


def _find_thumbnail(theme_dir: str) -> str | None:
    thumb_dir = os.path.join(theme_dir, "thumbnails")
    if os.path.isfile(os.path.join(thumb_dir, "thumbnail.png")):
        return "thumbnails/thumbnail.png"
    if os.path.isfile(os.path.join(theme_dir, "thumbnail.png")):
        return "thumbnail.png"
    return None


def _video_format(name: str, value: str | None) -> str:
    value = str(value or "").strip()
    if value:
        low = value.lower()
        if low in ("shorts", "short", "ショート"):
            return "Shorts"
        if low in ("long", "ロング"):
            return "Long"
        return value
    from config import config
    if name.startswith(config.FOLDER_PREFIX_SHORTS):
        return "Shorts"
    if name.startswith(config.FOLDER_PREFIX_LONG):
        return "Long"
    if name.startswith(config.FOLDER_PREFIX_MEETING):
        return "ネタ会議"
    return ""


def _history_db_info(local_id: str) -> dict[str, Any]:
    with ManagedConnection() as conn:
        row = conn.execute(
            """
            SELECT v.title,
                   COALESCE(ri.video_format, vm.video_format, v.video_type) AS video_format,
                   COALESCE(ri.video_title, v.title) AS video_title,
                   ri.render_engine,
                   vm.generation_type,
                   vm.source_video_title,
                   vm.purpose,
                   vm.fixed_comment,
                   sq.opening_score,
                   sq.actual_duration,
                   sq.actual_duration_status,
                   sq.final_review_score,
                   sq.validation_status
            FROM videos v
            LEFT JOIN render_info ri ON ri.local_id = v.local_id
            LEFT JOIN video_metadata vm ON vm.local_id = v.local_id
            LEFT JOIN script_quality sq ON sq.local_id = v.local_id
            WHERE v.local_id=?
            """,
            (local_id,),
        ).fetchone()
    return dict(row) if row else {}


def _fetch_yt_status_bulk(local_ids: list[str]) -> dict[str, dict]:
    """youtube_status テーブルを一括取得して local_id → dict で返す。"""
    if not local_ids:
        return {}
    placeholders = ",".join("?" * len(local_ids))
    with ManagedConnection() as conn:
        rows = conn.execute(
            f"SELECT local_id, youtube_video_id, publish_status FROM youtube_status"
            f" WHERE local_id IN ({placeholders})",
            local_ids,
        ).fetchall()
    return {r["local_id"]: dict(r) for r in rows}


def _fetch_known_video_ids() -> set[str]:
    """videos テーブルに存在する local_id を返す。uploaded 側の孤立フォルダ除外に使う。"""
    with ManagedConnection() as conn:
        rows = conn.execute("SELECT local_id FROM videos").fetchall()
    return {r["local_id"] for r in rows}


def _fetch_uploaded_video_ids_with_youtube_id() -> set[str]:
    """YouTube ID がDBにある uploaded 履歴の local_id を返す。"""
    with ManagedConnection() as conn:
        rows = conn.execute(
            """
            SELECT local_id
            FROM youtube_status
            WHERE youtube_video_id IS NOT NULL AND youtube_video_id != ''
            """
        ).fetchall()
    return {r["local_id"] for r in rows}


def list_histories(include_management: bool = False, include_uploaded: bool = False) -> list[dict[str, Any]]:
    """
    videos/（生成中・未アップロード）を走査する。
    include_uploaded=True の場合のみ 000_uploaded/（アップロード済みアーカイブ）も走査する。
    同名フォルダは videos/ 優先。
    アップロード状態は youtube_status テーブルから取得する。
    """
    output_root = get_output_root()
    known_video_ids = _fetch_known_video_ids()
    uploaded_ids_with_youtube = _fetch_uploaded_video_ids_with_youtube_id()
    seen: set[str] = set()
    items: list[dict[str, Any]] = []

    search_dirs = [get_output_videos_dir()]
    if include_uploaded:
        search_dirs.append(get_uploaded_dir())

    for search_dir in search_dirs:
        is_uploaded_dir = os.path.normpath(search_dir) == os.path.normpath(get_uploaded_dir())
        try:
            entries = sorted(os.scandir(search_dir), key=lambda e: e.name, reverse=True)
        except OSError:
            continue

        for entry in entries:
            name = entry.name
            if name in seen or name.startswith("."):
                continue
            if not entry.is_dir():
                continue
            if is_uploaded_dir and (name not in known_video_ids or name not in uploaded_ids_with_youtube):
                continue
            is_mgmt = _is_management(name)
            if is_mgmt and not include_management:
                continue
            seen.add(name)
            try:
                theme_dir = safe_output_path(entry.path, output_base=output_root)
            except Exception:
                continue

            db_info = _history_db_info(name)

            mp4_name = _find_mp4(theme_dir)
            thumb_rel = _find_thumbnail(theme_dir)
            video_format = _video_format(name, db_info.get("video_format"))

            items.append({
                "name": name,
                "is_management": is_mgmt,
                "title": db_info.get("video_title") or name,
                "video_format": video_format,
                "generation_kind": db_info.get("generation_type") or "",
                "source_video_title": db_info.get("source_video_title") or "",
                "generation_purpose": db_info.get("purpose") or "",
                "render_engine": db_info.get("render_engine") or "",
                "has_mp4": mp4_name is not None,
                "mp4_name": mp4_name,
                "has_thumbnail": thumb_rel is not None,
                "thumbnail_rel": thumb_rel,
                "opening_score": db_info.get("opening_score"),
                "final_score": db_info.get("final_review_score"),
            })

    # youtube_status を一括取得して付与
    yt_map = _fetch_yt_status_bulk([it["name"] for it in items])
    for it in items:
        yt = yt_map.get(it["name"], {})
        it["upload_status"] = yt.get("publish_status") or ""
        it["video_id"] = yt.get("youtube_video_id") or ""

    return items


def get_history_detail(history_name: str) -> dict[str, Any] | None:
    if ".." in history_name or "/" in history_name or "\\" in history_name:
        return None

    output_root = get_output_root()
    theme_dir = None
    for base in (get_output_videos_dir(), get_uploaded_dir()):
        candidate = os.path.join(base, history_name)
        if not os.path.isdir(candidate):
            continue
        if os.path.normpath(base) == os.path.normpath(get_uploaded_dir()):
            with ManagedConnection() as conn:
                exists = conn.execute(
                    """
                    SELECT 1
                    FROM videos v
                    JOIN youtube_status ys ON ys.local_id = v.local_id
                    WHERE v.local_id=?
                      AND ys.youtube_video_id IS NOT NULL
                      AND ys.youtube_video_id != ''
                    """,
                    (history_name,),
                ).fetchone()
            if not exists:
                return None
        try:
            theme_dir = safe_output_path(candidate, output_base=output_root)
            break
        except Exception:
            continue
    if theme_dir is None:
        return None

    script_txt = _read_text(os.path.join(theme_dir, "script.txt"))
    db_info = _history_db_info(history_name)
    opening_review = {"final_score": db_info.get("opening_score")} if db_info.get("opening_score") is not None else {}
    duration_review = {
        "actual_duration": db_info.get("actual_duration"),
        "actual_duration_status": db_info.get("actual_duration_status"),
    } if db_info.get("actual_duration") is not None or db_info.get("actual_duration_status") else {}
    final_review = {"final_score": db_info.get("final_review_score")} if db_info.get("final_review_score") is not None else {}
    render_info = {
        "video_title": db_info.get("video_title") or db_info.get("title") or history_name,
        "video_format": db_info.get("video_format") or "",
        "render_engine": db_info.get("render_engine") or "",
        "fixed_comment": db_info.get("fixed_comment") or "",
    }

    # アップロード状態は youtube_status テーブルから取得
    local_id = os.path.basename(theme_dir)
    with ManagedConnection() as conn:
        yt_row = conn.execute(
            "SELECT youtube_video_id, publish_status, publish_at,"
            " published_at, fixed_comment_id"
            " FROM youtube_status WHERE local_id=?",
            (local_id,),
        ).fetchone()
    upload_record: dict[str, Any] = {}
    if yt_row:
        upload_record = {
            "video_id":         yt_row["youtube_video_id"] or "",
            "publish_status":   yt_row["publish_status"] or "",
            "publish_at":       yt_row["publish_at"] or "",
            "published_at":     yt_row["published_at"] or "",
            "comment_thread_id": yt_row["fixed_comment_id"] or "",
        }

    mp4_name = _find_mp4(theme_dir)
    thumb_rel = _find_thumbnail(theme_dir)

    # Long サムネA/B/C
    long_thumbnails = []
    thumbs_dir = os.path.join(theme_dir, "thumbnails")
    if os.path.isdir(thumbs_dir):
        for fname in sorted(os.listdir(thumbs_dir)):
            if "_thumbnail_" in fname and fname.endswith(".png"):
                long_thumbnails.append(f"thumbnails/{fname}")

    # 背景画像
    backgrounds = []
    bg_dir = os.path.join(theme_dir, "backgrounds")
    if os.path.isdir(bg_dir):
        for fname in sorted(os.listdir(bg_dir)):
            if fname.endswith(".png"):
                backgrounds.append(f"backgrounds/{fname}")

    has_poll_copy = False
    has_fixed_comment = bool(db_info.get("fixed_comment"))

    return {
        "name": history_name,
        "theme_dir": theme_dir,
        "script_txt": script_txt,
        "metadata_txt": "",
        "opening_review": opening_review,
        "duration_review": duration_review,
        "final_review": final_review,
        "render_info": render_info,
        "upload_record": upload_record,
        "has_mp4": mp4_name is not None,
        "mp4_name": mp4_name,
        "has_thumbnail": thumb_rel is not None,
        "thumbnail_rel": thumb_rel,
        "long_thumbnails": long_thumbnails,
        "backgrounds": backgrounds,
        "has_poll_copy": has_poll_copy,
        "has_fixed_comment": has_fixed_comment,
    }


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
