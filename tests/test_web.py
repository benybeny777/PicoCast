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
    from conftest import local_api_client as TestClient
    os.environ["NVF_DISABLE_JOB_RUNNER"] = "1"
    from web_app.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _configured_active_profile(request, monkeypatch, tmp_path_factory):
    """設定済み（active channel あり）の状態を前提にする。

    初回セットアップ redirect ミドルウェアは active channel 未登録時のみ /setup へ
    誘導するため、通常ページのテストでは active profile を用意する。個別に
    get_active_profile を差し替えるテストは本体側の monkeypatch が優先される。
    `@pytest.mark.no_active_profile` を付けたテストでは未設定状態のままにする。
    """
    if request.node.get_closest_marker("no_active_profile"):
        return
    import core.channel_profile as cp
    root = tmp_path_factory.mktemp("active_profile_output")
    dummy = cp.ChannelProfile(
        profile_id="test_profile",
        channel_name="テストチャンネル",
        channel_handle="@test",
        genre_profile="general",
        output_root=str(root),
        is_active=True,
    )
    monkeypatch.setattr(cp, "get_active_profile", lambda: dummy)


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
    assert "高画質（FHD）生成" not in res.text
    assert "const imageStyle" in res.text
    assert "’通常’" not in res.text
    assert res.text.index('id="generate-btn-normal"') < res.text.index(
        'id="script-input-normal"'
    )
    assert res.text.index('id="generate-btn-meeting"') < res.text.index(
        'id="script-input-meeting"'
    )


# 5. /history ページが 200 を返す
def test_history_page(client):
    res = client.get("/history")
    assert res.status_code == 200


@pytest.mark.no_active_profile
def test_setup_page_renders_without_active_profile(client, monkeypatch):
    # 初回起動（active profile 未設定）でも /setup は 200 で描画できること
    import core.channel_profile as cp
    monkeypatch.setattr(cp, "get_active_profile", lambda: None)
    res = client.get("/setup")
    assert res.status_code == 200
    assert "初回セットアップ" in res.text
    assert "setupDetectServices" in res.text


def test_schedule_page_uses_new_default_slot_candidates(client, monkeypatch):
    import core.channel_schedule as channel_schedule

    monkeypatch.setattr(
        channel_schedule,
        "get_schedule",
        lambda: channel_schedule.ChannelSchedule(
            profile_id="test_profile",
            timezone_name="Asia/Tokyo",
            shorts_slot_hours=(12, 21),
            long_slot_hours=(22,),
        ),
    )
    res = client.get("/schedule")
    assert res.status_code == 200
    assert 'value="07:00"' not in res.text
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
    assert "管理者設定" in res.text
    assert "admin-config-form" in res.text
    assert "layout-preview-frame" in res.text
    assert "applyLayoutPreset" in res.text
    assert "applyWigglePreset" in res.text


def test_settings_hides_admin_when_developer_tools_disabled(client, monkeypatch):
    # 販売版（DEVELOPER_TOOLS_ENABLED=False）では管理者設定タブ・開発者モード・edition切替を隠す
    import config.config as cfg
    import web_app.services.config_service as cs
    monkeypatch.setattr(cfg, "DEVELOPER_TOOLS_ENABLED", False)
    res = client.get("/settings")
    assert res.status_code == 200
    assert "tab-btn-admin" not in res.text
    assert 'data-mode="developer"' not in res.text
    assert "devSetEdition('trial'" not in res.text
    # admin 項目は API から除外され、保存も拒否される
    assert all(not item.get("admin") for item in cs.get_editable_config())
    assert cs.save_config({"VOICEVOX_QUERY_TIMEOUT_SEC": "5"})


def test_settings_shows_admin_when_developer_tools_enabled(client, monkeypatch):
    import config.config as cfg
    import web_app.services.config_service as cs
    monkeypatch.setattr(cfg, "DEVELOPER_TOOLS_ENABLED", True)
    res = client.get("/settings")
    assert "tab-btn-admin" in res.text
    assert any(item.get("admin") for item in cs.get_editable_config())


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


