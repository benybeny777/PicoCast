"""署名付きライセンスキーの生成・検証。

キー形式: ``NVF1.<payload>.<signature>``
- payload: ライセンス内容の JSON（UTF-8）を URL-safe base64 にしたもの
- signature: payload 文字列（ASCII）への RSA-SHA256（PKCS#1 v1.5）署名を URL-safe base64 にしたもの

アプリには公開鍵だけを埋め込み、ネット接続なしで検証する。
発行は Google Apps Script（tools/license/gas）または tools/license/license_tool.py が秘密鍵で行う。
Apps Script の ``Utilities.computeRsaSha256Signature`` と同じ方式に揃えるため Ed25519 ではなく RSA を使う。
"""
from __future__ import annotations

import base64
import binascii
import json
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core.error_codes import AppError

KEY_PREFIX = "NVF1"
ACTIVATION_PREFIX = "NVA1"
_PUBLIC_KEY_SHA256 = "7698440a879856df52648fce95458ccd338dd85ab09dad85225756da0ca37ac5"
_logger = logging.getLogger(__name__)
# キーで発行できる edition（trial はキー不要のため含めない）
ISSUABLE_EDITIONS = ("standard", "pro")


@dataclass(frozen=True)
class LicensePayload:
    license_id: str
    edition: str
    buyer: str
    issued_at: str
    updates_until: str
    packs: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "v": 1,
            "lid": self.license_id,
            "ed": self.edition,
            "buyer": self.buyer,
            "iat": self.issued_at,
            "upd": self.updates_until,
            "packs": list(self.packs),
        }


@dataclass(frozen=True)
class ActivationPayload(LicensePayload):
    machine_code: str
    expires_at: str

    def to_dict(self) -> dict:
        return {**super().to_dict(), "mid": self.machine_code, "exp": self.expires_at}


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64decode(text: str) -> bytes:
    if not text or re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", text) is None:
        raise ValueError("base64 の形式が不正です")
    padded = text + "=" * (-len(text) % 4)
    return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)


def _invalid(detail: str) -> AppError:
    _logger.warning("[License] E-LICENSE-INVALID: %s", detail)
    return AppError("E-LICENSE-INVALID", detail)


def _validate_date(value: str, field: str, *, allow_empty: bool) -> str:
    if not value and allow_empty:
        return ""
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} の日付形式が不正です") from exc
    return value


def _payload_from_dict(data: dict) -> LicensePayload:
    if data.get("v") != 1:
        raise _invalid("未対応のキー形式です")
    edition = str(data.get("ed") or "")
    if edition not in ISSUABLE_EDITIONS:
        raise _invalid("未知の edition です")
    license_id = str(data.get("lid") or "").strip()
    if not license_id:
        raise _invalid("license_id がありません")
    packs = data.get("packs") or []
    if not isinstance(packs, list) or not all(isinstance(p, str) for p in packs):
        raise _invalid("packs の形式が不正です")
    return LicensePayload(
        license_id=license_id,
        edition=edition,
        buyer=str(data.get("buyer") or ""),
        issued_at=_validate_date(str(data.get("iat") or ""), "iat", allow_empty=False),
        updates_until=_validate_date(str(data.get("upd") or ""), "upd", allow_empty=True),
        packs=tuple(packs),
    )


def _load_public_key(public_key_pem: str) -> rsa.RSAPublicKey:
    key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    if not isinstance(key, rsa.RSAPublicKey):
        raise RuntimeError("ライセンス公開鍵が RSA ではありません")
    return key


def _public_key(public_key_pem: str | None) -> rsa.RSAPublicKey:
    if public_key_pem is None:
        from core.license_public_key import LICENSE_PUBLIC_KEY_PEM
        public_key_pem = LICENSE_PUBLIC_KEY_PEM
        try:
            actual_pin = hashlib.sha256(public_key_pem.encode("ascii")).hexdigest()
        except (UnicodeError, AttributeError):
            raise _invalid("ライセンス公開鍵の形式が不正です") from None
        if actual_pin != _PUBLIC_KEY_SHA256:
            raise _invalid("ライセンス公開鍵の整合性を確認できません")
    try:
        return _load_public_key(public_key_pem)
    except (ValueError, TypeError, UnicodeError, RuntimeError, UnsupportedAlgorithm):
        raise _invalid("ライセンス公開鍵を読み取れません") from None


