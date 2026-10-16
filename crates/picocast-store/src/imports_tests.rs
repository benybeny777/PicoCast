#![cfg(test)]
#![allow(clippy::unwrap_used, clippy::panic)]

use super::*;
use crate::{DataMode, StoreOptions, StorePaths};
use std::time::Duration;

fn fixture() -> (
    tempfile::TempDir,
    PathBuf,
    Store,
    MasterKey,
    MasterKey,
    SettingsImportOptions,
) {
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("settings-backup.db");
    let legacy = MasterKey::generate().unwrap();
    let target = MasterKey::generate().unwrap();
    let db = Connection::open(&source).unwrap();
    let at = "2026-10-16T12:00:00+09:00";
    let records = BTreeMap::from([
        (
            "channel_profiles",
            vec![
                json!({"profile_id":"a","channel_name":"検証","channel_handle":"@a","genre_profile":"fixture","output_root":"a","default_hashtags":"#検証","is_active":1,"created_at":at,"updated_at":at}),
            ],
        ),
        (
            "settings",
            vec![
                json!({"key":"SAMPLE_INTEGER","value":"3"}),
                json!({"key":"AUTOPILOT_POLICY:a","value":json!({"enabled":true,"daily_shorts":1,"daily_longs":0,"start_hour":6,"min_score":80,"daily_paid_limit":3,"consent_hash":"synthetic"}).to_string()}),
            ],
        ),
        (
            "prompt_templates",
            vec![
                json!({"template_id":"t1","profile_id":"a","template_name":"検証","template_kind":"script","is_default":1,"is_enabled":1,"system_rules":"役割","script_rules":"説明を優先","title_rules":null,"description":"説明","created_at":at,"updated_at":at}),
            ],
        ),
        (
            "character_profiles",
            vec![
                json!({"character_id":"c1","profile_id":"a","display_name":"架空","character_name":"架空","role":"説明","voice_backend":"voicevox","voice_speaker":"speaker","voice_speaker_id":3,"voice_styles_json":"{\"普通\":3}","credit_text":"音声クレジット","portrait_png_path":"asset:portrait.png","enabled":1,"created_at":at,"updated_at":at}),
            ],
        ),
        (
            "reading_dictionary_entries",
            vec![
                json!({"dict_type":"base","word":"東京","reading":"とうきょう","updated_at":at}),
                json!({"dict_type":"user","word":"東京","reading":"トウキョウ","updated_at":at}),
            ],
        ),
        (
            "reading_candidates",
            vec![
                json!({"word":"候補","reading":"こうほ","reason":"検証","source":"safe_auto","auto_applied":0,"review_required":1,"updated_at":at}),
            ],
        ),
        (
            "reading_dictionary_seed_state",
            vec![json!({"seed_name":"fixture","seeded_at":at,"row_count":2})],
        ),
        (
            "channel_schedule_settings",
            vec![
                json!({"profile_id":"a","timezone_name":"Asia/Tokyo","shorts_slot_hours":"[12,21]","long_slot_hours":"[22]","created_at":at,"updated_at":at}),
            ],
        ),
        (
            "channel_schedule_migrations",
            vec![json!({"migration_key":"fixture","applied_at":at})],
        ),
        ("bgm_assets", vec![]),
    ]);
    for (table, rows) in records {
        if rows.is_empty() {
            db.execute_batch(&format!("CREATE TABLE {table}(id TEXT)"))
                .unwrap();
            continue;
        }
        let columns: Vec<_> = rows[0].as_object().unwrap().keys().cloned().collect();
        db.execute_batch(&format!(
            "CREATE TABLE {table}({})",
            columns
                .iter()
                .map(|name| name.to_string())
                .collect::<Vec<_>>()
                .join(",")
        ))
        .unwrap();
        for row in rows {
            let values: Vec<_> = columns
                .iter()
                .map(|key| match &row[key] {
                    Value::Null => rusqlite::types::Value::Null,
                    Value::String(value) => rusqlite::types::Value::Text(value.clone()),
                    Value::Number(value) => {
                        rusqlite::types::Value::Integer(value.as_i64().unwrap())
                    }
                    _ => panic!("テストfixtureの型"),
                })
                .collect();
            db.execute(
                &format!(
                    "INSERT INTO {table} VALUES({})",
                    vec!["?"; columns.len()].join(",")
                ),
                rusqlite::params_from_iter(values),
            )
            .unwrap();
        }
    }
    db.execute_batch("CREATE TABLE encrypted_secrets(secret_id TEXT PRIMARY KEY,profile_id TEXT,secret_type TEXT,nonce BLOB,encrypted_value BLOB,key_version INTEGER)").unwrap();
    let (nonce, ciphertext) = legacy.encrypt_legacy_fixture(b"synthetic-secret-only");
    db.execute(
        "INSERT INTO encrypted_secrets VALUES('s1','a','google_api_key',?1,?2,1)",
        params![nonce, ciphertext],
    )
    .unwrap();
    drop(db);
    let paths = StorePaths::new(temp.path(), DataMode::Development).unwrap();
    let store = Store::open(
        &paths,
        StoreOptions {
            busy_timeout: Duration::from_secs(5),
            backup_pages_per_step: 16,
            backup_pause: Duration::from_millis(1),
        },
    )
    .unwrap();
    let options = SettingsImportOptions {
        setting_types: BTreeMap::from([("SAMPLE_INTEGER".into(), SettingKind::Integer)]),
        retired_settings: BTreeSet::new(),
        language: "ja".into(),
        timezone: "Asia/Tokyo".into(),
        bgm_files: BTreeMap::new(),
        assets_root: paths.assets_directory(),
        bgm_durations_ms: BTreeMap::new(),
    };
    (temp, source, store, legacy, target, options)
}

