#![cfg(test)]
#![allow(clippy::unwrap_used)]
use picocast_ai::Cancellation;
use picocast_core::{clock::Timestamp, ChannelId};
use picocast_pipeline::{
    content_hash, CachePolicy, Dag, Node, Pipeline, ResourceGate, ResourcePermit, RetrySafety,
    RunOptions, Step, StepCtx, StepFailure, StepFuture, TickOutcome,
};
use picocast_store::{
    jobs::{LeaseOptions, NewJob, WaitReason},
    repository::{Job, JobKey},
    DataMode, Store, StoreOptions, StorePaths,
};
use serde_json::{json, Value};
use std::{
    cell::{Cell, RefCell},
    collections::{BTreeMap, BTreeSet},
    rc::Rc,
    time::Duration,
};

fn channel() -> ChannelId {
    ChannelId::new("fixture").unwrap()
}
fn store_options() -> StoreOptions {
    StoreOptions {
        busy_timeout: Duration::from_secs(2),
        backup_pages_per_step: 8,
        backup_pause: Duration::from_millis(1),
    }
}
fn options() -> RunOptions {
    RunOptions {
        lease: LeaseOptions {
            lease_duration: Duration::from_secs(2),
            stale_after: Duration::from_secs(1),
        },
        heartbeat_interval: Duration::from_millis(5),
        step_timeout: Duration::from_secs(2),
        max_nodes: 100,
        max_payload_bytes: 100_000,
    }
}
fn at() -> Timestamp {
    Timestamp::parse("2020-01-01T00:00:00Z").unwrap()
}
fn new_job(id: &str) -> NewJob {
    NewJob {
        channel_id: channel(),
        id: id.into(),
        project_id: None,
        kind: "pipeline".into(),
        priority: 0,
        not_before: None,
        max_attempts: 3,
        at: at(),
    }
}
fn fixture() -> (tempfile::TempDir, StorePaths, Store) {
    let temp = tempfile::tempdir().unwrap();
    let paths = StorePaths::new(temp.path(), DataMode::Development).unwrap();
    let store = Store::open(&paths, store_options()).unwrap();
    store.create_channel(&channel(), "合成工程").unwrap();
    (temp, paths, store)
}
fn source() -> String {
    content_hash(&"synthetic-source-v1").unwrap()
}
fn node(id: &str, value: i64, dependencies: Vec<String>) -> Node {
    Node {
        id: id.into(),
        step: "sum".into(),
        version: 1,
        source_sha256: source(),
        input: json!({"value":value}),
        asset_hashes: BTreeSet::new(),
        model_id: None,
        settings: json!({"fixture":true}),
        dependencies,
        uses_gpu: false,
        retry_safety: RetrySafety::Repeatable,
        cache_policy: CachePolicy::ContentAddressed,
    }
}
struct Permit(Rc<Cell<usize>>);
impl Drop for Permit {
    fn drop(&mut self) {
        self.0.set(self.0.get() - 1);
    }
}
impl ResourcePermit for Permit {
    fn sleep_inhibited(&self) -> bool {
        true
    }
    fn gpu_ready(&self) -> bool {
        true
    }
}
struct Resources(Rc<Cell<usize>>);
impl ResourceGate for Resources {
    fn acquire<'a>(
        &'a mut self,
        _channel: &'a ChannelId,
        _gpu: bool,
        _cancel: &'a Cancellation,
    ) -> StepFuture<'a, Box<dyn ResourcePermit>> {
        self.0.set(self.0.get() + 1);
        let hold = self.0.clone();
        Box::pin(async move { Ok(Box::new(Permit(hold)) as Box<dyn ResourcePermit>) })
    }
}
type Counts = Rc<RefCell<BTreeMap<String, usize>>>;
struct Sum {
    counts: Counts,
    behavior: Rc<Cell<u8>>,
}
impl Step for Sum {
    const NAME: &'static str = "sum";
    const VERSION: u32 = 1;
    type Input = Value;
    type Output = i64;
    fn run<'a>(&'a self, input: Value, ctx: &'a StepCtx<'a>) -> StepFuture<'a, i64> {
        Box::pin(async move {
            *self
                .counts
                .borrow_mut()
                .entry(ctx.node_id.into())
                .or_default() += 1;
            ctx.cancel.check().map_err(StepFailure::Failed)?;
            match self.behavior.get() {
                1 => {
                    self.behavior.set(0);
                    return Err(StepFailure::Waiting {
                        reason: WaitReason::Offline,
                        resume_at: None,
                    });
                }
                2 => return std::future::pending().await,
                3 => {
                    self.behavior.set(0);
                    return Err(StepFailure::Failed(picocast_core::AppError::new(
                        "E-PIPELINE-OUTPUT",
                        "合成失敗",
                        "再開してください",
                    )));
                }
                _ => {}
            }
            let own = input["value"].as_i64().unwrap();
            let dependencies = ctx
                .dependencies
                .values()
                .map(|value| value.as_i64().unwrap())
                .sum::<i64>();
            Ok(own + dependencies)
        })
    }
}
fn pipeline(counts: Counts, behavior: Rc<Cell<u8>>, permits: Rc<Cell<usize>>) -> Pipeline {
    let mut pipeline = Pipeline::new(options(), Box::new(Resources(permits))).unwrap();
    pipeline
        .register(Sum { counts, behavior }, source())
        .unwrap();
    pipeline
}
fn job(store: &Store, id: &str) -> Job {
    store
        .repository(&channel())
        .unwrap()
        .get::<Job>(&JobKey {
            channel_id: channel(),
            id: id.into(),
        })
        .unwrap()
        .unwrap()
}
async fn finish(pipeline: &mut Pipeline, store: &mut Store, id: &str) {
    let (_handle, mut cancel) = Cancellation::pair();
    for _ in 0..100 {
        if matches!(
            pipeline
                .tick(store, &channel(), "worker", &mut cancel)
                .await
                .unwrap(),
            TickOutcome::Succeeded { .. }
        ) {
            return;
        }
    }
    assert_eq!(job(store, id).status, "succeeded");
}

