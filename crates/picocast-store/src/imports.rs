//! 旧設定のバックアップを読取り専用で新スキーマへ写像する。秘密値を報告へ含めない。
use crate::{
    db_failure, failure, io_failure,
    repository::{
        self, AppSetting, AppSettingKey, Asset, AssetRef, AutopilotPolicy, Channel, ChannelSetting,
        Character, MusicTags, Notification, PromptTemplate, PromptTemplateVersion,
        ReadingCandidate, ReadingEntry, Record, ScheduleSlot,
    },
    MasterKey, Store,
};
use picocast_core::{
    clock::{self, Timestamp},
    ChannelId, Result,
};
use rusqlite::{params, types::ValueRef, Connection, OpenFlags, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet, HashSet},
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, Copy)]
pub enum SettingKind {
    Boolean,
    Integer,
    Decimal,
    Json,
    Text,
}

/// 旧版文字列の型を曖昧に推定せず、呼出側の設定定義で指定する。
pub struct SettingsImportOptions {
    pub setting_types: BTreeMap<String, SettingKind>,
    /// 撤回済み販売設定等の原文は暗号化元DBにだけ保持し、有効設定へ移さない。
    pub retired_settings: BTreeSet<String>,
    pub language: String,
    pub timezone: String,
    /// 旧BGM識別子ごとに、利用者が指定したバックアップ素材を明示する。
    pub bgm_files: BTreeMap<String, PathBuf>,
    pub assets_root: PathBuf,
    /// 旧DBで未計測の尺は、呼出側で測定した値を明示する。0へ推測しない。
    pub bgm_durations_ms: BTreeMap<String, i64>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImportReport {
    pub source_sha256: String,
    pub source_counts: BTreeMap<String, usize>,
    pub verified_records: usize,
    pub holds: Vec<String>,
}

const TABLES: &[&str] = &[
    "channel_profiles",
    "settings",
    "prompt_templates",
    "character_profiles",
    "reading_dictionary_entries",
    "reading_candidates",
    "reading_dictionary_seed_state",
    "bgm_assets",
    "channel_schedule_settings",
    "channel_schedule_migrations",
];

pub(crate) fn import_failure() -> picocast_core::AppError {
    failure(
        "E-IMPORT-SETTINGS",
        "旧データの取り込み・照合に失敗しました。",
        "元データを変更せず、バックアップのスキーマ・関連・型・指定素材を確認してください。",
    )
}

pub(crate) fn open_legacy(path: &Path) -> Result<Connection> {
    if !path.is_absolute() || !path.is_file() {
        return Err(import_failure());
    }
    // オンラインバックアップ済みの単体DBを要求し、読取りでsidecarを生成しない。
    for suffix in ["-wal", "-shm"] {
        let mut sidecar = path.as_os_str().to_os_string();
        sidecar.push(suffix);
        if Path::new(&sidecar)
            .try_exists()
            .map_err(|_| import_failure())?
        {
            return Err(import_failure());
        }
    }
    let connection = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(db_failure)?;
    connection
        .execute_batch("PRAGMA query_only=ON; BEGIN;")
        .map_err(db_failure)?;
    let integrity: String = connection
        .query_row("PRAGMA integrity_check", [], |row| row.get(0))
        .map_err(db_failure)?;
    if integrity != "ok" {
        return Err(import_failure());
    }
    Ok(connection)
}

pub(crate) fn read_table(connection: &Connection, table: &str) -> Result<Vec<Value>> {
    if table.is_empty()
        || !table
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
    {
        return Err(import_failure());
    }
    let mut statement = connection
        .prepare(&format!("SELECT * FROM \"{table}\" ORDER BY rowid"))
        .map_err(db_failure)?;
    let names: Vec<_> = statement
        .column_names()
        .iter()
        .map(|name| (*name).to_owned())
        .collect();
    let mut query = statement.query([]).map_err(db_failure)?;
    let mut output = Vec::new();
    while let Some(row) = query.next().map_err(db_failure)? {
        let mut object = serde_json::Map::new();
        for (index, name) in names.iter().enumerate() {
            let value = match row.get_ref(index).map_err(db_failure)? {
                ValueRef::Null => Value::Null,
                ValueRef::Integer(value) => json!(value),
                ValueRef::Real(value) if value.is_finite() => json!(value),
                ValueRef::Text(bytes) => Value::String(
                    std::str::from_utf8(bytes)
                        .map_err(|_| import_failure())?
                        .into(),
                ),
                ValueRef::Blob(bytes) => json!({"sqlite_blob":bytes}),
                _ => return Err(import_failure()),
            };
            object.insert(name.clone(), value);
        }
        output.push(Value::Object(object));
    }
    Ok(output)
}

pub(crate) fn field<'a>(row: &'a Value, key: &str) -> Result<&'a str> {
    row.get(key)
        .and_then(Value::as_str)
        .ok_or_else(import_failure)
}
pub(crate) fn integer(row: &Value, key: &str) -> Result<i64> {
    row.get(key)
        .and_then(Value::as_i64)
        .ok_or_else(import_failure)
}
pub(crate) fn flag(row: &Value, key: &str) -> Result<bool> {
    match integer(row, key)? {
        0 => Ok(false),
        1 => Ok(true),
        _ => Err(import_failure()),
    }
}
pub(crate) fn timestamp(row: &Value, key: &str) -> Result<Timestamp> {
    Timestamp::parse(field(row, key)?)
}

