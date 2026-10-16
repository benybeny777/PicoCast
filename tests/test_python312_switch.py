"""切り替え準備の検査・退避を一時データだけで確認する。実 Apply は呼ばない。"""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import base64

import pytest


_spec = importlib.util.spec_from_file_location(
    "python312_switch_fixture", Path(__file__).resolve().parents[1] / "scripts" / "python312_switch.py"
)
switch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(switch)


@pytest.fixture
def migration_workspace(tmp_path):
    root = tmp_path / "workspace"
    (root / "data").mkdir(parents=True)
    metadata = root / "output" / "fixture" / "000_data" / "metadata.db"
    metadata.parent.mkdir(parents=True)
    settings = sqlite3.connect(root / "data" / "settings.db")
    jobs = sqlite3.connect(metadata)
    try:
        settings.execute("PRAGMA journal_mode=WAL")
        settings.executescript("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE channel_profiles(output_root TEXT);")
        settings.execute("INSERT INTO channel_profiles VALUES('fixture')")
        settings.commit()
        jobs.execute("PRAGMA journal_mode=WAL")
        jobs.execute("CREATE TABLE jobs(status TEXT,runner_pid INTEGER,started_at TEXT,heartbeat_at TEXT,created_at TEXT)")
        jobs.commit()
        yield root, settings, jobs, metadata
    finally:
        jobs.close()
        settings.close()


def runner(pid=42, *, workspace=True, role="runner", created="2026-10-16T00:00:00Z"):
    return {"pid": pid, "created_at": created, "workspace": workspace, "role": role}


def insert_job(connection, *, status="running", pid=None, started=None, heartbeat=None, created="2026-06-01T00:00:00Z"):
    connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?)", (status, pid, started, heartbeat, created))
    connection.commit()


@pytest.mark.parametrize(
    ("options", "processes", "expected"),
    [
        ({"pid": 99}, [runner()], {"running_historical": 1}),
        ({"pid": 42}, [runner(workspace=False, role="other")], {"running_historical": 1}),
        ({}, [runner()], {"running_historical": 1}),
        ({"created": None}, [runner()], {"running_ambiguous": 1}),
        ({"pid": 42, "started": "2026-10-16T00:01:00Z", "heartbeat": "2026-10-16T00:02:00Z"}, [runner()], {"running_active": 1}),
        ({"pid": 42}, [runner(workspace=False, role="other", created="2026-05-01T00:00:00Z")], {"running_ambiguous": 1}),
        ({"status": "queued"}, [runner()], {"queued": 1}),
    ],
)
def test_probe_distinguishes_old_active_reused_and_ambiguous_pids(migration_workspace, options, processes, expected):
    root, _settings, jobs, _metadata = migration_workspace
    insert_job(jobs, **options)
    result = switch.probe(root, processes)
    for name in ["queued", "running_active", "running_historical", "running_ambiguous"]:
        assert result[name] == expected.get(name, 0)


@pytest.mark.parametrize("enabled", [True, False, "false", None])
def test_probe_validates_autopilot_boolean_without_silent_downgrade(migration_workspace, enabled):
    root, settings, _jobs, _metadata = migration_workspace
    settings.execute("INSERT INTO settings VALUES('AUTOPILOT_POLICY:fixture',?)", (json.dumps({"enabled": enabled}),))
    settings.commit()
    if isinstance(enabled, bool):
        assert switch.probe(root, [])["autopilot_enabled"] == int(enabled)
    else:
        with pytest.raises(switch.MigrationCheckError) as error:
            switch.probe(root, [])
        assert error.value.code == "E-MIGRATION-POLICY"
        assert error.value.target == "autopilot_policy"


def test_probe_refuses_naive_job_time_without_assuming_timezone(migration_workspace):
    root, _settings, jobs, _metadata = migration_workspace
    insert_job(jobs, created="2026-06-01T00:00:00")
    with pytest.raises(switch.MigrationCheckError) as error:
        switch.probe(root, [runner()])
    assert error.value.code == "E-MIGRATION-TIMEZONE"
    assert error.value.target == "job_timestamp"


