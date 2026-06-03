"""
プロンプトテンプレート管理モジュール。

data/settings.db の prompt_templates テーブルで、
channel profile 別のプロンプトテンプレートを管理する。

テンプレートの使用可否は profile_id が主キー。
genre_profile は参考情報。

template_kind: 'script' / 'title' / 'meeting'
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_ROOT, "data", "settings.db")
_lock = threading.Lock()

TEMPLATE_KINDS = ("script", "title", "meeting")


# ─────────────────────────────────────────────────────────────────────────────
# テーブル定義
# ─────────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS prompt_templates (
    template_id               TEXT PRIMARY KEY,
    profile_id                TEXT NOT NULL,
    template_name             TEXT NOT NULL,
    template_kind             TEXT NOT NULL CHECK(template_kind IN ('script','title','meeting')),
    genre_profile             TEXT,
    is_default                INTEGER NOT NULL DEFAULT 0,
    is_enabled                INTEGER NOT NULL DEFAULT 1,
    system_rules              TEXT NOT NULL DEFAULT '',
    script_rules              TEXT NOT NULL DEFAULT '',
    title_rules               TEXT,
    meeting_rules             TEXT,
    ng_rules                  TEXT,
    description               TEXT,
    default_hashtags          TEXT,
    default_playlist_category TEXT,
    template_pack             TEXT NOT NULL DEFAULT 'legacy',
    visibility                TEXT NOT NULL DEFAULT 'private',
    product_bundle            TEXT NOT NULL DEFAULT '',
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL,
    UNIQUE(profile_id, template_name),
    FOREIGN KEY(profile_id) REFERENCES channel_profiles(profile_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_templates_default
    ON prompt_templates(profile_id, template_kind)
    WHERE is_default = 1;
"""


def _open_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    for stmt in _DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    _ensure_columns(conn)
    conn.commit()
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(prompt_templates)").fetchall()}
    additions = {
        "template_pack": "TEXT NOT NULL DEFAULT 'legacy'",
        "visibility": "TEXT NOT NULL DEFAULT 'private'",
        "product_bundle": "TEXT NOT NULL DEFAULT ''",
    }
    for col, ddl in additions.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE prompt_templates ADD COLUMN {col} {ddl}")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PromptTemplate:
    template_id: str
    profile_id: str
    template_name: str
    template_kind: str
    genre_profile: str | None
    is_default: bool
    is_enabled: bool
    system_rules: str
    script_rules: str
    title_rules: str | None
    meeting_rules: str | None
    ng_rules: str | None
    description: str | None
    default_hashtags: str | None
    default_playlist_category: str | None
    template_pack: str
    visibility: str
    product_bundle: str
    created_at: str
    updated_at: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "PromptTemplate":
        d = dict(row)
        return PromptTemplate(
            template_id=d["template_id"],
            profile_id=d["profile_id"],
            template_name=d["template_name"],
            template_kind=d["template_kind"],
            genre_profile=d.get("genre_profile"),
            is_default=bool(d["is_default"]),
            is_enabled=bool(d["is_enabled"]),
            system_rules=d["system_rules"] or "",
            script_rules=d["script_rules"] or "",
            title_rules=d.get("title_rules"),
            meeting_rules=d.get("meeting_rules"),
            ng_rules=d.get("ng_rules"),
            description=d.get("description"),
            default_hashtags=d.get("default_hashtags"),
            default_playlist_category=d.get("default_playlist_category"),
            template_pack=d.get("template_pack") or "legacy",
            visibility=d.get("visibility") or "private",
            product_bundle=d.get("product_bundle") or "",
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )


def list_templates(profile_id: str, kind: str | None = None) -> list[PromptTemplate]:
    """指定 profile_id のテンプレート一覧を返す。kind 指定で絞り込み可能。"""
    with _lock:
        conn = _open_db()
        try:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM prompt_templates WHERE profile_id=? AND template_kind=? ORDER BY is_default DESC, template_name",
                    (profile_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM prompt_templates WHERE profile_id=? ORDER BY template_kind, is_default DESC, template_name",
                    (profile_id,),
                ).fetchall()
            return [PromptTemplate.from_row(r) for r in rows]
        finally:
            conn.close()


def get_template(template_id: str) -> PromptTemplate | None:
    """template_id でテンプレートを取得する。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            return PromptTemplate.from_row(row) if row else None
        finally:
            conn.close()


def get_default_template(profile_id: str, kind: str) -> PromptTemplate | None:
    """profile_id + kind のデフォルトテンプレートを返す。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE profile_id=? AND template_kind=? AND is_default=1",
                (profile_id, kind),
            ).fetchone()
            return PromptTemplate.from_row(row) if row else None
        finally:
            conn.close()