pub(crate) fn put_checked<R: Record>(connection: &Connection, record: &R) -> Result<()> {
    if let Some(existing) = repository::get::<R>(connection, &record.key(), None)? {
        if existing.values()? != record.values()? {
            return Err(import_failure());
        }
    } else {
        repository::save(connection, record)?;
    }
    let reread =
        repository::get::<R>(connection, &record.key(), None)?.ok_or_else(import_failure)?;
    if reread.values()? != record.values()? {
        return Err(import_failure());
    }
    Ok(())
}

/// 同じ内容の素材は最初の来歴を維持し、サイズ・形式の矛盾だけを拒否する。
pub(crate) fn put_asset_checked(connection: &Connection, record: &Asset) -> Result<()> {
    if let Some(existing) = repository::get::<Asset>(connection, &record.key(), None)? {
        if existing.bytes != record.bytes || existing.ext != record.ext {
            return Err(import_failure());
        }
        Ok(())
    } else {
        put_checked(connection, record)
    }
}

fn snapshot_plaintext(value: &Value, key: &MasterKey) -> Result<zeroize::Zeroizing<Vec<u8>>> {
    if value["format"] != "aes-gcm-settings-backup-v1" {
        return Err(import_failure());
    }
    let nonce: Vec<u8> =
        serde_json::from_value(value["nonce"].clone()).map_err(|_| import_failure())?;
    let ciphertext: Vec<u8> =
        serde_json::from_value(value["ciphertext"].clone()).map_err(|_| import_failure())?;
    key.decrypt(
        &ChannelId::new("picocast-import:settings")?,
        "database-backup-v1",
        &nonce,
        &ciphertext,
    )
}

fn snapshot_envelope(bytes: &[u8], key: &MasterKey) -> Result<Value> {
    let (nonce, ciphertext) = key.encrypt(
        &ChannelId::new("picocast-import:settings")?,
        "database-backup-v1",
        bytes,
    )?;
    Ok(
        json!({"format":"aes-gcm-settings-backup-v1","nonce":nonce.to_vec(),"ciphertext":ciphertext}),
    )
}

pub(crate) fn verify_database_snapshots(connection: &Connection, key: &MasterKey) -> Result<usize> {
    let records = repository::GlobalRepository { connection }.list::<AppSetting>()?;
    let mut count = 0;
    for record in records.iter().filter(|record| {
        record
            .key
            .starts_with("legacy:encrypted-settings-snapshot:")
    }) {
        snapshot_plaintext(&record.value_json, key)?;
        count += 1;
    }
    Ok(count)
}

