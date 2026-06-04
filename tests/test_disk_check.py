"""ディスク空き容量チェック（E-DISK）のテスト。"""
from __future__ import annotations

import os
import sys
from collections import namedtuple

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_Usage = namedtuple("_Usage", "total used free")
_GB = 1024 ** 3


def test_assert_enough_disk_raises_when_low(monkeypatch, tmp_path):
    import core.disk_check as dc
    from core.error_codes import AppError

    monkeypatch.setattr(dc.config, "DISK_MIN_FREE_GB", 2.0)
    monkeypatch.setattr(dc, "_default_output_path", lambda: str(tmp_path))
    monkeypatch.setattr(dc.shutil, "disk_usage", lambda p: _Usage(100 * _GB, 99 * _GB, 1 * _GB))

    with pytest.raises(AppError) as exc:
        dc.assert_enough_disk()
    assert exc.value.code == "E-DISK"


def test_assert_enough_disk_ok_when_plenty(monkeypatch, tmp_path):
    import core.disk_check as dc

    monkeypatch.setattr(dc.config, "DISK_MIN_FREE_GB", 2.0)
    monkeypatch.setattr(dc, "_default_output_path", lambda: str(tmp_path))
    monkeypatch.setattr(dc.shutil, "disk_usage", lambda p: _Usage(100 * _GB, 50 * _GB, 50 * _GB))

    dc.assert_enough_disk()  # 例外が出なければOK


def test_assert_enough_disk_disabled_when_threshold_zero(monkeypatch, tmp_path):
    import core.disk_check as dc

    monkeypatch.setattr(dc.config, "DISK_MIN_FREE_GB", 0.0)

    def _fail(p):
        raise AssertionError("閾値0なのにディスクを測定した")

    monkeypatch.setattr(dc.shutil, "disk_usage", _fail)
    dc.assert_enough_disk()


def test_nearest_existing_walks_up(monkeypatch, tmp_path):
    import core.disk_check as dc
    missing = os.path.join(str(tmp_path), "a", "b", "c")
    assert dc._nearest_existing(missing) == str(tmp_path)
