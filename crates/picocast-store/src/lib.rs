//! チャンネルを明示する永続ストア。旧 Python データは参照しない。
#![allow(clippy::disallowed_methods)]

mod migrations;
pub mod repository;
mod secrets;

use std::path::Path;
use std::time::Duration;

use picocast_core::{clock, fsutil, ids::ChannelId, AppError, Result};
use rusqlite::{params, Connection, OptionalExtension};
use zeroize::Zeroizing;

pub use migrations::MigrationRecord;
pub use picocast_core::paths::{DataMode, StoragePolicy, StorePaths};
pub use secrets::MasterKey;

pub struct Store {
    connection: Connection,
    options: StoreOptions,
    storage_policy: StoragePolicy,
}

/// 調整可能な値は呼び出し側の設定正本から注入する。
#[derive(Debug, Clone)]
pub struct StoreOptions {
    pub busy_timeout: Duration,
    pub backup_pages_per_step: i32,
    pub backup_pause: Duration,
}

impl StoreOptions {
    fn validate(&self) -> Result<()> {
        if self.busy_timeout.is_zero()
            || self.backup_pages_per_step <= 0
            || self.backup_pause.is_zero()
        {
            return Err(failure(
                "E-STORE-OPTIONS",
                "DB の待機・バックアップ設定が不正です。",
                "待機時間とバックアップ単位を正の値で設定してください。",
            ));
        }
        Ok(())
    }
}

impl Store {
    /// 破損時は停止する。既存ファイルを空の DB に置き換えない。
    pub fn open(paths: &StorePaths, options: StoreOptions) -> Result<Self> {
        Self::open_with_policy(paths, options, &StoragePolicy::default())
    }

    pub fn open_with_policy(
        paths: &StorePaths,
        options: StoreOptions,
        policy: &StoragePolicy,
    ) -> Result<Self> {
        options.validate()?;
        paths.validate_storage(policy)?;
        std::fs::create_dir_all(&paths.root).map_err(|error| {
            io_failure(
                "E-STORE-OPEN",
                "保存先を作成できません。",
                "保存先の書き込み権限を確認してください。",
                &error,
            )
        })?;
        let mut connection = Connection::open(&paths.database).map_err(db_failure)?;
        connection
            .busy_timeout(options.busy_timeout)
            .map_err(db_failure)?;
        check_integrity(&connection)?;
        connection
            .pragma_update(None, "foreign_keys", true)
            .map_err(db_failure)?;
        let journal: String = connection
            .query_row("PRAGMA journal_mode=WAL", [], |row| row.get(0))
            .map_err(db_failure)?;
        if journal != "wal" {
            return Err(failure(
                "E-STORE-OPEN",
                "WAL モードを有効にできません。",
                "ローカルディスクの保存先を指定してください。",
            ));
        }
        migrations::apply(&mut connection, &paths.backups, &options)?;
        check_integrity(&connection)?;
        Ok(Self {
            connection,
            options,
            storage_policy: policy.clone(),
        })
    }

    pub fn schema_version(&self) -> Result<i64> {
        self.connection
            .pragma_query_value(None, "user_version", |row| row.get(0))
            .map_err(db_failure)
    }

    pub fn migration_history(&self) -> Result<Vec<MigrationRecord>> {
        migrations::history(&self.connection)
    }

    pub fn create_channel(&self, channel_id: &ChannelId, name: &str) -> Result<()> {
        validate_identity(name)?;
        self.connection
            .execute(
                "INSERT INTO channels(channel_id,name,created_at,updated_at) VALUES (?1,?2,?3,?3)",
                params![channel_id.as_str(), name, clock::now_utc_iso()],
            )
            .map_err(db_failure)?;
        Ok(())
    }

    pub fn channel_name(&self, channel_id: &ChannelId) -> Result<Option<String>> {
        self.connection
            .query_row(
                "SELECT name FROM channels WHERE channel_id=?1 AND archived_at IS NULL",
                [channel_id.as_str()],
                |row| row.get(0),
            )
            .optional()
            .map_err(db_failure)
    }

    /// アーカイブ済みも含め、管理画面に必要なチャンネルを型付きで列挙する。
    pub fn channels(&self) -> Result<Vec<repository::Channel>> {
        repository::channels(&self.connection)
    }

    pub fn delete_channel(&self, channel_id: &ChannelId) -> Result<bool> {
        Ok(self
            .connection
            .execute(
                "UPDATE channels SET archived_at=?2,updated_at=?2 WHERE channel_id=?1 AND archived_at IS NULL",
                params![channel_id.as_str(), clock::now_utc_iso()],
            )
            .map_err(db_failure)?
            > 0)
    }

