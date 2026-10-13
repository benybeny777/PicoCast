"""署名付きライセンスキーの検証とエディション判定のテスト。"""
from __future__ import annotations

import pytest

from core.error_codes import AppError
from core.license_key import LicensePayload, encode_license_key, generate_key_pair, verify_license_key


@pytest.fixture(scope="module")
def keys():
    return generate_key_pair()


def _payload(edition="pro", **kw):
    base = dict(license_id="lid0001", edition=edition, buyer="山田太郎", issued_at="2026-10-14",
                updates_until="2027-10-14", packs=("urban_legend",))
    base.update(kw)
    return LicensePayload(**base)


def test_valid_key_roundtrip(keys):
    private_pem, public_pem = keys
    key = encode_license_key(_payload(), private_pem)
    payload = verify_license_key(key, public_pem)
    assert payload.edition == "pro"
    assert payload.buyer == "山田太郎"
    assert payload.packs == ("urban_legend",)


def test_key_with_line_breaks_is_accepted(keys):
    private_pem, public_pem = keys
    key = encode_license_key(_payload(), private_pem)
    wrapped = "\n".join(key[i:i + 40] for i in range(0, len(key), 40))
    assert verify_license_key(wrapped, public_pem).license_id == "lid0001"


def test_tampered_payload_is_rejected(keys):
    private_pem, public_pem = keys
    standard = encode_license_key(_payload("standard"), private_pem)
    pro = encode_license_key(_payload("pro"), private_pem)
    # standard の署名に pro の中身を差し替える
    forged = ".".join([standard.split(".")[0], pro.split(".")[1], standard.split(".")[2]])
    with pytest.raises(AppError) as exc:
        verify_license_key(forged, public_pem)
    assert exc.value.code == "E-LICENSE-INVALID"


def test_key_signed_by_other_key_is_rejected(keys):
    _, public_pem = keys
    other_private, _ = generate_key_pair()
    with pytest.raises(AppError):
        verify_license_key(encode_license_key(_payload(), other_private), public_pem)


def test_unknown_edition_cannot_be_issued(keys):
    private_pem, _ = keys
    with pytest.raises(AppError):
        encode_license_key(_payload("studio"), private_pem)


def test_garbage_key_is_rejected(keys):
    _, public_pem = keys
    for bad in ("", "abc", "NVF1.xxx", "NVF1.@@@.@@@"):
        with pytest.raises(AppError):
            verify_license_key(bad, public_pem)


def test_license_manager_resolves_edition_from_key(keys, monkeypatch):
    import core.license_key as lk
    import core.license_manager as lm
    private_pem, public_pem = keys
    real_verify = lk.verify_license_key
    monkeypatch.setattr(lm, "verify_license_key", lambda key: real_verify(key, public_pem))
    key = encode_license_key(_payload("standard"), private_pem)

    monkeypatch.setattr(lm, "get_all", lambda: {"LICENSE_KEY": key})
    info = lm.get_license_info()
    assert info["edition"] == "trial"
    assert info["status"] == "not_activated"
    assert info["limits"]["max_profiles"] == 1
    assert info["limits"]["watermark"] is True

    # 旧方式の edition 直書きは無視される
    monkeypatch.setattr(lm, "get_all", lambda: {"LICENSE_EDITION": "pro"})
    assert lm.get_license_info()["edition"] == "trial"

    # 失効フラグがあれば trial に戻る
    monkeypatch.setattr(lm, "get_all", lambda: {"LICENSE_KEY": key, "LICENSE_REVOKED": "1"})
    info = lm.get_license_info()
    assert info["edition"] == "trial"
    assert info["status"] == "revoked"

    # 壊れたキーは trial + 理由表示
    monkeypatch.setattr(lm, "get_all", lambda: {"LICENSE_KEY": key[:-5] + "AAAAA"})
    info = lm.get_license_info()
    assert info["edition"] == "trial"
    assert info["status"] == "invalid"
    assert info["reason"]


def test_save_license_rejects_invalid_key(monkeypatch):
    import core.license_manager as lm
    saved = {}
    monkeypatch.setattr(lm, "set_many", saved.update)
    with pytest.raises(AppError):
        lm.save_license("NVF1.invalid.key")
    assert saved == {}
