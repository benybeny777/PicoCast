"""よみがな辞書を data/settings.db の単一テーブルで管理する。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

import core.settings_store as settings_store

_JST = timezone(timedelta(hours=9))
_VALID_TYPES = {"base", "user"}


def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings_store._DB_PATH), exist_ok=True)
    conn = sqlite3.connect(settings_store._DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reading_dictionary_entries (
            dict_type  TEXT NOT NULL,
            word       TEXT NOT NULL,
            reading    TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(dict_type, word),
            CHECK(dict_type IN ('base', 'user'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reading_candidates (
            word            TEXT PRIMARY KEY,
            reading         TEXT NOT NULL,
            reason          TEXT NOT NULL DEFAULT '',
            source          TEXT NOT NULL DEFAULT 'safe_auto',
            auto_applied    INTEGER NOT NULL DEFAULT 0,
            review_required INTEGER NOT NULL DEFAULT 1,
            updated_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reading_check_findings (
            word             TEXT NOT NULL,
            voicevox_reading TEXT NOT NULL,
            expected_reading TEXT NOT NULL,
            example          TEXT NOT NULL DEFAULT '',
            source           TEXT NOT NULL DEFAULT '',
            seen_count       INTEGER NOT NULL DEFAULT 1,
            dismissed        INTEGER NOT NULL DEFAULT 0,
            updated_at       TEXT NOT NULL,
            PRIMARY KEY(word, voicevox_reading)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reading_dictionary_seed_state (
            seed_name TEXT PRIMARY KEY,
            seeded_at TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def _validate_type(dict_type: str) -> None:
    if dict_type not in _VALID_TYPES:
        raise RuntimeError(f"不正なよみがな辞書種別です: {dict_type}")


def ensure_initialized() -> None:
    """settings.db に必要なテーブルを用意する。"""
    with _connect() as conn:
        seeded = conn.execute(
            "SELECT 1 FROM reading_dictionary_seed_state WHERE seed_name='initial'"
        ).fetchone()
        if seeded:
            return
        existing_count = conn.execute("SELECT COUNT(*) FROM reading_dictionary_entries").fetchone()[0]
        if existing_count == 0:
            from core.reading_dictionary_seed import READING_DICTIONARY_SEED

            now = _now_jst()
            total = 0
            base_words = set(READING_DICTIONARY_SEED.get("base", {}).keys())
            for dict_type, rows in READING_DICTIONARY_SEED.items():
                _validate_type(dict_type)
                if dict_type == "user":
                    rows = {word: reading for word, reading in rows.items() if word not in base_words}
                total += len(rows)
                conn.executemany(
                    """
                    INSERT INTO reading_dictionary_entries(dict_type, word, reading, updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(dict_type, word) DO NOTHING
                    """,
                    [(dict_type, word, reading, now) for word, reading in rows.items()],
                )
        else:
            total = int(existing_count)
        conn.execute(
            """
            INSERT INTO reading_dictionary_seed_state(seed_name, seeded_at, row_count)
            VALUES('initial', ?, ?)
            ON CONFLICT(seed_name) DO NOTHING
            """,
            (_now_jst(), total),
        )
        conn.commit()


def seed_initial_entries(entries: dict[str, dict[str, str]]) -> None:
    """初期データを投入する。既存エントリは上書きしない。"""
    with _connect() as conn:
        base_words = set(entries.get("base", {}).keys())
        for dict_type, rows in entries.items():
            _validate_type(dict_type)
            if dict_type == "user":
                rows = {word: reading for word, reading in rows.items() if word not in base_words}
            now = _now_jst()
            conn.executemany(
                """
                INSERT INTO reading_dictionary_entries(dict_type, word, reading, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(dict_type, word) DO NOTHING
                """,
                [(dict_type, word, reading, now) for word, reading in rows.items()],
            )
        conn.commit()


def load_all() -> dict[str, dict[str, str]]:
    ensure_initialized()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT dict_type, word, reading
            FROM reading_dictionary_entries
            ORDER BY dict_type ASC, word ASC
            """
        ).fetchall()
    result = {"base": {}, "user": {}}
    for row in rows:
        result[row["dict_type"]][row["word"]] = row["reading"]
    for word in list(result["user"].keys()):
        if word in result["base"]:
            del result["user"][word]
    return result


def load_dict(dict_type: str) -> dict[str, str]:
    _validate_type(dict_type)
    return load_all()[dict_type]


def save_dict(dict_type: str, entries: dict[str, str]) -> None:
    _validate_type(dict_type)
    normalized = {str(k).strip(): str(v).strip() for k, v in entries.items() if str(k).strip() and str(v).strip()}
    ensure_initialized()
    if dict_type == "user":
        base_words = set(load_dict("base").keys())
        normalized = {word: reading for word, reading in normalized.items() if word not in base_words}
    now = _now_jst()
    with _connect() as conn:
        conn.execute("DELETE FROM reading_dictionary_entries WHERE dict_type=?", (dict_type,))
        conn.executemany(
            """
            INSERT INTO reading_dictionary_entries(dict_type, word, reading, updated_at)
            VALUES(?,?,?,?)
            """,
            [(dict_type, word, reading, now) for word, reading in normalized.items()],
        )
        conn.commit()


def upsert_entry(dict_type: str, word: str, reading: str) -> None:
    _validate_type(dict_type)
    word = word.strip()
    reading = reading.strip()
    if not word or not reading:
        raise RuntimeError("word と reading は必須です")
    ensure_initialized()
    with _connect() as conn:
        if dict_type == "base":
            conn.execute(
                "DELETE FROM reading_dictionary_entries WHERE dict_type='user' AND word=?",
                (word,),
            )
        if dict_type == "user":
            duplicate = conn.execute(
                "SELECT 1 FROM reading_dictionary_entries WHERE dict_type='base' AND word=?",
                (word,),
            ).fetchone()
            if duplicate:
                return
        conn.execute(
            """
            INSERT INTO reading_dictionary_entries(dict_type, word, reading, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(dict_type, word) DO UPDATE SET
                reading=excluded.reading,
                updated_at=excluded.updated_at
            """,
            (dict_type, word, reading, _now_jst()),
        )
        conn.commit()


def delete_entry(dict_type: str, word: str) -> bool:
    _validate_type(dict_type)
    ensure_initialized()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM reading_dictionary_entries WHERE dict_type=? AND word=?",
            (dict_type, word),
        )
        conn.commit()
        return bool(cur.rowcount)