    pub fn set_setting(
        &self,
        channel_id: &ChannelId,
        key: &str,
        value: &serde_json::Value,
    ) -> Result<()> {
        self.require_channel(channel_id)?;
        validate_identity(key)?;
        let json = serde_json::to_string(value).map_err(|_| {
            failure(
                "E-STORE-SETTING",
                "設定を保存形式に変換できません。",
                "設定値の形式を確認してください。",
            )
        })?;
        self.connection.execute("INSERT INTO channel_settings(channel_id,key,value_json,updated_at) VALUES (?1,?2,?3,?4) ON CONFLICT(channel_id,key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at", params![channel_id.as_str(), key, json, clock::now_utc_iso()]).map_err(db_failure)?;
        Ok(())
    }

    pub fn setting(&self, channel_id: &ChannelId, key: &str) -> Result<Option<serde_json::Value>> {
        self.require_channel(channel_id)?;
        validate_identity(key)?;
        let json: Option<String> = self
            .connection
            .query_row(
                "SELECT value_json FROM channel_settings WHERE channel_id=?1 AND key=?2",
                params![channel_id.as_str(), key],
                |row| row.get(0),
            )
            .optional()
            .map_err(db_failure)?;
        json.map(|value| {
            serde_json::from_str(&value).map_err(|_| {
                failure(
                    "E-STORE-SETTING",
                    "保存された設定の形式が壊れています。",
                    "バックアップを復元してください。",
                )
            })
        })
        .transpose()
    }

    pub fn delete_setting(&self, channel_id: &ChannelId, key: &str) -> Result<bool> {
        self.require_channel(channel_id)?;
        validate_identity(key)?;
        Ok(self
            .connection
            .execute(
                "DELETE FROM channel_settings WHERE channel_id=?1 AND key=?2",
                params![channel_id.as_str(), key],
            )
            .map_err(db_failure)?
            > 0)
    }

    pub fn save_secret(
        &self,
        channel_id: &ChannelId,
        secret_type: &str,
        value: &[u8],
        master_key: &MasterKey,
    ) -> Result<()> {
        self.require_channel(channel_id)?;
        validate_identity(secret_type)?;
        let (nonce, encrypted) = master_key.encrypt(channel_id, secret_type, value)?;
        self.connection.execute("INSERT INTO secrets(channel_id,secret_type,nonce,encrypted_value,key_version,updated_at) VALUES (?1,?2,?3,?4,2,?5) ON CONFLICT(channel_id,secret_type) DO UPDATE SET nonce=excluded.nonce,encrypted_value=excluded.encrypted_value,key_version=excluded.key_version,updated_at=excluded.updated_at", params![channel_id.as_str(), secret_type, nonce.as_slice(), encrypted, clock::now_utc_iso()]).map_err(db_failure)?;
        Ok(())
    }

    pub fn load_secret(
        &self,
        channel_id: &ChannelId,
        secret_type: &str,
        master_key: &MasterKey,
    ) -> Result<Option<Zeroizing<Vec<u8>>>> {
        self.require_channel(channel_id)?;
        validate_identity(secret_type)?;
        let record: Option<(Vec<u8>, Vec<u8>, i64)> = self.connection.query_row("SELECT nonce,encrypted_value,key_version FROM secrets WHERE channel_id=?1 AND secret_type=?2", params![channel_id.as_str(), secret_type], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?))).optional().map_err(db_failure)?;
        record
            .map(|(nonce, encrypted, version)| {
                if version != 2 {
                    return Err(failure(
                        "E-SECRET-VERSION",
                        "認証情報の暗号形式に対応していません。",
                        "対応するバージョンで取り込みを行ってください。",
                    ));
                }
                master_key.decrypt(channel_id, secret_type, &nonce, &encrypted)
            })
            .transpose()
    }

    pub fn delete_secret(&self, channel_id: &ChannelId, secret_type: &str) -> Result<bool> {
        self.require_channel(channel_id)?;
        validate_identity(secret_type)?;
        Ok(self
            .connection
            .execute(
                "DELETE FROM secrets WHERE channel_id=?1 AND secret_type=?2",
                params![channel_id.as_str(), secret_type],
            )
            .map_err(db_failure)?
            > 0)
    }

    /// SQLite のオンラインバックアップ API で未 checkpoint の WAL も含める。
    pub fn backup_to(&self, destination: &Path) -> Result<()> {
        picocast_core::paths::validate_storage(destination, &self.storage_policy)?;
        backup_connection(&self.connection, destination, &self.options)
    }

    pub fn repository(&self, channel_id: &ChannelId) -> Result<repository::ChannelRepository<'_>> {
        self.require_channel(channel_id)?;
        Ok(repository::ChannelRepository {
            connection: &self.connection,
            channel_id: channel_id.clone(),
        })
    }

    pub fn global_repository(&self) -> repository::GlobalRepository<'_> {
        repository::GlobalRepository {
            connection: &self.connection,
        }
    }

    fn require_channel(&self, channel_id: &ChannelId) -> Result<()> {
        if self.channel_name(channel_id)?.is_none() {
            return Err(failure(
                "E-STORE-CHANNEL",
                "指定チャンネルが登録されていません。",
                "チャンネルを登録してから操作してください。",
            ));
        }
        Ok(())
    }
}