#[tokio::test]
async fn one_line_change_reruns_only_that_voice_and_downstream_dag_and_preserves_other_cache() {
    let (_temp, _paths, mut store) = fixture();
    let counts = Counts::default();
    let permits = Rc::new(Cell::new(0));
    let mut pipeline = pipeline(counts.clone(), Rc::new(Cell::new(0)), permits.clone());
    let mut dag = Dag {
        nodes: (0..20)
            .map(|index| node(&format!("voice:{index}"), index + 1, vec![]))
            .collect(),
    };
    dag.nodes.push(node(
        "timeline",
        0,
        (0..20).map(|index| format!("voice:{index}")).collect(),
    ));
    dag.nodes.push(node("render", 0, vec!["timeline".into()]));
    dag.nodes.push(node("qa", 0, vec!["render".into()]));
    pipeline
        .enqueue(&mut store, &new_job("first"), &dag)
        .unwrap();
    finish(&mut pipeline, &mut store, "first").await;
    assert_eq!(counts.borrow().values().sum::<usize>(), 23);
    counts.borrow_mut().clear();
    dag.nodes[0].input = json!({"value":999});
    assert_eq!(
        dag.invalidated(&BTreeSet::from(["voice:0".into()]))
            .unwrap(),
        BTreeSet::from([
            "voice:0".into(),
            "timeline".into(),
            "render".into(),
            "qa".into()
        ])
    );
    pipeline
        .enqueue(&mut store, &new_job("edited"), &dag)
        .unwrap();
    finish(&mut pipeline, &mut store, "edited").await;
    assert_eq!(
        counts.borrow().keys().cloned().collect::<BTreeSet<_>>(),
        BTreeSet::from([
            "voice:0".into(),
            "timeline".into(),
            "render".into(),
            "qa".into()
        ])
    );
    assert_eq!(permits.get(), 0);
}

#[tokio::test]
async fn restart_recovers_repeatable_step_and_reconcile_step_waits_without_resending() {
    for safety in [RetrySafety::Repeatable, RetrySafety::Reconcile] {
        let (_temp, paths, mut store) = fixture();
        let counts = Counts::default();
        let mut pipeline = pipeline(counts.clone(), Rc::new(Cell::new(0)), Rc::new(Cell::new(0)));
        let mut work = node("voice", 4, vec![]);
        work.retry_safety = safety;
        let dag = Dag { nodes: vec![work] };
        pipeline
            .enqueue(&mut store, &new_job("resume"), &dag)
            .unwrap();
        let lease = store
            .claim_job(&channel(), "lost-worker", &at(), options().lease)
            .unwrap()
            .unwrap();
        let hash = dag.nodes[0]
            .cache_key(&channel(), &BTreeMap::new())
            .unwrap();
        store
            .begin_job_step(&lease, &at(), "voice", 1, &hash)
            .unwrap();
        drop(store);
        let mut store = Store::open(&paths, store_options()).unwrap();
        let (_handle, mut cancel) = Cancellation::pair();
        let result = pipeline
            .tick(&mut store, &channel(), "new-worker", &mut cancel)
            .await
            .unwrap();
        if safety == RetrySafety::Repeatable {
            assert!(matches!(result, TickOutcome::Succeeded { .. }));
            assert_eq!(counts.borrow()["voice"], 1);
        } else {
            assert!(matches!(
                result,
                TickOutcome::Waiting {
                    reason: WaitReason::ExternalUnknown,
                    ..
                }
            ));
            assert!(counts.borrow().is_empty());
            assert_eq!(
                job(&store, "resume").wait_reason.as_deref(),
                Some("external_unknown")
            );
        }
        assert_eq!(job(&store, "resume").attempts, 1);
        if safety == RetrySafety::Reconcile {
            assert!(store.resume_waiting_job(&channel(), "resume").is_err());
            let now = Timestamp::parse(&picocast_core::clock::now_utc_iso()).unwrap();
            assert!(store
                .confirm_job_step_not_sent(&channel(), "resume", "voice", false, "operator", &now)
                .is_err());
            store
                .confirm_job_step_not_sent(&channel(), "resume", "voice", true, "operator", &now)
                .unwrap();
            finish(&mut pipeline, &mut store, "resume").await;
            assert_eq!(counts.borrow()["voice"], 1);
        }
    }
}

