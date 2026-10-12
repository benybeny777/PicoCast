"""pytest 共通設定。

テストが利用者の実データ（`data/settings.db`・`output/`・マスターキー・デバッグログ）を
読み書きしないよう、永続データの基準 `app_base_dir()` をテスト専用の一時フォルダへ向ける。
各モジュールは import 時に `app_base_dir()` から保存先を決めるため、どの本体モジュールより先に
差し替える必要がある（このファイルは pytest がテストモジュールより先に読み込む）。
"""
import os
import shutil
import sys
import tempfile

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

TEST_DATA_ROOT = tempfile.mkdtemp(prefix="yukkurijidou_test_data_")

import core.runtime_env as _runtime_env  # noqa: E402  差し替えは本体モジュールの import より前に行う

_runtime_env.app_base_dir = lambda: TEST_DATA_ROOT

# テストで使う既定の active profile。ジャンル seed がリポジトリに実在するものを使う。
TEST_PROFILE_ID = "zunkami"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "no_active_profile: active profile を用意せず未設定状態の挙動を検証する",
    )


def pytest_unconfigure(config):
    shutil.rmtree(TEST_DATA_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_active_profile(request):
    """テスト用 settings.db に active profile を1件用意する。

    `@pytest.mark.no_active_profile` のテストでは全 profile を非アクティブにする。
    `_DB_PATH` を独自の一時DBへ差し替えるテストには影響しない。
    `save_profile()` はジャンル seed をリポジトリ内へ複製するため使わず、行を直接書く。
    """
    import core.channel_profile as cp

    active = 0 if request.node.get_closest_marker("no_active_profile") else 1
    conn = cp._open_db()
    try:
        conn.execute("UPDATE channel_profiles SET is_active=0")
        conn.execute(
            """
            INSERT INTO channel_profiles
                (profile_id, channel_name, channel_handle, genre_profile, output_root,
                 is_active, created_at, updated_at)
            VALUES (?, 'テストチャンネル', ?, ?, ?, ?, '', '')
            ON CONFLICT(profile_id) DO UPDATE SET is_active = excluded.is_active
            """,
            (TEST_PROFILE_ID, f"@{TEST_PROFILE_ID}", TEST_PROFILE_ID, TEST_PROFILE_ID, active),
        )
        conn.commit()
    finally:
        conn.close()
    yield


@pytest.fixture
def dummy_google_api_key(monkeypatch):
    """Nano Banana の初期化に必要な Google API キーを、実キーを使わずダミーで用意する。

    クライアント生成だけを検証するテスト用。実通信はしない。
    """
    import core.secret_store as secret_store

    monkeypatch.setattr(secret_store, "has_secret", lambda secret_type, profile_id=None: secret_type == "google_api_key")
    monkeypatch.setattr(secret_store, "load_secret", lambda secret_type, profile_id=None: "dummy-google-api-key")
