#![cfg(test)]
#![allow(clippy::unwrap_used)]
use picocast_ai::Cancellation;
use picocast_core::{
    gpu::{GpuCoordinator, GpuRequirement, GpuSnapshot, ProbeFuture, VramProbe},
    ChannelId, Result,
};
use picocast_pipeline::{
    CoordinatedResources, ResourceGate, SleepInhibitor, SleepPermit, StepFailure,
};
use std::{cell::Cell, rc::Rc, sync::Arc, time::Duration};

const UUID: &str = "GPU-00000000-0000-0000-0000-000000000001";
struct Probe;
impl VramProbe for Probe {
    fn snapshot<'a>(&'a self, device: &'a str) -> ProbeFuture<'a> {
        Box::pin(async move {
            Ok(GpuSnapshot {
                device_uuid: device.into(),
                device_index: 0,
                free_bytes: 1000,
            })
        })
    }
}
struct Sleep {
    count: Rc<Cell<usize>>,
    active: bool,
    foreign: bool,
}
struct Hold {
    count: Rc<Cell<usize>>,
    channel: ChannelId,
    active: bool,
}
impl Drop for Hold {
    fn drop(&mut self) {
        self.count.set(self.count.get() - 1);
    }
}
impl SleepPermit for Hold {
    fn channel_id(&self) -> &ChannelId {
        &self.channel
    }
    fn active(&self) -> bool {
        self.active
    }
}
impl SleepInhibitor for Sleep {
    fn acquire(&mut self, channel: &ChannelId) -> Result<Box<dyn SleepPermit>> {
        self.count.set(self.count.get() + 1);
        Ok(Box::new(Hold {
            count: self.count.clone(),
            channel: if self.foreign {
                ChannelId::new("foreign")?
            } else {
                channel.clone()
            },
            active: self.active,
        }))
    }
}
fn requirement() -> GpuRequirement {
    GpuRequirement {
        minimum_free_bytes: 600,
        headroom_bytes: 100,
        wait_timeout: Duration::from_millis(5),
    }
}

#[tokio::test]
async fn shared_gpu_slot_waits_without_acquiring_sleep_and_releases_both_permits() {
    let gpu = GpuCoordinator::new(UUID.into(), 1, Arc::new(Probe)).unwrap();
    let count = Rc::new(Cell::new(0));
    let mut first = CoordinatedResources::new(
        Some((gpu.clone(), requirement())),
        Box::new(Sleep {
            count: count.clone(),
            active: true,
            foreign: false,
        }),
        Duration::from_secs(1),
    )
    .unwrap();
    let mut second = CoordinatedResources::new(
        Some((gpu, requirement())),
        Box::new(Sleep {
            count: count.clone(),
            active: true,
            foreign: false,
        }),
        Duration::from_secs(1),
    )
    .unwrap();
    let channel_a = ChannelId::new("a").unwrap();
    let channel_b = ChannelId::new("b").unwrap();
    let (_handle, cancel) = Cancellation::pair();
    let hold = first.acquire(&channel_a, true, &cancel).await.ok().unwrap();
    assert!(hold.gpu_ready() && hold.sleep_inhibited());
    assert_eq!(count.get(), 1);
    assert!(matches!(
        second.acquire(&channel_b, true, &cancel).await,
        Err(StepFailure::Waiting {
            reason: picocast_store::jobs::WaitReason::GpuBusy,
            resume_at: Some(_)
        })
    ));
    assert_eq!(count.get(), 1);
    drop(hold);
    assert_eq!(count.get(), 0);
    let hold = second
        .acquire(&channel_b, true, &cancel)
        .await
        .ok()
        .unwrap();
    assert!(hold.gpu_ready());
    drop(hold);
    assert_eq!(count.get(), 0);
}

#[tokio::test]
async fn cpu_still_requires_active_same_channel_sleep_permit() {
    for (active, foreign) in [(false, false), (true, true)] {
        let count = Rc::new(Cell::new(0));
        let mut resources = CoordinatedResources::new(
            None,
            Box::new(Sleep {
                count: count.clone(),
                active,
                foreign,
            }),
            Duration::from_secs(1),
        )
        .unwrap();
        let (_handle, cancel) = Cancellation::pair();
        assert!(
            matches!(resources.acquire(&ChannelId::new("a").unwrap(),false,&cancel).await,Err(StepFailure::Failed(error)) if error.code=="E-PIPELINE-RESOURCE")
        );
        assert_eq!(count.get(), 0);
    }
}

#[tokio::test]
async fn cpu_only_host_needs_no_gpu_but_rejects_gpu_work() {
    let count = Rc::new(Cell::new(0));
    let mut resources = CoordinatedResources::new(
        None,
        Box::new(Sleep {
            count: count.clone(),
            active: true,
            foreign: false,
        }),
        Duration::from_secs(1),
    )
    .unwrap();
    let channel = ChannelId::new("cpu").unwrap();
    let (_handle, cancel) = Cancellation::pair();
    let permit = resources
        .acquire(&channel, false, &cancel)
        .await
        .ok()
        .unwrap();
    assert!(permit.sleep_inhibited());
    assert!(!permit.gpu_ready());
    assert_eq!(count.get(), 1);
    drop(permit);
    assert_eq!(count.get(), 0);
    assert!(matches!(resources.acquire(&channel, true, &cancel).await,
        Err(StepFailure::Failed(error)) if error.code == "E-PIPELINE-RESOURCE"));
    assert_eq!(count.get(), 0);
}
