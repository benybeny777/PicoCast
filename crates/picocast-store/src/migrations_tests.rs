#![cfg(test)]
#![allow(clippy::unwrap_used)]

use super::*;
use crate::{DataMode, MasterKey, Store, StorePaths};
use picocast_core::ChannelId;

fn r0_fixture() -> (tempfile::TempDir, StorePaths, Connection) {
    let temporary = tempfile::tempdir().unwrap();
    let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
    std::fs::create_dir_all(&paths.root).unwrap();
    let connection = Connection::open(&paths.database).unwrap();
    connection.execute_batch(MIGRATIONS[0].sql).unwrap();
    connection
        .pragma_update(None, "user_version", MIGRATIONS[0].version)
        .unwrap();
    connection
        .execute(
            "INSERT INTO channels VALUES('one','一','2026-10-16T00:00:00Z')",
            [],
        )
        .unwrap();
    (temporary, paths, connection)
}

#[test]
fn known_r0_migrates_settings_and_authenticated_secrets_without_loss() {
    let (_temporary, paths, connection) = r0_fixture();
    let channel = ChannelId::new("one").unwrap();
    let key = MasterKey::generate().unwrap();
    let (nonce, ciphertext) = key.encrypt(&channel, "api", b"retained-secret").unwrap();
    connection
        .execute(
            "INSERT INTO settings VALUES('one','value','{\"保持\":true}','2026-10-16T00:00:00Z')",
            [],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO encrypted_secrets VALUES('one','api',?1,?2,2,'2026-10-16T00:00:00Z')",
            params![nonce.as_slice(), ciphertext],
        )
        .unwrap();
    drop(connection);
    let store = Store::open(&paths, crate::tests::options()).unwrap();
    assert_eq!(store.schema_version().unwrap(), latest_version());
    assert_eq!(
        store.setting(&channel, "value").unwrap(),
        Some(serde_json::json!({"保持":true}))
    );
    assert_eq!(
        store
            .load_secret(&channel, "api", &key)
            .unwrap()
            .unwrap()
            .as_slice(),
        b"retained-secret"
    );
    let history = store.migration_history().unwrap();
    assert_eq!(
        history
            .iter()
            .map(|record| record.checksum.len())
            .collect::<Vec<_>>(),
        vec![64, 64]
    );
    let backup_path = std::fs::read_dir(&paths.backups)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let backup = Connection::open(&backup_path).unwrap();
    assert_eq!(
        backup
            .pragma_query_value(None, "user_version", |row| row.get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        backup
            .query_row(
                "SELECT value_json FROM settings WHERE key='value'",
                [],
                |row| row.get::<_, String>(0)
            )
            .unwrap(),
        "{\"保持\":true}"
    );
    drop(backup);
    drop(store);
    Store::open(&paths, crate::tests::options()).unwrap();
    assert_eq!(
        std::fs::read_dir(&paths.backups).unwrap().count(),
        1,
        "再起動で移行を繰り返さない"
    );
}

#[test]
fn checksum_tamper_and_incomplete_history_stop_reopen() {
    let (_temporary, paths, store) = crate::tests::fixture();
    store
        .connection
        .execute(
            "UPDATE schema_migrations SET checksum='modified' WHERE version=1",
            [],
        )
        .unwrap();
    drop(store);
    assert_eq!(
        Store::open(&paths, crate::tests::options())
            .err()
            .unwrap()
            .code,
        "E-STORE-MIGRATION"
    );
    let connection = Connection::open(&paths.database).unwrap();
    connection
        .execute(
            "UPDATE schema_migrations SET checksum=?1 WHERE version=1",
            [checksum(MIGRATIONS[0].sql)],
        )
        .unwrap();
    connection
        .execute("DELETE FROM schema_migrations WHERE version=1", [])
        .unwrap();
    drop(connection);
    assert_eq!(
        Store::open(&paths, crate::tests::options())
            .err()
            .unwrap()
            .code,
        "E-STORE-MIGRATION"
    );
}

#[test]
fn unknown_r0_structure_is_never_automatically_authenticated() {
    let (_temporary, paths, connection) = r0_fixture();
    connection
        .execute("ALTER TABLE channels ADD COLUMN unknown TEXT", [])
        .unwrap();
    drop(connection);
    assert_eq!(
        Store::open(&paths, crate::tests::options())
            .err()
            .unwrap()
            .code,
        "E-STORE-MIGRATION"
    );
    let connection = Connection::open(&paths.database).unwrap();
    let ledger_exists: bool = connection
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='schema_migrations')",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(!ledger_exists);
    assert!(!paths.backups.exists());
}

#[test]
fn failing_domain_migration_rolls_back_all_changes_and_keeps_backup() {
    let (_temporary, paths, connection) = r0_fixture();
    connection
        .execute(
            "INSERT INTO settings VALUES('one','broken','invalid-json','2026-10-16T00:00:00Z')",
            [],
        )
        .unwrap();
    drop(connection);
    assert!(Store::open(&paths, crate::tests::options()).is_err());
    let connection = Connection::open(&paths.database).unwrap();
    assert_eq!(
        connection
            .pragma_query_value(None, "user_version", |row| row.get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        connection
            .query_row(
                "SELECT value_json FROM settings WHERE key='broken'",
                [],
                |row| row.get::<_, String>(0)
            )
            .unwrap(),
        "invalid-json"
    );
    let ledger_exists: bool = connection
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='schema_migrations')",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(!ledger_exists);
    assert_eq!(std::fs::read_dir(&paths.backups).unwrap().count(), 1);
}