def test_logs_page_uses_common_job_card_and_debug_polling(client):
    res = client.get("/logs")
    assert res.status_code == 200
    assert "updateJobCard(" in res.text
    assert "buildJobCardHtml(job)" in res.text
    assert "_startDebugPolling" in res.text
    assert "setInterval(() =>" in res.text
    assert "_logPollIntervalMs" in res.text
    assert "ログ選択中のため自動更新を一時停止しています" in res.text
    assert "wasAtBottom ? box.scrollHeight : previousScrollTop" in res.text
    assert "/api/settings/runtime/log-poll-interval" in res.text
    assert "_restartLogPolling()" in res.text
    assert '<button class="btn btn-secondary" onclick="location.reload()">更新</button>' not in res.text
    assert "読み込み / 更新" not in res.text


def test_logs_running_job_cancel_button_is_action_label(client):
    from web_app.job_manager import get_job_manager, JobStatus

    job = get_job_manager().create_job("generate", queued=False)
    job.status = JobStatus.RUNNING

    res = client.get("/logs")

    assert res.status_code == 200
    assert "running" in res.text
    assert "中止する" in res.text
    assert ">中止</button>" not in res.text


def test_log_poll_interval_runtime_endpoint(client, monkeypatch):
    from config import config

    monkeypatch.setattr(config, "WEB_LOG_POLL_INTERVAL_MS", 30000)
    res = client.get("/api/settings/runtime/log-poll-interval")

    assert res.status_code == 200
    assert res.json() == {"interval_ms": 30000}


# ── job_manager の状態遷移 ───────────────────────────────────────────────────
def test_job_manager_state_transitions():
    from web_app.job_manager import get_job_manager, JobStatus

    mgr = get_job_manager()
    job = mgr.create_job("test", queued=False)
    assert job.status == JobStatus.RUNNING

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
    (videos_dir / "Shorts_テスト動画" / "thumbnail.png").write_bytes(b"png")
    (videos_dir / "Long_テスト動画" / "video_native.mp4").write_bytes(b"mp4")

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
    (videos_dir / "short_テスト動画" / "thumbnail.png").write_bytes(b"png")

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "_history_db_info_bulk", lambda _local_ids: {
        "Shorts_台本だけ": {"video_format": "Shorts"},
    })
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
    (videos_dir / "Shorts_テスト動画" / "thumbnail.png").write_bytes(b"png")

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
    (uploaded_dir / "Shorts_DBあり" / "video_native.mp4").write_bytes(b"mp4")

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


def test_history_excludes_script_only_drafts(tmp_path, monkeypatch):
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    videos_dir = fake_output / "videos"
    (videos_dir / "Shorts_台本だけ").mkdir(parents=True)
    (videos_dir / "Shorts_生成物あり" / "thumbnails").mkdir(parents=True)
    (videos_dir / "Shorts_生成物あり" / "thumbnails" / "thumbnail.png").write_bytes(b"png")

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "_fetch_yt_status_bulk", lambda _local_ids: {})

    result = hs.list_histories(include_management=False)
    names = [r["name"] for r in result]

    assert "Shorts_台本だけ" not in names
    assert "Shorts_生成物あり" in names


def test_history_includes_script_only_committed_records(tmp_path, monkeypatch):
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    videos_dir = fake_output / "videos"
    (videos_dir / "Shorts_保存済み台本").mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, hs, fake_output)
    monkeypatch.setattr(hs, "_fetch_yt_status_bulk", lambda _local_ids: {})
    monkeypatch.setattr(
        hs,
        "_history_db_info_bulk",
        lambda _local_ids: {
            "Shorts_保存済み台本": {
                "video_title": "保存済み台本",
                "video_format": "Shorts",
                "has_script_content": 1,
            }
        },
    )

    result = hs.list_histories(include_management=False)

    assert [r["name"] for r in result] == ["Shorts_保存済み台本"]


