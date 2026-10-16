//! テーブルごとの型と封印された所有区分で SQL とチャンネル境界を共有する。

use crate::{db_failure, failure};
use picocast_core::{clock::Timestamp, ChannelId, Result};
use rusqlite::{params_from_iter, types::Value as SqlValue, Connection, OptionalExtension, Row};
use serde::{Deserialize, Serialize};
use serde_json::Value;

mod sealed {
    pub trait Sealed {}
}

/// 識別子と列名はこのモジュール内の定義だけから作る。外部実装を許可しない。
pub trait Record: sealed::Sealed + Sized {
    type Key: RecordKey;
    const TABLE: &'static str;
    const COLUMNS: &'static [&'static str];
    fn key(&self) -> Self::Key;
    fn values(&self) -> Result<Vec<SqlValue>>;
    fn read(row: &Row<'_>) -> rusqlite::Result<Self>;
}

pub trait RecordKey: sealed::Sealed {
    const COLUMNS: &'static [&'static str];
    fn values(&self) -> Result<Vec<SqlValue>>;
}

pub trait ChannelRecord: Record {
    fn channel_id(&self) -> &ChannelId;
}

pub trait GlobalRecord: Record {}

pub struct ChannelRepository<'a> {
    pub(crate) connection: &'a Connection,
    pub(crate) channel_id: ChannelId,
}

pub struct GlobalRepository<'a> {
    pub(crate) connection: &'a Connection,
}

pub(crate) fn channels(connection: &Connection) -> Result<Vec<Channel>> {
    list::<Channel>(connection, None)
}

impl ChannelRepository<'_> {
    fn ensure_active(&self) -> Result<()> {
        let active: bool = self
            .connection
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM channels WHERE channel_id=?1 AND archived_at IS NULL)",
                [self.channel_id.as_str()],
                |row| row.get(0),
            )
            .map_err(db_failure)?;
        if !active {
            return Err(boundary());
        }
        Ok(())
    }

    pub fn save<R: ChannelRecord>(&self, record: &R) -> Result<()> {
        self.ensure_active()?;
        if record.channel_id() != &self.channel_id {
            return Err(boundary());
        }
        save(self.connection, record)
    }

    pub fn get<R: ChannelRecord>(&self, key: &R::Key) -> Result<Option<R>> {
        self.ensure_active()?;
        get(self.connection, key, Some(&self.channel_id))
    }

    pub fn list<R: ChannelRecord>(&self) -> Result<Vec<R>> {
        self.ensure_active()?;
        list(self.connection, Some(&self.channel_id))
    }

    pub fn delete<R: ChannelRecord>(&self, key: &R::Key) -> Result<bool> {
        self.ensure_active()?;
        if R::TABLE == "channels"
            || R::TABLE == "project_revisions"
            || R::TABLE == "prompt_template_versions"
        {
            return Err(failure(
                "E-STORE-IDENTITY",
                "履歴またはチャンネルはこの操作では削除できません。",
                "チャンネルはアーカイブし、履歴は新しい版を追加してください。",
            ));
        }
        delete::<R>(self.connection, key, Some(&self.channel_id))
    }
}

impl GlobalRepository<'_> {
    pub fn save<R: GlobalRecord>(&self, record: &R) -> Result<()> {
        save(self.connection, record)
    }
    pub fn get<R: GlobalRecord>(&self, key: &R::Key) -> Result<Option<R>> {
        get(self.connection, key, None)
    }
    pub fn list<R: GlobalRecord>(&self) -> Result<Vec<R>> {
        list(self.connection, None)
    }
    pub fn delete<R: GlobalRecord>(&self, key: &R::Key) -> Result<bool> {
        if R::TABLE == "audit_log" {
            return Err(failure(
                "E-STORE-IDENTITY",
                "監査履歴は削除できません。",
                "訂正の理由を新しい監査履歴として記録してください。",
            ));
        }
        delete::<R>(self.connection, key, None)
    }
}

fn boundary() -> picocast_core::AppError {
    failure(
        "E-STORE-CHANNEL",
        "別チャンネルのデータは変更できません。",
        "対象チャンネルを明示したリポジトリを使ってください。",
    )
}

