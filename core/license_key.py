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
from dataclasses import dataclass
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core.error_codes import AppError

KEY_PREFIX = "NVF1"
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


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _invalid(detail: str) -> AppError:
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
        raise _invalid(f"未知の edition です: {edition}")
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


def verify_license_key(license_key: str, public_key_pem: str | None = None) -> LicensePayload:
    """キーの署名と内容を検証して中身を返す。不正なら AppError(E-LICENSE-INVALID)。"""
    if public_key_pem is None:
        from core.license_public_key import LICENSE_PUBLIC_KEY_PEM
        public_key_pem = LICENSE_PUBLIC_KEY_PEM
    text = "".join((license_key or "").split())  # メール本文からの貼り付けで混入する改行・空白を除去
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        raise _invalid("キーの形式が正しくありません。届いたキーを改行も含めてそのまま貼り付けてください")
    payload_b64, sig_b64 = parts[1], parts[2]
    try:
        signature = _b64decode(sig_b64)
    except (binascii.Error, ValueError) as exc:
        raise _invalid("署名部分を読み取れません") from exc
    try:
        _load_public_key(public_key_pem).verify(
            signature, payload_b64.encode("ascii"), padding.PKCS1v15(), hashes.SHA256(),
        )
    except (InvalidSignature, UnicodeEncodeError) as exc:
        raise _invalid("署名が一致しません（キーの誤り・改変の可能性）") from exc
    try:
        data = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        raise _invalid("キーの内容を読み取れません") from exc
    if not isinstance(data, dict):
        raise _invalid("キーの内容が不正です")
    return _payload_from_dict(data)


def encode_license_key(payload: LicensePayload, private_key_pem: str) -> str:
    """秘密鍵でキーを発行する（発行ツール・テスト用。アプリ本体は秘密鍵を持たない）。"""
    _payload_from_dict(payload.to_dict())  # 発行前に検証ルールを通す
    key = serialization.load_pem_private_key(private_key_pem.encode("ascii"), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise RuntimeError("秘密鍵が RSA ではありません")
    payload_json = json.dumps(payload.to_dict(), ensure_ascii=False, separators=(",", ":"))
    payload_b64 = _b64encode(payload_json.encode("utf-8"))
    signature = key.sign(payload_b64.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{KEY_PREFIX}.{payload_b64}.{_b64encode(signature)}"


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