def test_history_initializes_empty_metadata_db(tmp_path, monkeypatch):
    import core.metadata_db as m
    import web_app.services.history_service as hs

    fake_output = tmp_path / "output"
    videos_dir = fake_output / "videos"
    (videos_dir / "Shorts_初期化テスト").mkdir(parents=True)
    (videos_dir / "Shorts_初期化テスト" / "thumbnail.png").write_bytes(b"png")
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
    audio_dir = theme_dir / "audio"
    audio_dir.mkdir()
    (audio_dir / "001.wav").write_bytes(b"wav")
    (audio_dir / "memo.txt").write_text("ignore", encoding="utf-8")

    _patch_service_output_dirs(monkeypatch, hs, fake_output)

    res = client.get(f"/history/{quote(history_name, safe='')}")

    assert res.status_code == 200
    assert "const historyName =" in res.text
    assert "encodeURIComponent(historyName)" in res.text
    assert "history_names: [historyName]" in res.text
    assert "history_names: ['" not in res.text
    assert "音声データ" in res.text
    assert "1 件" in res.text


def test_history_open_folder_resolves_videos_dir(client, tmp_path, monkeypatch):
    import sys
    import web_app.routes.api_history as api_history

    fake_output = tmp_path / "output"
    theme_dir = fake_output / "videos" / "Shorts_フォルダ確認"
    theme_dir.mkdir(parents=True)

    monkeypatch.setattr(api_history, "find_history_dir", lambda name: str(theme_dir) if name == "Shorts_フォルダ確認" else None)
    opened = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(api_history.os, "startfile", lambda path: opened.append(path), raising=False)

    res = client.post("/api/history/Shorts_フォルダ確認/open-folder")

    assert res.status_code == 200
    assert opened == [str(theme_dir)]


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


def test_config_sanitizes_windows_path_control_escape():
    from web_app.services.config_service import sanitize_path_value

    broken = "C:\\Users\benyb\\AppData\\Local\\Programs\\VOICEVOX\\VOICEVOX.exe"

    assert sanitize_path_value(broken) == r"C:\Users\benyb\AppData\Local\Programs\VOICEVOX\VOICEVOX.exe"


def test_config_image_style_choices_current_is_csv(monkeypatch):
    from config import config
    from web_app.services.config_service import get_editable_config

    monkeypatch.setattr(config, "WEB_IMAGE_STYLE_CHOICES", ("通常", "アニメ", "水彩"))

    item = next(row for row in get_editable_config() if row["key"] == "WEB_IMAGE_STYLE_CHOICES")
    assert item["current"] == "通常,アニメ,水彩"
    assert "('" not in item["current"]


def test_config_has_admin_job_worker_setting():
    from web_app.services.config_service import get_editable_config

    item = next(row for row in get_editable_config() if row["key"] == "JOB_MAX_CONCURRENT_WORKERS")

    assert item["admin"] is True
    assert item["group"] == "ジョブ実行"
    assert item["min"] == 1
    assert item["max"] >= 1


def test_config_timeout_settings_are_admin():
    from web_app.services.config_service import get_editable_config

    items = {row["key"]: row for row in get_editable_config()}
    timeout_keys = [
        "VOICEVOX_CONNECTION_TIMEOUT_SEC",
        "VOICEVOX_QUERY_TIMEOUT_SEC",
        "VOICEVOX_SYNTHESIS_TIMEOUT_SEC",
        "SD_WEBUI_TIMEOUT_SEC",
        "WEB_VOICEVOX_CHECK_TIMEOUT_SEC",
        "WEB_FFMPEG_CHECK_TIMEOUT_SEC",
        "JOB_RUNNER_HEARTBEAT_TIMEOUT_SEC",
        "NATIVE_FFMPEG_TIMEOUT_SEC",
        "NATIVE_FFPROBE_TIMEOUT_SEC",
    ]

    for key in timeout_keys:
        assert items[key]["admin"] is True
        assert items[key]["group"] == "タイムアウト"


