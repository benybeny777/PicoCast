//! ジョブ状態・リース・工程結果の原子的な保存境界。
use crate::{
    db_failure, failure,
    repository::{
        self, AppSetting, AppSettingKey, AuditEntry, Job, JobKey, JobStep, JobStepKey, StepCache,
        StepCacheKey,
    },
    Store,
};
use picocast_core::{clock::Timestamp, ChannelId, Result};
use rusqlite::{Connection, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;

fn invalid() -> picocast_core::AppError {
    failure(
        "E-JOB-STATE",
        "ジョブの状態・実行権限が一致しません。",
        "最新のジョブ状態を読み直してください。期限切れの実行者から結果を保存しないでください。",
    )
}
fn valid_id(value: &str) -> bool {
    !value.is_empty() && value.trim() == value && !value.chars().any(char::is_control)
}
fn valid_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
fn valid_code(value: &str) -> bool {
    value.starts_with("E-")
        && value.len() > 2
        && value
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'-')
}
fn random_id(prefix: &str) -> Result<String> {
    let mut random = [0u8; 32];
    getrandom::fill(&mut random).map_err(|_| invalid())?;
    Ok(format!(
        "{prefix}:{}",
        random
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    ))
}

#[derive(Clone, Copy)]
pub struct LeaseOptions {
    pub lease_duration: Duration,
    pub stale_after: Duration,
}
impl LeaseOptions {
    pub fn validate(&self) -> Result<()> {
        if self.lease_duration.is_zero() || self.stale_after.is_zero() {
            Err(invalid())
        } else {
            Ok(())
        }
    }
}
fn deadline(at: &Timestamp, duration: Duration) -> Result<Timestamp> {
    picocast_core::clock::add_duration(at, duration)
}