def _verify_signed(text: str, prefix: str, public_key_pem: str | None) -> dict:
    if not isinstance(text, str):
        raise _invalid("キーの形式が不正です")
    text = "".join(text.split())  # メール本文からの貼り付けで混入する改行・空白を除去
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != prefix:
        raise _invalid("キーの形式が正しくありません。届いたキーを改行も含めてそのまま貼り付けてください")
    payload_b64, sig_b64 = parts[1], parts[2]
    try:
        signature = _b64decode(sig_b64)
    except (binascii.Error, ValueError):
        raise _invalid("署名部分を読み取れません") from None
    public_key = _public_key(public_key_pem)
    try:
        public_key.verify(
            signature, payload_b64.encode("ascii"), padding.PKCS1v15(), hashes.SHA256(),
        )
    except (InvalidSignature, UnicodeEncodeError):
        raise _invalid("署名が一致しません（キーの誤り・改変の可能性）") from None
    try:
        data = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except (binascii.Error, ValueError):
        raise _invalid("キーの内容を読み取れません") from None
    if not isinstance(data, dict):
        raise _invalid("キーの内容が不正です")
    return data


def verify_license_key(license_key: str, public_key_pem: str | None = None) -> LicensePayload:
    """キーの署名と内容を検証して中身を返す。不正なら AppError。"""
    return _payload_from_dict(_verify_signed(license_key, KEY_PREFIX, public_key_pem))


def _activation_from_dict(data: dict) -> ActivationPayload:
    required = {"v", "lid", "ed", "buyer", "iat", "upd", "packs", "mid", "exp"}
    if set(data) != required or type(data.get("v")) is not int:
        raise _invalid("証明書の項目が不正です")
    if not all(isinstance(data[k], str) for k in required - {"v", "packs"}):
        raise _invalid("証明書の文字列項目が不正です")
    if re.fullmatch(r"[A-Za-z0-9_-]+", data["lid"]) is None:
        raise _invalid("証明書の license_id が不正です")
    if re.fullmatch(r"[0-9a-f]{32}", data["mid"]) is None:
        raise _invalid("証明書の端末コードが不正です")
    if not isinstance(data["packs"], list) or any(
        not isinstance(p, str) or re.fullmatch(r"[A-Za-z0-9_-]+", p) is None for p in data["packs"]
    ) or len(set(data["packs"])) != len(data["packs"]):
        raise _invalid("証明書の packs が不正です")
    for field in ("upd",):
        if data[field] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data[field]) is None:
            raise _invalid("証明書の日付形式が不正です")
    for field in ("iat", "exp"):
        if field == "iat" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data[field]):
            _validate_date(data[field], field, allow_empty=False)
            continue
        if field == "exp" and not data[field]:
            continue
        try:
            timestamp = datetime.fromisoformat(data[field].replace("Z", "+00:00"))
            if "T" not in data[field] or timestamp.utcoffset() is None:
                raise ValueError("タイムゾーンがありません")
        except ValueError:
            raise _invalid("証明書の日時はタイムゾーン付き ISO 日時で指定してください") from None
    if data["v"] != 1 or data["ed"] not in ISSUABLE_EDITIONS:
        raise _invalid("未対応の証明書形式または edition です")
    _validate_date(data["upd"], "upd", allow_empty=True)
    return ActivationPayload(
        license_id=data["lid"], edition=data["ed"], buyer=data["buyer"],
        issued_at=data["iat"], updates_until=data["upd"], packs=tuple(data["packs"]),
        machine_code=data["mid"], expires_at=data["exp"],
    )


def verify_activation(activation: str, public_key_pem: str | None = None) -> ActivationPayload:
    """署名済みの端末証明書を検証する。端末・期限の照合は管理層で行う。"""
    return _activation_from_dict(_verify_signed(activation, ACTIVATION_PREFIX, public_key_pem))


def encode_license_key(payload: LicensePayload, private_key_pem: str) -> str:
    """秘密鍵でキーを発行する（発行ツール・テスト用。アプリ本体は秘密鍵を持たない）。"""
    _payload_from_dict(payload.to_dict())  # 発行前に検証ルールを通す
    return _encode_signed(payload.to_dict(), KEY_PREFIX, private_key_pem)


def encode_activation(payload: ActivationPayload, private_key_pem: str) -> str:
    """同じ発行鍵で端末証明書を発行する。"""
    _activation_from_dict(payload.to_dict())
    return _encode_signed(payload.to_dict(), ACTIVATION_PREFIX, private_key_pem)


def _encode_signed(data: dict, prefix: str, private_key_pem: str) -> str:
    key = serialization.load_pem_private_key(private_key_pem.encode("ascii"), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise RuntimeError("秘密鍵が RSA ではありません")
    payload_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload_b64 = _b64encode(payload_json.encode("utf-8"))
    signature = key.sign(payload_b64.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{prefix}.{payload_b64}.{_b64encode(signature)}"


def generate_key_pair() -> tuple[str, str]:
    """(秘密鍵PEM[PKCS#8], 公開鍵PEM) を生成する。Apps Script は PKCS#8 形式の秘密鍵を要求する。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_pem, public_pem
