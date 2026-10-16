//! パスフレーズで保護した可搬バックアップ。生キー・パスフレーズは表示しない。
use crate::repository::{AppSetting, AppSettingKey, Asset, Notification, NotificationKey};
use crate::{
    db_failure, failure, imports, io_failure, repository, MasterKey, Store, StoreOptions,
    StorePaths,
};
use argon2::{Algorithm, Argon2, Params, Version};
use picocast_core::{
    clock::{self, Timestamp},
    fsutil,
    paths::StoragePolicy,
    ChannelId, Result,
};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};
use zeroize::{Zeroize, Zeroizing};

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KdfOptions {
    pub memory_kib: u32,
    pub iterations: u32,
    pub parallelism: u32,
}

/// 調整値は設定正本から明示注入する。復元時の資源上限も外部headerを信用しない。
pub struct PortableOptions {
    pub kdf: KdfOptions,
    pub max_kdf: KdfOptions,
    pub minimum_passphrase_bytes: usize,
    pub chunk_bytes: usize,
    pub max_header_bytes: u64,
    pub max_manifest_bytes: usize,
    pub max_assets: usize,
    pub max_total_bytes: u64,
    pub offsite_policy: StoragePolicy,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PortableReport {
    pub channels: usize,
    pub assets: usize,
    pub secrets: usize,
    pub total_bytes: u64,
    pub offsite_verified: bool,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Metadata {
    version: u32,
    kdf: KdfOptions,
    salt: [u8; 16],
    bundle_id: [u8; 16],
    chunk_bytes: usize,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Header {
    metadata: Metadata,
    nonce: [u8; 12],
    manifest: Vec<u8>,
}
#[derive(PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FileEntry {
    sha256: String,
    ext: String,
    bytes: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    source_master: Vec<u8>,
    schema_version: i64,
    source_counts: BTreeMap<String, usize>,
    database: FileEntry,
    assets: Vec<FileEntry>,
}
impl Drop for Manifest {
    fn drop(&mut self) {
        self.source_master.zeroize();
    }
}

fn failed() -> picocast_core::AppError {
    failure("E-BACKUP-PORTABLE","暗号化バックアップの保存・認証・復元に失敗しました。","パスフレーズ、元DBとキー、容量、素材目録を確認し、既存の保存先を上書きせず再実行してください。")
}
fn io(error: std::io::Error) -> picocast_core::AppError {
    io_failure(
        "E-BACKUP-PORTABLE",
        "バックアップのファイル操作に失敗しました。",
        "保存先・権限・空き容量を確認してください。",
        &error,
    )
}
fn context(metadata: &Metadata) -> Result<String> {
    Ok(imports::digest_bytes(
        &serde_json::to_vec(metadata).map_err(|_| failed())?,
    ))
}
fn identity() -> Result<ChannelId> {
    ChannelId::new("picocast-portable-backup")
}
fn params_valid(kdf: KdfOptions, options: &PortableOptions) -> Result<Params> {
    if kdf.memory_kib > options.max_kdf.memory_kib
        || kdf.iterations > options.max_kdf.iterations
        || kdf.parallelism > options.max_kdf.parallelism
    {
        return Err(failed());
    }
    Params::new(kdf.memory_kib, kdf.iterations, kdf.parallelism, Some(32)).map_err(|_| failed())
}
fn derive(passphrase: &[u8], metadata: &Metadata, options: &PortableOptions) -> Result<MasterKey> {
    if options.minimum_passphrase_bytes == 0
        || passphrase.len() < options.minimum_passphrase_bytes
        || options.chunk_bytes == 0
        || options.chunk_bytes > u32::MAX as usize - 16
        || metadata.chunk_bytes == 0
        || metadata.chunk_bytes > options.chunk_bytes
        || metadata.version != 1
        || options.max_manifest_bytes == 0
        || options.max_assets == 0
        || options.max_total_bytes == 0
    {
        return Err(failed());
    }
    let parameters = params_valid(metadata.kdf, options)?;
    let mut key = Zeroizing::new([0u8; 32]);
    Argon2::new(Algorithm::Argon2id, Version::V0x13, parameters)
        .hash_password_into(passphrase, &metadata.salt, key.as_mut())
        .map_err(|_| failed())?;
    MasterKey::from_portable_material(key.as_slice())
}

fn table_counts(connection: &Connection) -> Result<BTreeMap<String, usize>> {
    let mut statement=connection.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*' ORDER BY name").map_err(db_failure)?;
    let names = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(db_failure)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(db_failure)?;
    let mut counts = BTreeMap::new();
    for name in names {
        let quoted = name.replace('"', "\"\"");
        let count: i64 = connection
            .query_row(&format!("SELECT COUNT(*) FROM \"{quoted}\""), [], |row| {
                row.get(0)
            })
            .map_err(db_failure)?;
        counts.insert(name, usize::try_from(count).map_err(|_| failed())?);
    }
    Ok(counts)
}

fn asset_manifest(connection: &Connection) -> Result<Vec<FileEntry>> {
    repository::GlobalRepository { connection }
        .list::<Asset>()?
        .into_iter()
        .map(|asset| {
            Ok(FileEntry {
                sha256: asset.sha256,
                ext: asset.ext,
                bytes: u64::try_from(asset.bytes).map_err(|_| failed())?,
            })
        })
        .collect()
}

fn new_target(
    target: &Path,
    source_root: Option<&Path>,
    policy: &StoragePolicy,
) -> Result<PathBuf> {
    picocast_core::paths::validate_storage(target, policy)?;
    if target.try_exists().map_err(io)? {
        return Err(failed());
    }
    let parent = target
        .parent()
        .ok_or_else(failed)?
        .canonicalize()
        .map_err(io)?;
    let resolved = parent.join(target.file_name().ok_or_else(failed)?);
    if let Some(source) = source_root {
        let source = source.canonicalize().map_err(io)?;
        if source.starts_with(&resolved) || resolved.starts_with(&source) {
            return Err(failed());
        }
    }
    Ok(parent)
}

fn regular_file(path: &Path) -> Result<std::fs::Metadata> {
    let metadata = std::fs::symlink_metadata(path).map_err(io)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(failed());
    }
    Ok(metadata)
}

fn encrypt_file(
    source: &Path,
    destination: &Path,
    entry: &FileEntry,
    key: &MasterKey,
    context: &str,
    role: &str,
    chunk: usize,
) -> Result<()> {
    let before = regular_file(source)?;
    if before.len() != entry.bytes || imports::digest_file(source)? != entry.sha256 {
        return Err(failed());
    }
    let mut input = std::fs::File::open(source).map_err(io)?;
    let mut output = fsutil::new_file_writer(destination)?;
    let mut buffer = Zeroizing::new(vec![0u8; chunk]);
    let mut index = 0u64;
    let mut total = 0u64;
    loop {
        let length = input.read(&mut buffer).map_err(io)?;
        let (nonce, ciphertext) = key.encrypt(
            &identity()?,
            &format!("{context}:{role}:{index}:{}", entry.bytes),
            &buffer[..length],
        )?;
        let size = u32::try_from(ciphertext.len()).map_err(|_| failed())?;
        output.write_all(&size.to_be_bytes()).map_err(io)?;
        output.write_all(&nonce).map_err(io)?;
        output.write_all(&ciphertext).map_err(io)?;
        total = total.checked_add(length as u64).ok_or_else(failed)?;
        if total > entry.bytes {
            return Err(failed());
        }
        if total == entry.bytes {
            break;
        }
        if length == 0 {
            return Err(failed());
        }
        index = index.checked_add(1).ok_or_else(failed)?;
    }
    output.finish()?;
    let after = regular_file(source)?;
    if before.len() != after.len()
        || before.modified().map_err(io)? != after.modified().map_err(io)?
        || imports::digest_file(source)? != entry.sha256
    {
        return Err(failed());
    }
    Ok(())
}

fn decrypt_file(
    source: &Path,
    destination: &Path,
    entry: &FileEntry,
    key: &MasterKey,
    context: &str,
    role: &str,
    chunk: usize,
) -> Result<()> {
    regular_file(source)?;
    let mut input = std::fs::File::open(source).map_err(io)?;
    let mut output = fsutil::new_file_writer(destination)?;
    let mut total = 0u64;
    let mut index = 0u64;
    loop {
        let mut length = [0u8; 4];
        input.read_exact(&mut length).map_err(io)?;
        let length = u32::from_be_bytes(length) as usize;
        if length < 16 || length > chunk.checked_add(16).ok_or_else(failed)? {
            return Err(failed());
        }
        let mut nonce = [0u8; 12];
        input.read_exact(&mut nonce).map_err(io)?;
        let mut ciphertext = vec![0u8; length];
        input.read_exact(&mut ciphertext).map_err(io)?;
        let plain = key.decrypt(
            &identity()?,
            &format!("{context}:{role}:{index}:{}", entry.bytes),
            &nonce,
            &ciphertext,
        )?;
        total = total.checked_add(plain.len() as u64).ok_or_else(failed)?;
        if total > entry.bytes {
            return Err(failed());
        }
        output.write_all(&plain).map_err(io)?;
        if total == entry.bytes {
            let mut extra = [0u8; 1];
            if input.read(&mut extra).map_err(io)? != 0 {
                return Err(failed());
            }
            break;
        }
        if plain.is_empty() {
            return Err(failed());
        }
        index = index.checked_add(1).ok_or_else(failed)?;
    }
    output.finish()?;
    if imports::digest_file(destination)? != entry.sha256 {
        return Err(failed());
    }
    Ok(())
}

fn read_header(
    bundle: &Path,
    passphrase: &[u8],
    options: &PortableOptions,
) -> Result<(Header, Manifest, MasterKey, String)> {
    if !bundle.is_absolute() {
        return Err(failed());
    }
    let metadata = std::fs::symlink_metadata(bundle).map_err(io)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(failed());
    }
    let path = bundle.join("header.json");
    if regular_file(&path)?.len() > options.max_header_bytes {
        return Err(failed());
    }
    let header: Header =
        serde_json::from_slice(&std::fs::read(path).map_err(io)?).map_err(|_| failed())?;
    if header.manifest.len()
        > options
            .max_manifest_bytes
            .checked_add(16)
            .ok_or_else(failed)?
    {
        return Err(failed());
    }
    let key = derive(passphrase, &header.metadata, options)?;
    let context = context(&header.metadata)?;
    let plaintext = key.decrypt(
        &identity()?,
        &format!("{context}:manifest"),
        &header.nonce,
        &header.manifest,
    )?;
    let manifest: Manifest = serde_json::from_slice(&plaintext).map_err(|_| failed())?;
    if manifest.assets.len() > options.max_assets || manifest.source_master.len() != 32 {
        return Err(failed());
    }
    let mut total = manifest.database.bytes;
    for asset in &manifest.assets {
        total = total.checked_add(asset.bytes).ok_or_else(failed)?;
        fsutil::content_asset_path(bundle, &asset.sha256, &asset.ext)?;
    }
    if total > options.max_total_bytes {
        return Err(failed());
    }
    Ok((header, manifest, key, context))
}