pub(crate) fn save<R: Record>(connection: &Connection, record: &R) -> Result<()> {
    let placeholders = vec!["?"; R::COLUMNS.len()].join(",");
    let mutable: Vec<_> = R::COLUMNS
        .iter()
        .filter(|column| !R::Key::COLUMNS.contains(column))
        .map(|column| format!("{column}=excluded.{column}"))
        .collect();
    // スナップショットとテンプレート版は上書きせず、版の重複を明示エラーにする。
    let immutable = matches!(
        R::TABLE,
        "project_revisions" | "prompt_template_versions" | "audit_log"
    );
    let conflict = if immutable {
        String::new()
    } else if mutable.is_empty() {
        format!(
            " ON CONFLICT({}) DO UPDATE SET {}=excluded.{}",
            R::Key::COLUMNS.join(","),
            R::Key::COLUMNS[0],
            R::Key::COLUMNS[0]
        )
    } else {
        format!(
            " ON CONFLICT({}) DO UPDATE SET {}",
            R::Key::COLUMNS.join(","),
            mutable.join(",")
        )
    };
    let sql = format!(
        "INSERT INTO {}({}) VALUES ({placeholders}){conflict}",
        R::TABLE,
        R::COLUMNS.join(",")
    );
    connection
        .execute(&sql, params_from_iter(record.values()?))
        .map_err(db_failure)?;
    Ok(())
}

fn predicate<K: RecordKey>(
    key: &K,
    channel: Option<&ChannelId>,
) -> Result<(String, Vec<SqlValue>)> {
    let mut clauses: Vec<_> = K::COLUMNS
        .iter()
        .map(|column| format!("{column}=?"))
        .collect();
    let mut values = key.values()?;
    if let Some(channel) = channel {
        clauses.push("channel_id=?".into());
        values.push(SqlValue::Text(channel.as_str().into()));
    }
    Ok((clauses.join(" AND "), values))
}

pub(crate) fn get<R: Record>(
    connection: &Connection,
    key: &R::Key,
    channel: Option<&ChannelId>,
) -> Result<Option<R>> {
    let (condition, values) = predicate(key, channel)?;
    let sql = format!(
        "SELECT {} FROM {} WHERE {condition}",
        R::COLUMNS.join(","),
        R::TABLE
    );
    connection
        .query_row(&sql, params_from_iter(values), R::read)
        .optional()
        .map_err(db_failure)
}

fn list<R: Record>(connection: &Connection, channel: Option<&ChannelId>) -> Result<Vec<R>> {
    let (condition, values) = match channel {
        Some(channel) => (
            " WHERE channel_id=?",
            vec![SqlValue::Text(channel.as_str().into())],
        ),
        None => ("", Vec::new()),
    };
    let sql = format!(
        "SELECT {} FROM {}{condition} ORDER BY {}",
        R::COLUMNS.join(","),
        R::TABLE,
        R::Key::COLUMNS.join(",")
    );
    let mut statement = connection.prepare(&sql).map_err(db_failure)?;
    let rows = statement
        .query_map(params_from_iter(values), R::read)
        .map_err(db_failure)?;
    rows.collect::<std::result::Result<Vec<_>, _>>()
        .map_err(db_failure)
}

fn delete<R: Record>(
    connection: &Connection,
    key: &R::Key,
    channel: Option<&ChannelId>,
) -> Result<bool> {
    let (condition, values) = predicate(key, channel)?;
    let sql = format!("DELETE FROM {} WHERE {condition}", R::TABLE);
    Ok(connection
        .execute(&sql, params_from_iter(values))
        .map_err(db_failure)?
        > 0)
}

trait SqlCodec: Sized {
    fn encode(&self) -> Result<SqlValue>;
    fn decode(row: &Row<'_>, name: &str) -> rusqlite::Result<Self>;
}

macro_rules! scalar_codec {
    ($kind:ty) => {
        impl SqlCodec for $kind {
            fn encode(&self) -> Result<SqlValue> {
                Ok(SqlValue::from(self.clone()))
            }
            fn decode(row: &Row<'_>, name: &str) -> rusqlite::Result<Self> {
                row.get(name)
            }
        }
    };
}
scalar_codec!(String);
scalar_codec!(i64);
scalar_codec!(f64);

impl SqlCodec for bool {
    fn encode(&self) -> Result<SqlValue> {
        Ok(SqlValue::Integer(i64::from(*self)))
    }
    fn decode(row: &Row<'_>, name: &str) -> rusqlite::Result<Self> {
        row.get(name)
    }
}

fn conversion_error(message: &str) -> rusqlite::Error {
    rusqlite::Error::FromSqlConversionFailure(
        0,
        rusqlite::types::Type::Text,
        Box::new(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            message.to_owned(),
        )),
    )
}