#[test]
fn retired_credentials_remain_only_in_encrypted_source_snapshot() {
    let (_temp, path, mut store, legacy, target, mut options) = fixture();
    let sensitive = "synthetic-retired-license-key";
    let source = Connection::open(&path).unwrap();
    source
        .execute(
            "INSERT INTO settings(key,value) VALUES('LICENSE_KEY',?1)",
            [sensitive],
        )
        .unwrap();
    drop(source);
    let before = std::fs::read(&path).unwrap();
    options.retired_settings.insert("LICENSE_KEY".into());
    let first = store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .unwrap();
    let second = store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .unwrap();
    assert_eq!(first, second);
    assert_eq!(std::fs::read(&path).unwrap(), before);
    let settings = store.global_repository().list::<AppSetting>().unwrap();
    assert!(settings
        .iter()
        .all(|setting| !setting.value_json.to_string().contains(sensitive)));
    let reference = settings
        .iter()
        .find(|setting| setting.key == "legacy:retired_settings:LICENSE_KEY")
        .unwrap();
    assert_eq!(
        reference.value_json["source"],
        "encrypted_settings_snapshot"
    );
    let snapshot = settings
        .iter()
        .find(|setting| setting.key == reference.value_json["snapshot_key"].as_str().unwrap())
        .unwrap();
    let restored = snapshot_plaintext(&snapshot.value_json, &target).unwrap();
    assert!(restored
        .windows(sensitive.len())
        .any(|part| part == sensitive.as_bytes()));
}

#[test]
fn imports_all_settings_domains_readonly_and_repeats_without_overwriting() {
    let (_temp, path, mut store, legacy, target, options) = fixture();
    let before = std::fs::read(&path).unwrap();
    let report = store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .unwrap();
    assert_eq!(report.source_counts["reading_dictionary_entries"], 2);
    assert_eq!(report.source_counts["encrypted_secrets"], 1);
    assert_eq!(report.holds.len(), 1);
    let again = store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .unwrap();
    assert_eq!(again, report);
    assert_eq!(std::fs::read(&path).unwrap(), before);
    let id = ChannelId::new("a").unwrap();
    assert_eq!(
        store
            .load_secret(&id, "google_api_key", &target)
            .unwrap()
            .unwrap()
            .as_slice(),
        b"synthetic-secret-only"
    );
    let repo = store.repository(&id).unwrap();
    assert_eq!(repo.list::<ScheduleSlot>().unwrap().len(), 21);
    let policy = repo.list::<AutopilotPolicy>().unwrap();
    assert!(!policy[0].enabled);
    assert_eq!(policy[0].budget_micros, 0);
    assert!(policy[0].paused_reason.is_some());
    assert_eq!(
        store
            .global_repository()
            .list::<ReadingEntry>()
            .unwrap()
            .len(),
        2
    );
    assert_eq!(repo.list::<PromptTemplateVersion>().unwrap().len(), 1);
    assert_eq!(repo.list::<Character>().unwrap()[0].speaker_id, "3");
}

#[test]
fn wrong_key_and_invalid_settings_roll_back_every_table() {
    let (_temp, path, mut store, _legacy, target, mut options) = fixture();
    let wrong = MasterKey::generate().unwrap();
    let error = store
        .import_legacy_settings(&path, Some(&wrong), &target, &options)
        .unwrap_err();
    assert_eq!(error.code, "E-SECRET-DECRYPT");
    assert!(store.channels().unwrap().is_empty());
    assert!(store
        .global_repository()
        .list::<AppSetting>()
        .unwrap()
        .is_empty());
    options.setting_types.clear();
    assert!(store
        .import_legacy_settings(&path, None, &target, &options)
        .is_err());
    assert!(store.channels().unwrap().is_empty());
}

#[test]
fn destination_conflict_is_rejected_without_replacing_existing_value() {
    let (_temp, path, mut store, legacy, target, options) = fixture();
    store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .unwrap();
    store
        .global_repository()
        .save(&AppSetting {
            key: "SAMPLE_INTEGER".into(),
            value_json: json!(99),
            updated_at: Timestamp::parse("2026-10-16T00:00:00Z").unwrap(),
        })
        .unwrap();
    assert!(store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .is_err());
    assert_eq!(
        store
            .global_repository()
            .get::<AppSetting>(&AppSettingKey {
                key: "SAMPLE_INTEGER".into()
            })
            .unwrap()
            .unwrap()
            .value_json,
        json!(99)
    );
}

