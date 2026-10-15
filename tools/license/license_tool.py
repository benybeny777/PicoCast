"""ライセンス鍵の生成・キー手動発行・検証ツール（販売者用。配布物には含めない）。

使い方（リポジトリのルートで実行）:
  python tools/license/license_tool.py genkey
      RSA 鍵ペアを作り、秘密鍵を ~/.nvf_license/private_key.pem に保存、
      公開鍵を core/license_public_key.py に書き込む。既存の秘密鍵は上書きしない。
  python tools/license/license_tool.py issue --edition pro --buyer "山田太郎" [--packs urban_legend,zunkami] [--update-months 12]
      手動でキーを発行して表示する（通常は Apps Script が自動発行する）。
      手動発行したキーは失効確認で見つかるよう、スプレッドシート「発行済み」シートにも記録すること。
  python tools/license/license_tool.py verify <key>
      キーを公開鍵で検証して中身を表示する。
  python tools/license/license_tool.py activate --key-file <購入キーのファイル> --machine-code <32桁端末コード> --permanent
      既存の購入キーと販売者秘密鍵でオーナー・オフライン用の無期限証明書を発行する。
      オンライン用は --permanent の代わりに --expires-at <UTCタイムゾーン付きISO日時> を指定する。
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from core.license_key import (  # noqa: E402
    ISSUABLE_EDITIONS, ActivationPayload, LicensePayload, encode_activation, encode_license_key,
    generate_key_pair, verify_activation, verify_license_key,
)

_PRIVATE_KEY_PATH = Path.home() / ".nvf_license" / "private_key.pem"
_PUBLIC_KEY_MODULE = _ROOT / "core" / "license_public_key.py"


def _add_months(base: date, months: int) -> date:
    month_index = base.month - 1 + months
    year, month = base.year + month_index // 12, month_index % 12 + 1
    for day in (base.day, 30, 29, 28):
        try:
            return base.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise ValueError(f"日付を計算できません: {base} + {months}か月")


def cmd_genkey(_args) -> None:
    if _PUBLIC_KEY_MODULE.exists():
        raise SystemExit("公開鍵が既にあります。発行済みキーを無効化する鍵の再生成は禁止です。")
    if _PRIVATE_KEY_PATH.exists():
        raise SystemExit(f"秘密鍵が既にあります（上書きしません）: {_PRIVATE_KEY_PATH}")
    private_pem, public_pem = generate_key_pair()
    _PRIVATE_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PRIVATE_KEY_PATH.write_text(private_pem, encoding="ascii")
    _PUBLIC_KEY_MODULE.write_text(
        '"""ライセンスキー検証用の公開鍵（tools/license/license_tool.py genkey が生成）。\n\n'
        "秘密鍵はリポジトリに置かない。鍵を作り直すと発行済みキーはすべて無効になる。\n"
        '"""\n'
        f'LICENSE_PUBLIC_KEY_PEM = """{public_pem}"""\n',
        encoding="utf-8",
    )
    print(f"秘密鍵: {_PRIVATE_KEY_PATH}（バックアップ必須・共有禁止）")
    print(f"公開鍵: {_PUBLIC_KEY_MODULE}")
    print("Apps Script のスクリプトプロパティ LICENSE_PRIVATE_KEY に秘密鍵 PEM の全文を登録してください。")


def cmd_issue(args) -> None:
    if not _PRIVATE_KEY_PATH.exists():
        raise SystemExit(f"秘密鍵がありません: {_PRIVATE_KEY_PATH}（既存の販売者秘密鍵を復元してください）")
    today = date.today()
    updates_until = "" if args.update_months <= 0 else _add_months(today, args.update_months).isoformat()
    payload = LicensePayload(
        license_id=args.license_id or uuid.uuid4().hex[:16],
        edition=args.edition,
        buyer=args.buyer,
        issued_at=today.isoformat(),
        updates_until=updates_until,
        packs=tuple(p.strip() for p in args.packs.split(",") if p.strip()),
    )
    key = encode_license_key(payload, _PRIVATE_KEY_PATH.read_text(encoding="ascii"))
    print(f"license_id: {payload.license_id}")
    print(key)


def cmd_verify(args) -> None:
    payload = verify_activation(args.key) if args.key.startswith("NVA1.") else verify_license_key(args.key)
    print(payload.to_dict())


def cmd_activate(args) -> None:
    """検証済み購入キーの権利を継承して手動証明書を発行する。"""
    if not _PRIVATE_KEY_PATH.exists():
        raise SystemExit("既存の販売者秘密鍵がありません。鍵を新規生成しないでください。")
    license_key = Path(args.key_file).read_text(encoding="utf-8-sig").strip()
    purchase = verify_license_key(license_key)
    activation = encode_activation(
        ActivationPayload(**purchase.__dict__, machine_code=args.machine_code,
                          expires_at="" if args.permanent else args.expires_at),
        _PRIVATE_KEY_PATH.read_text(encoding="ascii"),
    )
    verify_activation(activation)  # 既存の埋め込み公開鍵と秘密鍵の組を照合する
    print(activation)


def main() -> None:
    parser = argparse.ArgumentParser(description="Native Video Factory ライセンスツール")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("genkey").set_defaults(func=cmd_genkey)
    issue = sub.add_parser("issue")
    issue.add_argument("--edition", required=True, choices=ISSUABLE_EDITIONS)
    issue.add_argument("--buyer", required=True)
    issue.add_argument("--packs", default="")
    issue.add_argument("--update-months", type=int, default=12, help="無料アップデート期間（0=無期限）")
    issue.add_argument("--license-id", default="", help="再発行時に既存の license_id を引き継ぐ")
    issue.set_defaults(func=cmd_issue)
    verify = sub.add_parser("verify")
    verify.add_argument("key")
    verify.set_defaults(func=cmd_verify)
    activate = sub.add_parser("activate", help="既存購入キーから手動の端末証明書を発行")
    activate.add_argument("--key-file", required=True, help="購入キーを保存したローカルファイル")
    activate.add_argument("--machine-code", required=True, help="アプリが表示する32桁の端末コード")
    validity = activate.add_mutually_exclusive_group(required=True)
    validity.add_argument("--permanent", action="store_true", help="オーナー・オフライン利用者向け無期限証明書")
    validity.add_argument("--expires-at", help="UTCタイムゾーン付きISO日時")
    activate.set_defaults(func=cmd_activate)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
