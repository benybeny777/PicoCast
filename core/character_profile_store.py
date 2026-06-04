"""
キャラクター設定管理モジュール。

data/settings.db の character_profiles テーブルで、channel profile 別の
キャラクター設定（役割・口調・禁止台詞・掛け合いルール）を管理する。

台本テンプレート（prompt_templates）からキャラ設定を分離し、台本生成時に
有効なキャラクター設定を合成してプロンプトを作るための土台。

設計方針:
- profile_id（チャンネル）ごとに複数のキャラクター設定を持てる。
- enabled=1 のものだけを sort_order 順に合成する。
- 自動フォールバック禁止: 有効なキャラ設定が無いチャンネルでは合成側がエラーにする。
- 別チャンネルのキャラ設定を勝手に流用しない（profile_id で厳密に分離）。
"""
from __future__ import annotations

import json
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

_DDL = """
CREATE TABLE IF NOT EXISTS character_profiles (
    character_id      TEXT PRIMARY KEY,
    profile_id        TEXT NOT NULL,
    character_key     TEXT NOT NULL,
    display_name      TEXT NOT NULL,
    character_name    TEXT NOT NULL,
    role              TEXT NOT NULL DEFAULT '',
    tone_style        TEXT NOT NULL DEFAULT '',
    speaking_rules    TEXT NOT NULL DEFAULT '',
    forbidden_phrases TEXT NOT NULL DEFAULT '',
    dialogue_rules    TEXT NOT NULL DEFAULT '',
    voice_backend     TEXT NOT NULL DEFAULT 'voicevox',
    voice_speaker     TEXT NOT NULL DEFAULT '',
    voice_speaker_id  INTEGER,
    voice_styles_json TEXT NOT NULL DEFAULT '{}',
    portrait_png_path TEXT NOT NULL DEFAULT '',
    credit_required   INTEGER NOT NULL DEFAULT 1,
    credit_text       TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 1,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(profile_id, character_key),
    FOREIGN KEY(profile_id) REFERENCES channel_profiles(profile_id)
);
"""


