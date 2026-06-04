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


def test_every_catalog_entry_has_remediation():
    """製品方針: すべてのエラーに対処手順を必ず付ける。"""
    from core.error_codes import ERROR_CATALOG
    missing = [code for code, d in ERROR_CATALOG.items() if not d.remediation.strip()]
    assert not missing, f"remediation 未設定のエラーコード: {missing}"


def test_catalog_key_matches_error_code():
    """カタログキーと ErrorDef.code は安定IDとして必ず一致させる。"""
    from core.error_codes import ERROR_CATALOG
    mismatched = [key for key, definition in ERROR_CATALOG.items() if key != definition.code]
    assert not mismatched, f"key と code が不一致のエラーコード: {mismatched}"


def test_format_error_with_fix_appends_remediation():
    from core.error_codes import format_error
    text = format_error("E-VOICEVOX-DOWN", with_fix=True)
    assert text.startswith("[E-VOICEVOX-DOWN] ")
    assert "対処:" in text
    # with_fix=False では対処を付けない（既存の表示互換）
    assert "対処:" not in format_error("E-VOICEVOX-DOWN")
