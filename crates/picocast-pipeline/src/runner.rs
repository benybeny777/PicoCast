use crate::{
    content_hash, failure, now, CacheEnvelope, CachePolicy, Dag, Node, Provenance, RetrySafety,
    Step, StepCtx, StepFailure, StepFuture,
};
use picocast_ai::Cancellation;
use picocast_core::{clock::Instant, ChannelId, Result};
use picocast_store::{
    jobs::{JobConclusion, JobLease, JobSignal, LeaseOptions, NewJob, WaitReason},
    repository::{JobStep, StepCache, StepCacheKey},
    Store,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, time::Duration};

pub trait ResourcePermit {
    fn sleep_inhibited(&self) -> bool;
    fn gpu_ready(&self) -> bool;
}
pub trait ResourceGate {
    /// 実装は所有するセマフォ/VRAM確認/スリープ抑止をRAII permitに保持する。
    fn acquire<'a>(
        &'a mut self,
        channel: &'a ChannelId,
        uses_gpu: bool,
        cancel: &'a Cancellation,
    ) -> StepFuture<'a, Box<dyn ResourcePermit>>;
}
pub struct RunOptions {
    pub lease: LeaseOptions,
    pub heartbeat_interval: Duration,
    pub step_timeout: Duration,
    pub max_nodes: usize,
    pub max_payload_bytes: usize,
}
impl RunOptions {
    fn validate(&self) -> Result<()> {
        self.lease.validate()?;
        if self.heartbeat_interval.is_zero()
            || self.heartbeat_interval >= self.lease.lease_duration
            || self.heartbeat_interval >= self.lease.stale_after
            || self.step_timeout.is_zero()
            || self.max_nodes == 0
            || self.max_payload_bytes == 0
        {
            return Err(failure("E-PIPELINE-SETTINGS"));
        }
        Ok(())
    }
}