#[test]
fn missing_source_or_key_never_creates_a_file() {
    let temp = tempfile::tempdir().unwrap();
    let missing = temp.path().join("missing.db");
    assert!(open_legacy(&missing).is_err());
    assert!(!missing.exists());
    assert!(MasterKey::load(&missing).is_err());
    assert!(!missing.exists());
}

#[test]
fn bgm_copy_is_content_addressed_and_original_is_unchanged() {
    let (temp, path, mut store, legacy, target, mut options) = fixture();
    let music = temp.path().join("fixture.wav");
    picocast_core::fsutil::atomic_write(&music, b"synthetic-waveform").unwrap();
    let original = std::fs::read(&music).unwrap();
    let source = Connection::open(&path).unwrap();
    source.execute_batch("DROP TABLE bgm_assets; CREATE TABLE bgm_assets(bgm_id TEXT,profile_id TEXT,display_name TEXT,file_path TEXT,default_volume_db REAL,loop_enabled INTEGER,is_enabled INTEGER,is_default INTEGER,note TEXT,duration_sec REAL,created_at TEXT,updated_at TEXT); INSERT INTO bgm_assets VALUES('music1','a','検証用','000_assets/fixture.wav',-20,1,1,1,'架空素材',2.5,'2026-10-16T00:00:00Z','2026-10-16T00:00:00Z');").unwrap();
    drop(source);
    options.bgm_files.insert("music1".into(), music.clone());
    let report = store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .unwrap();
    assert_eq!(report.source_counts["bgm_assets"], 1);
    let assets = store.global_repository().list::<Asset>().unwrap();
    assert_eq!(assets.len(), 1);
    assert_eq!(assets[0].sha256, digest_file(&music).unwrap());
    assert_eq!(std::fs::read(&music).unwrap(), original);
    assert_eq!(
        store.global_repository().list::<MusicTags>().unwrap()[0].duration_ms,
        2500
    );
    assert_eq!(
        store
            .import_legacy_settings(&path, Some(&legacy), &target, &options)
            .unwrap(),
        report
    );
}

#[test]
fn readonly_source_rejects_writes_and_unknown_types_never_degrade_to_text() {
    let (_temp, path, _store, _legacy, _target, _options) = fixture();
    let before = std::fs::read(&path).unwrap();
    let source = open_legacy(&path).unwrap();
    assert!(source
        .execute("UPDATE settings SET value='changed'", [])
        .is_err());
    assert_eq!(std::fs::read(path).unwrap(), before);
    assert!(decode_setting("3.2", SettingKind::Integer).is_err());
    assert!(decode_setting("NaN", SettingKind::Decimal).is_err());
    assert!(decode_setting("perhaps", SettingKind::Boolean).is_err());
}

#[test]
fn every_unknown_table_column_and_blob_survives_in_encrypted_database_snapshot() {
    let (_temp, path, mut store, legacy, target, options) = fixture();
    let source = Connection::open(&path).unwrap();
    source.execute_batch("ALTER TABLE channel_profiles ADD COLUMN future_blob BLOB; UPDATE channel_profiles SET future_blob=x'0001ff'; CREATE TABLE autopilot_runs(run_id TEXT,state TEXT); INSERT INTO autopilot_runs VALUES('pending','working'); CREATE TABLE future_table(secret_blob BLOB,unknown_text TEXT); INSERT INTO future_table VALUES(x'010203','synthetic-opaque-data');").unwrap();
    drop(source);
    let bytes = std::fs::read(&path).unwrap();
    let report = store
        .import_legacy_settings(&path, Some(&legacy), &target, &options)
        .unwrap();
    assert_eq!(report.source_counts["autopilot_runs"], 1);
    assert_eq!(report.source_counts["future_table"], 1);
    assert!(report
        .holds
        .iter()
        .any(|hold| hold.contains("autopilot_runs")));
    let snapshot = store
        .global_repository()
        .get::<AppSetting>(&AppSettingKey {
            key: format!(
                "legacy:encrypted-settings-snapshot:{}",
                report.source_sha256
            ),
        })
        .unwrap()
        .unwrap();
    let nonce: Vec<u8> = serde_json::from_value(snapshot.value_json["nonce"].clone()).unwrap();
    let ciphertext: Vec<u8> =
        serde_json::from_value(snapshot.value_json["ciphertext"].clone()).unwrap();
    assert_eq!(
        target
            .decrypt(
                &ChannelId::new("picocast-import:settings").unwrap(),
                "database-backup-v1",
                &nonce,
                &ciphertext
            )
            .unwrap()
            .as_slice(),
        bytes
    );
    assert_eq!(std::fs::read(&path).unwrap(), bytes);
    assert_eq!(
        store
            .import_legacy_settings(&path, Some(&legacy), &target, &options)
            .unwrap(),
        report
    );
}
