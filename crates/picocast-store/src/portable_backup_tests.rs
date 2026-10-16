#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::*;
use crate::{DataMode, StoreOptions};

fn store_options() -> StoreOptions {
    StoreOptions {
        busy_timeout: Duration::from_secs(5),
        backup_pages_per_step: 16,
        backup_pause: Duration::from_millis(1),
    }
}
fn options() -> PortableOptions {
    PortableOptions {
        kdf: KdfOptions {
            memory_kib: 32,
            iterations: 1,
            parallelism: 1,
        },
        max_kdf: KdfOptions {
            memory_kib: 64,
            iterations: 2,
            parallelism: 2,
        },
        minimum_passphrase_bytes: 12,
        chunk_bytes: 64,
        max_header_bytes: 100_000,
        max_manifest_bytes: 20_000,
        max_assets: 20,
        max_total_bytes: 5_000_000,
        offsite_policy: StoragePolicy::default(),
    }
}
fn fixture() -> (tempfile::TempDir, StorePaths, Store, MasterKey) {
    let temp = tempfile::tempdir().unwrap();
    let paths = StorePaths::new(temp.path(), DataMode::Development).unwrap();
    let store = Store::open(&paths, store_options()).unwrap();
    let key = MasterKey::generate().unwrap();
    let id = ChannelId::new("fixture").unwrap();
    store.create_channel(&id, "架空").unwrap();
    store
        .save_secret(&id, "google_api_key", b"synthetic-only", &key)
        .unwrap();
    let (nonce, ciphertext) = key
        .encrypt(
            &ChannelId::new("picocast-import:settings").unwrap(),
            "database-backup-v1",
            b"synthetic legacy database",
        )
        .unwrap();
    store.global_repository().save(&AppSetting {
        key: "legacy:encrypted-settings-snapshot:fixture".into(),
        value_json: json!({"format":"aes-gcm-settings-backup-v1","nonce":nonce,"ciphertext":ciphertext}),
        updated_at: Timestamp::parse("2026-10-16T00:00:00Z").unwrap(),
    }).unwrap();
    let media = temp.path().join("fixture.png");
    fsutil::atomic_write(&media, &vec![42u8; 257]).unwrap();
    let copied = fsutil::import_content_addressed(&media, &paths.assets_directory()).unwrap();
    store
        .global_repository()
        .save(&Asset {
            sha256: copied.sha256,
            kind: "image".into(),
            ext: copied.ext,
            bytes: copied.bytes as i64,
            created_at: Timestamp::parse("2026-10-16T00:00:00Z").unwrap(),
            provenance_json: json!({"fixture":true}),
        })
        .unwrap();
    (temp, paths, store, key)
}

#[cfg(windows)]
#[test]
fn portable_roundtrip_rekeys_secrets_verifies_assets_and_copies_only_encrypted_offsite() {
    let (temp, paths, store, key) = fixture();
    let bundle = temp.path().join("bundle");
    let offsite = temp.path().join("offsite");
    let report = store
        .export_portable(
            &paths,
            &key,
            b"synthetic passphrase",
            &bundle,
            Some(&offsite),
            &options(),
        )
        .unwrap();
    assert!(report.offsite_verified);
    assert_eq!(report.assets, 1);
    let drill_parent = temp.path().join("drill");
    std::fs::create_dir(&drill_parent).unwrap();
    let scratch = StorePaths::new(&drill_parent, DataMode::Development).unwrap();
    assert!(
        store
            .run_restore_drill(
                &bundle,
                b"synthetic passphrase",
                &scratch,
                store_options(),
                &options(),
                None
            )
            .unwrap()
            .passed
    );
    assert_eq!(std::fs::read_dir(&drill_parent).unwrap().count(), 0);
    let dest_parent = temp.path().join("other-user");
    std::fs::create_dir(&dest_parent).unwrap();
    let destination = StorePaths::new(&dest_parent, DataMode::Production).unwrap();
    let (restored, result) = restore_portable(
        &offsite,
        b"synthetic passphrase",
        &destination,
        store_options(),
        &options(),
    )
    .unwrap();
    assert_eq!(result.assets, 1);
    let new = MasterKey::load(&destination.master_key).unwrap();
    assert_eq!(
        imports::verify_database_snapshots(&restored.connection, &new).unwrap(),
        1
    );
    assert!(imports::verify_database_snapshots(&restored.connection, &key).is_err());
    let id = ChannelId::new("fixture").unwrap();
    assert_eq!(
        restored
            .load_secret(&id, "google_api_key", &new)
            .unwrap()
            .unwrap()
            .as_slice(),
        b"synthetic-only"
    );
    assert!(restored.load_secret(&id, "google_api_key", &key).is_err());
    assert!(restore_portable(
        &bundle,
        b"synthetic passphrase",
        &destination,
        store_options(),
        &options()
    )
    .is_err());
    assert_eq!(
        store
            .load_secret(&id, "google_api_key", &key)
            .unwrap()
            .unwrap()
            .as_slice(),
        b"synthetic-only"
    );
}