pub(crate) fn rewrap_database_snapshots(
    connection: &Connection,
    old_key: &MasterKey,
    new_key: &MasterKey,
) -> Result<usize> {
    let records = repository::GlobalRepository { connection }.list::<AppSetting>()?;
    let mut count = 0;
    for mut record in records.into_iter().filter(|record| {
        record
            .key
            .starts_with("legacy:encrypted-settings-snapshot:")
    }) {
        let plain = snapshot_plaintext(&record.value_json, old_key)?;
        record.value_json = snapshot_envelope(&plain, new_key)?;
        repository::save(connection, &record)?;
        let persisted = repository::get::<AppSetting>(connection, &record.key(), None)?
            .ok_or_else(import_failure)?;
        if snapshot_plaintext(&persisted.value_json, new_key)?.as_slice() != plain.as_slice() {
            return Err(import_failure());
        }
        count += 1;
    }
    Ok(count)
}

pub(crate) fn digest_file(path: &Path) -> Result<String> {
    use std::io::Read;
    let mut file = std::fs::File::open(path).map_err(|error| {
        io_failure(
            "E-IMPORT-SETTINGS",
            "取り込み元を読み込めません。",
            "バックアップの権限を確認してください。",
            &error,
        )
    })?;
    let mut hash = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let length = file.read(&mut buffer).map_err(|error| {
            io_failure(
                "E-IMPORT-SETTINGS",
                "取り込み元を読み込めません。",
                "バックアップを確認してください。",
                &error,
            )
        })?;
        if length == 0 {
            break;
        }
        hash.update(&buffer[..length]);
    }
    Ok(hash
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect())
}

pub(crate) fn digest_bytes(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn decode_setting(raw: &str, kind: SettingKind) -> Result<Value> {
    match kind {
        SettingKind::Text => Ok(json!(raw)),
        SettingKind::Integer => raw
            .parse::<i64>()
            .map(|value| json!(value))
            .map_err(|_| import_failure()),
        SettingKind::Decimal => raw
            .parse::<f64>()
            .ok()
            .filter(|value| value.is_finite())
            .map(|value| json!(value))
            .ok_or_else(import_failure),
        SettingKind::Boolean => match raw.to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Ok(json!(true)),
            "0" | "false" | "no" | "off" => Ok(json!(false)),
            _ => Err(import_failure()),
        },
        SettingKind::Json => serde_json::from_str(raw).map_err(|_| import_failure()),
    }
}

fn preserve_row(
    connection: &Connection,
    table: &str,
    row: &Value,
    id: &str,
    at: &Timestamp,
    channel: Option<&ChannelId>,
) -> Result<()> {
    let key = format!("legacy:{table}:{id}");
    match channel {
        Some(channel) => put_checked(
            connection,
            &ChannelSetting {
                channel_id: channel.clone(),
                key,
                value_json: row.clone(),
                updated_at: at.clone(),
            },
        ),
        None => put_checked(
            connection,
            &AppSetting {
                key,
                value_json: row.clone(),
                updated_at: at.clone(),
            },
        ),
    }
}