def test_config_web_app_name_is_admin():
    from web_app.services.config_service import get_editable_config

    items = {row["key"]: row for row in get_editable_config()}
    admin_web_ui_keys = [
        "WEB_APP_NAME",
        "WEB_SUCCESS_RELOAD_DELAY_MS",
        "WEB_TOAST_VISIBLE_MS",
        "WEB_TOAST_HIDE_DELAY_MS",
    ]

    for key in admin_web_ui_keys:
        assert items[key]["admin"] is True
        assert items[key]["group"] == "Web UI"


def test_native_character_layout_settings_are_editable():
    from web_app.services.config_service import get_editable_config

    items = {row["key"]: row for row in get_editable_config()}
    layout_keys = [
        "CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET",
        "CHARACTER_UPPER_BODY_LONG_Y_OFFSET",
        "NATIVE_CHARACTER_SIDE_MARGIN_SHORTS",
        "NATIVE_CHARACTER_SIDE_MARGIN_LONG",
    ]
    wiggle_keys = [
        "NATIVE_ENABLE_TALK_WIGGLE",
        "NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS",
        "NATIVE_TALK_WIGGLE_X_PX",
        "NATIVE_TALK_WIGGLE_Y_PX",
        "NATIVE_TALK_WIGGLE_HZ",
        "NATIVE_REACTION_EFFECT_MIN_GAP_SEGMENTS",
    ]

    for key in layout_keys:
        assert items[key]["group"] == "native立ち絵配置"
        assert items[key].get("admin") is not True

    for key in wiggle_keys:
        assert items[key]["group"] == "エフェクト"
        assert items[key].get("admin") is not True
    assert items["NATIVE_ENABLE_TALK_WIGGLE"]["default"] == "0"


def test_save_config_does_not_write_environment(tmp_path, monkeypatch):
    import os
    import core.settings_store as settings_store
    import web_app.services.config_service as cs

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.delenv("NATIVE_CHARACTER_SIDE_MARGIN_SHORTS", raising=False)

    errors = cs.save_config({"NATIVE_CHARACTER_SIDE_MARGIN_SHORTS": "-140"})

    assert errors == []
    assert settings_store.get_all()["NATIVE_CHARACTER_SIDE_MARGIN_SHORTS"] == "-140"
    assert "NATIVE_CHARACTER_SIDE_MARGIN_SHORTS" not in os.environ


def test_voicevox_worker_limits_reject_unstable_parallelism():
    import web_app.services.config_service as cs

    assert cs.save_config({"VOICEVOX_QUERY_WORKERS": "5"})
    assert cs.save_config({"VOICEVOX_SYNTH_WORKERS": "2"})


def test_voicevox_worker_limits_accept_safe_values(tmp_path, monkeypatch):
    import core.settings_store as settings_store
    import web_app.services.config_service as cs

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))

    errors = cs.save_config({
        "VOICEVOX_QUERY_WORKERS": "4",
        "VOICEVOX_SYNTH_WORKERS": "1",
    })

    assert errors == []
    assert settings_store.get_all()["VOICEVOX_QUERY_WORKERS"] == "4"
    assert settings_store.get_all()["VOICEVOX_SYNTH_WORKERS"] == "1"


