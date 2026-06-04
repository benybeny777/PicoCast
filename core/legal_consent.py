"""法務文書（利用規約・EULA・プライバシーポリシー）への同意状態の管理。

初回セットアップの最初に同意を求め、未同意では生成・アップロード・セットアップ完了を
許可しない。同意状態は data/settings.db:settings に保存する。
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.settings_store import get_all, set_many

LEGAL_CONSENT_ACCEPTED_KEY = "LEGAL_CONSENT_ACCEPTED"
LEGAL_CONSENT_AT_KEY = "LEGAL_CONSENT_AT"

# /setup と /legal で提示する法務文書（ファイル名 → 表示名）。
LEGAL_DOCUMENTS: dict[str, str] = {
    "利用規約.md": "利用規約",
    "EULA.md": "使用許諾契約（EULA）",
    "プライバシーポリシー.md": "プライバシーポリシー",
    "特定商取引法に基づく表記.md": "特定商取引法に基づく表記",
}


def is_consent_accepted() -> bool:
    return get_all().get(LEGAL_CONSENT_ACCEPTED_KEY, "0").strip().lower() in ("1", "true", "yes", "on")


def accept_consent() -> dict:
    set_many({
        LEGAL_CONSENT_ACCEPTED_KEY: "1",
        LEGAL_CONSENT_AT_KEY: datetime.now(timezone.utc).isoformat(),
    })
    return consent_status()


def consent_status() -> dict:
    settings = get_all()
    return {
        "accepted": is_consent_accepted(),
        "accepted_at": settings.get(LEGAL_CONSENT_AT_KEY, ""),
        "documents": [{"file": f, "label": label} for f, label in LEGAL_DOCUMENTS.items()],
    }