trait DynamicStep {
    fn run<'a>(&'a self, input: Value, ctx: &'a StepCtx<'a>) -> StepFuture<'a, Value>;
}
struct TypedStep<S>(S);
impl<S: Step> DynamicStep for TypedStep<S> {
    fn run<'a>(&'a self, input: Value, ctx: &'a StepCtx<'a>) -> StepFuture<'a, Value> {
        Box::pin(async move {
            let input = serde_json::from_value(input)
                .map_err(|_| StepFailure::Failed(failure("E-PIPELINE-INPUT")))?;
            let output = self.0.run(input, ctx).await?;
            serde_json::to_value(output)
                .map_err(|_| StepFailure::Failed(failure("E-PIPELINE-OUTPUT")))
        })
    }
}
struct RegisteredStep {
    version: u32,
    source_sha256: String,
    implementation: Box<dyn DynamicStep>,
}
pub struct Pipeline {
    steps: BTreeMap<String, RegisteredStep>,
    resources: Box<dyn ResourceGate>,
    options: RunOptions,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum TickOutcome {
    Idle,
    Progressed {
        job_id: String,
        node_id: String,
        cache_hit: bool,
    },
    Succeeded {
        job_id: String,
    },
    Waiting {
        job_id: String,
        reason: WaitReason,
    },
    Cancelled {
        job_id: String,
    },
    Failed {
        job_id: String,
        code: String,
    },
}
const PLAN_STEP: &str = "$pipeline.plan";

impl Pipeline {
    pub fn new(options: RunOptions, resources: Box<dyn ResourceGate>) -> Result<Self> {
        options.validate()?;
        Ok(Self {
            steps: BTreeMap::new(),
            resources,
            options,
        })
    }
    pub fn register<S: Step + 'static>(
        &mut self,
        implementation: S,
        source_sha256: String,
    ) -> Result<()> {
        if S::NAME.is_empty()
            || S::VERSION == 0
            || !crate::valid_hash(&source_sha256)
            || self.steps.contains_key(S::NAME)
        {
            return Err(failure("E-PIPELINE-VERSION"));
        }
        self.steps.insert(
            S::NAME.into(),
            RegisteredStep {
                version: S::VERSION,
                source_sha256,
                implementation: Box::new(TypedStep(implementation)),
            },
        );
        Ok(())
    }
    fn validate_plan(&self, dag: &Dag) -> Result<()> {
        if dag.nodes.len() > self.options.max_nodes {
            return Err(failure("E-PIPELINE-INPUT"));
        }
        if serde_json::to_vec(dag)
            .map_err(|_| failure("E-PIPELINE-INPUT"))?
            .len()
            > self.options.max_payload_bytes
        {
            return Err(failure("E-PIPELINE-INPUT"));
        }
        for node in dag.ordered()? {
            let implementation = self
                .steps
                .get(&node.step)
                .ok_or_else(|| failure("E-PIPELINE-VERSION"))?;
            if implementation.version != node.version
                || implementation.source_sha256 != node.source_sha256
            {
                return Err(failure("E-PIPELINE-VERSION"));
            }
        }
        Ok(())
    }
    pub fn enqueue(&self, store: &mut Store, job: &NewJob, dag: &Dag) -> Result<()> {
        self.validate_plan(dag)?;
        let mut observed = std::collections::BTreeSet::new();
        for node in &dag.nodes {
            if !observed.insert((&node.step, node.version, &node.source_sha256)) {
                continue;
            }
            store.observe_step_source(&node.step, node.version, &node.source_sha256, &job.at)?;
        }
        store.enqueue_job(
            job,
            &[JobStep {
                channel_id: job.channel_id.clone(),
                job_id: job.id.clone(),
                step: PLAN_STEP.into(),
                step_version: 1,
                inputs_hash: content_hash(dag)?,
                status: "planned".into(),
                output_json: serde_json::to_value(dag).map_err(|_| failure("E-PIPELINE-INPUT"))?,
                started_at: None,
                finished_at: None,
                duration_ms: None,
                cost_micros: None,
            }],
        )
    }
    pub async fn tick(
        &mut self,
        store: &mut Store,
        channel: &ChannelId,
        worker: &str,
        cancel: &mut Cancellation,
    ) -> Result<TickOutcome> {
        cancel.check()?;
        let Some(lease) =
            store.claim_job_for_step(channel, worker, &now()?, self.options.lease, PLAN_STEP)?
        else {
            return Ok(TickOutcome::Idle);
        };
        match self.tick_claimed(store, &lease, cancel).await {
            Ok(outcome) => Ok(outcome),
            Err(error) => {
                tracing::error!(channel_id=channel.as_str(),job_id=%lease.job_id,code=%error.code,"ジョブの工程処理に失敗しました");
                let job = store.conclude_job(
                    &lease,
                    &now()?,
                    JobConclusion::Failed {
                        code: error.code.clone(),
                    },
                )?;
                if job.status == "cancelled" {
                    return Ok(TickOutcome::Cancelled {
                        job_id: lease.job_id,
                    });
                }
                Ok(TickOutcome::Failed {
                    job_id: lease.job_id,
                    code: error.code,
                })
            }
        }
    }
    async fn tick_claimed(
        &mut self,
        store: &mut Store,
        lease: &JobLease,
        cancel: &mut Cancellation,
    ) -> Result<TickOutcome> {
        let records = store
            .repository(&lease.channel_id)?
            .list::<JobStep>()?
            .into_iter()
            .filter(|row| row.job_id == lease.job_id)
            .map(|row| (row.step.clone(), row))
            .collect::<BTreeMap<_, _>>();
        let plan = records
            .get(PLAN_STEP)
            .ok_or_else(|| failure("E-PIPELINE-DAG"))?;
        let dag: Dag = serde_json::from_value(plan.output_json.clone())
            .map_err(|_| failure("E-PIPELINE-DAG"))?;
        if content_hash(&dag)? != plan.inputs_hash {
            return Err(failure("E-PIPELINE-DAG"));
        }
        self.validate_plan(&dag)?;
        let ordered = dag.ordered()?;
        let mut outputs = BTreeMap::new();
        for (index, node) in ordered.iter().enumerate() {
            let key = node.cache_key(&lease.channel_id, &outputs)?;
            if let Some(record) = records.get(&node.id) {
                if record.status == "succeeded"
                    && record.inputs_hash == key
                    && record.step_version == i64::from(node.version)
                {
                    let output = decode_output(
                        &record.output_json,
                        &lease.channel_id,
                        node,
                        &key,
                        &outputs,
                    )?;
                    outputs.insert(node.id.clone(), output);
                    continue;
                }
                if record.status == "running" && node.retry_safety == RetrySafety::Reconcile {
                    store.conclude_job(
                        lease,
                        &now()?,
                        JobConclusion::Waiting {
                            reason: WaitReason::ExternalUnknown,
                            resume_at: None,
                        },
                    )?;
                    return Ok(TickOutcome::Waiting {
                        job_id: lease.job_id.clone(),
                        reason: WaitReason::ExternalUnknown,
                    });
                }
            }
            let at = now()?;
            store.begin_job_step(lease, &at, &node.id, node.version, &key)?;
            let cache_key = StepCacheKey {
                step: node.step.clone(),
                step_version: node.version.into(),
                inputs_hash: key.clone(),
            };
            let cached = if node.cache_policy == CachePolicy::ContentAddressed {
                store.global_repository().get::<StepCache>(&cache_key)?
            } else {
                None
            };
            if let Some(cache) = cached {
                let envelope =
                    decode_output(&cache.outputs_json, &lease.channel_id, node, &key, &outputs)?;
                if cache.created_at != envelope.provenance.at
                    || cache.last_used_at < cache.created_at
                {
                    return Err(failure("E-PIPELINE-CACHE"));
                }
                store.publish_job_step(
                    lease,
                    &now()?,
                    &node.id,
                    cache.outputs_json.clone(),
                    0,
                    Some(cache),
                )?;
                return self.release_after_step(
                    store,
                    lease,
                    node,
                    index + 1 == ordered.len(),
                    true,
                );
            }
            let result = self
                .execute(store, lease, node, &key, &outputs, cancel)
                .await?;
            match result {
                Ok(value) => {
                    let provenance = Provenance {
                        step: node.step.clone(),
                        version: node.version,
                        source_sha256: node.source_sha256.clone(),
                        inputs_hash: key.clone(),
                        model_id: node.model_id.clone(),
                        settings_sha256: content_hash(&node.settings)?,
                        dependency_hashes: outputs
                            .iter()
                            .filter(|(id, _)| node.dependencies.contains(id))
                            .map(|(id, value)| (id.clone(), value.output_sha256.clone()))
                            .collect(),
                        asset_hashes: node.asset_hashes.clone(),
                        at: now()?,
                    };
                    let envelope = CacheEnvelope {
                        channel_id: lease.channel_id.clone(),
                        output_sha256: content_hash(&value.0)?,
                        output: value.0,
                        provenance,
                    };
                    let output = serde_json::to_value(&envelope)
                        .map_err(|_| failure("E-PIPELINE-OUTPUT"))?;
                    if serde_json::to_vec(&output)
                        .map_err(|_| failure("E-PIPELINE-OUTPUT"))?
                        .len()
                        > self.options.max_payload_bytes
                    {
                        return Err(failure("E-PIPELINE-OUTPUT"));
                    }
                    let cache = if node.cache_policy == CachePolicy::ContentAddressed {
                        Some(StepCache {
                            step: node.step.clone(),
                            step_version: node.version.into(),
                            inputs_hash: key,
                            outputs_json: output.clone(),
                            created_at: envelope.provenance.at.clone(),
                            last_used_at: envelope.provenance.at,
                        })
                    } else {
                        None
                    };
                    store.publish_job_step(lease, &now()?, &node.id, output, value.1, cache)?;
                    return self.release_after_step(
                        store,
                        lease,
                        node,
                        index + 1 == ordered.len(),
                        false,
                    );
                }
                Err(StepFailure::Waiting { reason, resume_at }) => {
                    store.conclude_job(
                        lease,
                        &now()?,
                        JobConclusion::Waiting { reason, resume_at },
                    )?;
                    return Ok(TickOutcome::Waiting {
                        job_id: lease.job_id.clone(),
                        reason,
                    });
                }
                Err(StepFailure::Cancelled) => {
                    store.conclude_job(lease, &now()?, JobConclusion::Cancelled)?;
                    return Ok(TickOutcome::Cancelled {
                        job_id: lease.job_id.clone(),
                    });
                }
                Err(StepFailure::ExternalUnknown(error)) => {
                    tracing::error!(channel_id=lease.channel_id.as_str(),job_id=%lease.job_id,code=%error.code,"外部処理の結果が不明なため再送せず待機します");
                    store.conclude_job(
                        lease,
                        &now()?,
                        JobConclusion::Waiting {
                            reason: WaitReason::ExternalUnknown,
                            resume_at: None,
                        },
                    )?;
                    return Ok(TickOutcome::Waiting {
                        job_id: lease.job_id.clone(),
                        reason: WaitReason::ExternalUnknown,
                    });
                }
                Err(StepFailure::Failed(error)) => {
                    store.record_job_step_failure(lease, &now()?, &node.id, &error.code)?;
                    return Err(error);
                }
            }
        }
        store.conclude_job(lease, &now()?, JobConclusion::Succeeded)?;
        Ok(TickOutcome::Succeeded {
            job_id: lease.job_id.clone(),
        })
    }
    fn release_after_step(
        &self,
        store: &mut Store,
        lease: &JobLease,
        node: &Node,
        last: bool,
        cache_hit: bool,
    ) -> Result<TickOutcome> {
        let conclusion = if last {
            JobConclusion::Succeeded
        } else {
            JobConclusion::Yield
        };
        let job = store.conclude_job(lease, &now()?, conclusion)?;
        if job.status == "cancelled" {
            return Ok(TickOutcome::Cancelled {
                job_id: lease.job_id.clone(),
            });
        }
        if last {
            Ok(TickOutcome::Succeeded {
                job_id: lease.job_id.clone(),
            })
        } else {
            Ok(TickOutcome::Progressed {
                job_id: lease.job_id.clone(),
                node_id: node.id.clone(),
                cache_hit,
            })
        }
    }
    async fn execute(
        &mut self,
        store: &mut Store,
        lease: &JobLease,
        node: &Node,
        key: &str,
        outputs: &BTreeMap<String, CacheEnvelope>,
        cancel: &mut Cancellation,
    ) -> Result<std::result::Result<(Value, u64), StepFailure>> {
        let implementation = &self
            .steps
            .get(&node.step)
            .ok_or_else(|| failure("E-PIPELINE-VERSION"))?
            .implementation;
        let (handle, step_cancel) = Cancellation::pair();
        let operation_key = if node.cache_policy == CachePolicy::Never {
            content_hash(&(lease.job_id.as_str(), node.id.as_str(), key))?
        } else {
            key.to_owned()
        };
        let dependencies = node
            .dependencies
            .iter()
            .map(|id| {
                outputs
                    .get(id)
                    .map(|value| (id.clone(), value.output.clone()))
                    .ok_or_else(|| failure("E-PIPELINE-DAG"))
            })
            .collect::<Result<BTreeMap<_, _>>>()?;
        let context = StepCtx {
            channel_id: &lease.channel_id,
            job_id: &lease.job_id,
            node_id: &node.id,
            operation_key: &operation_key,
            dependencies: &dependencies,
            input_assets: &node.asset_hashes,
            model_id: node.model_id.as_deref(),
            settings: &node.settings,
            cancel: &step_cancel,
        };
        let input = node.input.clone();
        let operation = async {
            let permit = self
                .resources
                .acquire(&lease.channel_id, node.uses_gpu, &step_cancel)
                .await?;
            if !permit.sleep_inhibited() || node.uses_gpu && !permit.gpu_ready() {
                return Err(StepFailure::Failed(failure("E-PIPELINE-RESOURCE")));
            }
            let value = implementation.run(input, &context).await;
            drop(permit);
            value
        };
        let start = Instant::now();
        let operation = tokio::time::timeout(self.options.step_timeout, operation);
        tokio::pin!(operation);
        loop {
            tokio::select! {
                biased;
                _=cancel.cancelled()=>{handle.cancel();return Ok(Err(StepFailure::Cancelled));},
                result=&mut operation=>return Ok(match result {Ok(value)=>value.map(|value|(value,u64::try_from(start.elapsed().as_millis()).unwrap_or(u64::MAX))),Err(_)=>Err(if node.retry_safety==RetrySafety::Reconcile {StepFailure::ExternalUnknown(failure("E-PIPELINE-TIMEOUT"))}else{StepFailure::Failed(failure("E-PIPELINE-TIMEOUT"))})}),
                _=tokio::time::sleep(self.options.heartbeat_interval)=>{
                    match store.heartbeat_job(lease,&now()?,self.options.lease)? {JobSignal::Active=>{},JobSignal::CancelRequested=>{handle.cancel();return Ok(Err(StepFailure::Cancelled));}}
                }
            }
        }
    }
}
fn decode_output(
    value: &Value,
    channel: &ChannelId,
    node: &Node,
    key: &str,
    dependencies: &BTreeMap<String, CacheEnvelope>,
) -> Result<CacheEnvelope> {
    let output: CacheEnvelope =
        serde_json::from_value(value.clone()).map_err(|_| failure("E-PIPELINE-CACHE"))?;
    output.validate(channel)?;
    let expected = node
        .dependencies
        .iter()
        .map(|id| {
            dependencies
                .get(id)
                .map(|output| (id.clone(), output.output_sha256.clone()))
                .ok_or_else(|| failure("E-PIPELINE-DAG"))
        })
        .collect::<Result<BTreeMap<_, _>>>()?;
    if output.provenance.step != node.step
        || output.provenance.version != node.version
        || output.provenance.source_sha256 != node.source_sha256
        || output.provenance.inputs_hash != key
        || output.provenance.model_id != node.model_id
        || output.provenance.settings_sha256 != content_hash(&node.settings)?
        || output.provenance.asset_hashes != node.asset_hashes
        || output.provenance.dependency_hashes != expected
    {
        return Err(failure("E-PIPELINE-CACHE"));
    }
    Ok(output)
}
