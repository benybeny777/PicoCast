"""
Web UI の最低限テスト。
外部API (VOICEVOX / YouTube / OpenAI) への実通信なしで動くことを確認する。
"""
import sys
import os
import pytest

# プロジェクトルートをパスに追加
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── FastAPI テストクライアント ───────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    os.environ["NVF_DISABLE_JOB_RUNNER"] = "1"
    from web_app.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _patch_service_output_dirs(monkeypatch, service, output_root):
    videos_dir = output_root / "videos"
    uploaded_dir = output_root / "000_uploaded"
    monkeypatch.setattr(service, "get_output_root", lambda: str(output_root), raising=False)
    monkeypatch.setattr(service, "get_output_videos_dir", lambda: str(videos_dir), raising=False)
    monkeypatch.setattr(service, "get_uploaded_dir", lambda: str(uploaded_dir), raising=False)


def _patch_metadata_db(monkeypatch, tmp_path):
    import core.metadata_db as m
    db_path = str(tmp_path / "metadata.db")
    monkeypatch.setattr(m, "get_db_path", lambda: db_path)
    m.initialize_db()
    return m


def _seed_fixed_comment_db(m, local_id, video_id, fixed_comment, *, title=None, publish_status="public", posted=False):
    with m.ManagedConnection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO videos(local_id, output_dir, title, video_type) VALUES(?,?,?,?)",
            (local_id, f"output/{local_id}", title or local_id, "Shorts"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO render_info(local_id, video_title, video_format) VALUES(?,?,?)",
            (local_id, title or local_id, "Shorts"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO video_metadata(local_id, fixed_comment, video_format) VALUES(?,?,?)",
            (local_id, fixed_comment, "Shorts"),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO youtube_status(
                local_id, youtube_video_id, publish_status, fixed_comment_posted
            ) VALUES(?,?,?,?)
            """,
            (local_id, video_id, publish_status, int(posted)),
        )
        conn.commit()


# 1. /health が成功する
def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# 2. /api/health も成功する
def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200


# 3. ダッシュボード (/) が 200 を返す
def test_dashboard_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "ダッシュボード" in res.text or "Web UI" in res.text
    # ダッシュボードにはAPIキー名や秘密ファイル名を表示しない
    assert "Google APIキー" not in res.text
    assert "client_secrets.json" not in res.text
    # ダッシュボードにはローカルサービス接続状態を表示する
    assert "連携アプリ" in res.text
    assert "VOICEVOX" in res.text
    assert "ffmpeg" in res.text


# 4. /generate ページが 200 を返す
def test_generate_page(client):
    res = client.get("/generate")
    assert res.status_code == 200
    assert "LongサムネAB" in res.text
    assert "Long節約" in res.text
    assert "高画質（FHD）生成" in res.text
    assert "const imageStyle" in res.text
    assert "’通常’" not in res.text


# 5. /history ページが 200 を返す
def test_history_page(client):
    res = client.get("/history")
    assert res.status_code == 200


def test_schedule_page_uses_new_default_slot_candidates(client):
    res = client.get("/schedule")
    assert res.status_code == 200
    assert 'value="07:00"' in res.text
    assert 'value="12:00"' in res.text
    assert 'value="21:00"' in res.text
    assert 'value="22:00"' in res.text
    assert 'value="19:00"' not in res.text
    assert "Long 週末" not in res.text


# 6. /settings ページが 200 を返す
def test_settings_page(client):
    res = client.get("/settings")
    assert res.status_code == 200
    assert "chf-google_api_key" in res.text
    assert "chf-youtube_client_secrets" in res.text


def test_settings_page_does_not_wait_full_status(client, monkeypatch):
    import web_app.routes.pages as pages

    def _raise_if_called():
        raise AssertionError("settings page must not run full service status checks")

    monkeypatch.setattr(pages.status_service, "get_cached_settings_status", _raise_if_called)
    res = client.get("/settings")
    assert res.status_code == 200


def test_settings_preload_returns_placeholder_on_cache_miss(monkeypatch):
    import web_app.services.settings_preload_service as preload

    started = []
    monkeypatch.setattr(preload, "_ollama_models_cache", None)
    monkeypatch.setattr(preload, "_bgm_files_cache", None)
    monkeypatch.setattr(preload, "_ollama_refreshing", False)
    monkeypatch.setattr(preload, "_bgm_refreshing", False)
    monkeypatch.setattr(preload, "_start_ollama_refresh", lambda: started.append("ollama"))
    monkeypatch.setattr(preload, "_start_bgm_refresh", lambda: started.append("bgm"))

    assert preload.get_cached_ollama_models() == {
        "models": [],
        "available": False,
        "cached": False,
        "refreshing": True,
    }
    assert preload.get_cached_bgm_files() == {
        "files": [],
        "available": True,
        "cached": False,
        "refreshing": True,
    }
    assert started == ["ollama", "bgm"]


def test_dashboard_scheduled_count_only_future_scheduled(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import core.upload_records as upload_records
    from web_app.services.status_service import _count_scheduled

    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    monkeypatch.setattr(upload_records, "load_upload_records", lambda: [
        {"publish_status": "scheduled", "publish_at": future},
        {"publish_status": "scheduled", "publish_at": past},
        {"publish_status": "private", "publish_at": future},
        {"publish_status": "unlisted", "publish_at": future},
        {"publish_status": "", "publish_at": future},
        {"publish_status": "published", "publish_at": past},
    ])

    assert _count_scheduled() == 1


# 7. /logs ページが 200 を返す
def test_logs_page(client):
    res = client.get("/logs")
    assert res.status_code == 200


def test_logs_running_job_cancel_button_is_action_label(client):
    from web_app.job_manager import get_job_manager, JobStatus

    job = get_job_manager().create_job("generate")
    job.status = JobStatus.RUNNING

    res = client.get("/logs")

    assert res.status_code == 200
    assert "running" in res.text
    assert "中止する" in res.text
    assert ">中止</button>" not in res.text


# ── job_manager の状態遷移 ───────────────────────────────────────────────────
def test_job_manager_state_transitions():
    from web_app.job_manager import get_job_manager, JobStatus

    mgr = get_job_manager()
    job = mgr.create_job("test")
    assert job.status == JobStatus.QUEUED

    # cancel_job
    ok = mgr.cancel_job(job.job_id)
    assert ok
    assert job.status == JobStatus.CANCELLED


def test_job_manager_get_missing():
    from web_app.job_manager import get_job_manager
    mgr = get_job_manager()
    result = mgr.get_job("nonexistent-id")
    assert result is None


def test_job_manager_cancel_missing():
    from web_app.job_manager import get_job_manager
    mgr = get_job_manager()
    ok = mgr.cancel_job("nonexistent-id")
    assert not ok


# ── パストラバーサル対策 ────────────────────────────────────────────────────
def test_path_traversal_rejected():
    from web_app.security import is_safe_output_path
    assert not is_safe_output_path("../../etc/passwd")
    assert not is_safe_output_path("../../../Windows/System32/cmd.exe")
    assert not is_safe_output_path("/etc/passwd")


def test_secret_files_rejected(monkeypatch, tmp_path):
    import web_app.security as sec
    from web_app.security import is_safe_output_path
    output_dir = str(tmp_path / "output")
    monkeypatch.setattr(sec, "_get_output_base", lambda: output_dir)
    # output/ 配下であっても秘密ファイル名は拒否
    assert not is_safe_output_path(os.path.join(output_dir, ".env"))
    assert not is_safe_output_path(os.path.join(output_dir, "token.json"))
    assert not is_safe_output_path(os.path.join(output_dir, "client_secrets.json"))


def test_safe_path_accepted(monkeypatch, tmp_path):
    import web_app.security as sec
    from web_app.security import is_safe_output_path
    output_dir = str(tmp_path / "output")
    monkeypatch.setattr(sec, "_get_output_base", lambda: output_dir)
    # output/ 自体はOK
    assert is_safe_output_path(output_dir)


# ── 履歴一覧が管理フォルダを適切に扱う ────────────────────────────────────
def test_history_excludes_management_dirs(tmp_path, monkeypatch):
    """Shorts_/Long_ プレフィックスがないフォルダは管理フォルダとして除外される。"""
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    videos_dir = fake_output / "videos"
    (videos_dir / "000_analytics").mkdir(parents=True)
    (videos_dir / "000_data").mkdir(parents=True)
    (videos_dir / "random_folder").mkdir(parents=True)
    (videos_dir / "Shorts_テスト動画").mkdir(parents=True)
    (videos_dir / "Long_テスト動画").mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "_fetch_yt_status_bulk", lambda _local_ids: {})

    result = hs.list_histories(include_management=False)
    names = [r["name"] for r in result]
    assert "000_analytics" not in names
    assert "000_data" not in names
    assert "random_folder" not in names
    assert "Shorts_テスト動画" in names
    assert "Long_テスト動画" in names


def test_history_accepts_legacy_short_prefix(tmp_path, monkeypatch):
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    videos_dir = fake_output / "videos"
    (videos_dir / "short_テスト動画").mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "_fetch_yt_status_bulk", lambda _local_ids: {})

    result = hs.list_histories(include_management=False)

    assert [r["name"] for r in result] == ["short_テスト動画"]
    assert result[0]["video_format"] == "Shorts"


def test_history_includes_management_when_requested(tmp_path, monkeypatch):
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    videos_dir = fake_output / "videos"
    (videos_dir / "000_analytics").mkdir(parents=True)
    (videos_dir / "Shorts_テスト動画").mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "_fetch_yt_status_bulk", lambda _local_ids: {})

    result = hs.list_histories(include_management=True)
    names = [r["name"] for r in result]
    assert "000_analytics" in names
    assert "Shorts_テスト動画" in names


def test_history_excludes_uploaded_orphans(tmp_path, monkeypatch):
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    uploaded_dir = fake_output / "000_uploaded"
    (uploaded_dir / "Shorts_DBあり").mkdir(parents=True)
    (uploaded_dir / "Shorts_DBなし").mkdir(parents=True)
    (uploaded_dir / "Shorts_IDなし").mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "_fetch_known_video_ids", lambda: {"Shorts_DBあり", "Shorts_IDなし"})
    monkeypatch.setattr(hs, "_fetch_uploaded_video_ids_with_youtube_id", lambda: {"Shorts_DBあり"})
    monkeypatch.setattr(hs, "_fetch_yt_status_bulk", lambda _local_ids: {})

    assert hs.list_histories() == []

    result = hs.list_histories(include_uploaded=True)
    names = [r["name"] for r in result]
    assert "Shorts_DBあり" in names
    assert "Shorts_DBなし" not in names
    assert "Shorts_IDなし" not in names


def test_history_initializes_empty_metadata_db(tmp_path, monkeypatch):
    import core.metadata_db as m
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    videos_dir = fake_output / "videos"
    (videos_dir / "Shorts_初期化テスト").mkdir(parents=True)
    db_path = tmp_path / "metadata.db"
    db_path.write_bytes(b"")

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(m, "get_db_path", lambda: str(db_path))
    monkeypatch.setattr(hs, "_fetch_yt_status_bulk", lambda _local_ids: {})

    result = hs.list_histories()

    assert [row["name"] for row in result] == ["Shorts_初期化テスト"]


def test_build_metadata_txt_from_db_info():
    """video_metadata 由来の dict から「メタデータ」欄テキストを組み立てられること。"""
    from web_app.services.history_service import _build_metadata_txt

    db_info = {
        "video_title": "人面犬の正体",
        "thumbnail_text": "犬じゃない",
        "description": "都市伝説の解説。",
        "tags": '["ずんだもん", "都市伝説", "怖い話"]',
        "generation_type": "新規",
        "source_video_title": "",
        "purpose": "正体誤解型",
        "fixed_comment": "あなたの地域にも？",
    }
    txt = _build_metadata_txt(db_info)
    assert "【動画タイトル】" in txt
    assert "人面犬の正体" in txt
    # tags は JSON 配列をカンマ区切りに整形する
    assert "ずんだもん, 都市伝説, 怖い話" in txt
    assert "【目的】" in txt
    # 空の項目（元動画）は出さない
    assert "【元動画】" not in txt


def test_build_metadata_txt_empty_when_no_fields():
    """メタデータが空なら空文字を返すこと。"""
    from web_app.services.history_service import _build_metadata_txt
    assert _build_metadata_txt({}) == ""


def test_history_detail_escapes_history_name_in_regenerate_js(client, tmp_path, monkeypatch):
    from urllib.parse import quote
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    history_name = "Shorts_Bob's 100%"
    theme_dir = fake_output / "videos" / history_name
    theme_dir.mkdir(parents=True)
    (theme_dir / "script.txt").write_text(
        "動画形式: Shorts\n生成区分: 新規\n動画タイトル: Bob's 100%\n",
        encoding="utf-8",
    )

    _patch_service_output_dirs(monkeypatch, hs, fake_output)

    res = client.get(f"/history/{quote(history_name, safe='')}")

    assert res.status_code == 200
    assert "const historyName =" in res.text
    assert "encodeURIComponent(historyName)" in res.text
    assert "history_names: [historyName]" in res.text
    assert "history_names: ['" not in res.text


def test_history_row_actions_do_not_embed_json_in_onclick(client):
    res = client.get("/history")
    assert res.status_code == 200
    assert "history-delete-one" in res.text
    assert "history-open-folder" in res.text
    assert "onclick=\"deleteOneHistory(" not in res.text
    assert "onclick=\"openFolder(" not in res.text


# ── 設定診断APIが秘密値を返さない ─────────────────────────────────────────
def test_settings_api_no_secrets(client):
    res = client.get("/api/settings/status")
    assert res.status_code == 200
    data = res.json()

    # APIキーの値そのものが含まれていないことを確認
    # (bool または None が返るべきで、文字列のキー値が含まれてはならない)
    assert isinstance(data.get("google_api_key"), bool)
    assert isinstance(data.get("openai_api_key"), bool)

    # レスポンスのテキストにキーの値がないことを大まかにチェック
    raw = res.text
    assert "sk-" not in raw  # OpenAI APIキーパターン
    assert "AIza" not in raw  # Google APIキーパターン


def test_config_rejects_newline_injection():
    from web_app.services.config_service import save_config
    errors = save_config({"FFMPEG_BIN": "ffmpeg\nOPENAI_API_KEY=leak"})
    assert errors
    assert "改行" in errors[0]


def test_config_image_style_choices_current_is_csv(monkeypatch):
    from config import config
    from web_app.services.config_service import get_editable_config

    monkeypatch.setattr(config, "WEB_IMAGE_STYLE_CHOICES", ("通常", "アニメ", "水彩"))

    item = next(row for row in get_editable_config() if row["key"] == "WEB_IMAGE_STYLE_CHOICES")
    assert item["current"] == "通常,アニメ,水彩"
    assert "('" not in item["current"]


def test_config_image_style_choices_save_normalizes_quotes(tmp_path, monkeypatch):
    import web_app.services.config_service as cs
    import core.settings_store as settings_store

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))

    errors = cs.save_config({"WEB_IMAGE_STYLE_CHOICES": "('通常', 'アニメ', '水彩')"})

    assert errors == []
    assert settings_store.get_all()["WEB_IMAGE_STYLE_CHOICES"] == "通常,アニメ,水彩"


def test_secrets_reject_newline_injection(tmp_path, monkeypatch):
    import core.secret_store as ss
    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(ss, "_get_master_key", lambda: b"\x06" * 32)
    from web_app.services.secrets_service import save_secrets
    errors = save_secrets({"OPENAI_API_KEY": "sk-test\nGOOGLE_API_KEY=leak"})
    assert errors
    assert "改行" in errors[0]


# ── /api/jobs API ──────────────────────────────────────────────────────────
def test_api_jobs_list(client):
    res = client.get("/api/jobs")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_jobs_cancel_missing(client):
    res = client.post("/api/jobs/nonexistent-id/cancel")
    assert res.status_code == 404


# ── /api/history API ───────────────────────────────────────────────────────
def test_api_history_list(client):
    res = client.get("/api/history")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_api_history_missing(client):
    res = client.get("/api/history/nonexistent-theme-xyz123")
    assert res.status_code == 404


def test_api_history_regenerate_requires_confirmation(client):
    res = client.post("/api/history/regenerate", json={"history_names": ["x"], "confirmed": False})
    assert res.status_code == 400


def test_api_history_delete_requires_confirmation(client):
    res = client.request("DELETE", "/api/history/Shorts_x", json={"confirmed": False})
    assert res.status_code == 400


def test_history_delete_service_removes_folder_and_db(tmp_path, monkeypatch):
    import core.metadata_db as m
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    theme_dir = fake_output / "videos" / "Shorts_削除テスト"
    theme_dir.mkdir(parents=True)
    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "find_history_dir", lambda name: str(theme_dir) if name == "Shorts_削除テスト" else None)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    with m.ManagedConnection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO videos(local_id, output_dir, title, video_type) VALUES(?,?,?,?)",
            ("Shorts_削除テスト", str(theme_dir), "削除テスト", "Shorts"),
        )
        conn.commit()

    result = hs.delete_history("Shorts_削除テスト", confirmed=True)

    assert result["deleted"] == "Shorts_削除テスト"
    assert not theme_dir.exists()
    with m.ManagedConnection() as conn:
        row = conn.execute("SELECT 1 FROM videos WHERE local_id=?", ("Shorts_削除テスト",)).fetchone()
    assert row is None


# ── 外部APIなしでもWebアプリが起動できる ──────────────────────────────────
def test_app_starts_without_external_apis(client):
    """VOICEVOX/YouTube未接続でも /health と / が返ることを確認。"""
    h = client.get("/health")
    assert h.status_code == 200
    d = client.get("/")
    assert d.status_code == 200


# ── /api/generate: 空台本はエラー ─────────────────────────────────────────
def test_generate_empty_script_rejected(client):
    res = client.post("/api/generate", json={"script": ""})
    assert res.status_code == 422  # Pydantic validation error


# ── /api/upload: confirmed=false はエラー ─────────────────────────────────
def test_upload_requires_confirmation(client):
    res = client.post("/api/upload", json={"history_name": "test", "confirmed": False})
    assert res.status_code == 400


# ── /fixed-comment ページおよびAPIの最低限テスト ──────────────────────────────
def test_fixed_comment_page(client):
    res = client.get("/fixed-comment")
    assert res.status_code == 200
    assert "固定コメント" in res.text


def test_fixed_comment_post_button_uses_data_attributes(client, monkeypatch):
    import web_app.routes.pages as pages

    monkeypatch.setattr(
        pages.fixed_comment_service,
        "list_fixed_comment_candidates",
        lambda only_unposted=True: [{
            "name": os.path.join("000_uploaded", "Shorts_引用符'テスト"),
            "location": "アップロード済み",
            "title": "引用符'と\"を含むタイトル",
            "video_id": "abc123",
            "publish_status": "public",
            "published_at": "2026-05-26T00:00:00Z",
            "fixed_comment": "コメント",
            "comment_thread_id": "",
            "already_posted": False,
        }],
    )

    res = client.get("/fixed-comment")
    assert res.status_code == 200
    assert "js-post-comment" in res.text
    assert "js-mark-posted" in res.text
    assert "https://youtu.be/abc123" in res.text
    assert "YouTubeを開く" in res.text
    assert "2026-05-26" in res.text
    assert "data-history-name=" in res.text
    assert "onclick=\"confirmPost" not in res.text


def test_fixed_comment_page_loads_posted_rows_for_toggle(client, monkeypatch):
    import web_app.routes.pages as pages

    called = {}

    def fake_candidates(only_unposted=True):
        called["only_unposted"] = only_unposted
        return [{
            "name": os.path.join("000_uploaded", "Shorts_投稿済みテスト"),
            "location": "アップロード済み",
            "title": "投稿済みテスト",
            "video_id": "posted123",
            "publish_status": "public",
            "published_at": "2026-05-26T00:00:00Z",
            "fixed_comment": "コメント",
            "comment_thread_id": "comment123",
            "fixed_comment_posted_at": "2026-05-26T01:00:00+09:00",
            "fixed_comment_pinned_at": "",
            "already_posted": True,
        }]

    monkeypatch.setattr(pages.fixed_comment_service, "list_fixed_comment_candidates", fake_candidates)

    res = client.get("/fixed-comment")
    assert res.status_code == 200
    assert called["only_unposted"] is False
    assert "posted-row" in res.text
    assert "投稿済みテスト" in res.text


def test_api_fixed_comment_candidates(client):
    res = client.get("/api/fixed-comment/candidates")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

def test_api_fixed_comment_requires_confirmation(client):
    res = client.post("/api/fixed-comment", json={"history_name": "test", "confirmed": False})
    assert res.status_code == 400


def test_api_fixed_comment_mark_posted_requires_confirmation(client):
    res = client.post("/api/fixed-comment/mark-posted", json={"history_name": "test", "confirmed": False})
    assert res.status_code == 400


def test_fixed_comment_candidates_include_uploaded_metadata(tmp_path, monkeypatch):
    import web_app.services.fixed_comment_service as fcs

    fake_output = tmp_path / "output"
    theme_dir = fake_output / "000_uploaded" / "Shorts_固定コメントテスト"
    theme_dir.mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, fcs, fake_output)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    _seed_fixed_comment_db(
        m,
        "Shorts_固定コメントテスト",
        "abc123",
        "投稿するコメントです",
        title="固定コメントのテスト",
    )
    monkeypatch.setattr(fcs, "_fetch_youtube_statuses", lambda _ids: {"abc123": {"privacyStatus": "public"}})

    candidates = fcs.list_fixed_comment_candidates()
    assert len(candidates) == 1
    assert candidates[0]["name"] == os.path.join("000_uploaded", "Shorts_固定コメントテスト")
    assert candidates[0]["fixed_comment"] == "投稿するコメントです"
    assert candidates[0]["title"] == "固定コメントのテスト"


def test_fixed_comment_candidates_filter_scheduled_locally(tmp_path, monkeypatch):
    import web_app.services.fixed_comment_service as fcs

    fake_output = tmp_path / "output"
    theme_dir = fake_output / "000_uploaded" / "Shorts_予約中テスト"
    theme_dir.mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, fcs, fake_output)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    _seed_fixed_comment_db(
        m,
        "Shorts_予約中テスト",
        "scheduled123",
        "予約中コメントです",
        publish_status="scheduled",
    )
    monkeypatch.setattr(fcs, "_fetch_youtube_statuses", lambda _ids: {"scheduled123": {"privacyStatus": "private"}})

    assert fcs.list_fixed_comment_candidates() == []


def test_fixed_comment_candidates_filter_missing_and_non_public_youtube(tmp_path, monkeypatch):
    import web_app.services.fixed_comment_service as fcs

    fake_output = tmp_path / "output"
    for name, video_id in [
        ("Shorts_公開テスト", "public123"),
        ("Shorts_非公開テスト", "private123"),
        ("Shorts_存在しないテスト", "missing123"),
    ]:
        (fake_output / "000_uploaded" / name).mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, fcs, fake_output)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    for name, video_id in [
        ("Shorts_公開テスト", "public123"),
        ("Shorts_非公開テスト", "private123"),
        ("Shorts_存在しないテスト", "missing123"),
    ]:
        _seed_fixed_comment_db(m, name, video_id, "コメントです", title=name)
    monkeypatch.setattr(fcs, "_fetch_youtube_statuses", lambda _ids: {
        "public123": {
            "privacyStatus": "public",
            "publishedAt": "2026-05-26T00:00:00Z",
            "title": "YouTube側タイトル",
        },
        "private123": {"privacyStatus": "private", "publishedAt": "2026-05-26T00:00:00Z"},
    })

    candidates = fcs.list_fixed_comment_candidates()
    assert len(candidates) == 1
    assert candidates[0]["video_id"] == "public123"
    assert candidates[0]["published_at"] == "2026-05-26T00:00:00Z"
    assert candidates[0]["title"] == "YouTube側タイトル"


def test_fixed_comment_mark_posted_writes_record(tmp_path, monkeypatch):
    import web_app.services.fixed_comment_service as fcs

    fake_output = tmp_path / "output"
    theme_dir = fake_output / "000_uploaded" / "Shorts_手動投稿済みテスト"
    theme_dir.mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, fcs, fake_output)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    _seed_fixed_comment_db(
        m,
        "Shorts_手動投稿済みテスト",
        "abc123",
        "手動で投稿したコメントです",
    )
    monkeypatch.setattr(fcs, "_fetch_youtube_statuses", lambda _ids: {"abc123": {"privacyStatus": "public"}})

    result = fcs.mark_fixed_comment_posted(os.path.join("000_uploaded", "Shorts_手動投稿済みテスト"))
    assert result["video_id"] == "abc123"

    with m.ManagedConnection() as conn:
        row = conn.execute(
            "SELECT fixed_comment_posted FROM youtube_status WHERE local_id=?",
            ("Shorts_手動投稿済みテスト",),
        ).fetchone()
    assert row["fixed_comment_posted"] == 1
    assert fcs.list_fixed_comment_candidates() == []


def test_fixed_comment_candidates_treat_pinned_as_posted(tmp_path, monkeypatch):
    import web_app.services.fixed_comment_service as fcs

    fake_output = tmp_path / "output"
    theme_dir = fake_output / "000_uploaded" / "Shorts_ピン留め済みテスト"
    theme_dir.mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, fcs, fake_output)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    _seed_fixed_comment_db(
        m,
        "Shorts_ピン留め済みテスト",
        "abc123",
        "投稿済みコメントです",
        posted=True,
    )
    monkeypatch.setattr(fcs, "_fetch_youtube_statuses", lambda _ids: {"abc123": {"privacyStatus": "public"}})

    assert fcs.list_fixed_comment_candidates() == []
    candidates = fcs.list_fixed_comment_candidates(only_unposted=False)
    assert len(candidates) == 1
    assert candidates[0]["already_posted"] is True


def test_auto_fixed_comment_scope_all_profiles(monkeypatch):
    import web_app.services.auto_fixed_comment_service as afc
    import web_app.services.fixed_comment_service as fcs

    class Profile:
        def __init__(self, profile_id):
            self.profile_id = profile_id

    calls = []
    monkeypatch.setattr(afc._cfg, "AUTO_FIXED_COMMENT_PROFILE_SCOPE", "all")
    monkeypatch.setattr("core.channel_profile.list_profiles", lambda: [Profile("ch_a"), Profile("ch_b")])
    monkeypatch.setattr(
        fcs,
        "list_fixed_comment_candidates",
        lambda only_unposted=True, profile_id=None: [{"name": f"{profile_id}_video"}],
    )
    monkeypatch.setattr(
        fcs,
        "submit_fixed_comment_job",
        lambda history_name, auto_posted=False, profile_id=None: calls.append((history_name, auto_posted, profile_id)) or "job",
    )

    afc._run_once()

    assert calls == [
        ("ch_a_video", True, "ch_a"),
        ("ch_b_video", True, "ch_b"),
    ]


def test_auto_fixed_comment_scope_active_only(monkeypatch):
    import web_app.services.auto_fixed_comment_service as afc
    import web_app.services.fixed_comment_service as fcs

    calls = []
    monkeypatch.setattr(afc._cfg, "AUTO_FIXED_COMMENT_PROFILE_SCOPE", "active")
    monkeypatch.setattr(
        fcs,
        "list_fixed_comment_candidates",
        lambda only_unposted=True, profile_id=None: [{"name": "active_video"}],
    )
    monkeypatch.setattr(
        fcs,
        "submit_fixed_comment_job",
        lambda history_name, auto_posted=False, profile_id=None: calls.append((history_name, auto_posted, profile_id)) or "job",
    )

    afc._run_once()

    assert calls == [("active_video", True, None)]


# ── ジョブDB queue ──
def test_claim_queued_job_is_atomic(tmp_path, monkeypatch):
    import core.metadata_db as m
    from web_app.job_manager import Job

    m = _patch_metadata_db(monkeypatch, tmp_path)
    job = Job("job-1", "generate", "test_profile", {"script": "動画形式: Shorts"})
    m.upsert_job(job.to_dict())

    claimed1 = m.claim_queued_job(111, ("generate",))
    claimed2 = m.claim_queued_job(222, ("generate",))

    assert claimed1["job_id"] == "job-1"
    assert claimed1["status"] == "running"
    assert claimed1["runner_pid"] == 111
    assert claimed2 is None


# ── reuse_audio の配管（サービス層） ──────────────────────────────────────────
def test_submit_generate_stores_reuse_audio_in_params(tmp_path, monkeypatch):
    """生成ジョブ登録時に reuse_audio / reuse_backgrounds を DB params に保存する。"""
    import web_app.services.generation_service as gs
    import core.metadata_db as m

    m = _patch_metadata_db(monkeypatch, tmp_path)
    monkeypatch.setattr("web_app.job_manager.JobManager._active_profile_id", lambda _self: "test_profile")

    job_id = gs.submit_generate_job(
        "動画形式: Shorts\n動画タイトル: t\n",
        reuse_audio=True,
        reuse_backgrounds=False,
    )
    rows = m.load_jobs_from_db()
    row = next(r for r in rows if r["job_id"] == job_id)
    assert row["params"]["reuse_audio"] is True
    assert row["params"]["reuse_backgrounds"] is False


def test_cancel_job_searches_all_profiles(tmp_path, monkeypatch):
    import core.metadata_db as m
    from web_app.job_manager import Job, JobManager

    profiles = {}

    def _switch_db(profile_id):
        db_path = str(tmp_path / profile_id / "metadata.db")
        monkeypatch.setattr(m, "get_db_path", lambda: db_path)
        m.initialize_db()

    class _Profile:
        def __init__(self, profile_id):
            self.profile_id = profile_id

    monkeypatch.setattr("core.channel_profile.list_profiles", lambda: [_Profile("profile_a"), _Profile("profile_b")])
    monkeypatch.setattr("core.channel_profile.get_profile", lambda profile_id: _Profile(profile_id))
    monkeypatch.setattr("core.channel_profile.get_active_profile", lambda: _Profile("profile_a"))

    original_enter = __import__("core.channel_profile", fromlist=["profile_context"]).profile_context.__enter__

    def _enter(self):
        result = original_enter(self)
        profiles["current"] = self.profile_id
        _switch_db(self.profile_id)
        return result

    monkeypatch.setattr("core.channel_profile.profile_context.__enter__", _enter)
    _switch_db("profile_b")
    m.upsert_job(Job("job-b", "generate", "profile_b", {}).to_dict())
    _switch_db("profile_a")

    assert JobManager().cancel_job("job-b") is True

    _switch_db("profile_b")
    row = next(r for r in m.load_jobs_from_db() if r["job_id"] == "job-b")
    assert row["status"] == "cancelled"


# ── 再生成エンドポイント ──────────────────────────────────────────────────────
def test_history_regenerate_accepts_reuse_audio(client):
    """reuse_audio を含むリクエストがスキーマで受理される（422にならない）こと。
    台本がDBに無いので 404（E-SCRIPT-MISSING）になるが、それはスキーマ通過の証拠。"""
    res = client.post("/api/history/regenerate", json={
        "history_names": ["Shorts_存在しない"],
        "reuse_audio": True,
        "reuse_backgrounds": True,
        "confirmed": True,
    })
    assert res.status_code == 404  # 422(バリデーション失敗)ではない


def test_image_regenerate_route_returns_job_id(client, monkeypatch):
    """画像再生成エンドポイントが image_keys を受けて job_id を返すこと。"""
    import web_app.routes.api_images as api_images
    monkeypatch.setattr(api_images, "submit_regenerate_job", lambda *a, **k: "job-xyz-1234")
    res = client.post("/api/images/Shorts_test/regenerate", json={
        "history_name": "Shorts_test",
        "image_keys": ["backgrounds/bg_004_001.png"],
        "prompts": {},
    })
    assert res.status_code == 200
    assert res.json().get("job_id") == "job-xyz-1234"


def test_history_db_info_bulk(monkeypatch, tmp_path):
    """_history_db_info_bulk が複数 local_id を1クエリでまとめて返すこと（N+1回避）。"""
    m = _patch_metadata_db(monkeypatch, tmp_path)
    import web_app.services.history_service as hs
    with m.ManagedConnection() as conn:
        for lid, title in [("Shorts_A", "タイトルA"), ("Shorts_B", "タイトルB")]:
            conn.execute("INSERT INTO videos(local_id, output_dir, title, video_type) VALUES(?,?,?,?)",
                         (lid, f"output/{lid}", title, "Shorts"))
            conn.execute("INSERT INTO render_info(local_id, video_title, video_format) VALUES(?,?,?)",
                         (lid, title, "Shorts"))
        conn.commit()

    info = hs._history_db_info_bulk(["Shorts_A", "Shorts_B", "存在しない"])
    assert set(info.keys()) == {"Shorts_A", "Shorts_B"}
    assert info["Shorts_A"]["video_title"] == "タイトルA"
    assert info["Shorts_B"]["video_format"] == "Shorts"
    assert hs._history_db_info_bulk([]) == {}