impl Store {
    /// 設定のオンラインバックアップだけを読み、照合まで成功した1transactionだけを確定する。
    pub fn import_legacy_settings(
        &mut self,
        source_path: &Path,
        legacy_key: Option<&MasterKey>,
        target_key: &MasterKey,
        options: &SettingsImportOptions,
    ) -> Result<ImportReport> {
        let source = open_legacy(source_path)?;
        let before = digest_file(source_path)?;
        clock::timezone(&options.timezone)?;
        picocast_core::paths::validate_storage(&options.assets_root, &self.storage_policy)?;
        if options.language.trim().is_empty() {
            return Err(import_failure());
        }
        let mut tables = BTreeMap::new();
        let mut report = ImportReport {
            source_sha256: before.clone(),
            ..ImportReport::default()
        };
        for table in TABLES {
            let rows = read_table(&source, table)?;
            report.source_counts.insert((*table).into(), rows.len());
            tables.insert(*table, rows);
        }
        let at = Timestamp::parse(&clock::now_utc_iso())?;
        let tx = self.connection.transaction().map_err(db_failure)?;
        // 取込み時刻は既存レコードから再利用し、同じ入力の再実行で差分を作らない。
        let stamp_key = format!("legacy:settings-import:{before}");
        let previous = repository::get::<AppSetting>(
            &tx,
            &AppSettingKey {
                key: stamp_key.clone(),
            },
            None,
        )?;
        let at = previous
            .as_ref()
            .map(|record| record.updated_at.clone())
            .unwrap_or(at);
        preserve_database_snapshot(&tx, source_path, &before, target_key, &at)?;
        let mut schema = source.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*' ORDER BY name").map_err(db_failure)?;
        let names = schema
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(db_failure)?
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(db_failure)?;
        for name in names {
            if !report.source_counts.contains_key(&name) && name != "encrypted_secrets" {
                let quoted = name.replace('"', "\"\"");
                let count: i64 = source
                    .query_row(&format!("SELECT COUNT(*) FROM \"{quoted}\""), [], |row| {
                        row.get(0)
                    })
                    .map_err(db_failure)?;
                report.source_counts.insert(
                    name.clone(),
                    usize::try_from(count).map_err(|_| import_failure())?,
                );
                report.holds.push(format!("旧表 {name} は暗号化した元DBのsnapshotへ全件保持しました。自動実行せず、専用写像の確認を待ちます。"));
            }
        }
        let mut channels = HashSet::new();
        for row in &tables["channel_profiles"] {
            let id = ChannelId::new(field(row, "profile_id")?)?;
            if !channels.insert(id.clone()) {
                return Err(import_failure());
            }
            let schedule = tables["channel_schedule_settings"].iter().find(|schedule| {
                schedule.get("profile_id").and_then(Value::as_str) == Some(id.as_str())
            });
            let timezone = match schedule {
                Some(row) => field(row, "timezone_name")?,
                None => &options.timezone,
            };
            clock::timezone(timezone)?;
            let record = Channel {
                channel_id: id.clone(),
                name: field(row, "channel_name")?.into(),
                handle: Some(field(row, "channel_handle")?.into()),
                language: Some(options.language.clone()),
                timezone: Some(timezone.to_owned()),
                genre_pack_id: Some(field(row, "genre_profile")?.into()),
                character_set_id: None,
                youtube_channel_id: None,
                operator: "legacy".into(),
                archived_at: None,
                created_at: timestamp(row, "created_at")?,
                updated_at: timestamp(row, "updated_at")?,
            };
            put_checked(&tx, &record)?;
            preserve_row(&tx, "channel_profiles", row, id.as_str(), &at, Some(&id))?;
        }
        for row in &tables["settings"] {
            let key = field(row, "key")?;
            if [
                "google_api_key",
                "openai_api_key",
                "hf_token",
                "nvf_master_key",
                "youtube_upload_token",
                "youtube_analytics_token",
                "youtube_client_secrets",
                "aquestalk_license_key",
            ]
            .contains(&key.to_ascii_lowercase().as_str())
            {
                return Err(import_failure());
            }
            if let Some(profile_id) = key.strip_prefix("AUTOPILOT_POLICY:") {
                let id = ChannelId::new(profile_id)?;
                if !channels.contains(&id) {
                    return Err(import_failure());
                }
                let policy: Value =
                    serde_json::from_str(field(row, "value")?).map_err(|_| import_failure())?;
                import_policy(&tx, &id, &policy, &at)?;
                report.holds.push(format!("{}: 旧有料API回数上限は金額へ換算できません。予算を設定して再承認するまで自動運用を保留します。", id.as_str()));
            } else if options.retired_settings.contains(key) {
                // 廃止したライセンス等の秘密値を、平文の互換設定へ複製しない。
                let reference = json!({"key":key,"source":"encrypted_settings_snapshot",
                    "snapshot_key":format!("legacy:encrypted-settings-snapshot:{before}")});
                preserve_row(&tx, "retired_settings", &reference, key, &at, None)?;
            } else {
                let kind = options.setting_types.get(key).ok_or_else(import_failure)?;
                let value = decode_setting(field(row, "value")?, *kind)?;
                put_checked(
                    &tx,
                    &AppSetting {
                        key: key.into(),
                        value_json: value,
                        updated_at: at.clone(),
                    },
                )?;
            }
        }
        import_templates(&tx, &tables["prompt_templates"], &channels, &at)?;
        import_characters(&tx, &tables["character_profiles"], &channels, &at)?;
        import_readings(&tx, &tables, &at)?;
        import_schedules(&tx, &tables["channel_schedule_settings"], &channels, &at)?;
        import_secrets(
            &tx,
            &source,
            &channels,
            legacy_key,
            target_key,
            &at,
            &mut report,
        )?;
        for table in [
            "reading_dictionary_seed_state",
            "channel_schedule_migrations",
        ] {
            for (index, row) in tables[table].iter().enumerate() {
                preserve_row(&tx, table, row, &index.to_string(), &at, None)?;
            }
        }
        import_bgm(&tx, &tables["bgm_assets"], &channels, &at, options)?;
        if !tables["bgm_assets"].is_empty() {
            report.holds.push("旧BGMの音源と設定を保持しました。利用規約・クレジットが未登録のため、確認するまでQAで自動採用を保留してください。".into());
        }
        put_checked(
            &tx,
            &AppSetting {
                key: stamp_key,
                value_json: json!({"source_sha256":before,"counts":report.source_counts}),
                updated_at: at.clone(),
            },
        )?;
        if digest_file(source_path)? != before {
            return Err(import_failure());
        }
        report.verified_records = report.source_counts.values().sum();
        tx.commit().map_err(db_failure)?;
        Ok(report)
    }
}