fn backup_connection(
    source: &Connection,
    destination: &Path,
    options: &StoreOptions,
) -> Result<()> {
    // 既存バックアップを上書きしない。API はこの保存層だけが所有する。
    let reservation = fsutil::reserve_new_file(destination)?;
    drop(reservation);
    let mut target =
        Connection::open_with_flags(destination, rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE)
            .map_err(db_failure)?;
    let backup = rusqlite::backup::Backup::new(source, &mut target).map_err(db_failure)?;
    backup
        .run_to_completion(options.backup_pages_per_step, options.backup_pause, None)
        .map_err(db_failure)?;
    drop(backup);
    check_integrity(&target)
}

fn check_integrity(connection: &Connection) -> Result<()> {
    let mut statement = connection
        .prepare("PRAGMA integrity_check")
        .map_err(db_failure)?;
    let mut rows = statement.query([]).map_err(db_failure)?;
    let mut count = 0;
    while let Some(row) = rows.next().map_err(db_failure)? {
        let status: String = row.get(0).map_err(db_failure)?;
        if status != "ok" {
            return Err(failure(
                "E-STORE-CORRUPT",
                "DB の破損を検出しました。",
                "アプリを停止し、バックアップを復元してください。",
            ));
        }
        count += 1;
    }
    if count != 1 {
        return Err(failure(
            "E-STORE-CORRUPT",
            "DB の整合性を確認できません。",
            "バックアップを復元してください。",
        ));
    }
    Ok(())
}

fn validate_identity(value: &str) -> Result<()> {
    if value.trim().is_empty() || value.contains('\0') {
        return Err(failure(
            "E-STORE-IDENTITY",
            "チャンネルまたはキー名が不正です。",
            "空ではない識別子を指定してください。",
        ));
    }
    Ok(())
}

fn db_failure(error: rusqlite::Error) -> AppError {
    // SQL 文や bind 値を記録しない。SQLite の分類だけを原因として残す。
    let classification = match error {
        rusqlite::Error::SqliteFailure(code, _) => format!("{:?}", code.code),
        _ => "conversion_or_query".to_owned(),
    };
    tracing::error!(code = "E-STORE-DB", cause = %classification, "DB 操作が失敗しました");
    AppError::new(
        "E-STORE-DB",
        "DB 操作に失敗しました。",
        "保存先の権限・空き容量・バックアップを確認してください。",
    )
}

pub(crate) fn failure(code: &str, message: &str, fix: &str) -> AppError {
    tracing::error!(code, cause = message, "保存層の操作が失敗しました");
    AppError::new(code, message, fix)
}