def test_analytics_expansion_threshold_applies_without_restart(tmp_path, monkeypatch):
    import config.config as cfg
    import core.settings_store as settings_store
    import web_app.services.config_service as cs

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(cfg, "ANALYTICS_EXPANSION_MIN_VIEWS_SHORTS", cfg.ANALYTICS_EXPANSION_MIN_VIEWS_SHORTS)

    errors = cs.save_config({"ANALYTICS_EXPANSION_MIN_VIEWS_SHORTS": "6000"})

    assert errors == []
    assert settings_store.get_all()["ANALYTICS_EXPANSION_MIN_VIEWS_SHORTS"] == "6000"
    assert cfg.ANALYTICS_EXPANSION_MIN_VIEWS_SHORTS == 6000


def test_refresh_runtime_settings_normalizes_legacy_voicevox_workers(tmp_path, monkeypatch):
    import config.config as cfg
    import core.settings_store as settings_store
    from core.runtime_config import refresh_runtime_settings

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(cfg, "VOICEVOX_QUERY_WORKERS", cfg.VOICEVOX_QUERY_WORKERS)
    monkeypatch.setattr(cfg, "VOICEVOX_SYNTH_WORKERS", cfg.VOICEVOX_SYNTH_WORKERS)
    settings_store.set_many({
        "VOICEVOX_QUERY_WORKERS": "8",
        "VOICEVOX_SYNTH_WORKERS": "4",
    })

    refresh_runtime_settings()

    saved = settings_store.get_all()
    assert saved["VOICEVOX_QUERY_WORKERS"] == "4"
    assert saved["VOICEVOX_SYNTH_WORKERS"] == "1"
    assert cfg.VOICEVOX_QUERY_WORKERS == 4
    assert cfg.VOICEVOX_SYNTH_WORKERS == 1


