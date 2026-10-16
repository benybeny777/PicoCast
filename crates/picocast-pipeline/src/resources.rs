use crate::{failure, ResourceGate, ResourcePermit, StepFailure, StepFuture};
use picocast_ai::Cancellation;
use picocast_core::{
    gpu::{GpuCoordinator, GpuPermit, GpuRequirement},
    ChannelId, Result,
};
use std::time::Duration;

/// TauriがOSの抑止ハンドルを所有する。別channelのpermitは使わない。
pub trait SleepPermit {
    fn channel_id(&self) -> &ChannelId;
    fn active(&self) -> bool;
}
pub trait SleepInhibitor {
    fn acquire(&mut self, channel: &ChannelId) -> Result<Box<dyn SleepPermit>>;
}

pub struct CoordinatedResources {
    gpu: Option<(GpuCoordinator, GpuRequirement)>,
    sleep: Box<dyn SleepInhibitor>,
    retry_after: Duration,
}
impl CoordinatedResources {
    pub fn new(
        gpu: Option<(GpuCoordinator, GpuRequirement)>,
        sleep: Box<dyn SleepInhibitor>,
        retry_after: Duration,
    ) -> Result<Self> {
        if retry_after.is_zero() {
            return Err(failure("E-PIPELINE-SETTINGS"));
        }
        Ok(Self {
            gpu,
            sleep,
            retry_after,
        })
    }
}
struct HeldResources {
    sleep: Box<dyn SleepPermit>,
    gpu: Option<GpuPermit>,
}
impl ResourcePermit for HeldResources {
    fn sleep_inhibited(&self) -> bool {
        self.sleep.active()
    }
    fn gpu_ready(&self) -> bool {
        self.gpu.is_some()
    }
}
impl ResourceGate for CoordinatedResources {
    fn acquire<'a>(
        &'a mut self,
        channel: &'a ChannelId,
        uses_gpu: bool,
        cancel: &'a Cancellation,
    ) -> StepFuture<'a, Box<dyn ResourcePermit>> {
        Box::pin(async move {
            cancel.check().map_err(StepFailure::Failed)?;
            let gpu = if uses_gpu {
                let (coordinator, requirement) = self
                    .gpu
                    .as_ref()
                    .ok_or_else(|| StepFailure::Failed(failure("E-PIPELINE-RESOURCE")))?;
                match coordinator.acquire(channel, requirement).await {
                    Ok(permit) => {
                        permit
                            .ensure_channel(channel)
                            .map_err(StepFailure::Failed)?;
                        Some(permit)
                    }
                    Err(error) if error.code == "E-GPU-BUSY" => {
                        return Err(StepFailure::Waiting {
                            reason: picocast_store::jobs::WaitReason::GpuBusy,
                            resume_at: Some(
                                picocast_core::clock::add_duration(
                                    &crate::now().map_err(StepFailure::Failed)?,
                                    self.retry_after,
                                )
                                .map_err(StepFailure::Failed)?,
                            ),
                        })
                    }
                    Err(error) => return Err(StepFailure::Failed(error)),
                }
            } else {
                None
            };
            cancel.check().map_err(StepFailure::Failed)?;
            let sleep = self.sleep.acquire(channel).map_err(StepFailure::Failed)?;
            if sleep.channel_id() != channel || !sleep.active() {
                return Err(StepFailure::Failed(failure("E-PIPELINE-RESOURCE")));
            }
            Ok(Box::new(HeldResources { sleep, gpu }) as Box<dyn ResourcePermit>)
        })
    }
}
