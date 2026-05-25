import os
import shutil

from config import (
    OUTPUT_ANALYTICS_DIR,
    OUTPUT_DATA_DIR,
    OUTPUT_DIR as CONFIG_OUTPUT_DIR,
    OUTPUT_LEGACY_DIR,
    UPLOAD_RECORDS_FILE as CONFIG_UPLOAD_RECORDS_FILE,
    UPLOADED_TITLES_FILE as CONFIG_UPLOADED_TITLES_FILE,
)


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))


def _abs_path(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(ROOT_DIR, path)


OUTPUT_DIR = _abs_path(CONFIG_OUTPUT_DIR)
DATA_DIR = _abs_path(OUTPUT_DATA_DIR)
ANALYTICS_DIR = _abs_path(OUTPUT_ANALYTICS_DIR)
LEGACY_DIR = _abs_path(OUTPUT_LEGACY_DIR)

UPLOAD_RECORDS_FILE = _abs_path(CONFIG_UPLOAD_RECORDS_FILE)
UPLOADED_TITLES_FILE = _abs_path(CONFIG_UPLOADED_TITLES_FILE)


def ensure_output_dirs() -> None:
    for path in (
        OUTPUT_DIR,
        DATA_DIR,
        ANALYTICS_DIR,
        LEGACY_DIR,
        os.path.dirname(UPLOAD_RECORDS_FILE),
        os.path.dirname(UPLOADED_TITLES_FILE),
    ):
        os.makedirs(path, exist_ok=True)


def migrate_root_file(filename: str, destination_dir: str, *, overwrite: bool = False) -> str:
    """旧出力ルートのファイルを整理済みディレクトリへ移動する（必要な場合のみ）。"""
    ensure_output_dirs()
    old_path = os.path.join(OUTPUT_DIR, filename)
    new_path = os.path.join(destination_dir, filename)
    if os.path.exists(old_path) and (overwrite or not os.path.exists(new_path)):
        shutil.move(old_path, new_path)
    return new_path


def analytics_paths(pattern_suffix: str) -> list[str]:
    paths: list[str] = []
    for directory in (ANALYTICS_DIR, OUTPUT_DIR):
        try:
            paths.extend(
                os.path.join(directory, name)
                for name in os.listdir(directory)
                if name.startswith("analytics_score_") and name.endswith(pattern_suffix)
            )
        except OSError:
            continue
    return paths
