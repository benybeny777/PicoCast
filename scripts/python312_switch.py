"""Python 切り替えの読み取り検査と、明示実行時だけの退避・隔離検証。"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


class MigrationCheckError(Exception):
    def __init__(self, code: str, target: str):
        super().__init__(code)
        self.code = code
        self.target = target


def readonly(path: Path, target="database"):
    try:
        return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise MigrationCheckError("E-MIGRATION-DB-OPEN", target) from error


def discover(root: Path):
    settings = root / "data" / "settings.db"
    if not settings.is_file():
        raise MigrationCheckError("E-MIGRATION-SETTINGS-MISSING", "settings_db")
    try:
        with closing(readonly(settings, "settings_db")) as connection:
            values = dict(connection.execute("SELECT key,value FROM settings"))
            profiles = list(connection.execute("SELECT output_root FROM channel_profiles"))
    except sqlite3.Error as error:
        raise MigrationCheckError("E-MIGRATION-DB-SCHEMA", "settings_db") from error
    base_value = values.get("OUTPUT_BASE_DIR", "").strip()
    base = Path(base_value) if base_value else root / "output"
    if not base.is_absolute():
        base = root / base
    candidates = {settings}
    missing = []
    for (relative,) in profiles:
        if not relative:
            raise MigrationCheckError("E-MIGRATION-PROFILE-PATH", "profile_output")
        output = Path(relative)
        if not output.is_absolute():
            output = base / output
        path = output / "000_data" / "metadata.db"
        if path.is_file():
            candidates.add(path.resolve())
        else:
            missing.append(str(path))
    # 登録外に残る DB も保護する。未登録プロファイルをアプリへ追加しない。
    if base.exists():
        candidates.update(path.resolve() for path in base.glob("*/000_data/metadata.db") if path.is_file())
    return sorted(candidates), missing, values


def instant(value, target="job_timestamp"):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise MigrationCheckError("E-MIGRATION-TIME", target) from error
    if parsed.tzinfo is None:
        raise MigrationCheckError("E-MIGRATION-TIMEZONE", target)
    return parsed.astimezone(timezone.utc)


def probe(root: Path, processes):
    databases, missing, settings = discover(root)
    try:
        policies = [json.loads(value) for key, value in settings.items() if key.startswith("AUTOPILOT_POLICY:")]
    except ValueError as error:
        raise MigrationCheckError("E-MIGRATION-POLICY", "autopilot_policy") from error
    if any(not isinstance(policy, dict) or not isinstance(policy.get("enabled"), bool) for policy in policies):
        raise MigrationCheckError("E-MIGRATION-POLICY", "autopilot_policy")
    process_map = {int(process["pid"]): process for process in processes}
    runners = [process for process in processes if process["workspace"] and process["role"] == "runner"]
    earliest_runner = min((instant(process["created_at"], "process_creation") for process in runners), default=None)
    queued = active = historical = ambiguous = 0
    for path in databases:
        if path.name != "metadata.db":
            continue
        with closing(readonly(path, "metadata_db")) as connection:
            try:
                exists = connection.execute("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='jobs' AND type='table')").fetchone()[0]
                records = list(connection.execute("SELECT status,runner_pid,started_at,heartbeat_at,created_at FROM jobs WHERE status IN ('queued','running')")) if exists else []
            except sqlite3.Error as error:
                raise MigrationCheckError("E-MIGRATION-DB-SCHEMA", "metadata_db") from error
            if not exists:
                raise MigrationCheckError("E-MIGRATION-DB-SCHEMA", "metadata_jobs")
            for status, runner_pid, started, heartbeat, created_at in records:
                if status == "queued":
                    queued += 1
                    continue
                # 開始時刻と心拍の無い旧記録でも、保存された作成時刻は判定根拠に含める。
                activity = max((value for value in [instant(started), instant(heartbeat), instant(created_at)] if value is not None), default=None)
                process = process_map.get(int(runner_pid)) if runner_pid else None
                if process is not None:
                    created = instant(process["created_at"], "process_creation")
                    if activity is not None and created > activity:
                        historical += 1
                    elif process["workspace"] and process["role"] == "runner":
                        active += 1
                    else:
                        ambiguous += 1
                elif runner_pid:
                    historical += 1
                elif not runners or (activity is not None and earliest_runner is not None and activity < earliest_runner):
                    historical += 1
                else:
                    ambiguous += 1
    return {"databases": len(databases), "missing_metadata": len(missing), "autopilot_enabled": sum(policy["enabled"] for policy in policies), "queued": queued, "running_active": active, "running_historical": historical, "running_ambiguous": ambiguous}


def safe_destination(path: Path, root: Path):
    if path.resolve().is_relative_to(root.resolve()):
        raise ValueError("退避先がリポジトリ内です")
    if path.exists():
        raise ValueError("退避先が既に存在します")
    path.mkdir(parents=True)


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backup(root: Path, destination: Path, timeout_seconds: int):
    safe_destination(destination, root)
    logging.basicConfig(filename=destination / "app_debug_migration.log", level=logging.INFO, encoding="utf-8")
    databases, missing, _ = discover(root)
    manifest = {"databases": [], "files": [], "missing_metadata": missing, "sample_generation": "未実行", "sample_render": "未実行"}
    for index, path in enumerate(databases):
        deadline = time.monotonic() + timeout_seconds
        def progress(_status, _remaining, _total):
            if time.monotonic() > deadline:
                raise TimeoutError("DB 退避の時間上限を超えました")
        target = destination / "databases" / str(index) / path.name
        target.parent.mkdir(parents=True)
        with closing(readonly(path)) as source:
            if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("元 DB の整合性検査に失敗しました")
            with closing(sqlite3.connect(target)) as copied:
                source.backup(copied, progress=progress)
                if copied.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("退避 DB の整合性検査に失敗しました")
        manifest["databases"].append({"source": str(path), "backup": str(target.relative_to(destination)), "sha256": digest(target)})
    sources = [root / name for name in [".env", "client_secrets.json", "token.json", "token_analytics.json", "data/secret_master.key"]]
    license_root = Path.home() / ".nvf_license"
    if license_root.is_dir():
        sources.extend(path for path in license_root.rglob("*") if path.is_file())
    for index, source in enumerate(sources):
        if source.is_file():
            target = destination / "private" / str(index) / source.name
            target.parent.mkdir(parents=True)
            shutil.copy2(source, target)
            if digest(source) != digest(target):
                raise ValueError("認証ファイルの退避照合に失敗しました")
            manifest["files"].append({"source": str(source), "backup": str(target.relative_to(destination)), "sha256": digest(target)})
    patch = subprocess.run(["git", "-C", str(root), "diff", "--binary", "HEAD"], check=True, capture_output=True, timeout=timeout_seconds).stdout
    (destination / "working-tree.patch").write_bytes(patch)
    staged = subprocess.run(["git", "-C", str(root), "diff", "--binary", "--cached"], check=True, capture_output=True, timeout=timeout_seconds).stdout
    (destination / "index.patch").write_bytes(staged)
    untracked = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"], check=True, capture_output=True, timeout=timeout_seconds).stdout
    for raw in untracked.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        source = root / relative
        if not source.resolve().is_relative_to(root.resolve()) or not source.is_file():
            raise ValueError("未追跡ファイルの実体を確認できません")
        target = destination / "untracked" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if digest(source) != digest(target):
            raise ValueError("未追跡ファイルの退避照合に失敗しました")
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"backed_up_databases": len(manifest["databases"]), "private_files": len(manifest["files"])}


def tests(root: Path, destination: Path, label: str, timeout_seconds: int):
    # conftest とオラクルの共通隔離が、collection より先に DB とネットワークを遮断する。
    if not (root / "tools" / "oracle_environment.py").is_file():
        raise ValueError("オフライン隔離の共通処理がありません")
    report = destination / (label + ".xml")
    arguments = [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--junitxml", str(report), "--basetemp", str(root / "temp" / "python312-switch" / label)]
    with (destination / "app_debug_migration.log").open("ab") as log:
        completed = subprocess.run(arguments, cwd=root, stdout=log, stderr=log, timeout=timeout_seconds)
        if completed.returncode != 0:
            raise ValueError("隔離全テストに失敗しました")
        oracle = subprocess.run([sys.executable, "tools/oracle.py"], cwd=root, stdout=log, stderr=log, timeout=timeout_seconds)
        if oracle.returncode != 0:
            raise ValueError("オフラインオラクルに失敗しました")
    tree = ET.parse(report)
    cases = tree.findall(".//testcase")
    if not cases:
        raise ValueError("テスト件数を確認できません")
    result = {"tests": len(cases), "case_ids": sorted(case.get("classname", "") + "::" + case.get("name", "") for case in cases), "skipped": sum(case.find("skipped") is not None for case in cases), "oracle": "一致"}
    (destination / (label + ".json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    if label == "python312":
        previous = json.loads((destination / "python311.json").read_text(encoding="utf-8"))
        if previous != result:
            raise ValueError("切り替え前後のテスト件数またはskip件数が一致しません")
    return result


def sync(root: Path, destination: Path, uv: Path, timeout_seconds: int):
    # 課金APIや認証付きindexの環境変数を依存導入へ渡さない。
    names = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in names}
    environment.update(UV_PROJECT_ENVIRONMENT=str(root / ".venv"), UV_PYTHON_DOWNLOADS="never", UV_NO_PROGRESS="1")
    completed = subprocess.run([str(uv), "--no-config", "sync", "--locked", "--group", "build", "--group", "dev", "--python", "3.12"], cwd=root, env=environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout_seconds)
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    output = re.sub(r"https?://[^\s]+", "<外部URL省略>", output)
    output = re.sub(r"\b(?:sk-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+)\b", "<秘密値省略>", output)
    (destination / "uv-sync-debug.log").write_text(output, encoding="utf-8")
    if completed.returncode != 0:
        raise ValueError("uv sync に失敗しました")
    return {"synced": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["probe", "backup", "tests", "sync"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--label", choices=["python311", "python312"])
    parser.add_argument("--uv", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.timeout_seconds <= 0:
            raise ValueError("時間上限は正の秒数が必要です")
        if arguments.operation == "probe":
            result = probe(arguments.root.resolve(), json.load(sys.stdin))
        else:
            if not arguments.apply or arguments.destination is None:
                raise ValueError("書込み操作には明示 apply と退避先が必要です")
            if arguments.operation == "backup":
                result = backup(arguments.root.resolve(), arguments.destination.resolve(), arguments.timeout_seconds)
            elif arguments.operation == "tests":
                if arguments.label is None:
                    raise ValueError("検証対象の版がありません")
                result = tests(arguments.root.resolve(), arguments.destination.resolve(), arguments.label, arguments.timeout_seconds)
            else:
                if arguments.uv is None:
                    raise ValueError("uv の実体が必要です")
                result = sync(arguments.root.resolve(), arguments.destination.resolve(), arguments.uv.resolve(), arguments.timeout_seconds)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except Exception as error:
        # CheckOnly はファイルを作れないため、詳細ログも Apply の退避先だけに残す。
        if arguments.apply and arguments.destination is not None and arguments.destination.is_dir():
            logging.basicConfig(filename=arguments.destination / "app_debug_migration.log", level=logging.INFO, encoding="utf-8")
            logging.exception("Python 切り替えの検査または退避に失敗しました")
        cause = error.__cause__ if error.__cause__ is not None else error
        diagnostic = {"ok": False, "code": getattr(error, "code", "E-MIGRATION-CHECK"), "target": getattr(error, "target", arguments.operation), "cause_type": type(cause).__name__, "sqlite_errorname": getattr(cause, "sqlite_errorname", None)}
        print(json.dumps(diagnostic, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
