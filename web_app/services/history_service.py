"""
生成履歴一覧・詳細取得サービス。
output/ 配下のフォルダを走査してメタ情報を集約する。
"""
import json
import os
from typing import Any

from core.output_paths import get_output_videos_dir, get_uploaded_dir, get_output_root
from web_app.security import is_video_folder, safe_output_path

def _is_management(name: str) -> bool:
    """[Shorts]/[Long] プレフィックスがないフォルダは管理用として扱う。"""
    return not is_video_folder(name)


def _safe_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


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


def _script_meta(theme_dir: str) -> dict[str, str]:
    script_text = _read_text(os.path.join(theme_dir, "script.txt"))
    if not script_text.strip():
        return {}
    from core.parser import ScriptParser
    items = ScriptParser.parse_string(script_text)
    return {it["type"]: it["text"] for it in items if it["type"] in ScriptParser.META_TYPES}


def _video_format(name: str, render_info: dict, script_meta: dict[str, str]) -> str:
    value = str(render_info.get("video_format") or script_meta.get("video_format") or "").strip()
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


def list_histories(include_management: bool = False) -> list[dict[str, Any]]:
    """
    videos/ と 000_uploaded/ の両方を走査する。
    移行後に 000_uploaded/ に移った旧動画も表示できるようにするため。
    同名フォルダが両方にある場合は videos/ を優先する。
    """
    output_root = get_output_root()
    results = []
    seen: set[str] = set()

    search_dirs = [
        get_output_videos_dir(),  # 生成中・未アップロード動画
        get_uploaded_dir(),       # アップロード済みアーカイブ（マイグレーション後も含む）
    ]

    for search_dir in search_dirs:
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
            is_mgmt = _is_management(name)
            if is_mgmt and not include_management:
                continue
            seen.add(name)
            try:
                theme_dir = safe_output_path(entry.path, output_base=output_root)
            except Exception:
                continue

            meta_d = os.path.join(theme_dir, "_meta")
            render_info = _safe_json(os.path.join(meta_d, "render_info.json"))
            opening_review = _safe_json(os.path.join(meta_d, "opening_review.json"))
            final_review = _safe_json(os.path.join(meta_d, "final_review.json"))
            upload_record = _safe_json(os.path.join(meta_d, "upload_record.json"))
            script_meta = _script_meta(theme_dir)

            mp4_name = _find_mp4(theme_dir)
            thumb_rel = _find_thumbnail(theme_dir)
            video_format = _video_format(name, render_info, script_meta)

            results.append({
                "name": name,
                "is_management": is_mgmt,
                "title": render_info.get("video_title") or script_meta.get("video_title") or name,
                "video_format": video_format,
                "generation_kind": render_info.get("generation_kind") or script_meta.get("generation_kind", ""),
                "source_video_title": render_info.get("source_video_title") or script_meta.get("source_video_title", ""),
                "generation_purpose": render_info.get("generation_purpose") or script_meta.get("generation_purpose", ""),
                "render_engine": render_info.get("render_engine", ""),
                "has_mp4": mp4_name is not None,
                "mp4_name": mp4_name,
                "has_thumbnail": thumb_rel is not None,
                "thumbnail_rel": thumb_rel,
                "opening_score": opening_review.get("final_score") or opening_review.get("overall_score"),
                "final_score": final_review.get("final_score"),
                "upload_status": upload_record.get("publish_status", ""),
                "video_id": upload_record.get("video_id", ""),
            })
    return results


def get_history_detail(history_name: str) -> dict[str, Any] | None:
    if ".." in history_name or "/" in history_name or "\\" in history_name:
        return None

    output_root = get_output_root()
    theme_dir = None

    # videos/ → 000_uploaded/ の順で探す
    for candidate_base in (get_output_videos_dir(), get_uploaded_dir()):
        candidate = os.path.join(candidate_base, history_name)
        if not os.path.isdir(candidate):
            continue
        try:
            theme_dir = safe_output_path(candidate, output_base=output_root)
            break
        except Exception:
            continue

    if theme_dir is None:
        return None

    meta_d = os.path.join(theme_dir, "_meta")

    script_txt = _read_text(os.path.join(theme_dir, "script.txt"))
    metadata_txt_raw = _read_text(os.path.join(meta_d, "metadata.txt"))
    opening_review = _safe_json(os.path.join(meta_d, "opening_review.json"))
    duration_review = _safe_json(os.path.join(meta_d, "duration_review.json"))
    final_review = _safe_json(os.path.join(meta_d, "final_review.json"))
    render_info = _safe_json(os.path.join(meta_d, "render_info.json"))
    upload_record = _safe_json(os.path.join(meta_d, "upload_record.json"))

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

    has_poll_copy = os.path.isfile(os.path.join(meta_d, "poll_copy.txt"))
    has_fixed_comment = os.path.isfile(os.path.join(meta_d, "fixed_comment.txt"))

    return {
        "name": history_name,
        "theme_dir": theme_dir,
        "script_txt": script_txt,
        "metadata_txt": metadata_txt_raw,
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