fn preserve_database_snapshot(
    tx: &Connection,
    path: &Path,
    hash: &str,
    key: &MasterKey,
    at: &Timestamp,
) -> Result<()> {
    let bytes = zeroize::Zeroizing::new(std::fs::read(path).map_err(|error| {
        io_failure(
            "E-IMPORT-SETTINGS",
            "元DBのsnapshotを読み込めません。",
            "バックアップを確認してください。",
            &error,
        )
    })?);
    if digest_bytes(&bytes) != hash {
        return Err(import_failure());
    }
    let name = format!("legacy:encrypted-settings-snapshot:{hash}");
    if let Some(existing) =
        repository::get::<AppSetting>(tx, &AppSettingKey { key: name.clone() }, None)?
    {
        if snapshot_plaintext(&existing.value_json, key)?.as_slice() != bytes.as_slice() {
            return Err(import_failure());
        }
    } else {
        put_checked(
            tx,
            &AppSetting {
                key: name.clone(),
                value_json: snapshot_envelope(&bytes, key)?,
                updated_at: at.clone(),
            },
        )?;
    }
    let persisted = repository::get::<AppSetting>(tx, &AppSettingKey { key: name }, None)?
        .ok_or_else(import_failure)?;
    if snapshot_plaintext(&persisted.value_json, key)?.as_slice() != bytes.as_slice() {
        return Err(import_failure());
    }
    Ok(())
}

fn channel(row: &Value, channels: &HashSet<ChannelId>) -> Result<ChannelId> {
    let id = ChannelId::new(field(row, "profile_id")?)?;
    if !channels.contains(&id) {
        return Err(import_failure());
    }
    Ok(id)
}

