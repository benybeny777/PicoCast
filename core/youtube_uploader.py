import os
import json
import tempfile
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "client_secrets.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "token.json")


THUMB_MAX_BYTES = 2 * 1024 * 1024  # YouTube 上限 2MB


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
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload_video(mp4_path, title, description, tags, thumbnail_path=None,
                 privacy="private", progress_callback=None):
    def _log(msg):
        if progress_callback:
            progress_callback(msg)
        else:
            print(msg, flush=True)

    _log("🔑 YouTube 認証中...")
    youtube = get_youtube_client()

    tag_list = [t.strip() for t in tags.replace("、", ",").split(",") if t.strip()]

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tag_list,
            "categoryId": "24",  # Entertainment
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
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