def create_template(
    profile_id: str,
    template_name: str,
    template_kind: str,
    system_rules: str = "",
    script_rules: str = "",
    title_rules: str | None = None,
    meeting_rules: str | None = None,
    ng_rules: str | None = None,
    genre_profile: str | None = None,
    description: str | None = None,
    default_hashtags: str | None = None,
    default_playlist_category: str | None = None,
    template_pack: str = "legacy",
    visibility: str = "private",
    product_bundle: str = "",
    is_default: bool = False,
    is_enabled: bool = True,
) -> PromptTemplate:
    """テンプレートを作成して返す。"""
    if template_kind not in TEMPLATE_KINDS:
        raise ValueError(f"template_kind は {TEMPLATE_KINDS} のいずれかで指定してください")
    template_id = str(uuid.uuid4())
    now = _now()
    with _lock:
        conn = _open_db()
        try:
            if is_default:
                # 同じ profile_id + kind の既存 default を解除
                conn.execute(
                    "UPDATE prompt_templates SET is_default=0, updated_at=? WHERE profile_id=? AND template_kind=? AND is_default=1",
                    (now, profile_id, template_kind),
                )
            conn.execute(
                """INSERT INTO prompt_templates
                   (template_id, profile_id, template_name, template_kind, genre_profile,
                    is_default, is_enabled, system_rules, script_rules, title_rules,
                    meeting_rules, ng_rules, description, default_hashtags,
                    default_playlist_category, template_pack, visibility, product_bundle,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (template_id, profile_id, template_name, template_kind, genre_profile,
                 int(is_default), int(is_enabled), system_rules, script_rules, title_rules,
                 meeting_rules, ng_rules, description, default_hashtags,
                 default_playlist_category, template_pack, visibility, product_bundle, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            return PromptTemplate.from_row(row)
        finally:
            conn.close()


def update_template(
    template_id: str,
    profile_id: str,
    *,
    template_name: str | None = None,
    system_rules: str | None = None,
    script_rules: str | None = None,
    title_rules: str | None = None,
    meeting_rules: str | None = None,
    ng_rules: str | None = None,
    description: str | None = None,
    default_hashtags: str | None = None,
    default_playlist_category: str | None = None,
    template_pack: str | None = None,
    visibility: str | None = None,
    product_bundle: str | None = None,
    is_enabled: bool | None = None,
) -> PromptTemplate:
    """active profile 所属のテンプレートだけ更新できる。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"テンプレートが見つかりません: {template_id}")
            if row["profile_id"] != profile_id:
                raise PermissionError(f"別 profile のテンプレートは更新できません: {template_id}")

            now = _now()
            updates: dict = {"updated_at": now}
            if template_name is not None:
                updates["template_name"] = template_name
            if system_rules is not None:
                updates["system_rules"] = system_rules
            if script_rules is not None:
                updates["script_rules"] = script_rules
            if title_rules is not None:
                updates["title_rules"] = title_rules
            if meeting_rules is not None:
                updates["meeting_rules"] = meeting_rules
            if ng_rules is not None:
                updates["ng_rules"] = ng_rules
            if description is not None:
                updates["description"] = description
            if default_hashtags is not None:
                updates["default_hashtags"] = default_hashtags
            if default_playlist_category is not None:
                updates["default_playlist_category"] = default_playlist_category
            if template_pack is not None:
                updates["template_pack"] = template_pack
            if visibility is not None:
                updates["visibility"] = visibility
            if product_bundle is not None:
                updates["product_bundle"] = product_bundle
            if is_enabled is not None:
                updates["is_enabled"] = int(is_enabled)

            set_clause = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE prompt_templates SET {set_clause} WHERE template_id=?",
                [*updates.values(), template_id],
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            return PromptTemplate.from_row(updated)
        finally:
            conn.close()


def set_default(template_id: str, profile_id: str) -> None:
    """指定テンプレートを同 kind のデフォルトに設定する（他の default は解除）。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"テンプレートが見つかりません: {template_id}")
            if row["profile_id"] != profile_id:
                raise PermissionError(f"別 profile のテンプレートは変更できません: {template_id}")
            kind = row["template_kind"]
            now = _now()
            conn.execute(
                "UPDATE prompt_templates SET is_default=0, updated_at=? WHERE profile_id=? AND template_kind=? AND is_default=1",
                (now, profile_id, kind),
            )
            conn.execute(
                "UPDATE prompt_templates SET is_default=1, updated_at=? WHERE template_id=?",
                (now, template_id),
            )
            conn.commit()
        finally:
            conn.close()


def delete_template(template_id: str, profile_id: str) -> None:
    """active profile 所属のテンプレートだけ削除できる。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"テンプレートが見つかりません: {template_id}")
            if row["profile_id"] != profile_id:
                raise PermissionError(f"別 profile のテンプレートは削除できません: {template_id}")
            conn.execute("DELETE FROM prompt_templates WHERE template_id=?", (template_id,))
            conn.commit()
        finally:
            conn.close()


def clone_template(template_id: str, target_profile_id: str, new_name: str) -> PromptTemplate:
    """
    テンプレートを別 profile_id へ複製する。
    複製後は新しい template_id として保存される（元のものは変更しない）。
    """
    src = get_template(template_id)
    if src is None:
        raise ValueError(f"テンプレートが見つかりません: {template_id}")
    return create_template(
        profile_id=target_profile_id,
        template_name=new_name,
        template_kind=src.template_kind,
        system_rules=src.system_rules,
        script_rules=src.script_rules,
        title_rules=src.title_rules,
        meeting_rules=src.meeting_rules,
        ng_rules=src.ng_rules,
        genre_profile=src.genre_profile,
        description=src.description,
        default_hashtags=src.default_hashtags,
        default_playlist_category=src.default_playlist_category,
        template_pack=src.template_pack,
        visibility=src.visibility,
        product_bundle=src.product_bundle,
        is_default=False,
        is_enabled=src.is_enabled,
    )


def has_templates(profile_id: str) -> bool:
    """profile_id にテンプレートが1件以上あるか確認する。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT 1 FROM prompt_templates WHERE profile_id=? LIMIT 1", (profile_id,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()