#[cfg(windows)]
#[test]
fn wrong_passphrase_and_corrupt_chunks_never_publish_partial_restore() {
    let (temp, paths, store, key) = fixture();
    let bundle = temp.path().join("bundle");
    store
        .export_portable(
            &paths,
            &key,
            b"synthetic passphrase",
            &bundle,
            None,
            &options(),
        )
        .unwrap();
    let dest_parent = temp.path().join("destination");
    std::fs::create_dir(&dest_parent).unwrap();
    let dest = StorePaths::new(&dest_parent, DataMode::Development).unwrap();
    assert!(restore_portable(
        &bundle,
        b"incorrect passphrase",
        &dest,
        store_options(),
        &options()
    )
    .is_err());
    assert!(!dest.root.exists());
    let path = bundle.join("asset-0.enc");
    let mut bytes = std::fs::read(&path).unwrap();
    bytes[20] ^= 1;
    fsutil::atomic_write(&path, &bytes).unwrap();
    assert!(restore_portable(
        &bundle,
        b"synthetic passphrase",
        &dest,
        store_options(),
        &options()
    )
    .is_err());
    assert!(!dest.root.exists());
    let outcome = store
        .run_restore_drill(
            &bundle,
            b"synthetic passphrase",
            &dest,
            store_options(),
            &options(),
            Some(&ChannelId::new("fixture").unwrap()),
        )
        .unwrap();
    assert!(!outcome.passed);
    assert_eq!(std::fs::read_dir(&dest_parent).unwrap().count(), 0);
    assert!(outcome.error_code.is_some());
    assert_eq!(
        store
            .repository(&ChannelId::new("fixture").unwrap())
            .unwrap()
            .list::<Notification>()
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn wrong_source_key_never_exports_normal_secrets_without_import_snapshots() {
    let (temp, paths, store, _key) = fixture();
    store
        .connection
        .execute("DELETE FROM app_settings", [])
        .unwrap();
    let destination = temp.path().join("bundle");
    assert!(store
        .export_portable(
            &paths,
            &MasterKey::generate().unwrap(),
            b"synthetic passphrase",
            &destination,
            None,
            &options()
        )
        .is_err());
    assert!(!destination.exists());
}

#[cfg(windows)]
#[test]
fn authenticated_manifest_must_match_database_asset_catalog_and_existing_scratch_survives() {
    let (temp, paths, store, key) = fixture();
    let bundle = temp.path().join("bundle");
    store
        .export_portable(
            &paths,
            &key,
            b"synthetic passphrase",
            &bundle,
            None,
            &options(),
        )
        .unwrap();
    let (mut header, mut manifest, key, context) =
        read_header(&bundle, b"synthetic passphrase", &options()).unwrap();
    manifest.assets.clear();
    let plaintext = Zeroizing::new(serde_json::to_vec(&manifest).unwrap());
    let (nonce, ciphertext) = key
        .encrypt(
            &identity().unwrap(),
            &format!("{context}:manifest"),
            &plaintext,
        )
        .unwrap();
    header.nonce = nonce;
    header.manifest = ciphertext;
    fsutil::atomic_write(
        &bundle.join("header.json"),
        &serde_json::to_vec(&header).unwrap(),
    )
    .unwrap();
    let destination_parent = temp.path().join("restore");
    std::fs::create_dir(&destination_parent).unwrap();
    let destination = StorePaths::new(&destination_parent, DataMode::Development).unwrap();
    assert!(restore_portable(
        &bundle,
        b"synthetic passphrase",
        &destination,
        store_options(),
        &options()
    )
    .is_err());
    assert!(!destination.root.exists());
    std::fs::create_dir(&destination.root).unwrap();
    let sentinel = destination.root.join("sentinel");
    fsutil::atomic_write(&sentinel, b"keep").unwrap();
    assert!(
        !store
            .run_restore_drill(
                &bundle,
                b"synthetic passphrase",
                &destination,
                store_options(),
                &options(),
                None
            )
            .unwrap()
            .passed
    );
    assert_eq!(std::fs::read(&sentinel).unwrap(), b"keep");
    assert_eq!(std::fs::read_dir(&destination_parent).unwrap().count(), 1);
}

#[test]
fn kdf_limits_and_drill_interval_are_explicit_and_global_failure_is_visible() {
    let (_temp, _paths, store, _key) = fixture();
    let at = Timestamp::parse("2026-10-16T00:00:00Z").unwrap();
    assert!(store
        .restore_drill_due(&at, Duration::from_secs(7 * 24 * 3600))
        .unwrap());
    let outcome = DrillOutcome {
        at: at.clone(),
        passed: false,
        error_code: Some("E-BACKUP-PORTABLE".into()),
        checked_assets: 0,
    };
    store.record_restore_drill(&outcome, None).unwrap();
    assert!(!store
        .restore_drill_due(&at, Duration::from_secs(7 * 24 * 3600))
        .unwrap());
    assert!(store
        .global_repository()
        .get::<AppSetting>(&AppSettingKey {
            key: "backup.restore_drill.latest".into()
        })
        .unwrap()
        .is_some());
    let mut metadata = Metadata {
        version: 1,
        kdf: options().kdf,
        salt: [1u8; 16],
        bundle_id: [2u8; 16],
        chunk_bytes: 64,
    };
    metadata.kdf.memory_kib = 1000;
    assert!(derive(b"synthetic passphrase", &metadata, &options()).is_err());
    assert!(store.restore_drill_due(&at, Duration::ZERO).is_err());
}
