"""テストが利用者の実データへ触れないことを固定する。"""
import os

from conftest import TEST_DATA_ROOT


def test_persistent_paths_point_to_test_data_root():
    """永続データの保存先がリポジトリ内ではなくテスト用一時フォルダを向いていること。"""
    import core.channel_profile as cp
    import core.secret_store as secret_store
    import core.settings_store as settings_store
    from config import config as cfg

    for path in (cp._DB_PATH, secret_store._DB_PATH, settings_store._DB_PATH, cfg.DEBUG_LOG_DIR):
        assert os.path.abspath(path).startswith(TEST_DATA_ROOT), path
