"""pytest 共通設定。"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_active_profile: active profile を用意せず未設定状態の挙動を検証する",
    )
