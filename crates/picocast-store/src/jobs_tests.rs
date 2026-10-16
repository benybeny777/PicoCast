#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::{JobConclusion, JobSignal, LeaseOptions, NewJob, WaitReason};
use crate::{
    repository::{Job, JobKey, JobStep},
    DataMode, Store, StoreOptions, StorePaths,
};
use picocast_core::{
    clock::{self, Timestamp},
    ChannelId,
};
use std::time::Duration;

fn at(seconds: u64) -> Timestamp {
    clock::add_duration(
        &Timestamp::parse("2026-10-16T00:00:00Z").unwrap(),
        Duration::from_secs(seconds),
    )
    .unwrap()
}
fn options() -> StoreOptions {
    StoreOptions {
        busy_timeout: Duration::from_secs(3),
        backup_pages_per_step: 8,
        backup_pause: Duration::from_millis(1),
    }
}
fn lease_options() -> LeaseOptions {
    LeaseOptions {
        lease_duration: Duration::from_secs(60),
        stale_after: Duration::from_secs(30),
    }
}
fn channel() -> ChannelId {
    ChannelId::new("fixture").unwrap()
}
fn fixture() -> (tempfile::TempDir, StorePaths, Store) {
    let temp = tempfile::tempdir().unwrap();
    let paths = StorePaths::new(temp.path(), DataMode::Development).unwrap();
    let store = Store::open(&paths, options()).unwrap();
    store.create_channel(&channel(), "合成ジョブ").unwrap();
    (temp, paths, store)
}
fn request(id: &str) -> NewJob {
    NewJob {
        channel_id: channel(),
        id: id.into(),
        project_id: None,
        kind: "fixture".into(),
        priority: 0,
        not_before: None,
        max_attempts: 3,
        at: at(0),
    }
}
fn get(store: &Store, id: &str) -> Job {
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

#[test]
fn concurrent_claim_is_atomic_and_stale_owner_is_fenced_even_with_same_worker_name() {
    let (_temp, paths, mut store) = fixture();
    store.enqueue_job(&request("job"), &[]).unwrap();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let mut workers = Vec::new();
    for _ in 0..2 {
        let paths = paths.clone();
        let barrier = barrier.clone();
        workers.push(std::thread::spawn(move || {
            let mut store = Store::open(&paths, options()).unwrap();
            barrier.wait();
            store
                .claim_job(&channel(), "same-worker", &at(0), lease_options())
                .unwrap()
        }));
    }
    let leases = workers
        .into_iter()
        .filter_map(|worker| worker.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(leases.len(), 1);
    let original = &leases[0];
    assert_eq!(
        store
            .heartbeat_job(original, &at(1), lease_options())
            .unwrap(),
        JobSignal::Active
    );
    let replacement = store
        .claim_job(&channel(), "same-worker", &at(32), lease_options())
        .unwrap()
        .unwrap();
    assert_ne!(original.fencing_key(), replacement.fencing_key());
    assert!(store
        .heartbeat_job(original, &at(33), lease_options())
        .is_err());
    assert!(store
        .conclude_job(original, &at(33), JobConclusion::Succeeded)
        .is_err());
    store
        .conclude_job(&replacement, &at(33), JobConclusion::Succeeded)
        .unwrap();
    assert_eq!(get(&store, "job").attempts, 1);
}

#[test]
fn waits_do_not_count_failures_and_cancellation_wins_over_success() {
    let (_temp, _paths, mut store) = fixture();
    store.enqueue_job(&request("job"), &[]).unwrap();
    for second in 0..12 {
        let lease = store
            .claim_job(&channel(), "worker", &at(second), lease_options())
            .unwrap()
            .unwrap();
        let job = store
            .conclude_job(
                &lease,
                &at(second),
                JobConclusion::Waiting {
                    reason: WaitReason::Offline,
                    resume_at: None,
                },
            )
            .unwrap();
        assert_eq!(job.attempts, 0);
        assert!(store
            .claim_job(&channel(), "worker", &at(second), lease_options())
            .unwrap()
            .is_none());
        store.resume_waiting_job(&channel(), "job").unwrap();
    }
    let lease = store
        .claim_job(&channel(), "worker", &at(12), lease_options())
        .unwrap()
        .unwrap();
    store
        .request_job_cancel(&channel(), "job", &at(13))
        .unwrap();
    assert_eq!(
        store
            .heartbeat_job(&lease, &at(13), lease_options())
            .unwrap(),
        JobSignal::CancelRequested
    );
    assert_eq!(
        store
            .conclude_job(&lease, &at(13), JobConclusion::Succeeded)
            .unwrap()
            .status,
        "cancelled"
    );
}

#[test]
fn expired_and_cross_channel_leases_cannot_publish_and_bad_enqueue_rolls_back() {
    let (_temp, _paths, mut store) = fixture();
    let invalid = JobStep {
        channel_id: channel(),
        job_id: "wrong".into(),
        step: "step".into(),
        step_version: 1,
        inputs_hash: "a".repeat(64),
        status: "planned".into(),
        output_json: serde_json::Value::Null,
        started_at: None,
        finished_at: None,
        duration_ms: None,
        cost_micros: None,
    };
    assert!(store.enqueue_job(&request("rollback"), &[invalid]).is_err());
    assert!(store
        .repository(&channel())
        .unwrap()
        .get::<Job>(&JobKey {
            channel_id: channel(),
            id: "rollback".into()
        })
        .unwrap()
        .is_none());
    store.enqueue_job(&request("job"), &[]).unwrap();
    let lease = store
        .claim_job(&channel(), "worker", &at(0), lease_options())
        .unwrap()
        .unwrap();
    store
        .begin_job_step(&lease, &at(0), "node", 1, &"b".repeat(64))
        .unwrap();
    assert!(store
        .publish_job_step(&lease, &at(60), "node", serde_json::Value::Null, 1, None)
        .is_err());
    let other = ChannelId::new("other").unwrap();
    store.create_channel(&other, "別").unwrap();
    let mut stolen = lease;
    stolen.channel_id = other;
    assert!(store
        .begin_job_step(&stolen, &at(1), "node", 1, &"b".repeat(64))
        .is_err());
}

#[test]
fn recovery_respects_failure_limit_and_heartbeat_time_order() {
    let (_temp, _paths, mut store) = fixture();
    let mut new = request("job");
    new.max_attempts = 1;
    store.enqueue_job(&new, &[]).unwrap();
    let lease = store
        .claim_job(&channel(), "worker", &at(0), lease_options())
        .unwrap()
        .unwrap();
    store
        .heartbeat_job(&lease, &at(5), lease_options())
        .unwrap();
    assert!(store
        .heartbeat_job(&lease, &at(4), lease_options())
        .is_err());
    assert!(store
        .claim_job(&channel(), "worker", &at(35), lease_options())
        .unwrap()
        .is_none());
    let job = get(&store, "job");
    assert_eq!(job.status, "failed");
    assert_eq!(job.error_code.as_deref(), Some("E-JOB-STUCK"));
}

#[test]
fn source_changes_without_version_bump_are_observed_persistently() {
    let (_temp, paths, mut store) = fixture();
    assert!(!store
        .observe_step_source("voice", 1, &"a".repeat(64), &at(0))
        .unwrap());
    drop(store);
    let mut store = Store::open(&paths, options()).unwrap();
    assert!(!store
        .observe_step_source("voice", 1, &"a".repeat(64), &at(1))
        .unwrap());
    assert!(store
        .observe_step_source("voice", 1, &"b".repeat(64), &at(1))
        .unwrap());
    assert!(!store
        .observe_step_source("voice", 2, &"b".repeat(64), &at(1))
        .unwrap());
}