def test_refresh_runtime_settings_normalizes_zero_voicevox_workers(tmp_path, monkeypatch):
    import config.config as cfg
    import core.settings_store as settings_store
    from core.runtime_config import refresh_runtime_settings

    monkeypatch.setattr(settings_store, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(cfg, "VOICEVOX_QUERY_WORKERS", cfg.VOICEVOX_QUERY_WORKERS)
    monkeypatch.setattr(cfg, "VOICEVOX_SYNTH_WORKERS", cfg.VOICEVOX_SYNTH_WORKERS)
    settings_store.set_many({
        "VOICEVOX_QUERY_WORKERS": "0",
        "VOICEVOX_SYNTH_WORKERS": "0",
    })

    refresh_runtime_settings()

    saved = settings_store.get_all()
    assert saved["VOICEVOX_QUERY_WORKERS"] == "1"
    assert saved["VOICEVOX_SYNTH_WORKERS"] == "1"
    assert cfg.VOICEVOX_QUERY_WORKERS == 1
    assert cfg.VOICEVOX_SYNTH_WORKERS == 1


def test_runner_worker_limit_reads_settings_db(monkeypatch):
    import workers.runner as runner
    import core.settings_store as settings_store

    monkeypatch.setattr(settings_store, "get_all", lambda: {"JOB_MAX_CONCURRENT_WORKERS": "2"})
    monkeypatch.setattr(runner, "_worker_limit_cache", (0.0, 1))

    assert runner._current_worker_limit(8) == 2


def test_runner_treats_empty_or_error_message_as_failure():
    from workers.runner import _result_error_message

    assert _result_error_message({"message": ""}).startswith("❌ 生成が原因不明")
    assert _result_error_message({"message": "Error: AI生成失敗"}) == "Error: AI生成失敗"
    assert _result_error_message({"message": "✅ 完成! 出力フォルダ: output/x"}) == ""


def test_run_render_success_includes_message(monkeypatch, tmp_path):
    """レンダー成功時の結果は message を持ち、原因不明エラーに誤判定されない。"""
    import threading
    from types import SimpleNamespace
    import workers.runner as runner

    monkeypatch.setattr(
        "core.native_renderer.render_native",
        lambda **kw: SimpleNamespace(output_path=str(tmp_path / "out.mp4")),
    )

    class _StubLog:
        def add(self, *a, **k):
            pass

    job = {"params": {"history_name": "h", "theme_dir": str(tmp_path)}}
    result = runner._run_render(job, threading.Event(), _StubLog())

    assert result.get("message")
    assert runner._result_error_message(result) == ""


def test_run_render_refreshes_settings_db_before_render(monkeypatch, tmp_path):
    """起動済みrunnerでも、再レンダー前にsettings.dbの最新設定をnative_rendererへ反映する。"""
    import threading
    from types import SimpleNamespace
    import core.native_renderer as native_renderer
    import workers.runner as runner

    monkeypatch.setattr("core.settings_store.get_all", lambda: {
        "NATIVE_TALK_WIGGLE_HZ": "2.5",
        "NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS": "4",
        "NATIVE_CHARACTER_SIDE_MARGIN_SHORTS": "-180",
        "CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET": "360",
    })
    monkeypatch.setattr(native_renderer, "NATIVE_TALK_WIGGLE_HZ", 5.5)
    monkeypatch.setattr(native_renderer, "NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS", 3)
    monkeypatch.setattr(native_renderer, "NATIVE_CHARACTER_SIDE_MARGIN_SHORTS", -120)
    monkeypatch.setattr(native_renderer, "CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET", 310)

    def fake_render(**kw):
        assert native_renderer.NATIVE_TALK_WIGGLE_HZ == 2.5
        assert native_renderer.NATIVE_TALK_WIGGLE_EVERY_N_SEGMENTS == 4
        assert native_renderer.NATIVE_CHARACTER_SIDE_MARGIN_SHORTS == -180
        assert native_renderer.CHARACTER_UPPER_BODY_SHORTS_Y_OFFSET == 360
        return SimpleNamespace(output_path=str(tmp_path / "out.mp4"))

    monkeypatch.setattr("core.native_renderer.render_native", fake_render)

    class _StubLog:
        def add(self, *a, **k):
            pass

    job = {"params": {"history_name": "h", "theme_dir": str(tmp_path)}}
    result = runner._run_render(job, threading.Event(), _StubLog())

    assert result["output_path"].endswith("out.mp4")


def test_discard_pending_jobs_cancels_only_queued_runnable(tmp_path, monkeypatch):
    """起動時破棄は queued の generate/render だけを cancelled にする。"""
    m = _patch_metadata_db(monkeypatch, tmp_path)

    base = {"profile_id": "p", "progress_text": "", "logs": [], "params": {}}
    m.upsert_job({**base, "job_id": "queued-gen", "type": "generate", "status": "queued"})
    m.upsert_job({**base, "job_id": "queued-render", "type": "render", "status": "queued"})
    m.upsert_job({**base, "job_id": "running-gen", "type": "generate", "status": "running"})
    m.upsert_job({**base, "job_id": "queued-other", "type": "image_regenerate", "status": "queued"})

    discarded = m.discard_pending_jobs(("generate", "render"))

    assert discarded == 2
    statuses = {r["job_id"]: r["status"] for r in m.load_jobs_from_db(max_n=10)}
    assert statuses["queued-gen"] == "cancelled"
    assert statuses["queued-render"] == "cancelled"
    assert statuses["running-gen"] == "running"
    assert statuses["queued-other"] == "queued"


def test_discard_orphan_running_jobs_fails_runnerless_running(tmp_path, monkeypatch):
    """runner情報のない running generate/render は起動時残骸として failed にする。"""
    m = _patch_metadata_db(monkeypatch, tmp_path)

    base = {"profile_id": "p", "progress_text": "", "logs": [], "params": {}}
    m.upsert_job({**base, "job_id": "orphan-gen", "type": "generate", "status": "running"})
    m.upsert_job({
        **base,
        "job_id": "runner-gen",
        "type": "generate",
        "status": "running",
        "runner_pid": 1234,
        "heartbeat_at": m._now_jst(),
    })
    m.upsert_job({**base, "job_id": "running-other", "type": "image_regenerate", "status": "running"})

    discarded = m.discard_orphan_running_jobs(("generate", "render"))

    assert discarded == 1
    rows = {r["job_id"]: r for r in m.load_jobs_from_db(max_n=10)}
    assert rows["orphan-gen"]["status"] == "failed"
    assert rows["runner-gen"]["status"] == "running"
    assert rows["running-other"]["status"] == "running"


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


# ── 単体再生リスト振り分け ──────────────────────────────────────────────────
def test_playlist_classifier_page(client, monkeypatch):
    import web_app.services.playlist_classifier_service as service

    monkeypatch.setattr(service, "list_classifier_candidates", lambda: [])
    res = client.get("/playlist-classifier")

    assert res.status_code == 200
    assert "この画面で手動実行した場合だけOllamaを使用します" in res.text


def test_playlist_classifier_requires_confirmation(client):
    res = client.post(
        "/api/playlist-classifier",
        json={
            "history_names": ["Long_テスト"],
            "only_unregistered": True,
            "confirmed": False,
        },
    )
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


def test_api_fixed_comment_mark_all_posted_requires_confirmation(client):
    res = client.post("/api/fixed-comment/mark-all-posted", json={"confirmed": False})
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


def test_fixed_comment_candidates_include_scheduled_when_youtube_public(tmp_path, monkeypatch):
    import web_app.services.fixed_comment_service as fcs

    fake_output = tmp_path / "output"
    theme_dir = fake_output / "000_uploaded" / "Shorts_公開済み予約テスト"
    theme_dir.mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, fcs, fake_output)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    _seed_fixed_comment_db(
        m,
        "Shorts_公開済み予約テスト",
        "public_scheduled123",
        "公開後に投稿するコメントです",
        publish_status="scheduled",
    )
    monkeypatch.setattr(
        fcs,
        "_fetch_youtube_statuses",
        lambda _ids: {
            "public_scheduled123": {
                "privacyStatus": "public",
                "publishedAt": "2026-06-02T12:00:00Z",
                "title": "YouTube側の公開済みタイトル",
            }
        },
    )

    candidates = fcs.list_fixed_comment_candidates()

    assert len(candidates) == 1
    assert candidates[0]["video_id"] == "public_scheduled123"
    assert candidates[0]["publish_status"] == "public"
    assert candidates[0]["title"] == "YouTube側の公開済みタイトル"


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