@dataclass(frozen=True)
class CharacterProfile:
    character_id: str
    profile_id: str
    character_key: str
    display_name: str
    character_name: str
    role: str
    tone_style: str
    speaking_rules: str
    forbidden_phrases: str
    dialogue_rules: str
    enabled: bool
    sort_order: int
    created_at: str
    updated_at: str
    voice_backend: str = "voicevox"
    voice_speaker: str = ""
    voice_speaker_id: int | None = None
    voice_styles: dict[str, int] | None = None
    portrait_png_path: str = ""
    credit_required: bool = True
    credit_text: str = ""

    @staticmethod
    def from_row(row: sqlite3.Row) -> "CharacterProfile":
        return CharacterProfile(
            character_id=row["character_id"],
            profile_id=row["profile_id"],
            character_key=row["character_key"],
            display_name=row["display_name"],
            character_name=row["character_name"],
            role=row["role"],
            tone_style=row["tone_style"],
            speaking_rules=row["speaking_rules"],
            forbidden_phrases=row["forbidden_phrases"],
            dialogue_rules=row["dialogue_rules"],
            voice_backend=row["voice_backend"],
            voice_speaker=row["voice_speaker"],
            voice_speaker_id=row["voice_speaker_id"],
            voice_styles=_parse_voice_styles(row["voice_styles_json"]),
            portrait_png_path=row["portrait_png_path"],
            credit_required=bool(row["credit_required"]),
            credit_text=row["credit_text"],
            enabled=bool(row["enabled"]),
            sort_order=row["sort_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


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
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(character_profiles)").fetchall()}
    additions = {
        "voice_speaker_id": "ALTER TABLE character_profiles ADD COLUMN voice_speaker_id INTEGER",
        "voice_backend": "ALTER TABLE character_profiles ADD COLUMN voice_backend TEXT NOT NULL DEFAULT 'voicevox'",
        "voice_speaker": "ALTER TABLE character_profiles ADD COLUMN voice_speaker TEXT NOT NULL DEFAULT ''",
        "voice_styles_json": "ALTER TABLE character_profiles ADD COLUMN voice_styles_json TEXT NOT NULL DEFAULT '{}'",
        "portrait_png_path": "ALTER TABLE character_profiles ADD COLUMN portrait_png_path TEXT NOT NULL DEFAULT ''",
        "credit_required": "ALTER TABLE character_profiles ADD COLUMN credit_required INTEGER NOT NULL DEFAULT 1",
        "credit_text": "ALTER TABLE character_profiles ADD COLUMN credit_text TEXT NOT NULL DEFAULT ''",
    }
    for column, sql in additions.items():
        if column not in columns:
            conn.execute(sql)


def _parse_voice_styles(raw: str | None) -> dict[str, int]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _logger.error("voice_styles_json のJSON解析に失敗しました", exc_info=True)
        raise RuntimeError("voice_styles_json が不正です") from exc
    if not isinstance(data, dict):
        _logger.error("voice_styles_json がオブジェクトではありません: type=%s", type(data).__name__)
        raise RuntimeError("voice_styles_json はオブジェクトである必要があります")
    result: dict[str, int] = {}
    for key, value in data.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError) as exc:
            _logger.error("voice_styles_json の話者IDが数値ではありません: emotion=%s", key, exc_info=True)
            raise RuntimeError("voice_styles_json の話者IDは数値で指定してください") from exc
    return result


def _voice_styles_json(value: dict[str, int] | str | None) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        _parse_voice_styles(value)
        return value
    result: dict[str, int] = {}
    for key, speaker_id in value.items():
        try:
            result[str(key)] = int(speaker_id)
        except (TypeError, ValueError) as exc:
            _logger.error("voice_styles の話者IDが数値ではありません: emotion=%s", key, exc_info=True)
            raise RuntimeError("voice_styles の話者IDは数値で指定してください") from exc
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def has_characters(profile_id: str) -> bool:
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT 1 FROM character_profiles WHERE profile_id=? LIMIT 1", (profile_id,)
            ).fetchone()
        finally:
            conn.close()
    return row is not None


def list_characters(profile_id: str, *, enabled_only: bool = False) -> list[CharacterProfile]:
    with _lock:
        conn = _open_db()
        try:
            sql = "SELECT * FROM character_profiles WHERE profile_id=?"
            if enabled_only:
                sql += " AND enabled=1"
            sql += " ORDER BY sort_order, character_key"
            rows = conn.execute(sql, (profile_id,)).fetchall()
        finally:
            conn.close()
    return [CharacterProfile.from_row(r) for r in rows]