fn import_templates(
    tx: &Connection,
    rows: &[Value],
    channels: &HashSet<ChannelId>,
    at: &Timestamp,
) -> Result<()> {
    for row in rows {
        let id = channel(row, channels)?;
        let template_id = field(row, "template_id")?.to_owned();
        put_checked(
            tx,
            &PromptTemplate {
                channel_id: id.clone(),
                id: template_id.clone(),
                kind: field(row, "template_kind")?.into(),
                name: field(row, "template_name")?.into(),
                is_default: flag(row, "is_default")?,
            },
        )?;
        let body = serde_json::to_string(&json!({"format":"legacy-template-v1","fields":row}))
            .map_err(|_| import_failure())?;
        put_checked(
            tx,
            &PromptTemplateVersion {
                channel_id: id.clone(),
                template_id: template_id.clone(),
                version: 1,
                body,
                created_at: timestamp(row, "created_at")?,
                author: "import".into(),
                reason: "旧版テンプレートの全フィールドを初版として保持".into(),
            },
        )?;
        preserve_row(tx, "prompt_templates", row, &template_id, at, Some(&id))?;
    }
    Ok(())
}

fn import_characters(
    tx: &Connection,
    rows: &[Value],
    channels: &HashSet<ChannelId>,
    at: &Timestamp,
) -> Result<()> {
    for row in rows {
        let id = channel(row, channels)?;
        let character_id = field(row, "character_id")?.to_owned();
        let speaker = row
            .get("voice_speaker_id")
            .and_then(Value::as_i64)
            .map(|value| value.to_string())
            .unwrap_or(field(row, "voice_speaker")?.into());
        let styles =
            serde_json::from_str(field(row, "voice_styles_json")?).map_err(|_| import_failure())?;
        if !matches!(field(row, "voice_backend")?, "voicevox" | "aquestalk") {
            return Err(import_failure());
        }
        put_checked(
            tx,
            &Character {
                channel_id: id.clone(),
                id: character_id.clone(),
                name: field(row, "display_name")?.into(),
                voice_provider: field(row, "voice_backend")?.into(),
                speaker_id: speaker,
                style_map_json: styles,
                credit_text: field(row, "credit_text")?.into(),
                usage_rules_json: json!({"format":"legacy-character-v1","fields":row}),
                layer_manifest_sha256: None,
            },
        )?;
        preserve_row(tx, "character_profiles", row, &character_id, at, Some(&id))?;
    }
    Ok(())
}

fn import_readings(
    tx: &Connection,
    tables: &BTreeMap<&str, Vec<Value>>,
    _at: &Timestamp,
) -> Result<()> {
    for row in &tables["reading_dictionary_entries"] {
        if !matches!(field(row, "dict_type")?, "base" | "user") {
            return Err(import_failure());
        }
        put_checked(
            tx,
            &ReadingEntry {
                surface: field(row, "word")?.into(),
                source: field(row, "dict_type")?.into(),
                reading: field(row, "reading")?.into(),
                accent_json: Value::Null,
                updated_at: timestamp(row, "updated_at")?,
            },
        )?;
    }
    for row in &tables["reading_candidates"] {
        put_checked(
            tx,
            &ReadingCandidate {
                surface: field(row, "word")?.into(),
                reading: field(row, "reading")?.into(),
                reason: field(row, "reason")?.into(),
                source: field(row, "source")?.into(),
                auto_applied: flag(row, "auto_applied")?,
                review_required: flag(row, "review_required")?,
                updated_at: timestamp(row, "updated_at")?,
            },
        )?;
    }
    Ok(())
}