pub struct NewJob {
    pub channel_id: ChannelId,
    pub id: String,
    pub project_id: Option<String>,
    pub kind: String,
    pub priority: i64,
    pub not_before: Option<Timestamp>,
    pub max_attempts: i64,
    pub at: Timestamp,
}
#[derive(Clone)]
pub struct JobLease {
    pub channel_id: ChannelId,
    pub job_id: String,
    token: String,
}
impl JobLease {
    pub fn fencing_key(&self) -> &str {
        &self.token
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WaitReason {
    Offline,
    GpuBusy,
    Quota,
    Budget,
    Window,
    ExternalUnknown,
}
impl WaitReason {
    fn as_str(self) -> &'static str {
        match self {
            Self::Offline => "offline",
            Self::GpuBusy => "gpu_busy",
            Self::Quota => "quota",
            Self::Budget => "budget",
            Self::Window => "window",
            Self::ExternalUnknown => "external_unknown",
        }
    }
}
pub enum JobConclusion {
    Succeeded,
    Yield,
    Cancelled,
    Waiting {
        reason: WaitReason,
        resume_at: Option<Timestamp>,
    },
    Failed {
        code: String,
    },
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JobSignal {
    Active,
    CancelRequested,
}

fn get_job(connection: &Connection, channel: &ChannelId, id: &str) -> Result<Job> {
    repository::get(
        connection,
        &JobKey {
            channel_id: channel.clone(),
            id: id.into(),
        },
        Some(channel),
    )?
    .ok_or_else(invalid)
}
fn held(connection: &Connection, lease: &JobLease, at: &Timestamp) -> Result<Job> {
    let job = get_job(connection, &lease.channel_id, &lease.job_id)?;
    if !matches!(job.status.as_str(), "running" | "cancel_requested")
        || job.lease_owner.as_deref() != Some(&lease.token)
        || job.lease_until.as_ref().is_none_or(|end| end <= at)
        || job
            .heartbeat_at
            .as_ref()
            .is_none_or(|previous| previous > at)
    {
        return Err(invalid());
    }
    Ok(job)
}
fn clear_lease(job: &mut Job) {
    job.lease_owner = None;
    job.lease_until = None;
    job.heartbeat_at = None;
}
fn due(job: &Job, at: &Timestamp) -> bool {
    job.not_before.as_ref().is_none_or(|value| value <= at)
}

impl Store {
    /// 同じ工程版で別の実装hashを観測したら警告する。cacheキーも必ずhashで分離する。
    pub fn observe_step_source(
        &mut self,
        name: &str,
        version: u32,
        source_hash: &str,
        at: &Timestamp,
    ) -> Result<bool> {
        if !valid_id(name) || version == 0 || !valid_hash(source_hash) {
            return Err(invalid());
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let key = AppSettingKey {
            key: format!("pipeline.step-source:{name}:{version}"),
        };
        let changed =
            if let Some(existing) = repository::get::<AppSetting>(&transaction, &key, None)? {
                let hash = existing
                    .value_json
                    .as_str()
                    .filter(|value| valid_hash(value))
                    .ok_or_else(invalid)?;
                hash != source_hash
            } else {
                repository::save(
                    &transaction,
                    &AppSetting {
                        key: key.key,
                        value_json: Value::String(source_hash.into()),
                        updated_at: at.clone(),
                    },
                )?;
                false
            };
        transaction.commit().map_err(db_failure)?;
        if changed {
            tracing::warn!(
                code = "E-PIPELINE-VERSION",
                step = name,
                version,
                "実装が変わりましたが工程の版が更新されていません"
            );
        }
        Ok(changed)
    }
    /// 初期工程を含め一括登録する。重複IDを既存ジョブの更新として扱わない。
    pub fn enqueue_job(&mut self, new: &NewJob, initial_steps: &[JobStep]) -> Result<()> {
        self.require_channel(&new.channel_id)?;
        if !valid_id(&new.id) || !valid_id(&new.kind) || new.max_attempts <= 0 {
            return Err(invalid());
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        if (repository::ChannelRepository {
            connection: &transaction,
            channel_id: new.channel_id.clone(),
        })
        .get::<Job>(&JobKey {
            channel_id: new.channel_id.clone(),
            id: new.id.clone(),
        })?
        .is_some()
        {
            return Err(invalid());
        }
        let job = Job {
            channel_id: new.channel_id.clone(),
            id: new.id.clone(),
            project_id: new.project_id.clone(),
            kind: new.kind.clone(),
            status: "queued".into(),
            priority: new.priority,
            not_before: new.not_before.clone(),
            attempts: 0,
            max_attempts: new.max_attempts,
            lease_owner: None,
            lease_until: None,
            heartbeat_at: None,
            wait_reason: None,
            error_code: None,
            created_at: new.at.clone(),
            started_at: None,
            finished_at: None,
        };
        repository::save(&transaction, &job)?;
        let mut ids = std::collections::BTreeSet::new();
        for step in initial_steps {
            if step.channel_id != new.channel_id
                || step.job_id != new.id
                || step.step_version <= 0
                || !valid_id(&step.step)
                || !valid_hash(&step.inputs_hash)
                || step.status != "planned"
                || !ids.insert(&step.step)
            {
                return Err(invalid());
            }
            repository::save(&transaction, step)?;
        }
        transaction.commit().map_err(db_failure)
    }

    pub fn claim_job(
        &mut self,
        channel: &ChannelId,
        worker: &str,
        at: &Timestamp,
        options: LeaseOptions,
    ) -> Result<Option<JobLease>> {
        self.claim_job_filtered(channel, worker, at, options, None)
    }
    /// 他のジョブ利用者のqueueを奪わず、指定の永続計画を持つジョブだけを取得する。
    pub fn claim_job_for_step(
        &mut self,
        channel: &ChannelId,
        worker: &str,
        at: &Timestamp,
        options: LeaseOptions,
        required_step: &str,
    ) -> Result<Option<JobLease>> {
        if !valid_id(required_step) {
            return Err(invalid());
        }
        self.claim_job_filtered(channel, worker, at, options, Some(required_step))
    }
    fn claim_job_filtered(
        &mut self,
        channel: &ChannelId,
        worker: &str,
        at: &Timestamp,
        options: LeaseOptions,
        required_step: Option<&str>,
    ) -> Result<Option<JobLease>> {
        self.require_channel(channel)?;
        options.validate()?;
        if !valid_id(worker) {
            return Err(invalid());
        }
        let until = deadline(at, options.lease_duration)?;
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let mut jobs = repository::ChannelRepository {
            connection: &transaction,
            channel_id: channel.clone(),
        }
        .list::<Job>()?;
        jobs.sort_by(|a, b| {
            b.priority
                .cmp(&a.priority)
                .then_with(|| a.created_at.cmp(&b.created_at))
                .then_with(|| a.id.cmp(&b.id))
        });
        for mut job in jobs {
            if let Some(step) = required_step {
                if repository::get::<JobStep>(
                    &transaction,
                    &JobStepKey {
                        channel_id: channel.clone(),
                        job_id: job.id.clone(),
                        step: step.into(),
                    },
                    Some(channel),
                )?
                .is_none()
                {
                    continue;
                }
            }
            let running = matches!(job.status.as_str(), "running" | "cancel_requested");
            if running {
                let expired = job.lease_until.as_ref().is_none_or(|end| end <= at);
                let stale = job
                    .heartbeat_at
                    .as_ref()
                    .map(|last| deadline(last, options.stale_after))
                    .transpose()?
                    .is_none_or(|end| end <= *at);
                if !expired && !stale {
                    continue;
                }
                if job.status == "cancel_requested" {
                    job.status = "cancelled".into();
                    job.finished_at = Some(at.clone());
                    clear_lease(&mut job);
                    repository::save(&transaction, &job)?;
                    continue;
                }
                job.attempts = job.attempts.checked_add(1).ok_or_else(invalid)?;
                job.error_code = Some("E-JOB-STUCK".into());
                tracing::warn!(channel_id=channel.as_str(),job_id=%job.id,code="E-JOB-STUCK",failures=job.attempts,"期限切れ・固着ジョブの実行権を回収します");
                if job.attempts >= job.max_attempts {
                    job.status = "failed".into();
                    job.finished_at = Some(at.clone());
                    clear_lease(&mut job);
                    repository::save(&transaction, &job)?;
                    continue;
                }
            } else if !(job.status == "queued" && due(&job, at)
                || job.status == "waiting" && job.not_before.is_some() && due(&job, at))
            {
                continue;
            }
            if job.created_at > *at || job.attempts >= job.max_attempts {
                continue;
            }
            let token = random_id(worker)?;
            job.status = "running".into();
            job.lease_owner = Some(token.clone());
            job.lease_until = Some(until.clone());
            job.heartbeat_at = Some(at.clone());
            job.started_at.get_or_insert_with(|| at.clone());
            job.finished_at = None;
            job.wait_reason = None;
            job.not_before = None;
            repository::save(&transaction, &job)?;
            transaction.commit().map_err(db_failure)?;
            return Ok(Some(JobLease {
                channel_id: channel.clone(),
                job_id: job.id,
                token,
            }));
        }
        transaction.commit().map_err(db_failure)?;
        Ok(None)
    }

    pub fn heartbeat_job(
        &mut self,
        lease: &JobLease,
        at: &Timestamp,
        options: LeaseOptions,
    ) -> Result<JobSignal> {
        options.validate()?;
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let mut job = held(&transaction, lease, at)?;
        match (repository::ChannelRepository {
            connection: &transaction,
            channel_id: lease.channel_id.clone(),
        })
        .get::<Job>(&JobKey {
            channel_id: lease.channel_id.clone(),
            id: lease.job_id.clone(),
        }) {
            Ok(Some(_)) => {}
            Ok(None) => return Err(invalid()),
            Err(error) if error.code == "E-STORE-CHANNEL" => {
                tracing::warn!(
                    channel_id = lease.channel_id.as_str(),
                    "アーカイブ済みチャンネルの工程を中断します"
                );
                job.status = "cancel_requested".into();
            }
            Err(error) => return Err(error),
        }
        let signal = if job.status == "cancel_requested" {
            JobSignal::CancelRequested
        } else {
            JobSignal::Active
        };
        job.lease_until = Some(deadline(at, options.lease_duration)?);
        job.heartbeat_at = Some(at.clone());
        repository::save(&transaction, &job)?;
        transaction.commit().map_err(db_failure)?;
        Ok(signal)
    }

    pub fn request_job_cancel(
        &mut self,
        channel: &ChannelId,
        id: &str,
        at: &Timestamp,
    ) -> Result<()> {
        self.require_channel(channel)?;
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let mut job = get_job(&transaction, channel, id)?;
        match job.status.as_str() {
            "queued" | "waiting" => {
                job.status = "cancelled".into();
                job.finished_at = Some(at.clone());
                clear_lease(&mut job);
            }
            "running" => job.status = "cancel_requested".into(),
            "cancel_requested" | "cancelled" => {}
            _ => return Err(invalid()),
        }
        repository::save(&transaction, &job)?;
        transaction.commit().map_err(db_failure)
    }

    pub fn resume_waiting_job(&mut self, channel: &ChannelId, id: &str) -> Result<()> {
        self.require_channel(channel)?;
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let mut job = get_job(&transaction, channel, id)?;
        if job.status != "waiting" || job.wait_reason.as_deref() == Some("external_unknown") {
            return Err(invalid());
        }
        job.status = "queued".into();
        job.wait_reason = None;
        job.not_before = None;
        repository::save(&transaction, &job)?;
        transaction.commit().map_err(db_failure)
    }

    /// 外部側で「未送信」を確認した利用者の操作専用。通常のresumeでは不明結果を解放しない。
    pub fn confirm_job_step_not_sent(
        &mut self,
        channel: &ChannelId,
        job_id: &str,
        step_id: &str,
        confirmed: bool,
        operator: &str,
        at: &Timestamp,
    ) -> Result<()> {
        self.require_channel(channel)?;
        if !confirmed || !valid_id(operator) {
            return Err(invalid());
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let mut job = get_job(&transaction, channel, job_id)?;
        let mut step = repository::get::<JobStep>(
            &transaction,
            &JobStepKey {
                channel_id: channel.clone(),
                job_id: job_id.into(),
                step: step_id.into(),
            },
            Some(channel),
        )?
        .ok_or_else(invalid)?;
        if job.status != "waiting"
            || job.wait_reason.as_deref() != Some("external_unknown")
            || step.status != "running"
        {
            return Err(invalid());
        }
        step.status = "planned".into();
        step.started_at = None;
        job.status = "queued".into();
        job.wait_reason = None;
        job.error_code = None;
        repository::save(&transaction, &step)?;
        repository::save(&transaction, &job)?;
        repository::save(
            &transaction,
            &AuditEntry {
                id: random_id("job-reconcile")?,
                at: at.clone(),
                actor: operator.into(),
                action: "pipeline.confirmed_not_sent".into(),
                target: job_id.into(),
                detail_json: serde_json::json!({"channel_id":channel.as_str(),"step_id":step_id}),
            },
        )?;
        transaction.commit().map_err(db_failure)
    }

    pub fn conclude_job(
        &mut self,
        lease: &JobLease,
        at: &Timestamp,
        conclusion: JobConclusion,
    ) -> Result<Job> {
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        let mut job = held(&transaction, lease, at)?;
        if job.status == "cancel_requested" || matches!(conclusion, JobConclusion::Cancelled) {
            job.status = "cancelled".into();
            job.finished_at = Some(at.clone());
        } else {
            match conclusion {
                JobConclusion::Succeeded => {
                    job.status = "succeeded".into();
                    job.finished_at = Some(at.clone());
                    job.error_code = None;
                }
                JobConclusion::Yield => {
                    job.status = "queued".into();
                    job.error_code = None;
                }
                JobConclusion::Waiting { reason, resume_at } => {
                    if resume_at.as_ref().is_some_and(|when| when <= at) {
                        return Err(invalid());
                    }
                    if reason != WaitReason::ExternalUnknown {
                        for mut step in (repository::ChannelRepository {
                            connection: &transaction,
                            channel_id: lease.channel_id.clone(),
                        })
                        .list::<JobStep>()?
                        {
                            if step.job_id == lease.job_id && step.status == "running" {
                                step.status = "planned".into();
                                step.started_at = None;
                                repository::save(&transaction, &step)?;
                            }
                        }
                    }
                    job.status = "waiting".into();
                    job.wait_reason = Some(reason.as_str().into());
                    job.not_before = resume_at;
                    job.error_code = if reason == WaitReason::ExternalUnknown {
                        Some("E-JOB-UNCERTAIN".into())
                    } else {
                        None
                    };
                }
                JobConclusion::Failed { code } => {
                    if !valid_code(&code) {
                        return Err(invalid());
                    }
                    job.attempts = job.attempts.checked_add(1).ok_or_else(invalid)?;
                    job.error_code = Some(code);
                    job.status = if job.attempts >= job.max_attempts {
                        "failed"
                    } else {
                        "queued"
                    }
                    .into();
                    if job.status == "failed" {
                        job.finished_at = Some(at.clone());
                    }
                }
                JobConclusion::Cancelled => return Err(invalid()),
            }
        }
        clear_lease(&mut job);
        repository::save(&transaction, &job)?;
        transaction.commit().map_err(db_failure)?;
        Ok(job)
    }

    pub fn begin_job_step(
        &mut self,
        lease: &JobLease,
        at: &Timestamp,
        step: &str,
        version: u32,
        inputs_hash: &str,
    ) -> Result<()> {
        if !valid_id(step) || version == 0 || !valid_hash(inputs_hash) {
            return Err(invalid());
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        if held(&transaction, lease, at)?.status != "running" {
            return Err(invalid());
        }
        repository::save(
            &transaction,
            &JobStep {
                channel_id: lease.channel_id.clone(),
                job_id: lease.job_id.clone(),
                step: step.into(),
                step_version: version.into(),
                inputs_hash: inputs_hash.into(),
                status: "running".into(),
                output_json: Value::Null,
                started_at: Some(at.clone()),
                finished_at: None,
                duration_ms: None,
                cost_micros: None,
            },
        )?;
        transaction.commit().map_err(db_failure)
    }

    /// 工程が明示した確定失敗だけを記録する。外部結果不明では呼ばない。
    pub fn record_job_step_failure(
        &mut self,
        lease: &JobLease,
        at: &Timestamp,
        step: &str,
        code: &str,
    ) -> Result<()> {
        if !valid_code(code) {
            return Err(invalid());
        }
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        if held(&transaction, lease, at)?.status != "running" {
            return Err(invalid());
        }
        let mut record = repository::get::<JobStep>(
            &transaction,
            &JobStepKey {
                channel_id: lease.channel_id.clone(),
                job_id: lease.job_id.clone(),
                step: step.into(),
            },
            Some(&lease.channel_id),
        )?
        .ok_or_else(invalid)?;
        if record.status != "running" {
            return Err(invalid());
        }
        record.status = "failed".into();
        record.finished_at = Some(at.clone());
        record.output_json = serde_json::json!({"error_code":code});
        repository::save(&transaction, &record)?;
        transaction.commit().map_err(db_failure)
    }

    pub fn publish_job_step(
        &mut self,
        lease: &JobLease,
        at: &Timestamp,
        step: &str,
        mut output: Value,
        duration_ms: u64,
        cache: Option<StepCache>,
    ) -> Result<()> {
        let transaction = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_failure)?;
        if held(&transaction, lease, at)?.status != "running" {
            return Err(invalid());
        }
        let mut record = repository::get::<JobStep>(
            &transaction,
            &JobStepKey {
                channel_id: lease.channel_id.clone(),
                job_id: lease.job_id.clone(),
                step: step.into(),
            },
            Some(&lease.channel_id),
        )?
        .ok_or_else(invalid)?;
        if record.status != "running" || record.started_at.as_ref().is_none_or(|start| start > at) {
            return Err(invalid());
        }
        if let Some(cache) = cache {
            if cache.step_version != record.step_version
                || cache.inputs_hash != record.inputs_hash
                || cache.outputs_json != output
                || cache.outputs_json.get("channel_id").and_then(Value::as_str)
                    != Some(lease.channel_id.as_str())
            {
                return Err(invalid());
            }
            let key = StepCacheKey {
                step: cache.step.clone(),
                step_version: cache.step_version,
                inputs_hash: cache.inputs_hash.clone(),
            };
            if let Some(mut old) = repository::get::<StepCache>(&transaction, &key, None)? {
                let mut expected = cache.outputs_json.clone();
                let mut existing = old.outputs_json.clone();
                if let Some(provenance) = expected
                    .get_mut("provenance")
                    .and_then(Value::as_object_mut)
                {
                    provenance.remove("at");
                }
                if let Some(provenance) = existing
                    .get_mut("provenance")
                    .and_then(Value::as_object_mut)
                {
                    provenance.remove("at");
                }
                if existing != expected {
                    return Err(invalid());
                }
                output = old.outputs_json.clone();
                old.last_used_at = at.clone();
                repository::save(&transaction, &old)?;
            } else {
                repository::save(&transaction, &cache)?;
            }
        }
        record.status = "succeeded".into();
        record.output_json = output;
        record.finished_at = Some(at.clone());
        record.duration_ms = Some(i64::try_from(duration_ms).map_err(|_| invalid())?);
        repository::save(&transaction, &record)?;
        transaction.commit().map_err(db_failure)
    }
}

#[cfg(test)]
#[path = "jobs_tests.rs"]
mod tests;
