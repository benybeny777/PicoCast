"""
core/output_paths.py と core/metadata_db.py のプロファイル別パステスト。

- output_root が profile 別に切り替わる
- metadata.db path が profile 別に切り替わる
- get_output_videos_dir / get_data_dir / get_uploaded_dir が profile に応じたパスを返す
- 別 profile のパスへのアクセスは security.py が拒否する
外部API実通信なし。
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture()
def profile_env(tmp_path, monkeypatch):
    """channel_profile DB を tmp_path に分離し、テスト用 profile を作成する。"""
    import core.channel_profile as cp

    monkeypatch.setattr(cp, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setattr(cp, "_ROOT", str(tmp_path))

    # food_trivia profile
    food = cp.ChannelProfile(
        profile_id="food_trivia",
        channel_name="食べ物チャンネル",
        channel_handle="@food_trivia",
        genre_profile="food_trivia",
        output_root="food_trivia",
    )
    urban = cp.ChannelProfile(
        profile_id="urban_legend",
        channel_name="都市伝説チャンネル",
        channel_handle="@urban_legend",
        genre_profile="urban_legend",
        output_root="urban_legend",
    )
    cp.save_profile(food)
    cp.save_profile(urban)

    yield cp, tmp_path, food, urban


# ── output_root が profile 別に切り替わる ──────────────────────────────────────

def test_output_root_changes_with_active_profile(profile_env):
    cp, tmp_path, food, urban = profile_env
    from core.output_paths import get_output_root

    cp.activate_profile("food_trivia")
    food_root = get_output_root()
    assert "food_trivia" in food_root
    assert "urban_legend" not in food_root

    cp.activate_profile("urban_legend")
    urban_root = get_output_root()
    assert "urban_legend" in urban_root
    assert "food_trivia" not in urban_root


def test_output_videos_dir_profile_specific(profile_env):
    cp, tmp_path, food, urban = profile_env
    from core.output_paths import get_output_videos_dir

    cp.activate_profile("food_trivia")
    food_dir = get_output_videos_dir()
    assert "food_trivia" in food_dir

    cp.activate_profile("urban_legend")
    urban_dir = get_output_videos_dir()
    assert "urban_legend" in urban_dir

    # 別 profile のパスが混ざらない
    assert food_dir != urban_dir


def test_data_dir_profile_specific(profile_env):
    cp, tmp_path, food, urban = profile_env
    from core.output_paths import get_data_dir

    cp.activate_profile("food_trivia")
    food_data = get_data_dir()

    cp.activate_profile("urban_legend")
    urban_data = get_data_dir()

    assert food_data != urban_data
    assert "food_trivia" in food_data
    assert "urban_legend" in urban_data


def test_uploaded_dir_profile_specific(profile_env):
    cp, tmp_path, food, urban = profile_env
    from core.output_paths import get_uploaded_dir

    cp.activate_profile("food_trivia")
    food_uploaded = get_uploaded_dir()

    cp.activate_profile("urban_legend")
    urban_uploaded = get_uploaded_dir()

    assert food_uploaded != urban_uploaded
    assert "food_trivia" in food_uploaded
    assert "urban_legend" in urban_uploaded


# ── metadata.db が profile 別に切り替わる ─────────────────────────────────────

def test_db_path_profile_specific(profile_env):
    cp, tmp_path, food, urban = profile_env
    from core.output_paths import get_db_path

    cp.activate_profile("food_trivia")
    food_db = get_db_path()

    cp.activate_profile("urban_legend")
    urban_db = get_db_path()

    assert food_db != urban_db
    assert "food_trivia" in food_db
    assert "urban_legend" in urban_db


# ── 出力ベースディレクトリの変更・移設 ───────────────────────────────────────

@pytest.fixture()
def relocate_env(profile_env, tmp_path, monkeypatch):
    """出力ベース移設テスト用。出力ベース・設定DBを tmp_path に分離する。"""
    import core.output_paths as op
    import core.settings_store as ss
    from config import config as cfg

    # 既定ベースは tmp_path/output に向ける（cp._ROOT も tmp_path 済み）
    monkeypatch.setattr(op, "_ROOT", str(tmp_path))
    # 設定保存先を tmp の settings.db に分離（本物の data/settings.db を汚さない）
    monkeypatch.setattr(ss, "_DB_PATH", str(tmp_path / "settings.db"))
    monkeypatch.setenv("OUTPUT_BASE_DIR", "")
    monkeypatch.setattr(cfg, "OUTPUT_BASE_DIR", "", raising=False)

    cp, _tmp, food, urban = profile_env
    cp.activate_profile("food_trivia")
    # 既存データを作成
    src_root = os.path.join(str(tmp_path), "output", "food_trivia")
    os.makedirs(os.path.join(src_root, "videos", "Shorts_a"), exist_ok=True)
    os.makedirs(os.path.join(src_root, "000_data"), exist_ok=True)
    with open(os.path.join(src_root, "000_data", "metadata.db"), "w", encoding="utf-8") as f:
        f.write("dummy")
    return cp, tmp_path, op, cfg


def test_relocate_output_base_moves_data_and_updates_config(relocate_env):
    cp, tmp_path, op, cfg = relocate_env
    new_base = os.path.join(str(tmp_path), "relocated")

    result = op.relocate_output_base(new_base, move=True)

    assert result["moved"] is True
    assert "food_trivia" in result["entries"]
    # 旧ベースからは消え、新ベースへ移動している
    assert not os.path.exists(os.path.join(str(tmp_path), "output", "food_trivia"))
    moved_db = os.path.join(new_base, "food_trivia", "000_data", "metadata.db")
    assert os.path.isfile(moved_db)
    # config と output_base_dir が新ベースに更新されている
    assert cfg.OUTPUT_BASE_DIR == os.path.normpath(new_base)
    assert os.path.normcase(op.output_base_dir()) == os.path.normcase(os.path.normpath(new_base))
    # active profile の出力解決も新ベース配下になる
    assert os.path.normcase(cp.require_active_profile().output_root_abs).startswith(
        os.path.normcase(os.path.normpath(new_base))
    )


def test_relocate_output_base_rejects_nested_path(relocate_env):
    cp, tmp_path, op, cfg = relocate_env
    nested = os.path.join(str(tmp_path), "output", "inside")
    with pytest.raises(ValueError):
        op.relocate_output_base(nested)


def test_relocate_output_base_rejects_existing_conflict(relocate_env):
    cp, tmp_path, op, cfg = relocate_env
    new_base = os.path.join(str(tmp_path), "relocated")
    # 移動先に同名 food_trivia を先に作っておく → 衝突で拒否
    os.makedirs(os.path.join(new_base, "food_trivia"), exist_ok=True)
    with pytest.raises(FileExistsError):
        op.relocate_output_base(new_base, move=True)


def test_change_output_base_refuses_when_jobs_active(relocate_env, monkeypatch):
    cp, tmp_path, op, cfg = relocate_env
    import web_app.services.output_dir_service as svc

    monkeypatch.setattr(svc, "_active_jobs_by_profile", lambda: {"food_trivia": 2})
    with pytest.raises(RuntimeError):
        svc.change_output_base(os.path.join(str(tmp_path), "relocated"), confirmed=True)


def test_change_output_base_requires_confirmation(relocate_env):
    cp, tmp_path, op, cfg = relocate_env
    import web_app.services.output_dir_service as svc

    with pytest.raises(ValueError):
        svc.change_output_base(os.path.join(str(tmp_path), "relocated"), confirmed=False)


# ── security.py が別 profile のパスを拒否する ─────────────────────────────────

def test_safe_output_path_rejects_other_profile(profile_env):
    cp, tmp_path, food, urban = profile_env
    from fastapi import HTTPException
    from web_app.security import safe_output_path

    cp.activate_profile("food_trivia")
    food_root = str(tmp_path / "output" / "food_trivia")
    urban_root = str(tmp_path / "output" / "urban_legend")

    # food_trivia の videos 配下は OK
    food_video_dir = os.path.join(food_root, "videos", "Shorts_test")
    os.makedirs(food_video_dir, exist_ok=True)
    result = safe_output_path(food_video_dir)
    assert result == os.path.realpath(food_video_dir)

    # urban_legend のパスは拒否
    urban_video_dir = os.path.join(urban_root, "videos", "Shorts_urban_test")
    with pytest.raises(HTTPException) as exc_info:
        safe_output_path(urban_video_dir)
    assert exc_info.value.status_code == 403


# ── find_history_dir が videos/ → 000_uploaded/ の順で実体解決する ──────────────

def test_find_history_dir_resolves_videos_and_uploaded(profile_env):
    cp, tmp_path, food, urban = profile_env
    from web_app.security import find_history_dir

    cp.activate_profile("food_trivia")
    food_root = str(tmp_path / "output" / "food_trivia")

    # videos/ 配下のフォルダを解決できる（output_root 直下では解決しない）
    videos_name = "Shorts_in_videos"
    videos_dir = os.path.join(food_root, "videos", videos_name)
    os.makedirs(videos_dir, exist_ok=True)
    assert find_history_dir(videos_name) == os.path.realpath(videos_dir)

    # 000_uploaded/ 配下のフォルダも解決できる
    uploaded_name = "Shorts_in_uploaded"
    uploaded_dir = os.path.join(food_root, "000_uploaded", uploaded_name)
    os.makedirs(uploaded_dir, exist_ok=True)
    assert find_history_dir(uploaded_name) == os.path.realpath(uploaded_dir)

    # 存在しない名前 / 不正名は None
    assert find_history_dir("Shorts_not_exist") is None
    assert find_history_dir("../evil") is None
    assert find_history_dir("a/b") is None
