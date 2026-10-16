//! 明示したバックアップだけを取り込み、照合結果をJSONで返す開発用入口。
use anyhow::{bail, Result};
use picocast_core::{clock::Timestamp, ChannelId};
use picocast_store::{
    channel_import::ChannelImportOptions,
    imports::{SettingKind, SettingsImportOptions},
    DataMode, MasterKey, Store, StoreOptions, StorePaths,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Configuration {
    Initialize {
        destination: Destination,
    },
    Settings {
        destination: Destination,
        source: SettingsSource,
    },
    Channel {
        destination: Destination,
        source: ChannelSource,
    },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Destination {
    data_parent: PathBuf,
    mode: Mode,
    master_key: PathBuf,
    busy_timeout_ms: u64,
    backup_pages_per_step: i32,
    backup_pause_ms: u64,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Mode {
    Production,
    Development,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SettingsSource {
    backup_root: PathBuf,
    original_root: PathBuf,
    database: PathBuf,
    master_key: Option<PathBuf>,
    language: String,
    timezone: String,
    setting_types: BTreeMap<String, JsonSettingKind>,
    retired_settings: BTreeSet<String>,
    bgm_files: BTreeMap<String, PathBuf>,
    bgm_durations_ms: BTreeMap<String, i64>,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum JsonSettingKind {
    Boolean,
    Integer,
    Decimal,
    Json,
    Text,
}
impl From<JsonSettingKind> for SettingKind {
    fn from(value: JsonSettingKind) -> Self {
        match value {
            JsonSettingKind::Boolean => Self::Boolean,
            JsonSettingKind::Integer => Self::Integer,
            JsonSettingKind::Decimal => Self::Decimal,
            JsonSettingKind::Json => Self::Json,
            JsonSettingKind::Text => Self::Text,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ChannelSource {
    backup_root: PathBuf,
    original_root: PathBuf,
    database: PathBuf,
    output_root: PathBuf,
    original_output_root: PathBuf,
    channel_id: String,
    timezone: String,
    imported_at: Timestamp,
    synthetic_media: bool,
    verified_running_jobs: BTreeMap<String, i64>,
}

fn config_error() -> anyhow::Error {
    anyhow::anyhow!("[E-IMPORT-CONFIG] 取り込み設定が不正です。JSONの形式・必須項目・絶対パス・バックアップ範囲を確認してください。")
}

fn parse_args(args: &[String]) -> Result<(&str, &Path)> {
    if args.len() != 3
        || !matches!(
            args[0].as_str(),
            "--settings" | "--channel" | "--initialize"
        )
        || args[1] != "--config"
    {
        bail!("使い方: cargo xtask import-legacy --initialize|--settings|--channel --config <JSONの絶対パス>");
    }
    let path = Path::new(&args[2]);
    if !path.is_absolute() {
        return Err(config_error());
    }
    Ok((&args[0], path))
}

fn load_config(path: &Path) -> Result<Configuration> {
    let bytes = std::fs::read(path).map_err(|_| config_error())?;
    // serdeの詳細には入力値が含まれ得るため、そのまま表示しない。
    serde_json::from_slice(&bytes).map_err(|_| config_error())
}

fn canonical(path: &Path) -> Result<PathBuf> {
    if !path.is_absolute() {
        return Err(config_error());
    }
    path.canonicalize().map_err(|_| config_error())
}

fn backup_path(path: &Path, backup_root: &Path, original_root: &Path) -> Result<PathBuf> {
    let backup = canonical(backup_root)?;
    let original = canonical(original_root)?;
    let target = canonical(path)?;
    if backup.starts_with(&original)
        || target.starts_with(&original)
        || !target.starts_with(&backup)
        || target == backup
    {
        return Err(config_error());
    }
    Ok(target)
}

fn destination_paths(
    destination: &Destination,
    backup_root: &Path,
    original_root: &Path,
) -> Result<StorePaths> {
    let mode = match destination.mode {
        Mode::Production => DataMode::Production,
        Mode::Development => DataMode::Development,
    };
    let paths = StorePaths::new(&destination.data_parent, mode)?;
    let resolved = canonical(&paths.root)?;
    let original = canonical(original_root)?;
    // 同じディレクトリ木を入力と出力にしない。キーも共通の正本に一致させる。
    if destination.master_key != paths.master_key
        || resolved.starts_with(backup_root)
        || backup_root.starts_with(&resolved)
        || resolved.starts_with(&original)
        || original.starts_with(&resolved)
    {
        return Err(config_error());
    }
    Ok(paths)
}

fn open_store(destination: &Destination, paths: &StorePaths) -> Result<Store> {
    Ok(Store::open(
        paths,
        StoreOptions {
            busy_timeout: Duration::from_millis(destination.busy_timeout_ms),
            backup_pages_per_step: destination.backup_pages_per_step,
            backup_pause: Duration::from_millis(destination.backup_pause_ms),
        },
    )?)
}

fn execute(mode: &str, config: Configuration) -> Result<Value> {
    match config {
        Configuration::Initialize { destination } if mode == "--initialize" => {
            let mode = match destination.mode {
                Mode::Production => DataMode::Production,
                Mode::Development => DataMode::Development,
            };
            let paths = StorePaths::new(&destination.data_parent, mode)?;
            paths.validate_storage(&Default::default())?;
            if destination.master_key != paths.master_key
                || paths.database.try_exists().map_err(|_| config_error())?
                || paths.master_key.try_exists().map_err(|_| config_error())?
            {
                return Err(config_error());
            }
            if paths.root.try_exists().map_err(|_| config_error())?
                && std::fs::read_dir(&paths.root)
                    .map_err(|_| config_error())?
                    .next()
                    .is_some()
            {
                return Err(config_error());
            }
            let _store = open_store(&destination, &paths)?;
            let _key = MasterKey::create(&paths.master_key)?;
            Ok(json!({"kind":"initialize","status":"initialized","operation":"inactive"}))
        }
        Configuration::Settings {
            destination,
            source,
        } if mode == "--settings" => {
            let database =
                backup_path(&source.database, &source.backup_root, &source.original_root)?;
            let backup = canonical(&source.backup_root)?;
            let paths = destination_paths(&destination, &backup, &source.original_root)?;
            let target_key = MasterKey::load(&destination.master_key)?;
            let old_key = source
                .master_key
                .as_ref()
                .map(|path| {
                    backup_path(path, &source.backup_root, &source.original_root)
                        .and_then(|path| Ok(MasterKey::load(&path)?))
                })
                .transpose()?;
            let mut bgm_files = BTreeMap::new();
            for (id, path) in source.bgm_files {
                bgm_files.insert(
                    id,
                    backup_path(&path, &source.backup_root, &source.original_root)?,
                );
            }
            let mut store = open_store(&destination, &paths)?;
            let report = store.import_legacy_settings(
                &database,
                old_key.as_ref(),
                &target_key,
                &SettingsImportOptions {
                    setting_types: source
                        .setting_types
                        .into_iter()
                        .map(|(key, kind)| (key, kind.into()))
                        .collect(),
                    retired_settings: source.retired_settings,
                    language: source.language,
                    timezone: source.timezone,
                    bgm_files,
                    assets_root: paths.assets_directory(),
                    bgm_durations_ms: source.bgm_durations_ms,
                },
            )?;
            let status = if report.holds.is_empty() {
                "verified"
            } else {
                "verified_with_holds"
            };
            Ok(json!({"kind":"settings","status":status,"verification":"matched","report":report}))
        }
        Configuration::Channel {
            destination,
            source,
        } if mode == "--channel" => {
            let database =
                backup_path(&source.database, &source.backup_root, &source.original_root)?;
            let output_root = backup_path(
                &source.output_root,
                &source.backup_root,
                &source.original_root,
            )?;
            let backup = canonical(&source.backup_root)?;
            let paths = destination_paths(&destination, &backup, &source.original_root)?;
            // チャンネル取込でも宛先の既存キーを検査し、誤った新環境を作らない。
            let _target_key = MasterKey::load(&destination.master_key)?;
            if !source.original_output_root.is_absolute()
                || !source
                    .original_output_root
                    .starts_with(&source.original_root)
            {
                return Err(config_error());
            }
            // PIDだけでは起動時刻・コマンドを検証できない。CLIは稼働中処理を引き継がない。
            if !source.verified_running_jobs.is_empty() {
                return Err(config_error());
            }
            let mut store = open_store(&destination, &paths)?;
            let report = store.import_legacy_channel(
                &ChannelId::new(source.channel_id)?,
                &ChannelImportOptions {
                    metadata_path: database,
                    output_root,
                    original_output_root: source.original_output_root,
                    assets_root: paths.assets_directory(),
                    source_timezone: source.timezone,
                    imported_at: source.imported_at,
                    synthetic_media: source.synthetic_media,
                    verified_running_jobs: BTreeMap::new(),
                },
            )?;
            let status = if report.held_jobs + report.abandoned_jobs > 0 {
                "verified_with_holds"
            } else {
                "verified"
            };
            Ok(
                json!({"kind":"channel","status":status,"verification":"matched","operation":"legacy","report":report}),
            )
        }
        _ => Err(config_error()),
    }
}

fn run_checked(args: &[String]) -> Result<()> {
    let (mode, path) = parse_args(args)?;
    let report = execute(mode, load_config(path)?)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&report).map_err(|_| config_error())?
    );
    Ok(())
}

pub fn run(args: &[String]) -> Result<()> {
    if let Err(error) = run_checked(args) {
        // CLIの最上位境界。anyhowのDebugやbacktraceを標準エラーへ流さない。
        eprintln!("{error}");
        std::process::exit(1);
    }
    Ok(())
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn parser_requires_explicit_mode_absolute_config_and_no_unknown_flags() {
        let path = std::env::current_dir()
            .unwrap()
            .join("fixture.json")
            .to_string_lossy()
            .into_owned();
        assert!(parse_args(&["--settings".into(), "--config".into(), path]).is_ok());
        assert!(parse_args(&[]).is_err());
        assert!(parse_args(&[
            "--settings".into(),
            "--config".into(),
            "relative.json".into()
        ])
        .is_err());
        assert!(parse_args(&["--live".into(), "--config".into(), "x".into()]).is_err());
        assert!(serde_json::from_value::<Configuration>(
            json!({"kind":"settings","unexpected":"secret-value"})
        )
        .is_err());
    }

    #[test]
    fn backup_scope_rejects_live_paths_and_directory_escape() {
        let temp = tempfile::tempdir().unwrap();
        let original = temp.path().join("original");
        let backup = temp.path().join("backup");
        std::fs::create_dir_all(&original).unwrap();
        std::fs::create_dir_all(&backup).unwrap();
        let live = original.join("settings.db");
        let copy = backup.join("settings.db");
        picocast_core::fsutil::atomic_write(&live, b"live").unwrap();
        picocast_core::fsutil::atomic_write(&copy, b"copy").unwrap();
        assert!(backup_path(&live, &backup, &original).is_err());
        assert!(backup_path(&copy, &backup, &original).is_ok());
        assert!(backup_path(&copy, &backup, &backup).is_err());
        assert_eq!(std::fs::read(live).unwrap(), b"live");
    }

    #[test]
    fn documented_configs_are_valid_and_nested_unknown_fields_are_rejected() {
        let document = include_str!("../../docs/legacy-import.md").replace("\r\n", "\n");
        let mut count = 0;
        for block in document.split("```json\n").skip(1) {
            let text = block.split_once("\n```").unwrap().0;
            let value: Value = serde_json::from_str(text).unwrap();
            assert!(serde_json::from_value::<Configuration>(value.clone()).is_ok());
            for location in ["source", "destination"] {
                let mut invalid = value.clone();
                invalid[location]["unexpected"] = json!("synthetic-sensitive-value");
                assert!(serde_json::from_value::<Configuration>(invalid).is_err());
            }
            count += 1;
        }
        assert_eq!(count, 3);
    }

    #[test]
    fn malformed_config_errors_do_not_echo_values() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("invalid.json");
        picocast_core::fsutil::atomic_write(&path, b"{\"kind\":\"synthetic-sensitive-value\"}")
            .unwrap();
        let error = load_config(&path).err().unwrap().to_string();
        assert!(error.contains("E-IMPORT-CONFIG"));
        assert!(!error.contains("synthetic-sensitive-value"));
    }

    fn destination(parent: &Path) -> Destination {
        let paths = StorePaths::new(parent, DataMode::Development).unwrap();
        Destination {
            data_parent: parent.into(),
            mode: Mode::Development,
            master_key: paths.master_key,
            busy_timeout_ms: 5000,
            backup_pages_per_step: 16,
            backup_pause_ms: 1,
        }
    }

    #[cfg(windows)]
    #[test]
    fn explicit_initialize_creates_new_target_and_never_replaces_existing_key_or_database() {
        let temp = tempfile::tempdir().unwrap();
        let first = execute(
            "--initialize",
            Configuration::Initialize {
                destination: destination(temp.path()),
            },
        )
        .unwrap();
        assert_eq!(first["status"], "initialized");
        let paths = StorePaths::new(temp.path(), DataMode::Development).unwrap();
        let key = std::fs::read(&paths.master_key).unwrap();
        let db = std::fs::read(&paths.database).unwrap();
        assert!(execute(
            "--initialize",
            Configuration::Initialize {
                destination: destination(temp.path())
            }
        )
        .is_err());
        assert_eq!(std::fs::read(&paths.master_key).unwrap(), key);
        assert_eq!(std::fs::read(&paths.database).unwrap(), db);
        let backup = temp.path().join("backup");
        std::fs::create_dir_all(&backup).unwrap();
        assert!(destination_paths(
            &destination(temp.path()),
            &canonical(&backup).unwrap(),
            &canonical(&paths.root).unwrap()
        )
        .is_err());
        let original_child = paths.root.join("old_source");
        std::fs::create_dir_all(&original_child).unwrap();
        assert!(destination_paths(
            &destination(temp.path()),
            &canonical(&backup).unwrap(),
            &canonical(&original_child).unwrap()
        )
        .is_err());
    }

    #[test]
    fn initialize_rejects_existing_payload_before_creating_db_or_key() {
        let temp = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(temp.path(), DataMode::Development).unwrap();
        std::fs::create_dir_all(&paths.root).unwrap();
        let keep = paths.root.join("keep.txt");
        picocast_core::fsutil::atomic_write(&keep, b"keep").unwrap();
        assert!(execute(
            "--initialize",
            Configuration::Initialize {
                destination: destination(temp.path())
            }
        )
        .is_err());
        assert_eq!(std::fs::read(keep).unwrap(), b"keep");
        assert!(!paths.database.exists());
        assert!(!paths.master_key.exists());
    }
}
