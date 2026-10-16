//! 旧チャンネルのバックアップを読み取り、原記録と内容アドレス素材を照合して保存する。

use crate::repository::{
    Asset, AssetRef, AuditEntry, AuditEntryKey, Channel, ChannelKey, Job, JobStep, Project,
    ProjectRevision, Topic, Upload, YoutubeVideo,
};
use crate::{db_failure, imports, repository, Store};
use picocast_core::{
    clock::{self, Timestamp},
    fsutil, ChannelId, Result,
};
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// output_rootはコピーの実体、original_output_rootは旧DBに保存された元の出力ルート。
pub struct ChannelImportOptions {
    pub metadata_path: PathBuf,
    pub output_root: PathBuf,
    pub original_output_root: PathBuf,
    pub assets_root: PathBuf,
    pub source_timezone: String,
    pub imported_at: Timestamp,
    pub synthetic_media: bool,
    /// 呼出側で起動時刻・実行内容・チャンネルまで照合したjob_idとPIDだけを入れる。
    pub verified_running_jobs: BTreeMap<String, i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChannelImportReport {
    pub source_sha256: String,
    pub source_counts: BTreeMap<String, usize>,
    pub projects: usize,
    pub assets: usize,
    pub abandoned_jobs: usize,
    pub held_jobs: usize,
    pub analytics_preserved: usize,
    pub excluded_protected_files: Vec<String>,
    pub cas_root: PathBuf,
}

#[derive(Clone, Serialize, Deserialize)]
struct ImportedAsset {
    relative_path: String,
    sha256: String,
    bytes: u64,
    ext: String,
    owner_id: Option<String>,
}

type Tables = BTreeMap<String, Vec<Value>>;

impl Store {
    /// 旧DBはオンラインバックアップ済みの単体ファイルだけを受け付ける。
    /// 失敗時は登録をrollbackし、共有され得るCAS実体は削除しない。
    pub fn import_legacy_channel(
        &mut self,
        channel_id: &ChannelId,
        options: &ChannelImportOptions,
    ) -> Result<ChannelImportReport> {
        let channel = repository::get::<Channel>(
            &self.connection,
            &ChannelKey {
                channel_id: channel_id.clone(),
            },
            None,
        )?
        .ok_or_else(imports::import_failure)?;
        if channel.operator != "legacy"
            || channel.archived_at.is_some()
            || channel.timezone.as_deref() != Some(options.source_timezone.as_str())
            || !options.original_output_root.is_absolute()
            || !options.output_root.is_absolute()
            || !options.assets_root.is_absolute()
        {
            return Err(imports::import_failure());
        }
        clock::timezone(&options.source_timezone)?;
        let language = channel
            .language
            .as_ref()
            .filter(|value| !value.is_empty())
            .ok_or_else(imports::import_failure)?
            .clone();
        let before = imports::digest_file(&options.metadata_path)?;
        let source = imports::open_legacy(&options.metadata_path)?;
        let tables = read_tables(&source)?;
        let videos = rows(&tables, "videos");
        if !tables.contains_key("videos") {
            return Err(imports::import_failure());
        }
        let directories = project_directories(videos, options)?;
        let (assets, excluded_protected_files) = collect_assets(options, &directories)?;
        let audit_id = format!("legacy-metadata:{}", channel_id.as_str());
        let previous = repository::get::<AuditEntry>(
            &self.connection,
            &AuditEntryKey {
                id: audit_id.clone(),
            },
            None,
        )?;
        let at = previous.map_or_else(|| options.imported_at.clone(), |record| record.at);
        let tx = self.connection.transaction().map_err(db_failure)?;
        let mut report = ChannelImportReport {
            source_sha256: before.clone(),
            source_counts: tables
                .iter()
                .map(|(table, values)| (table.clone(), values.len()))
                .collect(),
            projects: videos.len(),
            assets: assets.len(),
            abandoned_jobs: 0,
            held_jobs: 0,
            analytics_preserved: rows(&tables, "analytics_snapshots").len(),
            excluded_protected_files,
            cas_root: options.assets_root.clone(),
        };
        import_topics(&tx, channel_id, &tables, options, &at)?;
        for video in videos {
            import_project(
                &tx, channel_id, video, &tables, &assets, options, &at, &language,
            )?;
        }
        import_assets(&tx, channel_id, &assets, &at)?;
        import_jobs(&tx, channel_id, &tables, options, &at, &mut report)?;
        // 期間累計の分析を日次値と偽って保存しない。全指標と未知の列・表も原記録へ残す。
        imports::put_checked(
            &tx,
            &AuditEntry {
                id: audit_id,
                at: at.clone(),
                actor: "import".into(),
                action: "legacy_channel_import".into(),
                target: channel_id.as_str().into(),
                detail_json: json!({"source_sha256":before, "source_timezone":options.source_timezone,
                "tables":tables, "assets":assets, "source_counts":report.source_counts,
                "excluded_protected_files":report.excluded_protected_files}),
            },
        )?;
        verify_assets(options, &assets, &report.excluded_protected_files)?;
        if imports::digest_file(&options.metadata_path)? != before {
            return Err(imports::import_failure());
        }
        tx.commit().map_err(db_failure)?;
        drop(source);
        Ok(report)
    }
}

fn read_tables(source: &Connection) -> Result<Tables> {
    let mut statement = source.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        .map_err(db_failure)?;
    let names = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(db_failure)?
        .collect::<rusqlite::Result<Vec<_>>>()
        .map_err(db_failure)?;
    let mut tables = BTreeMap::new();
    for name in names {
        let mut values = imports::read_table(source, &name)?;
        values.sort_by_key(Value::to_string);
        tables.insert(name, values);
    }
    Ok(tables)
}

fn rows<'a>(tables: &'a Tables, table: &str) -> &'a [Value] {
    tables.get(table).map_or(&[], Vec::as_slice)
}

