"""副作用のないルートでローカルAPI保護の拒否と許可を検証する。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse

from web_app.local_api_security import LocalApiSecurityMiddleware


@pytest.fixture
def guarded():
    app = FastAPI()
    calls = []

    @app.api_route("/operation", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def operation():
        calls.append(True)
        return {"ok": True}

    @app.get("/page")
    def page():
        return HTMLResponse("画面")

    app.add_middleware(LocalApiSecurityMiddleware, token="test-token")
    return app, calls


@pytest.mark.parametrize("host", ["evil.test:58080", "127.0.0.1.evil.test:58080", "localhost:58081", "localhost", "127.0.0.1:58080@evil.test"])
def test_bad_host_rejected_before_route(guarded, host):
    app, calls = guarded
    with TestClient(app, base_url="http://127.0.0.1:58080") as client:
        response = client.get("/operation", headers={"Host": host})
    assert response.status_code == 400
    assert "E-WEB-REQUEST" in response.json()["detail"]
    assert not calls


@pytest.mark.parametrize("source", [None, "null", "https://127.0.0.1:58080", "http://evil.test", "http://localhost:58080", "http://127.0.0.1:58081", "http://127.0.0.1:58080/path", "http://[broken"])
def test_bad_origin_rejected(guarded, source):
    app, calls = guarded
    headers = {"X-PicoCast-Token": "test-token"}
    if source is not None:
        headers["Origin"] = source
    with TestClient(app, base_url="http://127.0.0.1:58080") as client:
        assert client.post("/operation", headers=headers).status_code == 403
    assert not calls


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("token", [None, "old-token", "é"])
def test_missing_or_wrong_token_rejected(guarded, method, token):
    app, calls = guarded
    headers = [(b"origin", b"http://127.0.0.1:58080")]
    if token is not None:
        headers.append((b"x-picocast-token", token.encode("latin-1")))
    with TestClient(app, base_url="http://127.0.0.1:58080") as client:
        assert client.request(method, "/operation", headers=headers).status_code == 403
    assert not calls


@pytest.mark.parametrize("origin", ["http://127.0.0.1:58080", "http://localhost:58081", "http://127.0.0.1"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_same_origin_and_token_accepted(guarded, origin, method):
    app, calls = guarded
    with TestClient(app, base_url=origin) as client:
        response = client.request(method, "/operation", headers={"Origin": origin, "X-PicoCast-Token": "test-token"})
    assert response.status_code == 200
    assert calls == [True]


def test_referer_and_duplicate_headers(guarded):
    app, calls = guarded
    origin = "http://127.0.0.1:58080"
    headers = {"Referer": origin + "/settings", "X-PicoCast-Token": "test-token"}
    with TestClient(app, base_url=origin) as client:
        assert client.post("/operation", headers=headers).status_code == 200
        assert client.post("/operation", headers={**headers, "Origin": "null"}).status_code == 403
        for name, value in [("Host", "127.0.0.1:58080"), ("Origin", origin), ("X-PicoCast-Token", "test-token")]:
            duplicates = [("Origin", origin), ("X-PicoCast-Token", "test-token")]
            duplicates = [(key, val) for key, val in duplicates if key.lower() != name.lower()]
            duplicates.extend([(name, value), (name, value)])
            assert client.post("/operation", headers=duplicates).status_code in (400, 403)
        assert client.get("/page").headers["cache-control"] == "no-store"
        assert client.get("/operation").status_code == 200
    assert len(calls) == 2
