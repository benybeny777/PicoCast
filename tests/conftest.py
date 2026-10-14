"""pytest 共通設定。"""


def local_api_client(app, **kwargs):
    """通常の画面と同じ宛先・Origin・トークンを持つテストクライアント。"""
    from fastapi.testclient import TestClient
    origin = "http://127.0.0.1"
    headers = {"Origin": origin}
    if hasattr(app.state, "local_api_token"):
        headers["X-PicoCast-Token"] = app.state.local_api_token
    headers.update(kwargs.pop("headers", {}))
    return TestClient(app, base_url=origin, headers=headers, **kwargs)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_active_profile: active profile を用意せず未設定状態の挙動を検証する",
    )