def test_fixed_comment_mark_all_posted_writes_records(tmp_path, monkeypatch):
    import web_app.services.fixed_comment_service as fcs

    fake_output = tmp_path / "output"
    (fake_output / "000_uploaded" / "Shorts_一括1").mkdir(parents=True)
    (fake_output / "000_uploaded" / "Shorts_一括2").mkdir(parents=True)

    _patch_service_output_dirs(monkeypatch, fcs, fake_output)
    m = _patch_metadata_db(monkeypatch, tmp_path)
    _seed_fixed_comment_db(m, "Shorts_一括1", "vid1", "コメント1")
    _seed_fixed_comment_db(m, "Shorts_一括2", "vid2", "コメント2")
    monkeypatch.setattr(
        fcs,
        "_fetch_youtube_statuses",
        lambda _ids: {
            "vid1": {"privacyStatus": "public"},
            "vid2": {"privacyStatus": "public"},
        },
    )

    result = fcs.mark_all_fixed_comments_posted()

    assert result["marked"] == 2
    assert result["failed"] == 0
    with m.ManagedConnection() as conn:
        rows = conn.execute(
            "SELECT local_id, fixed_comment_posted FROM youtube_status ORDER BY local_id"
        ).fetchall()
    assert {row["local_id"]: row["fixed_comment_posted"] for row in rows} == {
        "Shorts_一括1": 1,
        "Shorts_一括2": 1,
    }


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
    # 自動投稿は OS タスク経由の post_all_pending（直接投稿）で行う。scope=all を検証。
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
        "post_fixed_comment_now",
        lambda history_name, profile_id=None, auto_posted=False, log=None, is_cancelled=None:
            (calls.append((history_name, auto_posted, profile_id)) or {"comment_thread_id": "ct"}),
    )

    result = afc.post_all_pending()

    assert calls == [
        ("ch_a_video", True, "ch_a"),
        ("ch_b_video", True, "ch_b"),
    ]
    assert result["posted"] == 2


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
        "post_fixed_comment_now",
        lambda history_name, profile_id=None, auto_posted=False, log=None, is_cancelled=None:
            (calls.append((history_name, auto_posted, profile_id)) or {"comment_thread_id": "ct"}),
    )

    afc.post_all_pending()

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