fn import_schedules(
    tx: &Connection,
    rows: &[Value],
    channels: &HashSet<ChannelId>,
    at: &Timestamp,
) -> Result<()> {
    for row in rows {
        let id = channel(row, channels)?;
        clock::timezone(field(row, "timezone_name")?)?;
        preserve_row(tx, "channel_schedule_settings", row, "slots", at, Some(&id))?;
        for key in ["shorts_slot_hours", "long_slot_hours"] {
            let hours: Vec<i64> =
                serde_json::from_str(field(row, key)?).map_err(|_| import_failure())?;
            let mut seen = BTreeSet::new();
            for hour in hours {
                if !(0..=23).contains(&hour) || !seen.insert(hour) {
                    return Err(import_failure());
                }
                for weekday in 0..7 {
                    put_checked(
                        tx,
                        &ScheduleSlot {
                            channel_id: id.clone(),
                            format: if key == "shorts_slot_hours" {
                                "shorts"
                            } else {
                                "long"
                            }
                            .into(),
                            weekday,
                            local_time: format!("{hour:02}:00"),
                        },
                    )?;
                }
            }
        }
    }
    Ok(())
}

fn import_policy(tx: &Connection, id: &ChannelId, policy: &Value, at: &Timestamp) -> Result<()> {
    let shorts = integer(policy, "daily_shorts")?;
    let longs = integer(policy, "daily_longs")?;
    let start = integer(policy, "start_hour")?;
    let score = integer(policy, "min_score")?;
    let paid = integer(policy, "daily_paid_limit")?;
    if policy.get("enabled").and_then(Value::as_bool).is_none()
        || shorts < 0
        || longs < 0
        || !(0..=23).contains(&start)
        || !(0..=100).contains(&score)
        || paid < 0
    {
        return Err(import_failure());
    }
    let daily = shorts.checked_add(longs).ok_or_else(import_failure)?;
    let reason = "旧版のAPI回数上限は金額予算へ換算できません。予算設定と再承認が必要です。";
    put_checked(
        tx,
        &ChannelSetting {
            channel_id: id.clone(),
            key: "legacy:autopilot_policy".into(),
            value_json: policy.clone(),
            updated_at: at.clone(),
        },
    )?;
    put_checked(
        tx,
        &AutopilotPolicy {
            channel_id: id.clone(),
            enabled: false,
            daily_count: daily,
            quality_threshold: score as f64,
            budget_micros: 0,
            window_json: json!({"start_hour":start,"daily_shorts":shorts,"daily_longs":longs}),
            paused_reason: Some(reason.into()),
            paused_at: Some(at.clone()),
        },
    )?;
    put_checked(
        tx,
        &Notification {
            channel_id: id.clone(),
            id: "legacy-settings-autopilot-hold".into(),
            kind: "migration".into(),
            severity: "warning".into(),
            dedupe_key: "legacy-settings-autopilot-hold".into(),
            message_key: "migration.autopilot_budget_required".into(),
            args_json: json!({"reason":reason}),
            created_at: at.clone(),
            resolved_at: None,
        },
    )
}