fn optional_text(row: &Value, field: &str) -> Result<Option<String>> {
    match row.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        _ => Err(imports::import_failure()),
    }
}

fn time(row: &Value, key: &str, options: &ChannelImportOptions) -> Result<Option<Timestamp>> {
    optional_text(row, key)?
        .map(|value| clock::parse_legacy(&value, &options.source_timezone))
        .transpose()
}

fn related(tables: &Tables, table: &str, local_id: &str) -> Result<Option<Value>> {
    let matches: Vec<_> = rows(tables, table)
        .iter()
        .filter(|row| row.get("local_id").and_then(Value::as_str) == Some(local_id))
        .collect();
    match matches.as_slice() {
        [] => Ok(None),
        [one] => Ok(Some((*one).clone())),
        _ => Err(imports::import_failure()),
    }
}

fn project_id(local_id: &str) -> String {
    format!("legacy-video:{local_id}")
}
fn topic_id(local_id: &str) -> String {
    format!("legacy-topic:{local_id}")
}

fn project_directories(
    videos: &[Value],
    options: &ChannelImportOptions,
) -> Result<BTreeMap<PathBuf, String>> {
    let mut directories = BTreeMap::new();
    for row in videos {
        let id = imports::field(row, "local_id")?;
        if id.is_empty() {
            return Err(imports::import_failure());
        }
        if let Some(directory) = optional_text(row, "output_dir")?.filter(|value| !value.is_empty())
        {
            let original = Path::new(&directory);
            let relative = original
                .strip_prefix(&options.original_output_root)
                .map_err(|_| imports::import_failure())?;
            if relative
                .components()
                .any(|part| !matches!(part, std::path::Component::Normal(_)))
                || directories
                    .insert(relative.to_path_buf(), project_id(id))
                    .is_some()
            {
                return Err(imports::import_failure());
            }
        }
    }
    Ok(directories)
}

fn collect_assets(
    options: &ChannelImportOptions,
    directories: &BTreeMap<PathBuf, String>,
) -> Result<(Vec<ImportedAsset>, Vec<String>)> {
    let scan = scan_assets(options)?;
    let mut output = Vec::new();
    for path in scan.files {
        let relative = path
            .strip_prefix(&scan.root)
            .map_err(|_| imports::import_failure())?;
        let owner_id = directories
            .iter()
            .filter(|(directory, _)| relative.starts_with(directory))
            .max_by_key(|(directory, _)| directory.components().count())
            .map(|(_, id)| id.clone());
        let copied = fsutil::import_content_addressed(&path, &options.assets_root)?;
        output.push(ImportedAsset {
            relative_path: relative
                .to_str()
                .ok_or_else(imports::import_failure)?
                .replace('\\', "/"),
            sha256: copied.sha256,
            bytes: copied.bytes,
            ext: copied.ext,
            owner_id,
        });
    }
    Ok((output, scan.excluded))
}

