#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::*;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
const DEVICE: &str = "GPU-01234567-89ab-cdef-0123-456789abcdef";
struct Probe {
    free: AtomicU64,
    blocked: AtomicBool,
    entered: tokio::sync::Notify,
}
impl Probe {
    fn new(free: u64) -> Self {
        Self {
            free: AtomicU64::new(free),
            blocked: AtomicBool::new(false),
            entered: tokio::sync::Notify::new(),
        }
    }
}
impl VramProbe for Probe {
    fn snapshot<'a>(&'a self, device_uuid: &'a str) -> ProbeFuture<'a> {
        Box::pin(async move {
            self.entered.notify_one();
            if self.blocked.load(Ordering::SeqCst) {
                return std::future::pending().await;
            }
            Ok(GpuSnapshot {
                device_uuid: device_uuid.to_owned(),
                device_index: 2,
                free_bytes: self.free.load(Ordering::SeqCst),
            })
        })
    }
}
fn requirement(minimum: u64) -> GpuRequirement {
    GpuRequirement {
        minimum_free_bytes: minimum,
        headroom_bytes: 10,
        wait_timeout: Duration::from_millis(50),
    }
}
#[test]
fn nvidia_rows_reject_na_overflow_wrong_device_and_multiple_devices() {
    let snapshot = parse_snapshot(&format!("2, {DEVICE}, 1024\r\n"), DEVICE).unwrap();
    assert_eq!(snapshot.device_index, 2);
    assert_eq!(snapshot.free_bytes, 1024 * 1024 * 1024);
    for text in [
        format!("2, {DEVICE}, [N/A]"),
        format!("2, {DEVICE}, 18446744073709551615"),
        format!("2, {DEVICE}, 1\n2, {DEVICE}, 2"),
        "2, GPU-ffffffff-ffff-ffff-ffff-ffffffffffff, 1".into(),
    ] {
        assert_eq!(
            parse_snapshot(&text, DEVICE).err().unwrap().code,
            "E-GPU-UNAVAILABLE"
        );
    }
}
#[tokio::test]
async fn shared_slots_memory_and_channel_bound_permits_release_without_double_counting() {
    let probe = Arc::new(Probe::new(100));
    let coordinator = GpuCoordinator::new(DEVICE.into(), 2, probe.clone()).unwrap();
    let channel = ChannelId::new("fixture-a").unwrap();
    let first = coordinator
        .acquire(&channel, &requirement(40))
        .await
        .unwrap();
    let second = coordinator
        .clone()
        .acquire(&channel, &requirement(40))
        .await
        .unwrap();
    assert_eq!(first.device_index(), 2);
    assert!(first
        .ensure_channel(&ChannelId::new("fixture-b").unwrap())
        .is_err());
    assert_eq!(
        coordinator
            .acquire(&channel, &requirement(1))
            .await
            .err()
            .unwrap()
            .code,
        "E-GPU-BUSY"
    );
    drop(first);
    probe.free.store(50, Ordering::SeqCst);
    let replacement = coordinator
        .acquire(&channel, &requirement(40))
        .await
        .unwrap();
    drop(replacement);
    probe.free.store(40, Ordering::SeqCst);
    assert_eq!(
        coordinator
            .acquire(&channel, &requirement(40))
            .await
            .err()
            .unwrap()
            .code,
        "E-GPU-BUSY"
    );
    drop(second);
    probe.free.store(100, Ordering::SeqCst);
    assert!(coordinator
        .acquire(&channel, &requirement(90))
        .await
        .is_ok());
}
#[tokio::test]
async fn cancellation_and_probe_timeout_never_leak_the_acquired_slot() {
    let probe = Arc::new(Probe::new(100));
    probe.blocked.store(true, Ordering::SeqCst);
    let coordinator = GpuCoordinator::new(DEVICE.into(), 1, probe.clone()).unwrap();
    let channel = ChannelId::new("fixture").unwrap();
    let task_coordinator = coordinator.clone();
    let task_channel = channel.clone();
    let task = tokio::spawn(async move {
        task_coordinator
            .acquire(&task_channel, &requirement(40))
            .await
    });
    probe.entered.notified().await;
    task.abort();
    assert!(task.await.err().unwrap().is_cancelled());
    assert_eq!(
        coordinator
            .acquire(&channel, &requirement(40))
            .await
            .err()
            .unwrap()
            .code,
        "E-GPU-BUSY"
    );
    probe.blocked.store(false, Ordering::SeqCst);
    assert!(coordinator
        .acquire(&channel, &requirement(40))
        .await
        .is_ok());
    assert!(coordinator
        .acquire(&channel, &requirement(0))
        .await
        .is_err());
}
