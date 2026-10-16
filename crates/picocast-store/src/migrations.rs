//! 番号付き SQL の履歴を検証し、既知の R0 DB だけを安全に引き継ぐ。

use crate::{backup_connection, db_failure, failure, StoreOptions};
use picocast_core::{clock, Result};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use sha2::{Digest, Sha256};
use std::path::Path;

struct Migration {
    version: i64,
    sql: &'static str,
}

const MIGRATIONS: &[Migration] = &[
    Migration {
        version: 1,
        sql: include_str!("../migrations/0001_r0.sql"),
    },
    Migration {
        version: 2,
        sql: include_str!("../migrations/0002_domain.sql"),
    },
];

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct MigrationRecord {
    pub version: i64,
    pub checksum: String,
    pub applied_at: clock::Timestamp,
}

pub(crate) fn history(connection: &Connection) -> Result<Vec<MigrationRecord>> {
    verify_history(connection)?;
    let mut statement = connection
        .prepare("SELECT version,checksum,applied_at FROM schema_migrations ORDER BY version")
        .map_err(db_failure)?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
            ))
        })
        .map_err(db_failure)?;
    rows.map(|row| {
        let (version, checksum, at) = row.map_err(db_failure)?;
        Ok(MigrationRecord {
            version,
            checksum,
            applied_at: clock::Timestamp::parse(&at)?,
        })
    })
    .collect()
}

pub(crate) fn latest_version() -> i64 {
    MIGRATIONS.last().map_or(0, |migration| migration.version)
}

fn checksum(sql: &str) -> String {
    // Git の改行変換だけで別の移行と判定しない。SQL 本文の変更はそのまま検出する。
    let normalized = sql.replace("\r\n", "\n");
    let digest = Sha256::digest(normalized.as_bytes());
    digest.iter().map(|value| format!("{value:02x}")).collect()
}

pub(crate) fn apply(
    connection: &mut Connection,
    backups: &Path,
    options: &StoreOptions,
) -> Result<()> {
    let pending = verify_history(connection)?;
    if pending == MIGRATIONS.len() {
        return Ok(());
    }
    std::fs::create_dir_all(backups).map_err(|error| {
        crate::io_failure(
            "E-STORE-BACKUP",
            "移行前のバックアップ先を作成できません。",
            "保存先の権限と空き容量を確認してください。",
            &error,
        )
    })?;
    let mut suffix = [0u8; 16];
    getrandom::fill(&mut suffix).map_err(|error| {
        tracing::error!(code="E-STORE-BACKUP", cause=%error, "移行バックアップの識別子を生成できませんでした");
        failure("E-STORE-BACKUP", "移行バックアップを準備できません。", "OS の乱数機能を確認してください。")
    })?;
    let suffix: String = suffix.iter().map(|value| format!("{value:02x}")).collect();
    backup_connection(
        connection,
        &backups.join(format!("before-v{}-{suffix}.db", latest_version())),
        options,
    )?;
    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(db_failure)?;
    // 他プロセスが先に移行した場合も、書込み権を確保してから再検証する。
    let pending = verify_history(&transaction)?;
    transaction.execute_batch("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL);").map_err(db_failure)?;
    if pending == 1 {
        // 台帳のない R0 の認証は verify_history 内の厳密な構造照合が前提。
        transaction.execute("INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (?1,?2,?3) ON CONFLICT(version) DO NOTHING", params![MIGRATIONS[0].version, checksum(MIGRATIONS[0].sql), clock::now_utc_iso()]).map_err(db_failure)?;
    }
    for migration in &MIGRATIONS[pending..] {
        transaction
            .execute_batch(migration.sql)
            .map_err(db_failure)?;
        transaction
            .execute(
                "INSERT INTO schema_migrations(version,checksum,applied_at) VALUES (?1,?2,?3)",
                params![
                    migration.version,
                    checksum(migration.sql),
                    clock::now_utc_iso()
                ],
            )
            .map_err(db_failure)?;
        transaction
            .pragma_update(None, "user_version", migration.version)
            .map_err(db_failure)?;
    }
    let broken: Option<String> = transaction
        .query_row(
            "SELECT \"table\" FROM pragma_foreign_key_check LIMIT 1",
            [],
            |row| row.get(0),
        )
        .optional()
        .map_err(db_failure)?;
    if broken.is_some() {
        return Err(invalid("移行後の参照整合性が一致しません。"));
    }
    transaction.commit().map_err(db_failure)
}

fn verify_history(connection: &Connection) -> Result<usize> {
    let version: i64 = connection
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .map_err(db_failure)?;
    if version > latest_version() || version < 0 {
        return Err(failure(
            "E-STORE-VERSION",
            "DB のバージョンに対応していません。",
            "DB に対応する新しいアプリを使用してください。",
        ));
    }
    let exists: bool = connection.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations')", [], |row| row.get(0)).map_err(db_failure)?;
    if !exists {
        match version {
            0 => {
                let count: i64 = connection
                    .query_row(
                        "SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'",
                        [],
                        |row| row.get(0),
                    )
                    .map_err(db_failure)?;
                if count != 0 {
                    return Err(invalid("未登録の DB 構造を検出しました。"));
                }
                return Ok(0);
            }
            1 => {
                verify_r0_schema(connection)?;
                return Ok(1);
            }
            _ => return Err(invalid("DB の移行履歴がありません。")),
        }
    }
    let mut statement = connection
        .prepare("SELECT version,checksum FROM schema_migrations ORDER BY version")
        .map_err(db_failure)?;
    let rows = statement
        .query_map([], |row| {
            Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
        })
        .map_err(db_failure)?;
    let mut count = 0;
    for record in rows {
        let (number, stored_checksum) = record.map_err(db_failure)?;
        let migration = MIGRATIONS
            .get(count)
            .ok_or_else(|| invalid("このアプリより新しい DB です。"))?;
        if migration.version != number || checksum(migration.sql) != stored_checksum {
            return Err(invalid(
                "適用済み SQL の番号またはチェックサムが一致しません。",
            ));
        }
        count += 1;
    }
    let expected_version = count
        .checked_sub(1)
        .and_then(|index| MIGRATIONS.get(index))
        .map_or(0, |migration| migration.version);
    if version != expected_version {
        return Err(invalid("DB の版と移行履歴が一致しません。"));
    }
    if count == 0 {
        return Err(invalid("移行履歴が空です。"));
    }
    Ok(count)
}

fn verify_r0_schema(connection: &Connection) -> Result<()> {
    let normalize = |sql: &str| {
        sql.split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .trim_end_matches(';')
            .to_owned()
    };
    let mut statement = connection.prepare("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY name").map_err(db_failure)?;
    let actual = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(db_failure)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(db_failure)?;
    let mut expected: Vec<_> = MIGRATIONS[0]
        .sql
        .split(';')
        .filter(|sql| !sql.trim().is_empty())
        .map(normalize)
        .collect();
    let mut actual: Vec<_> = actual.iter().map(|sql| normalize(sql)).collect();
    expected.sort();
    actual.sort();
    if actual != expected {
        return Err(invalid("既知の R0 DB と構造が一致しません。"));
    }
    Ok(())
}

fn invalid(message: &str) -> picocast_core::AppError {
    failure("E-STORE-MIGRATION", message, "対応するアプリ版と SQL ファイルを復元してください。既存 DB を削除せず、移行前バックアップを保管してください。")
}

#[cfg(test)]
#[path = "migrations_tests.rs"]
mod tests;