pub(crate) fn io_failure(code: &str, message: &str, fix: &str, error: &std::io::Error) -> AppError {
    tracing::error!(code, cause = ?error.kind(), os_code = ?error.raw_os_error(), "保存層のファイル操作が失敗しました");
    AppError::new(code, message, fix)
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    fn channel(value: &str) -> ChannelId {
        ChannelId::new(value).unwrap()
    }

    pub(super) fn options() -> StoreOptions {
        StoreOptions {
            busy_timeout: Duration::from_secs(5),
            backup_pages_per_step: 128,
            backup_pause: Duration::from_millis(10),
        }
    }

    pub(super) fn fixture() -> (tempfile::TempDir, StorePaths, Store) {
        let temporary = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        let store = Store::open(&paths, options()).unwrap();
        (temporary, paths, store)
    }

    #[test]
    fn settings_are_scoped_and_persistent() {
        let (_temporary, paths, store) = fixture();
        store.create_channel(&channel("one"), "一").unwrap();
        store.create_channel(&channel("two"), "二").unwrap();
        store
            .set_setting(&channel("one"), "speed", &serde_json::json!(1.2))
            .unwrap();
        assert_eq!(store.setting(&channel("two"), "speed").unwrap(), None);
        assert!(store
            .set_setting(&channel("missing"), "speed", &serde_json::json!(1))
            .is_err());
        drop(store);
        let reopened = Store::open(&paths, options()).unwrap();
        assert_eq!(
            reopened.setting(&channel("one"), "speed").unwrap(),
            Some(serde_json::json!(1.2))
        );
    }

    #[test]
    fn backup_includes_wal_and_refuses_existing_destination() {
        let (_temporary, paths, store) = fixture();
        store
            .connection
            .pragma_update(None, "wal_autocheckpoint", 0)
            .unwrap();
        store
            .create_channel(&channel("wal"), "未 checkpoint")
            .unwrap();
        let destination = paths.backups.join("manual.db");
        store.backup_to(&destination).unwrap();
        let restored = Connection::open(&destination).unwrap();
        let name: String = restored
            .query_row(
                "SELECT name FROM channels WHERE channel_id='wal'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(name, "未 checkpoint");
        assert!(store.backup_to(&destination).is_err());
    }

    #[test]
    fn corrupted_database_is_not_replaced() {
        let temporary = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        std::fs::create_dir_all(&paths.root).unwrap();
        let corrupted = b"broken database";
        fsutil::atomic_write(&paths.database, corrupted).unwrap();
        assert!(Store::open(&paths, options()).is_err());
        assert_eq!(std::fs::read(&paths.database).unwrap(), corrupted);
    }

    #[test]
    fn secrets_authenticate_channel_and_type() {
        let (_temporary, _paths, store) = fixture();
        store.create_channel(&channel("one"), "一").unwrap();
        store.create_channel(&channel("two"), "二").unwrap();
        let key = MasterKey::generate().unwrap();
        store
            .save_secret(&channel("one"), "api", b"sample", &key)
            .unwrap();
        assert_eq!(
            store
                .load_secret(&channel("one"), "api", &key)
                .unwrap()
                .unwrap()
                .as_slice(),
            b"sample"
        );
        store
            .connection
            .execute(
                "UPDATE secrets SET channel_id='two' WHERE channel_id='one'",
                [],
            )
            .unwrap();
        assert!(store.load_secret(&channel("two"), "api", &key).is_err());
    }

    #[test]
    fn production_and_development_paths_are_separate() {
        let temporary = tempfile::tempdir().unwrap();
        let production = StorePaths::new(temporary.path(), DataMode::Production).unwrap();
        let development = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        assert_ne!(production.database, development.database);
        assert_ne!(production.master_key, development.master_key);
    }

    #[test]
    fn unsafe_path_is_rejected_without_creating_database() {
        let temporary = tempfile::tempdir().unwrap();
        let paths =
            StorePaths::new(&temporary.path().join("Dropbox"), DataMode::Development).unwrap();
        let error = Store::open(&paths, options()).err().unwrap();
        assert_eq!(error.code, "E-STORE-UNSAFE-PATH");
        assert!(!paths.root.exists());
        let policy = StoragePolicy {
            allow_cloud_sync: true,
            ..Default::default()
        };
        let store = Store::open_with_policy(&paths, options(), &policy).unwrap();
        assert_eq!(
            store.schema_version().unwrap(),
            migrations::latest_version()
        );
    }

    #[test]
    fn custom_sync_root_and_backup_are_guarded() {
        let (temporary, _paths, store) = fixture();
        let synchronized = temporary.path().join("custom-sync");
        let paths = StorePaths::new(&synchronized, DataMode::Development).unwrap();
        let policy = StoragePolicy {
            sync_roots: vec![synchronized],
            ..Default::default()
        };
        assert_eq!(
            Store::open_with_policy(&paths, options(), &policy)
                .err()
                .unwrap()
                .code,
            "E-STORE-UNSAFE-PATH"
        );
        let backup = temporary.path().join("OneDrive").join("backup.db");
        assert_eq!(
            store.backup_to(&backup).unwrap_err().code,
            "E-STORE-UNSAFE-PATH"
        );
        assert!(!backup.exists());
    }

    #[cfg(windows)]
    #[test]
    fn unc_path_is_rejected_before_network_access() {
        let paths = StorePaths::new(
            Path::new(r"\\picocast-invalid-server\share\data"),
            DataMode::Development,
        )
        .unwrap();
        let error = Store::open(&paths, options()).err().unwrap();
        assert_eq!(error.code, "E-STORE-UNSAFE-PATH");
    }

    #[test]
    fn unknown_database_is_not_implicitly_adopted() {
        let temporary = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        std::fs::create_dir_all(&paths.root).unwrap();
        let connection = Connection::open(&paths.database).unwrap();
        connection
            .execute_batch(
                "CREATE TABLE channels(marker TEXT); INSERT INTO channels VALUES ('keep');",
            )
            .unwrap();
        drop(connection);
        assert!(Store::open(&paths, options()).is_err());
        let connection = Connection::open(&paths.database).unwrap();
        let version: i64 = connection
            .pragma_query_value(None, "user_version", |row| row.get(0))
            .unwrap();
        assert_eq!(version, 0);
        let marker: String = connection
            .query_row("SELECT marker FROM channels", [], |row| row.get(0))
            .unwrap();
        assert_eq!(marker, "keep");
        assert!(!paths.backups.exists());
    }
}
