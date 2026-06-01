"""
エラーコードの中央カタログ（core/error_codes.py）のテスト。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_catalog_lookup_and_format():
    from core.error_codes import get_error, format_error

    d = get_error("E-IMG-BUSY")
    assert d.code == "E-IMG-BUSY"
    assert d.category == "api_busy"
    assert d.retry_recommended is True
    assert format_error("E-IMG-BUSY").startswith("[E-IMG-BUSY] ")
    assert "背景4/8" in format_error("E-IMG-BUSY", "背景4/8")


def test_unknown_code_falls_back_to_e_unknown():
    from core.error_codes import get_error
    assert get_error("存在しないコード").code == "E-UNKNOWN"


def test_image_error_code_mapping():
    from core.error_codes import image_error_code
    assert image_error_code("api_busy") == "E-IMG-BUSY"
    assert image_error_code("auth") == "E-IMG-AUTH"
    assert image_error_code("quota") == "E-IMG-QUOTA"
    assert image_error_code("generic") == "E-IMG-FAIL"
    assert image_error_code("なにか") == "E-IMG-FAIL"


def test_app_error_carries_code_and_message():
    from core.error_codes import AppError
    e = AppError("E-IMG-BUSY", detail="503 UNAVAILABLE")
    assert e.code == "E-IMG-BUSY"
    assert e.category == "api_busy"
    assert e.retry_recommended is True
    assert "[E-IMG-BUSY]" in str(e)
    assert "503 UNAVAILABLE" in str(e)


def test_image_generation_error_exposes_catalog_code():
    from core.image_generator import ImageGenerationError
    assert ImageGenerationError("x", category="api_busy").code == "E-IMG-BUSY"
    assert ImageGenerationError("x", category="auth").code == "E-IMG-AUTH"
    assert ImageGenerationError("x", category="generic").code == "E-IMG-FAIL"