struct AssetScan {
    root: PathBuf,
    files: Vec<PathBuf>,
    excluded: Vec<String>,
}

fn scan_assets(options: &ChannelImportOptions) -> Result<AssetScan> {
    let root =
        std::fs::canonicalize(&options.output_root).map_err(|_| imports::import_failure())?;
    if resolve_destination(&options.assets_root)?.starts_with(&root) {
        return Err(imports::import_failure());
    }
    let source_db =
        std::fs::canonicalize(&options.metadata_path).map_err(|_| imports::import_failure())?;
    let mut pending = vec![root.clone()];
    let mut files = Vec::new();
    let mut excluded = Vec::new();
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(directory).map_err(|_| imports::import_failure())? {
            let entry = entry.map_err(|_| imports::import_failure())?;
            let metadata = entry.metadata().map_err(|_| imports::import_failure())?;
            if entry
                .file_type()
                .map_err(|_| imports::import_failure())?
                .is_symlink()
                || is_reparse(&metadata)
            {
                return Err(imports::import_failure());
            }
            if metadata.is_dir() {
                pending.push(entry.path());
            } else if metadata.is_file() {
                let path = entry.path();
                if path != source_db && !protected_source(&path) {
                    files.push(path);
                } else {
                    excluded.push(
                        path.strip_prefix(&root)
                            .map_err(|_| imports::import_failure())?
                            .to_str()
                            .ok_or_else(imports::import_failure)?
                            .replace('\\', "/"),
                    );
                }
            } else {
                return Err(imports::import_failure());
            }
        }
    }
    files.sort();
    excluded.sort();
    Ok(AssetScan {
        root,
        files,
        excluded,
    })
}

fn resolve_destination(path: &Path) -> Result<PathBuf> {
    let mut existing = path;
    let mut suffix = Vec::new();
    while !existing
        .try_exists()
        .map_err(|_| imports::import_failure())?
    {
        suffix.push(
            existing
                .file_name()
                .ok_or_else(imports::import_failure)?
                .to_os_string(),
        );
        existing = existing.parent().ok_or_else(imports::import_failure)?;
    }
    let mut canonical = std::fs::canonicalize(existing).map_err(|_| imports::import_failure())?;
    for part in suffix.into_iter().rev() {
        canonical.push(part);
    }
    Ok(canonical)
}

// DB・sidecar・認証情報は素材の保存先へ複製しない。元ファイルはそのまま保護する。
fn protected_source(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    name.starts_with(".env")
        || name.contains("secret")
        || name.contains("token")
        || matches!(
            extension.as_str(),
            "db" | "sqlite" | "sqlite3" | "key" | "pem" | "pfx" | "p12"
        )
        || ["-wal", "-shm", "-journal"]
            .iter()
            .any(|suffix| name.ends_with(suffix))
}

#[cfg(windows)]
fn is_reparse(metadata: &std::fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;
    metadata.file_attributes() & 0x400 != 0
}
#[cfg(not(windows))]
fn is_reparse(_metadata: &std::fs::Metadata) -> bool {
    false
}

fn verify_assets(
    options: &ChannelImportOptions,
    assets: &[ImportedAsset],
    excluded: &[String],
) -> Result<()> {
    let scan = scan_assets(options)?;
    let actual = scan
        .files
        .iter()
        .map(|path| {
            path.strip_prefix(&scan.root)
                .map_err(|_| imports::import_failure())?
                .to_str()
                .map(|value| value.replace('\\', "/"))
                .ok_or_else(imports::import_failure)
        })
        .collect::<Result<Vec<_>>>()?;
    if actual
        != assets
            .iter()
            .map(|asset| asset.relative_path.clone())
            .collect::<Vec<_>>()
        || scan.excluded != excluded
    {
        return Err(imports::import_failure());
    }
    for asset in assets {
        if imports::digest_file(&options.output_root.join(&asset.relative_path))? != asset.sha256 {
            return Err(imports::import_failure());
        }
    }
    Ok(())
}

