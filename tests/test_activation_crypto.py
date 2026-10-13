"""端末証明書の署名・厳格な入力検証・ローカル保存保護を確認する。"""
from dataclasses import replace

import pytest

from core.error_codes import AppError
from core.license_key import (
    ActivationPayload, encode_activation, generate_key_pair, verify_activation,
)


@pytest.fixture(scope="module")
def keys():
    return generate_key_pair()


@pytest.fixture
def payload():
    return ActivationPayload(
        license_id="lid0001", edition="pro", buyer="購入者", issued_at="2026-10-14",
        updates_until="2027-10-14", packs=("urban_legend",),
        machine_code="a" * 32, expires_at="2026-11-13T00:00:00Z",
    )


@pytest.mark.parametrize("iat", ["2026-10-14", "2026-10-14T01:02:03+00:00"])
@pytest.mark.parametrize("expiry", ["", "2026-11-13T00:00:00Z", "2026-11-13T09:00:00+09:00"])
def test_activation_roundtrip(keys, payload, iat, expiry):
    expected = replace(payload, issued_at=iat, expires_at=expiry)
    signed = encode_activation(expected, keys[0])
    assert signed.startswith("NVA1.")
    assert verify_activation(signed, keys[1]) == expected


@pytest.mark.parametrize("changes", [
    {"machine_code": "a" * 31}, {"machine_code": "A" * 32},
    {"machine_code": "x" * 32}, {"expires_at": "2026-11-13"},
    {"expires_at": "2026-11-13T00:00:00"}, {"expires_at": "invalid"},
    {"license_id": ""}, {"license_id": "bad\nlid"},
    {"packs": ("../secret",)}, {"packs": ("urban_legend", "urban_legend")},
    {"issued_at": "2026-02-30"}, {"issued_at": "2026-10-14T00:00:00"},
    {"updates_until": "2026-02-30"}, {"edition": "trial"},
])
def test_invalid_fields_rejected_before_issue(keys, payload, changes):
    with pytest.raises(AppError):
        encode_activation(replace(payload, **changes), keys[0])


def test_other_key_and_modified_signature_are_rejected(keys, payload):
    signed = encode_activation(payload, keys[0])
    _, other_public = generate_key_pair()
    for bad, public in ((signed, other_public), (signed + "@", keys[1]),
                        (signed.replace("NVA1", "NVF1", 1), keys[1])):
        with pytest.raises(AppError):
            verify_activation(bad, public)


@pytest.mark.parametrize("changes", [
    {"v": True}, {"v": 2}, {"mid": 123}, {"buyer": None},
    {"packs": "urban_legend"}, {"unexpected": "value"}, {"iat": ""},
])
def test_signed_invalid_schema_is_rejected(keys, payload, changes):
    from core.license_key import _encode_signed
    signed = _encode_signed({**payload.to_dict(), **changes}, "NVA1", keys[0])
    with pytest.raises(AppError):
        verify_activation(signed, keys[1])


def test_default_public_key_pin_rejects_replacement(keys, payload, monkeypatch):
    import core.license_public_key as public_module
    monkeypatch.setattr(public_module, "LICENSE_PUBLIC_KEY_PEM", keys[1])
    signed = encode_activation(payload, keys[0])
    with pytest.raises(AppError, match="整合性"):
        verify_activation(signed)
    assert verify_activation(signed, keys[1]) == payload


def test_local_data_windows_uses_dpapi_and_propagates_failure(monkeypatch, caplog):
    import core.secret_store as store
    monkeypatch.setattr(store.sys, "platform", "win32")
    monkeypatch.setattr(store, "_dpapi_protect", lambda value: b"protected:" + value)
    monkeypatch.setattr(store, "_dpapi_unprotect", lambda value: value.removeprefix(b"protected:"))
    assert store.unprotect_local_data(store.protect_local_data(b"certificate")) == b"certificate"

    def fail(_value):
        raise store.MasterKeyError("DPAPI failure")

    monkeypatch.setattr(store, "_dpapi_unprotect", fail)
    with pytest.raises(store.MasterKeyError):
        store.unprotect_local_data(b"encrypted")
    assert "復号に失敗" in caplog.text


def test_local_data_mac_retains_signed_certificate(monkeypatch):
    import core.secret_store as store
    monkeypatch.setattr(store.sys, "platform", "darwin")
    assert store.unprotect_local_data(store.protect_local_data(b"signed")) == b"signed"