def test_source_connection_is_readonly(migration_workspace):
    root, _settings, _jobs, _metadata = migration_workspace
    path = root / "data" / "settings.db"
    before = path.read_bytes()
    with closing(switch.readonly(path, "fixture")) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO settings VALUES('must-not-write','value')")
    assert path.read_bytes() == before


def test_online_backup_contains_wal_preserves_sources_and_private_files(migration_workspace, tmp_path, monkeypatch):
    root, settings, jobs, metadata = migration_workspace
    settings.execute("INSERT INTO settings VALUES('fixture-value','retained')")
    settings.commit()
    insert_job(jobs, status="completed")
    home = tmp_path / "fixture-home"
    (home / ".nvf_license").mkdir(parents=True)
    (home / ".nvf_license" / "private_key.pem").write_bytes(b"fixture-private-key")
    monkeypatch.setattr(switch.Path, "home", staticmethod(lambda: home))
    (root / ".env").write_text("FIXTURE_ONLY=not-a-real-secret\n", encoding="utf-8")
    (root / "data" / "secret_master.key").write_bytes(b"fixture-master-key")
    (root / ".gitignore").write_text("data/\noutput/\n.env\n", encoding="utf-8")
    (root / "tracked.txt").write_text("before\n", encoding="utf-8")
    commands = [["init"], ["add", ".gitignore", "tracked.txt"], ["-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "fixture"]]
    for command in commands:
        subprocess.run(["git", "-C", str(root), *command], check=True, capture_output=True)
    (root / "tracked.txt").write_text("after\n", encoding="utf-8")
    (root / "untracked.txt").write_bytes(b"uncommitted-fixture")
    paths = [root / "data" / "settings.db", Path(str(root / "data" / "settings.db") + "-wal"), metadata, Path(str(metadata) + "-wal"), root / "data" / "secret_master.key", home / ".nvf_license" / "private_key.pem"]
    before = {path: path.read_bytes() for path in paths}
    destination = tmp_path / "outside-repository-backup"
    result = switch.backup(root, destination, timeout_seconds=30)
    assert result == {"backed_up_databases": 2, "private_files": 3}
    assert {path: path.read_bytes() for path in paths} == before
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    for database in manifest["databases"]:
        with closing(sqlite3.connect(destination / database["backup"])) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            if Path(database["source"]).name == "settings.db":
                assert connection.execute("SELECT value FROM settings WHERE key='fixture-value'").fetchone() == ("retained",)
            else:
                assert connection.execute("SELECT status FROM jobs").fetchall() == [("completed",)]
    assert (destination / "untracked" / "untracked.txt").read_bytes() == b"uncommitted-fixture"
    assert b"after" in (destination / "working-tree.patch").read_bytes()
    assert manifest["sample_generation"] == "未実行"
    assert manifest["sample_render"] == "未実行"


def test_backup_rejects_repository_destination_before_mutation(migration_workspace):
    root, _settings, _jobs, _metadata = migration_workspace
    destination = root / "forbidden-backup"
    with pytest.raises(ValueError, match="リポジトリ内"):
        switch.backup(root, destination, timeout_seconds=30)
    assert not destination.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 の純粋関数検証")
def test_powershell_stop_order_uses_parent_links_instead_of_pid_sorting():
    path = (Path(__file__).resolve().parents[1] / "scripts" / "switch-python312.ps1").as_posix().replace("'", "''")
    code = r"""
$ErrorActionPreference='Stop'
$tokens=$null
$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'parse failure'}
$function=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-RunnerStopOrder'},$true)
Invoke-Expression $function.Extent.Text
$items=@([pscustomobject]@{pid=28808;parent=0},[pscustomobject]@{pid=26960;parent=28808},[pscustomobject]@{pid=1;parent=26960})
$order=@(Get-RunnerStopOrder -Runners $items | ForEach-Object {$_.pid})
[string]::Join(',',$order)
""".replace("__SCRIPT__", path)
    encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.stdout.decode("utf-8").strip() == "1,26960,28808"