fn import_topics(
    tx: &Connection,
    channel: &ChannelId,
    tables: &Tables,
    options: &ChannelImportOptions,
    at: &Timestamp,
) -> Result<()> {
    for row in rows(tables, "topic_history") {
        let local_id = imports::field(row, "local_id")?;
        imports::put_checked(
            tx,
            &Topic {
                channel_id: channel.clone(),
                id: topic_id(local_id),
                title: optional_text(row, "title")?.unwrap_or_default(),
                source: "legacy".into(),
                source_ref: optional_text(row, "topic_key")?,
                priority: 0,
                due_at: None,
                status: optional_text(row, "status")?.unwrap_or_else(|| "legacy_unset".into()),
                created_at: time(row, "created_at", options)?.unwrap_or_else(|| at.clone()),
            },
        )?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn import_project(
    tx: &Connection,
    channel: &ChannelId,
    video: &Value,
    tables: &Tables,
    assets: &[ImportedAsset],
    options: &ChannelImportOptions,
    at: &Timestamp,
    language: &str,
) -> Result<()> {
    let local_id = imports::field(video, "local_id")?;
    let id = project_id(local_id);
    let metadata = related(tables, "video_metadata", local_id)?.unwrap_or(Value::Null);
    let youtube = related(tables, "youtube_status", local_id)?.unwrap_or(Value::Null);
    let youtube_id = optional_text(&youtube, "youtube_video_id")?.filter(|value| !value.is_empty());
    let created = time(video, "created_at", options)?.unwrap_or_else(|| at.clone());
    let updated = time(video, "updated_at", options)?.unwrap_or_else(|| created.clone());
    let tags = match optional_text(&metadata, "tags")? {
        Some(value) => {
            let tags: Value =
                serde_json::from_str(&value).map_err(|_| imports::import_failure())?;
            if !tags
                .as_array()
                .is_some_and(|items| items.iter().all(Value::is_string))
            {
                return Err(imports::import_failure());
            }
            tags
        }
        None => json!([]),
    };
    let topic = rows(tables, "topic_history")
        .iter()
        .any(|row| row.get("local_id").and_then(Value::as_str) == Some(local_id))
        .then(|| topic_id(local_id));
    let project = Project {
        channel_id: channel.clone(),
        id: id.clone(),
        format: optional_text(video, "video_type")?.unwrap_or_else(|| "legacy_unset".into()),
        language: language.into(),
        status: optional_text(&youtube, "publish_status")?.unwrap_or_else(|| "legacy_unset".into()),
        topic_id: topic,
        title: optional_text(video, "title")?.unwrap_or_default(),
        description: optional_text(&metadata, "description")?.unwrap_or_default(),
        tags_json: tags,
        publish_at: time(&youtube, "publish_at", options)?,
        synthetic_media: options.synthetic_media,
        youtube_video_id: youtube_id.clone(),
        current_revision: 1,
        created_at: created.clone(),
        updated_at: updated.clone(),
    };
    imports::put_checked(tx, &project)?;
    let raw: BTreeMap<_, Vec<_>> = tables
        .iter()
        .map(|(table, values)| {
            (
                table.clone(),
                values
                    .iter()
                    .filter(|row| {
                        row.get("local_id").and_then(Value::as_str) == Some(local_id)
                            || youtube_id.as_ref().is_some_and(|id| {
                                row.get("youtube_video_id").and_then(Value::as_str) == Some(id)
                            })
                    })
                    .cloned()
                    .collect(),
            )
        })
        .collect();
    imports::put_checked(
        tx,
        &ProjectRevision {
            channel_id: channel.clone(),
            project_id: id.clone(),
            revision: 1,
            snapshot_json: json!({"kind":"legacy_metadata", "script_content":video.get("script_content"),
            "tables":raw, "assets":assets.iter().filter(|asset| asset.owner_id.as_deref() == Some(id.as_str())).collect::<Vec<_>>()}),
            author: "import".into(),
            reason: "旧台本原文と動画・投稿・分析の原記録を保持。構文解析はWP-R2-2で行う".into(),
            created_at: created.clone(),
        },
    )?;
    if let Some(video_id) = youtube_id {
        imports::put_checked(
            tx,
            &YoutubeVideo {
                channel_id: channel.clone(),
                video_id: video_id.clone(),
                project_id: Some(id.clone()),
                title: project.title,
                privacy: optional_text(&youtube, "privacy_status")?
                    .unwrap_or_else(|| "legacy_unset".into()),
                published_at: time(&youtube, "published_at", options)?,
                synced_at: at.clone(),
            },
        )?;
        imports::put_checked(
            tx,
            &Upload {
                channel_id: channel.clone(),
                id: format!("legacy-upload:{local_id}"),
                project_id: id,
                request_json: json!({"legacy_youtube_status":youtube, "legacy_video_metadata":metadata}),
                session_uri: None,
                bytes_sent: 0,
                video_id: Some(video_id),
                status: "legacy_recorded".into(),
                processing_status: None,
                failure_reason: None,
                created_at: created,
                updated_at: updated,
            },
        )?;
    }
    Ok(())
}

fn import_assets(
    tx: &Connection,
    channel: &ChannelId,
    assets: &[ImportedAsset],
    at: &Timestamp,
) -> Result<()> {
    for asset in assets {
        let bytes = i64::try_from(asset.bytes).map_err(|_| imports::import_failure())?;
        imports::put_asset_checked(
            tx,
            &Asset {
                sha256: asset.sha256.clone(),
                kind: "legacy".into(),
                ext: asset.ext.clone(),
                bytes,
                created_at: at.clone(),
                provenance_json: json!({"source":"legacy_channel_import"}),
            },
        )?;
        imports::put_checked(
            tx,
            &AssetRef {
                channel_id: channel.clone(),
                owner_kind: if asset.owner_id.is_some() {
                    "project"
                } else {
                    "channel"
                }
                .into(),
                owner_id: asset
                    .owner_id
                    .clone()
                    .unwrap_or_else(|| channel.as_str().into()),
                sha256: asset.sha256.clone(),
                role: format!("legacy:{}", asset.relative_path),
            },
        )?;
    }
    Ok(())
}

fn import_jobs(
    tx: &Connection,
    channel: &ChannelId,
    tables: &Tables,
    options: &ChannelImportOptions,
    at: &Timestamp,
    report: &mut ChannelImportReport,
) -> Result<()> {
    for row in rows(tables, "jobs") {
        if optional_text(row, "profile_id")?.is_some_and(|profile| profile != channel.as_str()) {
            return Err(imports::import_failure());
        }
        let legacy_id = imports::field(row, "job_id")?;
        let source_status = optional_text(row, "status")?.unwrap_or_else(|| "legacy_unset".into());
        let status = match source_status.as_str() {
            "running"
                if row
                    .get("runner_pid")
                    .and_then(Value::as_i64)
                    .is_some_and(|pid| {
                        options.verified_running_jobs.get(legacy_id) == Some(&pid)
                    }) =>
            {
                report.held_jobs += 1;
                "legacy_running".into()
            }
            "running" => {
                report.abandoned_jobs += 1;
                "abandoned".into()
            }
            "queued" | "pending" => {
                report.held_jobs += 1;
                format!("legacy_{source_status}")
            }
            _ => source_status,
        };
        let id = format!("legacy-job:{legacy_id}");
        let job = Job {
            channel_id: channel.clone(),
            id: id.clone(),
            project_id: None,
            kind: optional_text(row, "job_type")?.unwrap_or_else(|| "legacy_unset".into()),
            status: status.clone(),
            priority: 0,
            not_before: None,
            attempts: 0,
            max_attempts: 1,
            lease_owner: None,
            lease_until: None,
            heartbeat_at: time(row, "heartbeat_at", options)?,
            wait_reason: Some("legacy_import_requires_review".into()),
            error_code: None,
            created_at: time(row, "created_at", options)?.unwrap_or_else(|| at.clone()),
            started_at: time(row, "started_at", options)?,
            finished_at: time(row, "finished_at", options)?,
        };
        imports::put_checked(tx, &job)?;
        let bytes = serde_json::to_vec(row).map_err(|_| imports::import_failure())?;
        imports::put_checked(
            tx,
            &JobStep {
                channel_id: channel.clone(),
                job_id: id,
                step: "legacy_snapshot".into(),
                step_version: 1,
                inputs_hash: imports::digest_bytes(&bytes),
                status,
                output_json: row.clone(),
                started_at: job.started_at,
                finished_at: job.finished_at,
                duration_ms: None,
                cost_micros: None,
            },
        )?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "channel_import_tests.rs"]
mod tests;
