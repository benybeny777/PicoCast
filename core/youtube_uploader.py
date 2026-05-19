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
CLIENT_SECRETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "client_secrets.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "token.json")


THUMB_MAX_BYTES = 2 * 1024 * 1024  # YouTube 上限 2MB


def _strip_video_type_prefix(title):
    title = str(title or "").strip()
    for prefix in ("[Shorts]", "[Long]", "[SHORT]", "[LONG]"):
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
    img = Image.open(path).convert("RGB")
    try:
        for quality in (85, 75, 60, 45):
            img.save(tmp.name, "JPEG", quality=quality)
            if os.path.getsize(tmp.name) <= THUMB_MAX_BYTES:
                return tmp.name
    finally:
        img.close()
    return tmp.name  # 最低品質でも返す


def get_youtube_client():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                # スコープ変更・トークン失効などで再認証が必要な場合
                if any(k in str(e).lower() for k in ("invalid_scope", "invalid_grant", "unauthorized")):
                    if os.path.exists(TOKEN_FILE):
                        os.remove(TOKEN_FILE)
                    creds = None
                else:
                    raise
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def post_comment(video_id: str, comment_text: str, progress_callback=None) -> str | None:
    """動画にコメントを投稿する。成功時はコメントスレッドIDを返す。"""
    def _log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

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


def get_video_statuses(video_ids: list[str]) -> dict[str, dict]:
    """video_id のリストを渡し、{video_id: {"privacyStatus": ..., "publishAt": ...}} を返す。
    見つからない動画は結果に含まれない。50件ずつバッチ処理。
    """
    if not video_ids:
        return {}
    youtube = get_youtube_client()
    result = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        resp = youtube.videos().list(part="status", id=",".join(chunk)).execute()
        for item in resp.get("items", []):
            vid = item.get("id")
            st = item.get("status", {})
            if vid:
                result[vid] = {
                    "privacyStatus": st.get("privacyStatus"),
                    "publishAt": st.get("publishAt"),
                }
    return result


def update_video_publish_time(video_id: str, publish_at, progress_callback=None) -> bool:
    """予約投稿済み動画の公開予定日時を変更する。publish_at は timezone 付き datetime 推奨。"""
    def _log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

    try:
        from datetime import datetime
        publish_at_str = publish_at.isoformat() if isinstance(publish_at, datetime) else str(publish_at)
        youtube = get_youtube_client()
        current = youtube.videos().list(part="status", id=video_id).execute()
        items = current.get("items", [])
        if not items:
            _log(f"  ⚠ 動画が見つかりません: {video_id}")
            return False
        status = items[0].get("status", {})
        if status.get("privacyStatus") != "private":
            _log(f"  ⚠ private動画ではないため予約変更できません: {status.get('privacyStatus')}")
            return False

        body = {
            "id": video_id,
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at_str,
                "selfDeclaredMadeForKids": bool(status.get("selfDeclaredMadeForKids", False)),
            },
        }
        youtube.videos().update(part="status", body=body).execute()
        _log(f"  ✅ YouTube公開予定を変更: {publish_at_str}")
        return True
    except Exception as e:
        _log(f"  ⚠ 公開予定変更エラー: {e}")
        if "forbidden" in str(e).lower() or "403" in str(e):
            _log("  💡 token.json を削除して再認証すると解決する場合があります")
        return False


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
        result["reason"] = str(e)
        _log(f"  ⚠ 再生リスト追加エラー: {e}")
        if "forbidden" in str(e).lower() or "403" in str(e):
            _log("  💡 token.json を削除して再認証すると解決する場合があります。")
        return result


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

    title = _strip_video_type_prefix(title)

    _log("🔑 YouTube 認証中...")
    youtube = get_youtube_client()

    tag_list = [t.strip() for t in tags.replace("、", ",").split(",") if t.strip()]

    # publish_at が指定されていれば ISO8601 文字列に統一
    publish_at_str = None
    if publish_at is not None:
        from datetime import datetime
        publish_at_str = publish_at.isoformat() if isinstance(publish_at, datetime) else str(publish_at)

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

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            _log(f"  ... {pct}%")

    video_id = response["id"]
    _log(f"✅ アップロード完了: https://youtu.be/{video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        _log("🖼  サムネイルを設定中...")
        upload_thumb = _compress_thumbnail(thumbnail_path)
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(upload_thumb)
        ).execute()
        if upload_thumb != thumbnail_path and os.path.exists(upload_thumb):
            os.remove(upload_thumb)
        _log("  ✅ サムネイル設定完了")

    return video_id