def load_candidates() -> dict[str, dict]:
    ensure_initialized()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT word, reading, reason, source, auto_applied, review_required
            FROM reading_candidates
            ORDER BY word ASC
            """
        ).fetchall()
    return {
        row["word"]: {
            "surface": row["word"],
            "reading": row["reading"],
            "reason": row["reason"],
            "source": row["source"],
            "auto_applied": bool(row["auto_applied"]),
            "review_required": bool(row["review_required"]),
        }
        for row in rows
    }


def save_candidates(candidates: dict[str, dict]) -> None:
    normalized = {}
    for word, item in candidates.items():
        word = str(item.get("surface") or word).strip()
        reading = str(item.get("reading") or "").strip()
        if not word or not reading:
            continue
        normalized[word] = {
            "reading": reading,
            "reason": str(item.get("reason") or ""),
            "source": str(item.get("source") or "safe_auto"),
            "auto_applied": int(bool(item.get("auto_applied"))),
            "review_required": int(bool(item.get("review_required", True))),
        }
    ensure_initialized()
    now = _now_jst()
    with _connect() as conn:
        conn.execute("DELETE FROM reading_candidates")
        conn.executemany(
            """
            INSERT INTO reading_candidates(
                word, reading, reason, source, auto_applied, review_required, updated_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            [
                (
                    word,
                    item["reading"],
                    item["reason"],
                    item["source"],
                    item["auto_applied"],
                    item["review_required"],
                    now,
                )
                for word, item in normalized.items()
            ],
        )
        conn.commit()


# ── 読み違いの可能性（core/reading_check.py が見つけたもの） ─────────────────────

def record_findings(findings, source: str) -> int:
    """見つかった読み違いの可能性を記録する。同じ語・同じ VOICEVOX の読みは件数だけ増やす。

    「無視」にしたもの（dismissed）は再表示しない。記録した（無視されていない）件数を返す。
    """
    if not findings:
        return 0
    ensure_initialized()
    now = _now_jst()
    active = 0
    with _connect() as conn:
        for f in findings:
            conn.execute(
                """
                INSERT INTO reading_check_findings(
                    word, voicevox_reading, expected_reading, example, source, seen_count, dismissed, updated_at
                ) VALUES(?,?,?,?,?,1,0,?)
                ON CONFLICT(word, voicevox_reading) DO UPDATE SET
                    expected_reading=excluded.expected_reading,
                    example=excluded.example,
                    source=excluded.source,
                    seen_count=reading_check_findings.seen_count + 1,
                    updated_at=excluded.updated_at
                """,
                (f.word, f.voicevox_reading, f.expected_reading, f.text, source, now),
            )
            dismissed = conn.execute(
                "SELECT dismissed FROM reading_check_findings WHERE word=? AND voicevox_reading=?",
                (f.word, f.voicevox_reading),
            ).fetchone()[0]
            active += 0 if dismissed else 1
        conn.commit()
    return active


def list_findings() -> list[dict]:
    """未対応（無視していない）の読み違いの可能性。よく出る順。"""
    ensure_initialized()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT word, voicevox_reading, expected_reading, example, source, seen_count, updated_at
            FROM reading_check_findings WHERE dismissed=0
            ORDER BY seen_count DESC, updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def accept_finding(word: str, reading: str) -> None:
    """正しい読みを辞書（基本辞書）へ登録し、その語の読み違いの可能性を片付ける。

    基本辞書は形態素解析の前に文字列置換されるため、動詞・形容詞や1文字の漢字にも効く。
    """
    upsert_entry("base", word, reading)
    with _connect() as conn:
        conn.execute("DELETE FROM reading_check_findings WHERE word=?", (word,))
        conn.commit()


def dismiss_finding(word: str, voicevox_reading: str) -> bool:
    """VOICEVOX の読みで正しいとして、同じ組み合わせを今後表示しない。"""
    ensure_initialized()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE reading_check_findings SET dismissed=1, updated_at=? WHERE word=? AND voicevox_reading=?",
            (_now_jst(), word, voicevox_reading),
        )
        conn.commit()
        return bool(cur.rowcount)