fn import_secrets(
    tx: &Connection,
    source: &Connection,
    channels: &HashSet<ChannelId>,
    legacy_key: Option<&MasterKey>,
    target_key: &MasterKey,
    at: &Timestamp,
    report: &mut ImportReport,
) -> Result<()> {
    let mut statement=source.prepare("SELECT profile_id,secret_type,nonce,encrypted_value,key_version FROM encrypted_secrets ORDER BY secret_id").map_err(db_failure)?;
    let mut rows = statement.query([]).map_err(db_failure)?;
    let mut count = 0;
    while let Some(row) = rows.next().map_err(db_failure)? {
        let profile: String = row.get(0).map_err(db_failure)?;
        let secret_type: String = row.get(1).map_err(db_failure)?;
        let id = ChannelId::new(profile)?;
        if !channels.contains(&id) || row.get::<_, i64>(4).map_err(db_failure)? != 1 {
            return Err(import_failure());
        }
        let nonce: Vec<u8> = row.get(2).map_err(db_failure)?;
        let ciphertext: Vec<u8> = row.get(3).map_err(db_failure)?;
        let value = legacy_key
            .ok_or_else(import_failure)?
            .decrypt_legacy(&nonce, &ciphertext)?;
        std::str::from_utf8(&value).map_err(|_| import_failure())?;
        let existing:Option<(Vec<u8>,Vec<u8>,i64)>=tx.query_row("SELECT nonce,encrypted_value,key_version FROM secrets WHERE channel_id=?1 AND secret_type=?2",params![id.as_str(),secret_type],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional().map_err(db_failure)?;
        if let Some((nonce, ciphertext, version)) = existing {
            if version != 2
                || target_key
                    .decrypt(&id, &secret_type, &nonce, &ciphertext)?
                    .as_slice()
                    != value.as_slice()
            {
                return Err(import_failure());
            }
        } else {
            let (nonce, ciphertext) = target_key.encrypt(&id, &secret_type, &value)?;
            tx.execute("INSERT INTO secrets(channel_id,secret_type,nonce,encrypted_value,key_version,updated_at) VALUES(?1,?2,?3,?4,2,?5)",params![id.as_str(),secret_type,nonce.as_slice(),ciphertext,at.to_utc_iso()]).map_err(db_failure)?;
        }
        let persisted: (Vec<u8>, Vec<u8>) = tx
            .query_row(
                "SELECT nonce,encrypted_value FROM secrets WHERE channel_id=?1 AND secret_type=?2",
                params![id.as_str(), secret_type],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .map_err(db_failure)?;
        if target_key
            .decrypt(&id, &secret_type, &persisted.0, &persisted.1)?
            .as_slice()
            != value.as_slice()
        {
            return Err(import_failure());
        }
        count += 1;
    }
    report
        .source_counts
        .insert("encrypted_secrets".into(), count);
    Ok(())
}

fn import_bgm(
    tx: &Connection,
    rows: &[Value],
    channels: &HashSet<ChannelId>,
    at: &Timestamp,
    options: &SettingsImportOptions,
) -> Result<()> {
    for row in rows {
        let id = channel(row, channels)?;
        let bgm_id = field(row, "bgm_id")?;
        let source = options.bgm_files.get(bgm_id).ok_or_else(import_failure)?;
        // 入力を先に検証し、元BGM情報は全フィールドを保持する。
        let duration = match row.get("duration_sec").and_then(Value::as_f64) {
            Some(seconds)
                if seconds.is_finite()
                    && seconds >= 0.0
                    && seconds < (i64::MAX as f64) / 1000.0 =>
            {
                (seconds * 1000.0).round() as i64
            }
            None if row.get("duration_sec") == Some(&Value::Null) => *options
                .bgm_durations_ms
                .get(bgm_id)
                .ok_or_else(import_failure)?,
            _ => return Err(import_failure()),
        };
        if duration < 0 {
            return Err(import_failure());
        }
        for key in ["loop_enabled", "is_enabled", "is_default"] {
            flag(row, key)?;
        }
        row.get("default_volume_db")
            .and_then(Value::as_f64)
            .filter(|value| value.is_finite())
            .ok_or_else(import_failure)?;
        preserve_row(tx, "bgm_assets", row, bgm_id, at, Some(&id))?;
        let copied = picocast_core::fsutil::import_content_addressed(source, &options.assets_root)?;
        let bytes = i64::try_from(copied.bytes).map_err(|_| import_failure())?;
        put_asset_checked(
            tx,
            &Asset {
                sha256: copied.sha256.clone(),
                kind: "audio".into(),
                ext: copied.ext.clone(),
                bytes,
                created_at: timestamp(row, "created_at")?,
                provenance_json: json!({"source":"legacy-bgm-backup"}),
            },
        )?;
        put_checked(
            tx,
            &AssetRef {
                channel_id: id.clone(),
                owner_kind: "channel".into(),
                owner_id: id.as_str().into(),
                sha256: copied.sha256.clone(),
                role: format!("bgm:{bgm_id}"),
            },
        )?;
        put_checked(
            tx,
            &MusicTags {
                sha256: copied.sha256,
                mood: "未分類".into(),
                tempo_bpm: None,
                duration_ms: duration,
                loop_start_ms: None,
                loop_end_ms: None,
                manual: true,
            },
        )?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "imports_tests.rs"]
mod tests;
