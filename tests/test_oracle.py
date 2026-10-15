"""別プロセスでの旧版オラクル再現を確認する。"""
from pathlib import Path
import subprocess
import sys
import pytest


def test_legacy_oracle_contract():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "tools" / "oracle.py")], cwd=root,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_oracle_rejects_unsupported_contract_and_duplicate_id():
    from tools.oracle import evaluate
    with pytest.raises(ValueError, match="契約版"):
        evaluate({"contract_version": 2, "cases": []})
    with pytest.raises(ValueError, match="重複"):
        evaluate({"contract_version": 1, "cases": [{"id": "same"}, {"id": "same"}]})


def test_network_guard_prevents_unmocked_connections():
    import socket
    with socket.socket() as connection, pytest.raises(RuntimeError, match="実ネットワーク"):
        connection.connect(("127.0.0.1", 9))


def test_socketpair_and_anyio_client_work_under_network_guard():
    import socket
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    first, second = socket.socketpair()
    with first, second:
        first.sendall(b"test")
        assert second.recv(4) == b"test"
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
