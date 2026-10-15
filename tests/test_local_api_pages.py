"""実アプリのテンプレートとHTTP保護の接続を確認する。"""
from fastapi.testclient import TestClient


def test_setup_page_loads_shared_fetch_and_token():
    from web_app.app import app
    with TestClient(app, base_url="http://127.0.0.1:58123") as client:
        response = client.get("/setup")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert f'content="{app.state.local_api_token}"' in response.text
        assert '/static/api.js?' in response.text
        assert client.get("/static/api.js").status_code == 200
        # 存在しないルートに届くことと、無保護要求が届かないことを区別する。
        assert client.post("/api/local-protection-test").status_code == 403
        headers = {"Origin": "http://127.0.0.1:58123", "X-PicoCast-Token": app.state.local_api_token}
        assert client.post("/api/local-protection-test", headers=headers).status_code == 404