fn rewrap_secrets(
    connection: &Connection,
    old: &MasterKey,
    new: Option<&MasterKey>,
) -> Result<usize> {
    let mut statement = connection
        .prepare("SELECT channel_id,secret_type,nonce,encrypted_value,key_version FROM secrets")
        .map_err(db_failure)?;
    let records = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Vec<u8>>(2)?,
                row.get::<_, Vec<u8>>(3)?,
                row.get::<_, i64>(4)?,
            ))
        })
        .map_err(db_failure)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(db_failure)?;
    for (id, kind, nonce, ciphertext, version) in &records {
        if *version != 2 {
            return Err(failed());
        }
        let id = ChannelId::new(id.clone())?;
        let plaintext = old.decrypt(&id, kind, nonce, ciphertext)?;
        let Some(new) = new else { continue };
        let (nonce, ciphertext) = new.encrypt(&id, kind, &plaintext)?;
        connection.execute("UPDATE secrets SET nonce=?1,encrypted_value=?2 WHERE channel_id=?3 AND secret_type=?4",params![nonce.as_slice(),ciphertext,id.as_str(),kind]).map_err(db_failure)?;
        let (nonce, ciphertext): (Vec<u8>, Vec<u8>) = connection
            .query_row(
                "SELECT nonce,encrypted_value FROM secrets WHERE channel_id=?1 AND secret_type=?2",
                params![id.as_str(), kind],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .map_err(db_failure)?;
        if new.decrypt(&id, kind, &nonce, &ciphertext)?.as_slice() != plaintext.as_slice() {
            return Err(failed());
        }
    }
    Ok(records.len())
}

