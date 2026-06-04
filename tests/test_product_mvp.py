from __future__ import annotations

import zipfile
import sqlite3
from pathlib import Path
from types import SimpleNamespace


def test_license_defaults_to_trial(monkeypatch):
    import core.license_manager as lm
    monkeypatch.setattr(lm, "get_all", lambda: {})
    info = lm.get_license_info()
    assert info["edition"] == "trial"
    assert info["limits"]["watermark"] is True
    assert info["limits"]["youtube_upload"] is False


def test_license_info_exposes_purchase_url_and_upgrade(monkeypatch):
    import core.license_manager as lm
    monkeypatch.setattr(lm, "get_all", lambda: {})
    monkeypatch.setattr(lm.config, "PRODUCT_PURCHASE_URL", "https://example.com/buy")
    info = lm.get_license_info()
    assert info["purchase_url"] == "https://example.com/buy"
    assert info["upgrade_available"] is True  # trial は上位余地あり


def test_upload_block_message_includes_purchase_cta(monkeypatch):
    import core.license_manager as lm
    monkeypatch.setattr(lm, "get_all", lambda: {"LICENSE_EDITION": "trial"})
    monkeypatch.setattr(lm.config, "PRODUCT_PURCHASE_URL", "https://example.com/buy")
    import pytest
    with pytest.raises(RuntimeError) as exc:
        lm.assert_can_upload()
    assert "https://example.com/buy" in str(exc.value)


def test_diagnostics_masks_secret_values(tmp_path, monkeypatch):
    import web_app.services.diagnostics_service as ds

    monkeypatch.setattr(ds, "_DIAG_DIR", tmp_path)
    monkeypatch.setattr(ds, "get_all", lambda: {
        "GOOGLE_API_KEY": "AIza-should-not-appear",
        "OPENAI_API_KEY": "sk-should-not-appear",
        "LICENSE_ID": "license-should-not-appear",
        "WEB_APP_NAME": "Native Video Factory",
    })

    import web_app.services.status_service as status_service
    monkeypatch.setattr(status_service, "get_settings_status", lambda: {
        "google_api_key": True,
        "openai_api_key": True,
        "voicevox": {"ok": True},
    })

    import core.gui_support as gui_support
    monkeypatch.setattr(gui_support, "build_app_version", lambda: "test-version")

    class DummyJobManager:
        def list_jobs(self):
            return [{
                "job_id": "job1",
                "type": "generate",
                "status": "failed",
                "progress_text": "API_KEY=AIza-should-not-appear",
                "error": "token=secret-token",
                "logs": [{"message": "OPENAI_API_KEY=sk-should-not-appear"}],
            }]

    import web_app.job_manager as jm
    monkeypatch.setattr(jm, "get_job_manager", lambda: DummyJobManager())

    result = ds.create_diagnostics_package()
    with zipfile.ZipFile(result["path"], "r") as zf:
        blob = b"".join(zf.read(name) for name in zf.namelist()).decode("utf-8")

    assert "AIza-should-not-appear" not in blob
    assert "sk-should-not-appear" not in blob
    assert "license-should-not-appear" not in blob
    assert "secret-token" not in blob
    assert "***MASKED***" in blob


def test_detect_services_proposes_known_paths(monkeypatch):
    import psutil
    import core.service_detector as sd

    class _Addr:
        def __init__(self, port):
            self.port = port

    class _Conn:
        def __init__(self, port, pid):
            self.status = psutil.CONN_LISTEN
            self.laddr = _Addr(port)
            self.pid = pid

    monkeypatch.setattr(
        sd.psutil, "net_connections",
        lambda kind="tcp": [_Conn(50021, 111), _Conn(11434, 222), _Conn(7860, 333)],
    )
    monkeypatch.setattr(sd, "_proc_exe", lambda pid: f"/proc/{pid}/exe")
    monkeypatch.setattr(sd, "_find_process_exe_by_keyword", lambda kws: "C:/VOICEVOX/VOICEVOX.exe")
    monkeypatch.setattr(sd.shutil, "which", lambda name: "C:/ffmpeg/bin/ffmpeg.exe")

    result = sd.detect_services()
    proposed = result["proposed"]
    assert proposed["VOICEVOX_URL"] == "http://127.0.0.1:50021"
    assert proposed["VOICEVOX_PATH"] == "C:/VOICEVOX/VOICEVOX.exe"
    assert proposed["OLLAMA_BASE_URL"] == "http://127.0.0.1:11434"
    assert proposed["SD_WEBUI_BASE_URL"] == "http://127.0.0.1:7860"
    assert proposed["FFMPEG_BIN"] == "C:/ffmpeg/bin/ffmpeg.exe"
    # 全キーが EDITABLE_CONFIG に存在し、適用可能であること
    from web_app.services.config_service import EDITABLE_CONFIG
    editable = {item["key"] for item in EDITABLE_CONFIG}
    assert set(proposed).issubset(editable)


def test_product_seed_profiles_excludes_existing_channel_specific_profiles():
    from core.prompt_profile_loader import list_product_seed_profiles
    profiles = list_product_seed_profiles()
    assert "general" in profiles
    assert "zunkami" not in profiles
    seed_root = Path("config/SEED/prompt_packs/product")
    blob = "\n".join(path.read_text(encoding="utf-8") for path in seed_root.rglob("*") if path.is_file())
    assert "@zunkami" not in blob
    assert "食べ物雑学" not in blob


def test_backup_and_restore_settings_and_metadata(tmp_path, monkeypatch):
    import web_app.services.backup_service as bs
    import core.metadata_db as m

    settings_db = tmp_path / "data" / "settings.db"
    settings_db.parent.mkdir()
    with sqlite3.connect(settings_db) as conn:
        conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings(key, value) VALUES('A','settings-v1')")
        conn.commit()
    profile_root = tmp_path / "output" / "profile_a"
    metadata_db = profile_root / "000_data" / "metadata.db"
    metadata_db.parent.mkdir(parents=True)
    metadata_db.write_bytes(b"metadata-v1")

    monkeypatch.setattr(bs, "_ROOT", tmp_path)
    monkeypatch.setattr(bs, "_BACKUP_DIR", tmp_path / "output" / "_backups")
    monkeypatch.setattr(bs, "_SETTINGS_DB", settings_db)
    monkeypatch.setattr(m, "SCHEMA_VERSION", 7)

    import core.channel_profile as cp
    monkeypatch.setattr(cp, "list_profiles", lambda: [
        SimpleNamespace(profile_id="profile_a", output_root_abs=str(profile_root))
    ])

    created = bs.create_backup()
    with sqlite3.connect(settings_db) as conn:
        conn.execute("UPDATE settings SET value='settings-broken' WHERE key='A'")
        conn.commit()
    metadata_db.write_bytes(b"metadata-broken")
    restored = bs.restore_backup(created["path"], confirmed=True)

    with sqlite3.connect(settings_db) as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='A'").fetchone()[0] == "settings-v1"
    assert metadata_db.read_bytes() == b"metadata-v1"
    assert "pre_restore_backup" in restored