def create_character(
    *,
    profile_id: str,
    character_key: str,
    display_name: str,
    character_name: str,
    role: str = "",
    tone_style: str = "",
    speaking_rules: str = "",
    forbidden_phrases: str = "",
    dialogue_rules: str = "",
    voice_backend: str = "voicevox",
    voice_speaker: str = "",
    voice_speaker_id: int | None = None,
    voice_styles: dict[str, int] | str | None = None,
    portrait_png_path: str = "",
    credit_required: bool = True,
    credit_text: str = "",
    enabled: bool = True,
    sort_order: int = 0,
) -> str:
    """キャラクター設定を作成する。戻り値は character_id。"""
    character_id = str(uuid.uuid4())
    now = _now()
    with _lock:
        conn = _open_db()
        try:
            if enabled:
                conn.execute(
                    """
                    UPDATE character_profiles
                       SET enabled=0, updated_at=?
                     WHERE profile_id=? AND character_name=? AND character_id<>?
                    """,
                    (now, profile_id, character_name, character_id),
                )
            conn.execute(
                """
                INSERT INTO character_profiles
                    (character_id, profile_id, character_key, display_name, character_name,
                     role, tone_style, speaking_rules, forbidden_phrases, dialogue_rules,
                     voice_backend, voice_speaker, voice_speaker_id, voice_styles_json, portrait_png_path,
                     credit_required, credit_text,
                     enabled, sort_order, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (character_id, profile_id, character_key, display_name, character_name,
                 role, tone_style, speaking_rules, forbidden_phrases, dialogue_rules,
                 voice_backend, voice_speaker, voice_speaker_id, _voice_styles_json(voice_styles), portrait_png_path,
                 1 if credit_required else 0, credit_text,
                 1 if enabled else 0, sort_order, now, now),
            )
            conn.commit()
        finally:
            conn.close()
    return character_id


def _update_character_locked(conn: sqlite3.Connection, character_id: str, **fields) -> None:
    """conn と _lock を保持した状態でキャラクター設定を更新する。"""
    allowed = {
        "display_name", "character_name", "role", "tone_style", "speaking_rules",
        "forbidden_phrases", "dialogue_rules", "voice_backend", "voice_speaker",
        "voice_speaker_id", "voice_styles", "voice_styles_json", "portrait_png_path",
        "credit_required", "credit_text",
        "enabled", "sort_order",
    }
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    if "voice_styles" in sets:
        sets["voice_styles_json"] = _voice_styles_json(sets.pop("voice_styles"))
    if "voice_styles_json" in sets:
        sets["voice_styles_json"] = _voice_styles_json(sets["voice_styles_json"])
    if "enabled" in sets:
        sets["enabled"] = 1 if sets["enabled"] else 0
    if "credit_required" in sets:
        sets["credit_required"] = 1 if sets["credit_required"] else 0
    cols = ", ".join(f"{k}=?" for k in sets)
    vals = list(sets.values()) + [_now(), character_id]
    conn.execute(f"UPDATE character_profiles SET {cols}, updated_at=? WHERE character_id=?", vals)


def update_character(character_id: str, **fields) -> None:
    """指定キャラクター設定のフィールドを更新する。"""
    if fields.get("enabled") is True:
        enable_fields = dict(fields)
        enable_fields.pop("enabled", None)
        enable_character_exclusive(character_id, **enable_fields)
        return
    with _lock:
        conn = _open_db()
        try:
            _update_character_locked(conn, character_id, **fields)
            conn.commit()
        finally:
            conn.close()


def enable_character_exclusive(character_id: str, **fields) -> None:
    """指定キャラクターを有効化し、同一 profile・同一 character_name の他設定を無効化する。"""
    with _lock:
        conn = _open_db()
        try:
            row = conn.execute(
                "SELECT profile_id, character_name FROM character_profiles WHERE character_id=?",
                (character_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("キャラクター設定が見つかりません")
            update_fields = dict(fields)
            update_fields["enabled"] = True
            _update_character_locked(conn, character_id, **update_fields)
            updated = conn.execute(
                "SELECT profile_id, character_name FROM character_profiles WHERE character_id=?",
                (character_id,),
            ).fetchone()
            profile_id = updated["profile_id"]
            character_name = updated["character_name"]
            now = _now()
            conn.execute(
                """
                UPDATE character_profiles
                   SET enabled=0, updated_at=?
                 WHERE profile_id=? AND character_name=? AND character_id<>?
                """,
                (now, profile_id, character_name, character_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            _logger.error("キャラクター設定の排他有効化に失敗: character_id=%s", character_id, exc_info=True)
            raise
        finally:
            conn.close()


def set_enabled(character_id: str, enabled: bool) -> None:
    if enabled:
        enable_character_exclusive(character_id)
    else:
        update_character(character_id, enabled=False)


def delete_character(character_id: str) -> None:
    with _lock:
        conn = _open_db()
        try:
            conn.execute("DELETE FROM character_profiles WHERE character_id=?", (character_id,))
            conn.commit()
        finally:
            conn.close()


def resolve_character_voice_settings(profile_id: str | None, character_name: str, emotion: str = "ノーマル") -> dict:
    """profile のキャラ設定と config.CHARACTERS から音声バックエンド設定を解決する。"""
    name = str(character_name or "").strip()
    emotion = str(emotion or "ノーマル").strip() or "ノーマル"
    if profile_id:
        matches = [c for c in list_characters(profile_id) if c.character_name == name]
        matches.sort(key=lambda c: (not c.enabled, c.sort_order, c.character_key))
        for character in matches:
            backend = (character.voice_backend or "voicevox").strip().lower()
            speaker = str(character.voice_speaker or "").strip()
            if character.voice_styles and emotion in character.voice_styles:
                speaker = str(character.voice_styles[emotion])
            if not speaker and character.voice_speaker_id is not None:
                speaker = str(character.voice_speaker_id)
            if speaker:
                return {
                    "backend": backend,
                    "speaker": speaker,
                    "speaker_id": int(speaker) if backend == "voicevox" and speaker.isdigit() else None,
                }
            if character.voice_speaker_id is not None:
                return {"backend": backend, "speaker": str(character.voice_speaker_id), "speaker_id": int(character.voice_speaker_id)}

    from config import CHARACTERS
    for config_item in CHARACTERS.values():
        if config_item.get("name") == name:
            styles = config_item.get("styles") or {}
            speaker_id = int(styles.get(emotion, config_item["speaker_id"]))
            return {"backend": "voicevox", "speaker": str(speaker_id), "speaker_id": speaker_id}
    _logger.error("未対応の話者です: profile_id=%s character=%s emotion=%s", profile_id, name, emotion)
    raise RuntimeError(f"未対応の話者です: {name}。キャラクター設定で音声バックエンドと話者IDを登録してください。")


def resolve_character_voice(profile_id: str | None, character_name: str, emotion: str = "ノーマル") -> int:
    """VOICEVOX 用 speaker ID を返す。VOICEVOX 以外は生成器未対応として停止する。"""
    settings = resolve_character_voice_settings(profile_id, character_name, emotion)
    if settings["backend"] != "voicevox":
        _logger.error(
            "未対応の音声バックエンドです: profile_id=%s character=%s emotion=%s backend=%s",
            profile_id, character_name, emotion, settings["backend"],
        )
        raise RuntimeError(
            f"音声バックエンド '{settings['backend']}' はまだ生成処理に未対応です。"
            "キャラクター設定は保存済みですが、音声生成アダプタの実装が必要です。"
        )
    if settings["speaker_id"] is None:
        _logger.error(
            "VOICEVOX speaker ID が数値ではありません: profile_id=%s character=%s emotion=%s speaker=%s",
            profile_id, character_name, emotion, settings["speaker"],
        )
        raise RuntimeError("VOICEVOX speaker ID は数値で指定してください。")
    return int(settings["speaker_id"])


def _default_credit_text(character: CharacterProfile) -> str:
    backend = (character.voice_backend or "voicevox").strip()
    if not backend:
        return ""
    return f"{backend.upper()}:{character.character_name}" if backend.lower() == "voicevox" else f"{backend}:{character.character_name}"


def build_character_credit_block(profile_id: str | None, character_names: list[str] | set[str] | tuple[str, ...] | None) -> str:
    """台本で使ったキャラクターに必要なクレジット表記を説明文用に組み立てる。"""
    names = [str(name or "").strip() for name in (character_names or []) if str(name or "").strip()]
    if not names:
        names = ["ずんだもん", "四国めたん"]
    lines: list[str] = []
    seen: set[str] = set()
    characters = list_characters(profile_id) if profile_id else []
    for name in names:
        matches = [c for c in characters if c.character_name == name]
        matches.sort(key=lambda c: (not c.enabled, c.sort_order, c.character_key))
        character = matches[0] if matches else None
        if character:
            if not character.credit_required:
                continue
            text = (character.credit_text or "").strip() or _default_credit_text(character)
        else:
            from config import CHARACTERS
            config_item = next((item for item in CHARACTERS.values() if item.get("name") == name), None)
            if not config_item:
                _logger.error("クレジット設定の無いキャラクターです: profile_id=%s character=%s", profile_id, name)
                raise RuntimeError(f"クレジット設定の無いキャラクターです: {name}")
            text = f"VOICEVOX:{name}"
        if text and text not in seen:
            seen.add(text)
            lines.append(text)
    if not lines:
        return ""
    return "\n\n【使用音声合成】" + " / ".join(lines)
