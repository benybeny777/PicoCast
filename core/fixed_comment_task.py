"""固定コメント自動投稿の OS タスク登録。

Web UI / runner が起動していなくても、OS のスケジューラから
`<exe> --post-fixed-comments`（開発時は `python -m web_app.app --post-fixed-comments`）を
予約スロット時刻に定期実行して未投稿の固定コメントを投稿する。

- Windows: タスクスケジューラ（PowerShell Register-ScheduledTask、ユーザータスク・管理者権限不要）
- macOS:   launchd LaunchAgent（~/Library/LaunchAgents）

同一PCで複数のインストール/テストディレクトリを使い分けても区別できるよう、
タスク名/ラベルにインストールディレクトリの識別子（リーフ名＋パスのハッシュ）を含める。
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import subprocess
import sys

from core.runtime_env import app_base_dir, is_frozen

_logger = logging.getLogger(__name__)

_TASK_PREFIX = "NativeVideoFactory-FixedComment"
_MAC_LABEL_PREFIX = "com.nativevideofactory.fixedcomment"
# 予約スロット時刻の何分後に投稿するか（auto_fixed_comment_service の _PUBLISH_BUFFER_SEC=300 と揃える）
_BUFFER_MINUTE = 5


# ── 識別子・コマンド・時刻 ────────────────────────────────────────────────────

def _dir_parts() -> tuple[str, str, str]:
    """(リーフ名, パスハッシュ8桁, フルパス) を返す。"""
    base = app_base_dir()
    leaf = os.path.basename(base.rstrip("/\\")) or "root"
    leaf = re.sub(r"[^A-Za-z0-9_-]+", "_", leaf)[:24] or "root"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return leaf, digest, base


def task_name() -> str:
    """Windows タスク名（ディレクトリ識別子つき）。"""
    leaf, digest, _ = _dir_parts()
    return f"{_TASK_PREFIX}-{leaf}-{digest}"


def _mac_label() -> str:
    leaf, digest, _ = _dir_parts()
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", leaf).strip("-").lower() or "root"
    return f"{_MAC_LABEL_PREFIX}.{safe}.{digest}"


def _mac_plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{_mac_label()}.plist")


def _command() -> tuple[str, list[str], str]:
    """(実行ファイル, 引数list, 作業ディレクトリ) を返す。"""
    base = app_base_dir()
    if is_frozen():
        return sys.executable, ["--post-fixed-comments"], base
    return sys.executable, ["-m", "web_app.app", "--post-fixed-comments"], base


def _slot_hours() -> list[int]:
    """全チャンネルの予約スロット時刻（時）。取得失敗時は既定スロット。"""
    try:
        from core.channel_profile import list_profiles
        from core.channel_schedule import get_schedule
        hours: set[int] = set()
        for profile in list_profiles():
            schedule = get_schedule(profile.profile_id)
            hours.update(schedule.shorts_slot_hours)
            hours.update(schedule.long_slot_hours)
        if hours:
            return sorted(hours)
    except Exception:
        _logger.warning("スロット時刻の取得に失敗。既定スロットでタスク登録します", exc_info=True)
    from core.upload_scheduler import SLOTS, LONG_SLOTS_WEEKDAY, LONG_SLOTS_WEEKEND
    return sorted(set(SLOTS + LONG_SLOTS_WEEKDAY + LONG_SLOTS_WEEKEND))


def slot_times() -> list[str]:
    """投稿実行時刻のリスト（"HH:MM"）。スロット時刻＋バッファ分。"""
    return [f"{h:02d}:{_BUFFER_MINUTE:02d}" for h in _slot_hours()]


# ── 公開API ─────────────────────────────────────────────────────────────────

def status() -> dict:
    """登録状態を返す（OS非対応や未登録でも例外を投げない）。"""
    system = platform.system()
    info = {
        "supported": system in ("Windows", "Darwin"),
        "os": system,
        "registered": False,
        "task_name": task_name() if system == "Windows" else _mac_label(),
        "target_dir": app_base_dir(),
        "times": slot_times(),
    }
    if not info["supported"]:
        return info
    try:
        if system == "Windows":
            info["registered"] = _windows_exists()
        else:
            info["registered"] = os.path.isfile(_mac_plist_path())
    except Exception:
        _logger.warning("タスク状態の取得に失敗", exc_info=True)
    return info


def register() -> dict:
    """予約スロット時刻に定期実行するタスクを登録する。"""
    system = platform.system()
    times = slot_times()
    if system == "Windows":
        _register_windows(times)
    elif system == "Darwin":
        _register_mac(times)
    else:
        raise RuntimeError(f"このOSは未対応です（Windows / macOS のみ）: {system}")
    _logger.info("固定コメント投稿タスクを登録: %s times=%s dir=%s", status()["task_name"], times, app_base_dir())
    return status()


def unregister() -> dict:
    """登録済みタスクを削除する（未登録でもエラーにしない）。"""
    system = platform.system()
    if system == "Windows":
        _unregister_windows()
    elif system == "Darwin":
        _unregister_mac()
    else:
        raise RuntimeError(f"このOSは未対応です（Windows / macOS のみ）: {system}")
    _logger.info("固定コメント投稿タスクを削除: %s", status()["task_name"])
    return status()


# ── Windows（タスクスケジューラ） ─────────────────────────────────────────────

def _run_powershell(script: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"PowerShell 実行に失敗しました: {(proc.stderr or proc.stdout or '').strip()}")
    return proc


def _windows_exists() -> bool:
    proc = subprocess.run(
        ["schtasks", "/query", "/tn", task_name()],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return proc.returncode == 0


def _register_windows(times: list[str]) -> None:
    exe, args, workdir = _command()
    arg_str = " ".join(args)
    name = task_name()
    desc = f"Native Video Factory 固定コメント自動投稿 ({app_base_dir()})"
    triggers = ", ".join(f'(New-ScheduledTaskTrigger -Daily -At "{t}")' for t in times)
    script = (
        f'$ErrorActionPreference="Stop";'
        f'$a = New-ScheduledTaskAction -Execute "{exe}" -Argument "{arg_str}" -WorkingDirectory "{workdir}";'
        f'$t = @({triggers});'
        f'$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries;'
        f'Register-ScheduledTask -TaskName "{name}" -Action $a -Trigger $t -Settings $s -Description "{desc}" -Force | Out-Null'
    )
    _run_powershell(script)


def _unregister_windows() -> None:
    proc = subprocess.run(
        ["schtasks", "/delete", "/tn", task_name(), "/f"],
        capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    # 未登録（存在しない）はエラー扱いにしない
    if proc.returncode != 0 and "ERROR: The system cannot find" not in (proc.stderr or "") \
            and "見つかりません" not in (proc.stderr or ""):
        # 既に無い場合のメッセージは握りつぶし、それ以外のみ記録
        if _windows_exists():
            raise RuntimeError(f"タスク削除に失敗しました: {(proc.stderr or proc.stdout or '').strip()}")


# ── macOS（launchd LaunchAgent） ─────────────────────────────────────────────

def _register_mac(times: list[str]) -> None:
    import plistlib
    exe, args, workdir = _command()
    label = _mac_label()
    path = _mac_plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    intervals = [{"Hour": int(t[:2]), "Minute": int(t[3:5])} for t in times]
    plist = {
        "Label": label,
        "ProgramArguments": [exe, *args],
        "StartCalendarInterval": intervals,
        "WorkingDirectory": workdir,
        "RunAtLoad": False,
        "ProcessType": "Background",
    }
    with open(path, "wb") as f:
        plistlib.dump(plist, f)
    # 既存をunloadしてから登録（エラーは無視）
    subprocess.run(["launchctl", "unload", path], capture_output=True, text=True)
    proc = subprocess.run(["launchctl", "load", path], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"launchctl load に失敗しました: {(proc.stderr or proc.stdout or '').strip()}")


def _unregister_mac() -> None:
    path = _mac_plist_path()
    if os.path.isfile(path):
        subprocess.run(["launchctl", "unload", path], capture_output=True, text=True)
        os.remove(path)
