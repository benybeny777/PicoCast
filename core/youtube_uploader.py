import os
import json
import tempfile
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
_DEFAULT_PROFILE = "default"


def _resolve_profile_id(profile_id: str | None) -> str:
    """
    profile_id が未指定の場合、active channel profile の profile_id を使う。
    active profile も未設定なら "default" にフォールバック。
    """
    if profile_id is not None:
        return profile_id
    try:
        from core.channel_profile import get_active_profile
        p = get_active_profile()
        return p.profile_id if p else _DEFAULT_PROFILE
    except Exception:
        return _DEFAULT_PROFILE


THUMB_MAX_BYTES = 2 * 1024 * 1024  # YouTube 上限 2MB


def _strip_video_type_prefix(title):
    title = str(title or "").strip()
    from config import config as _cfg
    for prefix in _cfg._LEGACY_FOLDER_PREFIXES:
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title


def _compress_thumbnail(path):
    """2MB を超えるサムネイルを JPEG に変換・圧縮して一時ファイルパスを返す。"""
    if os.path.getsize(path) <= THUMB_MAX_BYTES:
        return path
    from PIL import Image
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    with Image.open(path) as src:
        img = src.convert("RGB")
    try:
        for quality in (85, 75, 60, 45):
            img.save(tmp.name, "JPEG", quality=quality)
            if os.path.getsize(tmp.name) <= THUMB_MAX_BYTES:
                return tmp.name
    finally:
        img.close()
    return tmp.name  # 最低品質でも返す



def get_youtube_client(profile_id: str | None = None):
    """
    YouTube Data API クライアントを取得する。
    トークンは DB（encrypted_secrets）から読み込み、refresh 後は DB へ再保存する。
    token.json / client_secrets.json ファイルは使用しない。
    """
    profile_id = _resolve_profile_id(profile_id)
    from core.secret_store import has_secret, load_secret, save_secret, delete_secret, SecretNotFoundError

    creds = None
    if has_secret("youtube_upload_token", profile_id=profile_id):
        token_json = load_secret("youtube_upload_token", profile_id=profile_id)
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                save_secret("youtube_upload_token", creds.to_json(), profile_id=profile_id)
            except Exception as e:
                # スコープ変更・トークン失効などで再認証が必要な場合
                if any(k in str(e).lower() for k in ("invalid_scope", "invalid_grant", "unauthorized")):
                    delete_secret("youtube_upload_token", profile_id=profile_id)
                    creds = None
                else:
                    raise
        if not creds or not creds.valid:
            if not has_secret("youtube_client_secrets", profile_id=profile_id):
                raise SecretNotFoundError(
                    "YouTube client_secrets が未登録です。"
                    "設定画面の「認証情報」から登録してください。"
                )
            client_config = json.loads(
                load_secret("youtube_client_secrets", profile_id=profile_id)
            )
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)
            save_secret("youtube_upload_token", creds.to_json(), profile_id=profile_id)

    return build("youtube", "v3", credentials=creds)


def _close_youtube_client(youtube):
    if youtube is not None and hasattr(youtube, "close"):
        youtube.close()


def post_comment(video_id: str, comment_text: str, progress_callback=None) -> str | None:
    """動画にコメントを投稿する。成功時はコメントスレッドIDを返す。"""
    def _log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

    youtube = None
    try:
        youtube = get_youtube_client()
        response = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": comment_text}
                    }
                }
            }
        ).execute()
        return response.get("id")
    except Exception as e:
        _log(f"  ⚠ コメント投稿エラー: {e}")
        if "forbidden" in str(e).lower() or "403" in str(e):
            _log("  💡 token.json を削除して再認証すると解決する場合があります")
        return None
    finally:
        _close_youtube_client(youtube)


