"""旧版テストとオラクルで共有する、実設定に触れない一時環境。"""
from __future__ import annotations

import atexit
import ast
from contextlib import ExitStack
import gc
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
from unittest.mock import patch


def isolate():
    """本番モジュールを読む前に呼び、一時データ領域を返す。"""
    from core import runtime_env
    import dotenv

    root = Path(__file__).resolve().parents[1]
    if "config.config" in __import__("sys").modules:
        raise RuntimeError("隔離はconfigの読み込み前に実行してください")
    base = root / "temp" / "legacy-tests"
    base.mkdir(parents=True, exist_ok=True)
    directory = tempfile.TemporaryDirectory(prefix="session-", dir=base)
    target = Path(directory.name)
    def cleanup():
        # 旧版SQLite接続の循環参照を解放してからWindowsの一時DBを削除する。
        gc.collect()
        directory.cleanup()

    atexit.register(cleanup)
    tree = ast.parse((root / "config" / "config.py").read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.isupper()}
    for name in names | {"GOOGLE_API_KEY", "OPENAI_API_KEY", "HF_TOKEN", "NVF_MASTER_KEY"}:
        os.environ.pop(name, None)
    os.environ["NVF_DISABLE_JOB_RUNNER"] = "1"
    runtime_env.app_base_dir = lambda: str(target)
    original_load = dotenv.load_dotenv

    def load_test_dotenv(dotenv_path=None, *args, **kwargs):
        return original_load(dotenv_path or target / ".env", *args, **kwargs)

    dotenv.load_dotenv = load_test_dotenv
    # プロファイル保存がジャンルseedを複製しても、ソース資産を書き換えない。
    from core import channel_profile
    resources = target / "resources"
    for relative in ["config/prompt_profiles", "config/SEED"]:
        source = root / relative
        if source.exists():
            shutil.copytree(source, resources / relative)
    channel_profile._RES_ROOT = str(resources)
    return directory, target


def deny_network():
    """テストの意図しない実API通信を接続前に拒否する。"""
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair
    local = threading.local()

    def rejected(connection, *args, **kwargs):
        if getattr(local, "socketpair_depth", 0):
            return original_connect(connection, *args, **kwargs)
        raise RuntimeError("隔離テストから実ネットワークへ接続できません。通信をモックしてください")

    def internal_socketpair(*args, **kwargs):
        # Windows標準実装のself-pipe生成中だけ、同一スレッドの内部接続を許可する。
        local.socketpair_depth = getattr(local, "socketpair_depth", 0) + 1
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            local.socketpair_depth -= 1

    guard = ExitStack()
    guard.enter_context(patch("socket.socket.connect", rejected))
    guard.enter_context(patch("socket.socketpair", internal_socketpair))
    atexit.register(guard.close)
    return guard