impl SqlCodec for ChannelId {
    fn encode(&self) -> Result<SqlValue> {
        Ok(SqlValue::Text(self.as_str().into()))
    }
    fn decode(row: &Row<'_>, name: &str) -> rusqlite::Result<Self> {
        ChannelId::new(row.get::<_, String>(name)?)
            .map_err(|_| conversion_error("invalid channel identifier"))
    }
}

impl SqlCodec for Timestamp {
    fn encode(&self) -> Result<SqlValue> {
        Ok(SqlValue::Text(self.to_utc_iso()))
    }
    fn decode(row: &Row<'_>, name: &str) -> rusqlite::Result<Self> {
        Timestamp::parse(&row.get::<_, String>(name)?)
            .map_err(|_| conversion_error("invalid timestamp"))
    }
}

impl SqlCodec for Value {
    fn encode(&self) -> Result<SqlValue> {
        serde_json::to_string(self)
            .map(SqlValue::Text)
            .map_err(|_| {
                failure(
                    "E-STORE-SETTING",
                    "JSON を保存できません。",
                    "JSON の形式を確認してください。",
                )
            })
    }
    fn decode(row: &Row<'_>, name: &str) -> rusqlite::Result<Self> {
        serde_json::from_str(&row.get::<_, String>(name)?)
            .map_err(|_| conversion_error("invalid JSON"))
    }
}

impl<T: SqlCodec> SqlCodec for Option<T> {
    fn encode(&self) -> Result<SqlValue> {
        self.as_ref().map_or(Ok(SqlValue::Null), SqlCodec::encode)
    }
    fn decode(row: &Row<'_>, name: &str) -> rusqlite::Result<Self> {
        if row.get_ref(name)?.data_type() == rusqlite::types::Type::Null {
            Ok(None)
        } else {
            T::decode(row, name).map(Some)
        }
    }
}

macro_rules! record {
    ($record:ident, $key:ident, $table:literal, $scope:ident, {$($key_name:ident : $key_type:ty),+}, {$($field:ident : $type:ty),*}) => {
        #[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
        pub struct $record { $(pub $key_name: $key_type,)+ $(pub $field: $type,)* }
        #[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
        pub struct $key { $(pub $key_name: $key_type,)+ }
        impl sealed::Sealed for $record {}
        impl sealed::Sealed for $key {}
        impl RecordKey for $key {
            const COLUMNS: &'static [&'static str] = &[$(stringify!($key_name)),+];
            fn values(&self) -> Result<Vec<SqlValue>> { Ok(vec![$(self.$key_name.encode()?),+]) }
        }
        impl Record for $record {
            type Key = $key;
            const TABLE: &'static str = $table;
            const COLUMNS: &'static [&'static str] = &[$(stringify!($key_name),)+ $(stringify!($field),)*];
            fn key(&self) -> Self::Key { $key { $($key_name:self.$key_name.clone(),)+ } }
            fn values(&self) -> Result<Vec<SqlValue>> { Ok(vec![$(self.$key_name.encode()?,)+ $(self.$field.encode()?,)*]) }
            fn read(row: &Row<'_>) -> rusqlite::Result<Self> { Ok(Self { $($key_name: <$key_type>::decode(row, stringify!($key_name))?,)+ $($field: <$type>::decode(row, stringify!($field))?,)* }) }
        }
        scope!($record, $scope);
        #[cfg(test)]
        impl tests::Sample for $record {
            fn sample() -> Self { Self { $($key_name: tests::fixture(stringify!($key_name)),)+ $($field: tests::fixture(stringify!($field)),)* } }
        }
    };
}

macro_rules! scope {
    ($record:ident, channel) => {
        impl ChannelRecord for $record {
            fn channel_id(&self) -> &ChannelId {
                &self.channel_id
            }
        }
    };
    ($record:ident, global) => {
        impl GlobalRecord for $record {}
    };
}