def get_video_statuses(video_ids: list[str], youtube=None) -> dict[str, dict]:
    """video_id のリストを渡し、{video_id: {"privacyStatus": ..., "publishAt": ...}} を返す。
    見つからない動画は結果に含まれない。50件ずつバッチ処理。
    """
    if not video_ids:
        return {}
    owns_client = youtube is None
    if owns_client:
        youtube = get_youtube_client()
    result = {}
    try:
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            resp = youtube.videos().list(part="snippet,status,contentDetails", id=",".join(chunk)).execute()
            for item in resp.get("items", []):
                vid = item.get("id")
                st = item.get("status", {})
                sn = item.get("snippet", {})
                cd = item.get("contentDetails", {})
                if vid:
                    result[vid] = {
                        "privacyStatus": st.get("privacyStatus"),
                        "publishAt": st.get("publishAt"),
                        "title": sn.get("title"),
                        "publishedAt": sn.get("publishedAt"),
                        "duration": cd.get("duration"),
                    }
        return result
    finally:
        if owns_client:
            _close_youtube_client(youtube)


def _duration_seconds(duration: str | None) -> int | None:
    if not duration:
        return None
    import re
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        str(duration),
    )
    if not match:
        return None
    parts = {k: int(v or 0) for k, v in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def infer_video_type(title: str | None = None, duration: str | None = None) -> str:
    text = str(title or "").strip()
    from config import config as _cfg
    if text.startswith(_cfg.FOLDER_PREFIX_LONG):
        return "long"
    if text.startswith(_cfg.FOLDER_PREFIX_SHORTS):
        return "shorts"
    seconds = _duration_seconds(duration)
    if seconds is not None and seconds <= 60:
        return "shorts"
    return "long"


def _youtube_publish_at(publish_at) -> tuple[str, str]:
    """(YouTube向けUTC RFC3339, JST表示文字列) を返す。"""
    from datetime import datetime, timedelta, timezone

    JST = timezone(timedelta(hours=9))
    if isinstance(publish_at, datetime):
        dt = publish_at
    else:
        text = str(publish_at).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    jst = dt.astimezone(JST).replace(microsecond=0)
    utc = dt.astimezone(timezone.utc).replace(microsecond=0)
    return utc.isoformat().replace("+00:00", "Z"), jst.strftime("%Y-%m-%d %H:%M JST")


def get_channel_upload_video_statuses() -> dict[str, dict]:
    """認証済みチャンネルのアップロード再生リストの動画ステータス・スニペットを返す。"""
    youtube = None
    try:
        youtube = get_youtube_client()
        channel = youtube.channels().list(part="contentDetails", mine=True, maxResults=1).execute()
        items = channel.get("items", [])
        if not items:
            return {}
        uploads_id = (
            items[0]
            .get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if not uploads_id:
            return {}

        video_ids = []
        page_token = None
        while True:
            kwargs = {
                "part": "contentDetails",
                "playlistId": uploads_id,
                "maxResults": 50,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = youtube.playlistItems().list(**kwargs).execute()
            for item in resp.get("items", []):
                vid = item.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        statuses = get_video_statuses(video_ids, youtube=youtube)
        for data in statuses.values():
            data["video_type"] = infer_video_type(data.get("title"), data.get("duration"))
        return statuses
    finally:
        _close_youtube_client(youtube)


def update_video_publish_time(video_id: str, publish_at, progress_callback=None) -> bool:
    """予約投稿済み動画の公開予定日時を変更する。publish_at は timezone 付き datetime 推奨。"""
    def _log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

    youtube = None
    try:
        publish_at_str, publish_at_display = _youtube_publish_at(publish_at)
        youtube = get_youtube_client()
        current = youtube.videos().list(part="status", id=video_id).execute()
        items = current.get("items", [])
        if not items:
            _log(f"  ⚠ 動画が見つかりません: {video_id}")
            return False
        status = items[0].get("status", {})
        privacy_status = status.get("privacyStatus")
        if privacy_status not in ("private", "unlisted"):
            _log(f"  ⚠ 予約変更対象外の公開状態です: {privacy_status}")
            return False
        if privacy_status == "unlisted" and not status.get("publishAt"):
            _log("  ⚠ 限定公開済みで公開予定がないため、APIでは予約投稿に戻せません")
            return False

        made_for_kids = bool(status.get("selfDeclaredMadeForKids", False))
        body = {
            "id": video_id,
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at_str,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        youtube.videos().update(part="status", body=body).execute()
        _log(f"  ✅ YouTube公開予定を変更: {publish_at_display} ({publish_at_str})")
        return True
    except Exception as e:
        _log(f"  ⚠ 公開予定変更エラー: {e}")
        if "forbidden" in str(e).lower() or "403" in str(e):
            _log("  💡 token.json を削除して再認証すると解決する場合があります")
        return False
    finally:
        _close_youtube_client(youtube)


def _find_playlist_id_by_name(youtube, playlist_name: str) -> str | None:
    target = str(playlist_name or "").strip()
    if not target:
        return None

    page_token = None
    while True:
        kwargs = dict(part="snippet", mine=True, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlists().list(**kwargs).execute()
        for item in resp.get("items", []):
            title = (item.get("snippet", {}).get("title") or "").strip()
            if title == target:
                return item.get("id")
        page_token = resp.get("nextPageToken")
        if not page_token:
            return None


def _playlist_contains_video(youtube, playlist_id: str, video_id: str) -> bool:
    page_token = None
    while True:
        kwargs = dict(part="contentDetails", playlistId=playlist_id, maxResults=50)
        if page_token:
            kwargs["pageToken"] = page_token
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            if item.get("contentDetails", {}).get("videoId") == video_id:
                return True
        page_token = resp.get("nextPageToken")
        if not page_token:
            return False


def add_video_to_playlist_by_name(video_id: str, playlist_name: str, progress_callback=None) -> dict:
    """再生リスト名の完全一致で動画を追加する。既に入っている場合は追加しない。"""
    def _log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

    playlist_name = str(playlist_name or "").strip()
    result = {
        "ok": False,
        "skipped": False,
        "playlist_name": playlist_name,
        "playlist_id": None,
        "playlist_item_id": None,
        "reason": "",
    }
    if not video_id:
        result["reason"] = "video_id が空です"
        return result
    if not playlist_name:
        result["skipped"] = True
        result["reason"] = "再生リスト名が未設定です"
        return result

    youtube = None
    try:
        youtube = get_youtube_client()
        playlist_id = _find_playlist_id_by_name(youtube, playlist_name)
        if not playlist_id:
            result["reason"] = f"再生リストが見つかりません: {playlist_name}"
            _log(f"  ⚠ 再生リストが見つかりません: {playlist_name}")
            return result

        result["playlist_id"] = playlist_id
        if _playlist_contains_video(youtube, playlist_id, video_id):
            result["ok"] = True
            result["skipped"] = True
            result["reason"] = "既に再生リストへ登録済みです"
            _log(f"  ✅ 再生リスト登録済み: {playlist_name}")
            return result

        resp = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute()
        result["ok"] = True
        result["playlist_item_id"] = resp.get("id")
        result["reason"] = "追加しました"
        _log(f"  ✅ 再生リストへ追加: {playlist_name}")
        return result
    except Exception as e:
        err_str = str(e)
        if "videoNotFound" in err_str or "Video not found" in err_str:
            result["reason"] = "動画がYouTubeに存在しません（削除済みの可能性）"
            result["not_found"] = True
            _log(f"  ⚠ 動画が見つかりません（削除済み?）: {video_id}")
        else:
            result["reason"] = err_str
            _log(f"  ⚠ 再生リスト追加エラー: {e}")
            if "forbidden" in err_str.lower() or "403" in err_str:
                _log("  💡 token.json を削除して再認証すると解決する場合があります。")
        return result
    finally:
        _close_youtube_client(youtube)


def create_playlist(name: str, description: str = "", privacy: str = "public") -> dict:
    """再生リストを作成する。同名が既に存在する場合はIDを返してスキップする。"""
    youtube = None
    try:
        youtube = get_youtube_client()
        existing_id = _find_playlist_id_by_name(youtube, name)
        if existing_id:
            return {"ok": True, "created": False, "id": existing_id, "name": name, "reason": "既存の再生リストを使用"}
        resp = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": name, "description": description},
                "status": {"privacyStatus": privacy},
            },
        ).execute()
        return {"ok": True, "created": True, "id": resp.get("id"), "name": name, "reason": "作成しました"}
    except Exception as e:
        return {"ok": False, "created": False, "id": None, "name": name, "reason": str(e)}
    finally:
        _close_youtube_client(youtube)


def _read_script_text_for_tags(mp4_path: str) -> str:
    output_dir = os.path.dirname(os.path.abspath(mp4_path))
    script_path = os.path.join(output_dir, "script.txt")
    if not os.path.exists(script_path):
        return ""
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _write_youtube_metadata(output_dir: str, title: str, youtube_tags: list[str], extra: dict | None = None) -> str | None:
    return None


def upload_video(mp4_path, title, description, tags, thumbnail_path=None,
                 privacy="private", publish_at=None, progress_callback=None):
    """
    publish_at: datetime (JST) または ISO8601 文字列を指定すると予約投稿になる。
                指定時は privacyStatus が自動的に 'private' になる。
    """
    def _log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

    from core.youtube_metadata import optimize_upload_metadata, split_tags
    from core.cta_policy import append_long_youtube_chapters, probe_duration_sec, read_policy_file

    title = _strip_video_type_prefix(title)
    from config import config as _cfg
    _s_pfx = _cfg.FOLDER_PREFIX_SHORTS
    is_shorts = _s_pfx in str(mp4_path) or _s_pfx in str(title)
    script_text = _read_script_text_for_tags(mp4_path)
    title, description, tags = optimize_upload_metadata(
        title,
        description,
        tags,
        is_shorts=is_shorts,
        script_text=script_text,
    )
    policy_data = read_policy_file(os.path.dirname(os.path.abspath(mp4_path)))
    if not is_shorts:
        description, chapters_added = append_long_youtube_chapters(
            description,
            script_text,
            duration_sec=probe_duration_sec(mp4_path),
        )
        long_policy = dict(policy_data.get("long_policy") or {})
        long_policy.update({
            "related_video_navigation_allowed": True,
            "vidiq_title_adjustment_allowed": True,
            "youtube_chapters_added": bool(chapters_added),
        })
        policy_data["long_policy"] = long_policy

    _log("🔑 YouTube 認証中...")
    youtube = None

    try:
        youtube = get_youtube_client()

        tag_list = split_tags(tags)

        # publish_at が指定されていれば ISO8601 文字列に統一
        publish_at_str = None
        if publish_at is not None:
            publish_at_str, _publish_at_display = _youtube_publish_at(publish_at)

        status_body = {
            "privacyStatus": "private" if publish_at_str else privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,
        }
        if publish_at_str:
            status_body["publishAt"] = publish_at_str

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tag_list,
                "categoryId": "24",  # Entertainment
                "defaultLanguage": "ja",
                "defaultAudioLanguage": "ja",
            },
            "status": status_body,
        }

        media = MediaFileUpload(mp4_path, chunksize=5 * 1024 * 1024, resumable=True)
        _log(f"📤 アップロード開始: {os.path.basename(mp4_path)}")
        try:
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    _log(f"  ... {pct}%")
        finally:
            del media

        video_id = response["id"]
        _log(f"✅ アップロード完了: https://youtu.be/{video_id}")

        if thumbnail_path and os.path.exists(thumbnail_path):
            _log("🖼  サムネイルを設定中...")
            upload_thumb = _compress_thumbnail(thumbnail_path)
            thumb_media = MediaFileUpload(upload_thumb)
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=thumb_media
                ).execute()
            finally:
                del thumb_media
                if upload_thumb != thumbnail_path and os.path.exists(upload_thumb):
                    os.remove(upload_thumb)
            _log("  ✅ サムネイル設定完了")

        return video_id
    finally:
        _close_youtube_client(youtube)