#[tokio::test]
async fn offline_wait_does_not_become_uncertain_or_increment_failures_and_cancel_drops_resources() {
    let (_temp, paths, mut store) = fixture();
    let counts = Counts::default();
    let behavior = Rc::new(Cell::new(1));
    let permits = Rc::new(Cell::new(0));
    let mut pipeline = pipeline(counts, behavior.clone(), permits.clone());
    let mut work = node("voice", 4, vec![]);
    work.retry_safety = RetrySafety::Reconcile;
    let dag = Dag { nodes: vec![work] };
    pipeline
        .enqueue(&mut store, &new_job("wait"), &dag)
        .unwrap();
    let (_handle, mut cancel) = Cancellation::pair();
    assert!(matches!(
        pipeline
            .tick(&mut store, &channel(), "worker", &mut cancel)
            .await
            .unwrap(),
        TickOutcome::Waiting {
            reason: WaitReason::Offline,
            ..
        }
    ));
    assert_eq!(job(&store, "wait").attempts, 0);
    store.resume_waiting_job(&channel(), "wait").unwrap();
    finish(&mut pipeline, &mut store, "wait").await;
    behavior.set(2);
    let dag = Dag {
        nodes: vec![node("pending", 999, vec![])],
    };
    pipeline
        .enqueue(&mut store, &new_job("cancel"), &dag)
        .unwrap();
    let mut controller = Store::open(&paths, store_options()).unwrap();
    let active_channel = channel();
    let operation = pipeline.tick(&mut store, &active_channel, "worker", &mut cancel);
    let control = async {
        tokio::time::sleep(Duration::from_millis(15)).await;
        controller
            .request_job_cancel(
                &channel(),
                "cancel",
                &Timestamp::parse(&picocast_core::clock::now_utc_iso()).unwrap(),
            )
            .unwrap();
    };
    let (result, _) = tokio::join!(operation, control);
    assert!(matches!(result.unwrap(), TickOutcome::Cancelled { .. }));
    assert_eq!(permits.get(), 0);
    assert_eq!(job(&store, "cancel").attempts, 0);
}

#[test]
fn cycle_wrong_version_asset_hash_and_cross_channel_cache_are_rejected() {
    let counts = Counts::default();
    let pipeline = pipeline(counts, Rc::new(Cell::new(0)), Rc::new(Cell::new(0)));
    let (_temp, _paths, mut store) = fixture();
    let cyclic = Dag {
        nodes: vec![
            node("a", 1, vec!["b".into()]),
            node("b", 2, vec!["a".into()]),
        ],
    };
    assert!(pipeline
        .enqueue(&mut store, &new_job("cycle"), &cyclic)
        .is_err());
    let mut wrong = node("wrong", 1, vec![]);
    wrong.version = 2;
    assert!(pipeline
        .enqueue(&mut store, &new_job("version"), &Dag { nodes: vec![wrong] })
        .is_err());
    let mut wrong = node("wrong", 1, vec![]);
    wrong.asset_hashes.insert("file.png".into());
    assert!(pipeline
        .enqueue(&mut store, &new_job("asset"), &Dag { nodes: vec![wrong] })
        .is_err());
    let work = node("a", 1, vec![]);
    assert_ne!(
        work.cache_key(&channel(), &BTreeMap::new()).unwrap(),
        work.cache_key(&ChannelId::new("other").unwrap(), &BTreeMap::new())
            .unwrap()
    );
}