record!(Channel, ChannelKey, "channels", channel, {channel_id: ChannelId}, {name: String, handle: Option<String>, language: Option<String>, timezone: Option<String>, genre_pack_id: Option<String>, character_set_id: Option<String>, youtube_channel_id: Option<String>, operator: String, archived_at: Option<Timestamp>, created_at: Timestamp, updated_at: Timestamp});
record!(AppSetting, AppSettingKey, "app_settings", global, {key: String}, {value_json: Value, updated_at: Timestamp});
record!(ChannelSetting, ChannelSettingKey, "channel_settings", channel, {channel_id: ChannelId, key: String}, {value_json: Value, updated_at: Timestamp});
record!(AuditEntry, AuditEntryKey, "audit_log", global, {id: String}, {at: Timestamp, actor: String, action: String, target: String, detail_json: Value});
record!(CrashReport, CrashReportKey, "crash_reports", global, {id: String}, {at: Timestamp, version: String, step: String, summary_json: Value, acknowledged_at: Option<Timestamp>});
record!(Character, CharacterKey, "characters", channel, {channel_id: ChannelId, id: String}, {name: String, voice_provider: String, speaker_id: String, style_map_json: Value, credit_text: String, usage_rules_json: Value, layer_manifest_sha256: Option<String>});
record!(PromptTemplate, PromptTemplateKey, "prompt_templates", channel, {channel_id: ChannelId, id: String}, {kind: String, name: String, is_default: bool});
record!(PromptTemplateVersion, PromptTemplateVersionKey, "prompt_template_versions", channel, {channel_id: ChannelId, template_id: String, version: i64}, {body: String, created_at: Timestamp, author: String, reason: String});
record!(Topic, TopicKey, "topics", channel, {channel_id: ChannelId, id: String}, {title: String, source: String, source_ref: Option<String>, priority: i64, due_at: Option<Timestamp>, status: String, created_at: Timestamp});
record!(Project, ProjectKey, "projects", channel, {channel_id: ChannelId, id: String}, {format: String, language: String, status: String, topic_id: Option<String>, title: String, description: String, tags_json: Value, publish_at: Option<Timestamp>, synthetic_media: bool, youtube_video_id: Option<String>, current_revision: i64, created_at: Timestamp, updated_at: Timestamp});
record!(ProjectRevision, ProjectRevisionKey, "project_revisions", channel, {channel_id: ChannelId, project_id: String, revision: i64}, {snapshot_json: Value, author: String, reason: String, created_at: Timestamp});
record!(Scene, SceneKey, "scenes", channel, {channel_id: ChannelId, id: String}, {project_id: String, ord: i64, background_sha256: Option<String>, background_prompt: Option<String>, camera_json: Value, mood: String, notes: String});
record!(Line, LineKey, "lines", channel, {channel_id: ChannelId, id: String}, {scene_id: String, ord: i64, speaker_id: String, text: String, reading_override: Option<String>, accent_json: Value, expression: Option<String>, style_id: Option<String>, emphasis_json: Value, pause_after_ms: i64});
record!(Asset, AssetKey, "assets", global, {sha256: String}, {kind: String, ext: String, bytes: i64, created_at: Timestamp, provenance_json: Value});
record!(AssetRef, AssetRefKey, "asset_refs", channel, {channel_id: ChannelId, owner_kind: String, owner_id: String, sha256: String, role: String}, {});
record!(AssetLicense, AssetLicenseKey, "asset_licenses", global, {sha256: String}, {provider: String, terms_url: String, credit_text: String, commercial_ok: bool, checked_at: Timestamp});
record!(MusicTags, MusicTagsKey, "music_tags", global, {sha256: String}, {mood: String, tempo_bpm: Option<f64>, duration_ms: i64, loop_start_ms: Option<i64>, loop_end_ms: Option<i64>, manual: bool});
record!(Job, JobKey, "jobs", channel, {channel_id: ChannelId, id: String}, {project_id: Option<String>, kind: String, status: String, priority: i64, not_before: Option<Timestamp>, attempts: i64, max_attempts: i64, lease_owner: Option<String>, lease_until: Option<Timestamp>, heartbeat_at: Option<Timestamp>, wait_reason: Option<String>, error_code: Option<String>, created_at: Timestamp, started_at: Option<Timestamp>, finished_at: Option<Timestamp>});
record!(JobStep, JobStepKey, "job_steps", channel, {channel_id: ChannelId, job_id: String, step: String}, {step_version: i64, inputs_hash: String, status: String, output_json: Value, started_at: Option<Timestamp>, finished_at: Option<Timestamp>, duration_ms: Option<i64>, cost_micros: Option<i64>});
record!(StepCache, StepCacheKey, "step_cache", global, {step: String, step_version: i64, inputs_hash: String}, {outputs_json: Value, created_at: Timestamp, last_used_at: Timestamp});
record!(QaResult, QaResultKey, "qa_results", channel, {channel_id: ChannelId, project_id: String, revision: i64, check_id: String}, {result: String, value_json: Value, created_at: Timestamp});
record!(Upload, UploadKey, "uploads", channel, {channel_id: ChannelId, id: String}, {project_id: String, request_json: Value, session_uri: Option<String>, bytes_sent: i64, video_id: Option<String>, status: String, processing_status: Option<String>, failure_reason: Option<String>, created_at: Timestamp, updated_at: Timestamp});
record!(YoutubeVideo, YoutubeVideoKey, "youtube_videos", channel, {channel_id: ChannelId, video_id: String}, {project_id: Option<String>, title: String, privacy: String, published_at: Option<Timestamp>, synced_at: Timestamp});
record!(QuotaLedger, QuotaLedgerKey, "quota_ledger", channel, {channel_id: ChannelId, day_pt: String, endpoint: String}, {units: i64});
record!(AnalyticsDaily, AnalyticsDailyKey, "analytics_daily", channel, {channel_id: ChannelId, video_id: String, date: String}, {views: Option<i64>, watch_seconds: Option<f64>, avg_view_pct: Option<f64>, impressions: Option<i64>, ctr: Option<f64>, subs_gained: Option<i64>, revenue_micros: Option<i64>, fetched_at: Timestamp});
record!(RetentionCurve, RetentionCurveKey, "retention_curves", channel, {channel_id: ChannelId, video_id: String, fetched_on: String}, {curve_json: Value});
record!(Insight, InsightKey, "insights", channel, {channel_id: ChannelId, id: String}, {kind: String, pattern_json: Value, evidence_json: Value, score: f64, status: String, created_at: Timestamp});
record!(InsightUsage, InsightUsageKey, "insight_usage", channel, {channel_id: ChannelId, project_id: String, insight_id: String}, {});
record!(Experiment, ExperimentKey, "experiments", channel, {channel_id: ChannelId, id: String}, {factor: String, variants_json: Value, status: String});
record!(ExperimentAssignment, ExperimentAssignmentKey, "experiment_assignments", channel, {channel_id: ChannelId, project_id: String, experiment_id: String}, {variant: String});
record!(AutopilotPolicy, AutopilotPolicyKey, "autopilot_policies", channel, {channel_id: ChannelId}, {enabled: bool, daily_count: i64, quality_threshold: f64, budget_micros: i64, window_json: Value, paused_reason: Option<String>, paused_at: Option<Timestamp>});
record!(ScheduleSlot, ScheduleSlotKey, "schedule_slots", channel, {channel_id: ChannelId, format: String, weekday: i64, local_time: String}, {});
record!(CostLedger, CostLedgerKey, "cost_ledger", channel, {channel_id: ChannelId, id: String}, {project_id: Option<String>, job_id: Option<String>, provider: String, model: String, units_json: Value, cost_micros: Option<i64>, at: Timestamp});
record!(Notification, NotificationKey, "notifications", channel, {channel_id: ChannelId, id: String}, {kind: String, severity: String, dedupe_key: String, message_key: String, args_json: Value, created_at: Timestamp, resolved_at: Option<Timestamp>});
record!(ReadingEntry, ReadingEntryKey, "reading_entries", global, {surface: String, source: String}, {reading: String, accent_json: Value, updated_at: Timestamp});
record!(ReadingCandidate, ReadingCandidateKey, "reading_candidates", global, {surface: String}, {reading: String, reason: String, source: String, auto_applied: bool, review_required: bool, updated_at: Timestamp});

#[cfg(test)]
#[path = "repository_tests.rs"]
mod tests;