impl Store {
    pub fn export_portable(
        &self,
        paths: &StorePaths,
        source_key: &MasterKey,
        passphrase: &[u8],
        destination: &Path,
        offsite: Option<&Path>,
        options: &PortableOptions,
    ) -> Result<PortableReport> {
        if self
            .connection
            .path()
            .map(Path::new)
            .ok_or_else(failed)?
            .canonicalize()
            .map_err(io)?
            != paths.database.canonicalize().map_err(io)?
        {
            return Err(failed());
        }
        let parent = new_target(destination, Some(&paths.root), &StoragePolicy::default())?;
        let work = tempfile::Builder::new()
            .prefix("portable-work-")
            .tempdir_in(&parent)
            .map_err(io)?;
        let snapshot = paths.relocated(work.path())?;
        self.backup_to(&snapshot.database)?;
        let db = imports::open_legacy(&snapshot.database)?;
        imports::verify_database_snapshots(&db, source_key)?;
        // source keyの適合を検証するだけで元DBは更新しない。
        let secret_count = rewrap_secrets(&db, source_key, None)?;
        let source_counts = table_counts(&db)?;
        let schema_version = db
            .pragma_query_value(None, "user_version", |row| row.get(0))
            .map_err(db_failure)?;
        let assets = asset_manifest(&db)?;
        let channels = *source_counts.get("channels").ok_or_else(failed)?;
        drop(db);
        if assets.len() > options.max_assets {
            return Err(failed());
        }
        let manifest = Manifest {
            source_master: source_key.portable_material().to_vec(),
            schema_version,
            source_counts,
            database: FileEntry {
                sha256: imports::digest_file(&snapshot.database)?,
                ext: "db".into(),
                bytes: regular_file(&snapshot.database)?.len(),
            },
            assets,
        };
        let total = manifest
            .assets
            .iter()
            .try_fold(manifest.database.bytes, |total, asset| {
                total.checked_add(asset.bytes).ok_or_else(failed)
            })?;
        if total > options.max_total_bytes {
            return Err(failed());
        }
        let mut salt = [0u8; 16];
        let mut bundle_id = [0u8; 16];
        getrandom::fill(&mut salt).map_err(|_| failed())?;
        getrandom::fill(&mut bundle_id).map_err(|_| failed())?;
        let metadata = Metadata {
            version: 1,
            kdf: options.kdf,
            salt,
            bundle_id,
            chunk_bytes: options.chunk_bytes,
        };
        let key = derive(passphrase, &metadata, options)?;
        let context = context(&metadata)?;
        let stage = tempfile::Builder::new()
            .prefix("portable-encrypted-")
            .tempdir_in(&parent)
            .map_err(io)?;
        encrypt_file(
            &snapshot.database,
            &stage.path().join("database.enc"),
            &manifest.database,
            &key,
            &context,
            "database",
            metadata.chunk_bytes,
        )?;
        for (index, asset) in manifest.assets.iter().enumerate() {
            let path =
                fsutil::content_asset_path(&paths.assets_directory(), &asset.sha256, &asset.ext)?;
            encrypt_file(
                &path,
                &stage.path().join(format!("asset-{index}.enc")),
                asset,
                &key,
                &context,
                &format!("asset-{index}"),
                metadata.chunk_bytes,
            )?;
        }
        let plaintext = Zeroizing::new(serde_json::to_vec(&manifest).map_err(|_| failed())?);
        if plaintext.len() > options.max_manifest_bytes {
            return Err(failed());
        }
        let (nonce, ciphertext) =
            key.encrypt(&identity()?, &format!("{context}:manifest"), &plaintext)?;
        let header = Header {
            metadata,
            nonce,
            manifest: ciphertext,
        };
        let encoded = serde_json::to_vec(&header).map_err(|_| failed())?;
        if encoded.len() as u64 > options.max_header_bytes {
            return Err(failed());
        }
        fsutil::atomic_write_new(&stage.path().join("header.json"), &encoded)?;
        let mut report = PortableReport {
            channels,
            assets: manifest.assets.len(),
            secrets: secret_count,
            total_bytes: total,
            offsite_verified: false,
        };
        // 暗号化成果物を復号して照合してから公開する。平文の一時DBはlocal work内だけ。
        decrypt_file(
            &stage.path().join("database.enc"),
            &work.path().join("verify-database"),
            &manifest.database,
            &key,
            &context,
            "database",
            header.metadata.chunk_bytes,
        )?;
        for (index, asset) in manifest.assets.iter().enumerate() {
            decrypt_file(
                &stage.path().join(format!("asset-{index}.enc")),
                &work.path().join(format!("verify-{index}")),
                asset,
                &key,
                &context,
                &format!("asset-{index}"),
                header.metadata.chunk_bytes,
            )?;
        }
        fsutil::publish_new_directory(stage.path(), destination)?;
        let _published = stage.keep();
        if let Some(offsite) = offsite {
            copy_offsite(
                destination,
                offsite,
                &paths.root,
                manifest.assets.len(),
                options,
            )?;
            report.offsite_verified = true;
        }
        Ok(report)
    }
}