#[tokio::test]
async fn mutable_external_steps_never_reuse_global_cache_and_failures_are_bounded() {
    let (_temp, _paths, mut store) = fixture();
    let counts = Counts::default();
    let mut pipeline = pipeline(counts.clone(), Rc::new(Cell::new(3)), Rc::new(Cell::new(0)));
    let mut work = node("external", 4, vec![]);
    work.cache_policy = CachePolicy::Never;
    let dag = Dag { nodes: vec![work] };
    pipeline
        .enqueue(&mut store, &new_job("first"), &dag)
        .unwrap();
    let (_handle, mut cancel) = Cancellation::pair();
    assert!(matches!(
        pipeline
            .tick(&mut store, &channel(), "worker", &mut cancel)
            .await
            .unwrap(),
        TickOutcome::Failed { .. }
    ));
    assert_eq!(job(&store, "first").attempts, 1);
    finish(&mut pipeline, &mut store, "first").await;
    pipeline
        .enqueue(&mut store, &new_job("second"), &dag)
        .unwrap();
    finish(&mut pipeline, &mut store, "second").await;
    assert_eq!(counts.borrow()["external"], 3);
    assert!(store
        .global_repository()
        .list::<picocast_store::repository::StepCache>()
        .unwrap()
        .is_empty());
}

#[tokio::test]
async fn corrupted_cache_is_not_returned_or_overwritten_with_empty_results() {
    let (_temp, _paths, mut store) = fixture();
    let counts = Counts::default();
    let mut pipeline = pipeline(counts.clone(), Rc::new(Cell::new(0)), Rc::new(Cell::new(0)));
    let dag = Dag {
        nodes: vec![node("value", 4, vec![])],
    };
    pipeline
        .enqueue(&mut store, &new_job("first"), &dag)
        .unwrap();
    finish(&mut pipeline, &mut store, "first").await;
    let mut cache = store
        .global_repository()
        .list::<picocast_store::repository::StepCache>()
        .unwrap()
        .pop()
        .unwrap();
    cache.outputs_json["output"] = json!(999);
    store.global_repository().save(&cache).unwrap();
    counts.borrow_mut().clear();
    pipeline
        .enqueue(&mut store, &new_job("second"), &dag)
        .unwrap();
    let (_handle, mut cancel) = Cancellation::pair();
    assert!(
        matches!(pipeline.tick(&mut store,&channel(),"worker",&mut cancel).await.unwrap(),TickOutcome::Failed {code,..} if code=="E-PIPELINE-CACHE")
    );
    assert!(counts.borrow().is_empty());
    assert_eq!(
        store
            .global_repository()
            .list::<picocast_store::repository::StepCache>()
            .unwrap()[0]
            .outputs_json["output"],
        999
    );
}

#[test]
fn content_keys_change_with_assets_models_settings_sources_and_versions() {
    let original = node("one", 1, vec![]);
    let key = original.cache_key(&channel(), &BTreeMap::new()).unwrap();
    for variant in 0..5 {
        let mut changed = original.clone();
        match variant {
            0 => {
                changed.asset_hashes.insert("a".repeat(64));
            }
            1 => changed.model_id = Some("new-model".into()),
            2 => changed.settings = json!({"value":2}),
            3 => changed.source_sha256 = "b".repeat(64),
            _ => changed.version = 2,
        };
        assert_ne!(
            key,
            changed.cache_key(&channel(), &BTreeMap::new()).unwrap()
        );
    }
    assert_eq!(
        content_hash(&json!({"a":1,"b":2})).unwrap(),
        content_hash(&json!({"b":2,"a":1})).unwrap()
    );
}

#[tokio::test]
async fn pipeline_does_not_claim_or_fail_other_queue_owners_jobs() {
    let (_temp, _paths, mut store) = fixture();
    let mut unrelated = new_job("unrelated");
    unrelated.kind = "other-service".into();
    unrelated.priority = 999;
    store.enqueue_job(&unrelated, &[]).unwrap();
    let mut pipeline = pipeline(
        Counts::default(),
        Rc::new(Cell::new(0)),
        Rc::new(Cell::new(0)),
    );
    pipeline
        .enqueue(
            &mut store,
            &new_job("owned"),
            &Dag {
                nodes: vec![node("one", 1, vec![])],
            },
        )
        .unwrap();
    finish(&mut pipeline, &mut store, "owned").await;
    assert_eq!(job(&store, "unrelated").status, "queued");
    assert_eq!(job(&store, "unrelated").attempts, 0);
    let (_handle, mut cancel) = Cancellation::pair();
    assert!(matches!(
        pipeline
            .tick(&mut store, &channel(), "worker", &mut cancel)
            .await
            .unwrap(),
        TickOutcome::Idle
    ));
}