def test_get_job_prefers_db_for_queued_runner_job(tmp_path, monkeypatch):
    import core.metadata_db as m
    from web_app.job_manager import JobManager

    m = _patch_metadata_db(monkeypatch, tmp_path)
    monkeypatch.setattr("web_app.job_manager.JobManager._active_profile_id", lambda _self: "test_profile")

    mgr = JobManager()
    job = mgr.create_job("generate", {"script": "動画形式: Shorts"}, queued=True)
    m.append_job_logs(job.job_id, [{"time": "2026-06-02T12:00:00+09:00", "tag": "info", "message": "runner側ログ"}])
    m.update_job_progress(job.job_id, "runner側進捗", "2026-06-02T12:00:00+09:00")

    found = mgr.get_job(job.job_id)

    assert found is not None
    assert found.progress_text == "runner側進捗"
    assert found.logs[-1]["message"] == "runner側ログ"


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


def test_submit_generate_logs_queue_wait_note(tmp_path, monkeypatch):
    """同時実行枠が埋まっている場合、登録直後にキュー待機理由をログへ出す。"""
    import web_app.services.generation_service as gs
    import core.metadata_db as m

    m = _patch_metadata_db(monkeypatch, tmp_path)
    monkeypatch.setattr("web_app.job_manager.JobManager._active_profile_id", lambda _self: "test_profile")
    monkeypatch.setattr("core.settings_store.get_all", lambda: {"JOB_MAX_CONCURRENT_WORKERS": "1"})
    m.upsert_job({
        "job_id": "running-job",
        "type": "generate",
        "profile_id": "test_profile",
        "status": "running",
        "progress_text": "実行中",
        "logs": [],
        "params": {},
        "runner_pid": 1234,
        "heartbeat_at": m._now_jst(),
    })

    job_id = gs.submit_generate_job("動画形式: Shorts\n動画タイトル: queue-test\n")
    row = next(r for r in m.load_jobs_from_db(max_n=10) if r["job_id"] == job_id)

    assert any("キュー待機中" in log["message"] for log in row["logs"])


def test_batch_generate_registers_parent_before_child_jobs(tmp_path, monkeypatch):
    """複数生成は全子ジョブを即時投入せず、親ジョブだけを先に登録する。"""
    import web_app.services.generation_service as gs
    import core.metadata_db as m

    m = _patch_metadata_db(monkeypatch, tmp_path)
    monkeypatch.setattr("web_app.job_manager.JobManager._active_profile_id", lambda _self: "test_profile")
    monkeypatch.setattr(
        "web_app.job_manager.JobManager.submit",
        lambda self, job, fn, *args, **kwargs: None,
    )

    job_ids = gs.submit_batch_generate_jobs([
        "動画形式: Shorts\n動画タイトル: a\n",
        "動画形式: Shorts\n動画タイトル: b\n",
        "動画形式: Shorts\n動画タイトル: c\n",
    ])
    rows = m.load_jobs_from_db(max_n=10)

    assert len(job_ids) == 1
    assert [row["type"] for row in rows] == ["generate_batch"]
    assert rows[0]["params"]["count"] == 3


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