fn copy_offsite(
    source: &Path,
    destination: &Path,
    source_root: &Path,
    assets: usize,
    options: &PortableOptions,
) -> Result<()> {
    let parent = new_target(destination, Some(source_root), &options.offsite_policy)?;
    let stage = tempfile::Builder::new()
        .prefix("portable-offsite-")
        .tempdir_in(parent)
        .map_err(io)?;
    let mut names = vec!["header.json".to_owned(), "database.enc".to_owned()];
    names.extend((0..assets).map(|index| format!("asset-{index}.enc")));
    for name in names {
        let from = source.join(&name);
        regular_file(&from)?;
        let mut input = std::fs::File::open(&from).map_err(io)?;
        let target = stage.path().join(name);
        let mut output = fsutil::new_file_writer(&target)?;
        std::io::copy(&mut input, &mut output).map_err(io)?;
        output.finish()?;
        if imports::digest_file(&from)? != imports::digest_file(&target)? {
            return Err(failed());
        }
    }
    fsutil::publish_new_directory(stage.path(), destination)?;
    let _published = stage.keep();
    Ok(())
}

pub fn restore_portable(
    bundle: &Path,
    passphrase: &[u8],
    destination: &StorePaths,
    store_options: StoreOptions,
    options: &PortableOptions,
) -> Result<(Store, PortableReport)> {
    let parent = new_target(&destination.root, Some(bundle), &StoragePolicy::default())?;
    let (header, manifest, key, context) = read_header(bundle, passphrase, options)?;
    let stage = tempfile::Builder::new()
        .prefix("portable-restore-")
        .tempdir_in(parent)
        .map_err(io)?;
    let paths = destination.relocated(stage.path())?;
    decrypt_file(
        &bundle.join("database.enc"),
        &paths.database,
        &manifest.database,
        &key,
        &context,
        "database",
        header.metadata.chunk_bytes,
    )?;
    for (index, asset) in manifest.assets.iter().enumerate() {
        let path =
            fsutil::content_asset_path(&paths.assets_directory(), &asset.sha256, &asset.ext)?;
        decrypt_file(
            &bundle.join(format!("asset-{index}.enc")),
            &path,
            asset,
            &key,
            &context,
            &format!("asset-{index}"),
            header.metadata.chunk_bytes,
        )?;
    }
    let old = MasterKey::from_portable_material(&manifest.source_master)?;
    let new = MasterKey::generate()?;
    let mut restored = Store::open(&paths, store_options.clone())?;
    if restored.schema_version()? != manifest.schema_version
        || table_counts(&restored.connection)? != manifest.source_counts
        || asset_manifest(&restored.connection)? != manifest.assets
    {
        return Err(failed());
    }
    let transaction = restored.connection.transaction().map_err(db_failure)?;
    let secrets = rewrap_secrets(&transaction, &old, Some(&new))?;
    imports::rewrap_database_snapshots(&transaction, &old, &new)?;
    transaction.commit().map_err(db_failure)?;
    new.save_new(&paths.master_key)?;
    let report = PortableReport {
        channels: restored.channels()?.len(),
        assets: manifest.assets.len(),
        secrets,
        total_bytes: manifest.assets.iter().map(|entry| entry.bytes).sum::<u64>()
            + manifest.database.bytes,
        offsite_verified: false,
    };
    if table_counts(&restored.connection)? != manifest.source_counts {
        return Err(failed());
    }
    crate::check_integrity(&restored.connection)?;
    drop(restored);
    fsutil::publish_new_directory(stage.path(), &destination.root)?;
    let _published = stage.keep();
    Ok((Store::open(destination, store_options)?, report))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DrillOutcome {
    pub at: Timestamp,
    pub passed: bool,
    pub error_code: Option<String>,
    pub checked_assets: usize,
}
impl Store {
    pub fn restore_drill_due(&self, at: &Timestamp, interval: Duration) -> Result<bool> {
        if interval.is_zero() {
            return Err(failed());
        }
        let latest = self.global_repository().get::<AppSetting>(&AppSettingKey {
            key: "backup.restore_drill.latest".into(),
        })?;
        match latest {
            None => Ok(true),
            Some(record) => {
                let elapsed = at
                    .as_utc()
                    .signed_duration_since(record.updated_at.as_utc())
                    .to_std()
                    .map_err(|_| failed())?;
                Ok(elapsed >= interval)
            }
        }
    }

    pub fn record_restore_drill(
        &self,
        outcome: &DrillOutcome,
        channel: Option<&ChannelId>,
    ) -> Result<()> {
        if let Some(id) = channel {
            self.repository(id)?;
        }
        let transaction = self
            .connection
            .unchecked_transaction()
            .map_err(db_failure)?;
        repository::save(
            &transaction,
            &AppSetting {
                key: "backup.restore_drill.latest".into(),
                value_json: serde_json::to_value(outcome).map_err(|_| failed())?,
                updated_at: outcome.at.clone(),
            },
        )?;
        if let Some(id) = channel {
            let repository = repository::ChannelRepository {
                connection: &transaction,
                channel_id: id.clone(),
            };
            let key = NotificationKey {
                channel_id: id.clone(),
                id: "backup-restore-drill".into(),
            };
            let old = repository.get::<Notification>(&key)?;
            if !outcome.passed || old.is_some() {
                repository.save(&Notification {
                    channel_id: id.clone(),
                    id: key.id,
                    kind: "backup".into(),
                    severity: "error".into(),
                    dedupe_key: "backup-restore-drill".into(),
                    message_key: "backup.restore_drill_failed".into(),
                    args_json: json!({"code":outcome.error_code}),
                    created_at: old.map_or_else(|| outcome.at.clone(), |record| record.created_at),
                    resolved_at: if outcome.passed {
                        Some(outcome.at.clone())
                    } else {
                        None
                    },
                })?;
            }
        }
        transaction.commit().map_err(db_failure)
    }

    pub fn run_restore_drill(
        &self,
        bundle: &Path,
        passphrase: &[u8],
        scratch: &StorePaths,
        store_options: StoreOptions,
        options: &PortableOptions,
        channel: Option<&ChannelId>,
    ) -> Result<DrillOutcome> {
        let at = Timestamp::parse(&clock::now_utc_iso())?;
        // 利用者のscratch自体には触れず、所有する一時領域だけを復元・削除する。
        let operation = (|| {
            let source = self
                .connection
                .path()
                .map(Path::new)
                .and_then(Path::parent)
                .ok_or_else(failed)?;
            let parent = new_target(&scratch.root, Some(source), &StoragePolicy::default())?;
            let work = tempfile::Builder::new()
                .prefix("portable-drill-")
                .tempdir_in(parent)
                .map_err(io)?;
            let target = scratch.relocated(&work.path().join("restored"))?;
            let restored = restore_portable(bundle, passphrase, &target, store_options, options);
            let result = match restored {
                Ok((store, report)) => {
                    drop(store);
                    Ok(report)
                }
                Err(error) => Err(error),
            };
            work.close().map_err(io)?;
            result
        })();
        let outcome = match operation {
            Ok(report) => DrillOutcome {
                at,
                passed: true,
                error_code: None,
                checked_assets: report.assets,
            },
            Err(error) => {
                tracing::error!(code=%error.code,"バックアップ復元訓練に失敗しました");
                DrillOutcome {
                    at,
                    passed: false,
                    error_code: Some(error.code),
                    checked_assets: 0,
                }
            }
        };
        self.record_restore_drill(&outcome, channel)?;
        Ok(outcome)
    }
}

#[cfg(test)]
#[path = "portable_backup_tests.rs"]
mod tests;
