//! 明示GPU要求の枠とVRAM予約を共有し、読取不能を空き容量と扱わない。
use crate::{proc, AppError, ChannelId, Result};
use std::{
    future::Future,
    path::PathBuf,
    pin::Pin,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub type ProbeFuture<'a> = Pin<Box<dyn Future<Output = Result<GpuSnapshot>> + Send + 'a>>;
pub trait VramProbe: Send + Sync {
    fn snapshot<'a>(&'a self, device_uuid: &'a str) -> ProbeFuture<'a>;
}

/// UUID等の機器情報はDebugやログへ自動出力しない。
#[derive(Clone)]
pub struct GpuSnapshot {
    pub device_uuid: String,
    pub device_index: u32,
    pub free_bytes: u64,
}

fn failure(code: &str, cause: &'static str) -> AppError {
    tracing::error!(code, cause, "GPUの実行条件を確認できませんでした");
    AppError::new(
        code,
        "GPU処理を開始できませんでした",
        "GPUの明示許可・対象機器・ドライバー・空きVRAMと待機上限を確認してください",
    )
}
fn valid_uuid(value: &str) -> bool {
    value.strip_prefix("GPU-").is_some_and(|id| {
        id.len() == 36
            && id.bytes().enumerate().all(|(index, byte)| {
                if matches!(index, 8 | 13 | 18 | 23) {
                    byte == b'-'
                } else {
                    byte.is_ascii_hexdigit()
                }
            })
    })
}

/// 既存ツールの絶対パスだけを受け、読取専用のquery-gpu以外を発行しない。
pub struct NvidiaSmiProbe {
    program: PathBuf,
    timeout: Duration,
    max_output_bytes: usize,
}
impl NvidiaSmiProbe {
    pub fn new(program: PathBuf, timeout: Duration, max_output_bytes: usize) -> Result<Self> {
        crate::paths::require_regular_file(&program)?;
        if timeout.is_zero() || max_output_bytes == 0 {
            return Err(failure("E-GPU-CONFIG", "probe_configuration"));
        }
        Ok(Self {
            program,
            timeout,
            max_output_bytes,
        })
    }
}
impl VramProbe for NvidiaSmiProbe {
    fn snapshot<'a>(&'a self, device_uuid: &'a str) -> ProbeFuture<'a> {
        Box::pin(async move {
            if !valid_uuid(device_uuid) {
                return Err(failure("E-GPU-CONFIG", "device_uuid"));
            }
            let args = [
                "--query-gpu=index,uuid,memory.free".into(),
                "--format=csv,noheader,nounits".into(),
                format!("--id={device_uuid}").into(),
            ];
            let output = proc::run(
                &self.program,
                &args,
                proc::RunOptions {
                    timeout: self.timeout,
                    max_output_bytes: self.max_output_bytes,
                },
            )
            .await
            .map_err(|error| {
                tracing::error!(code = %error.code, "GPU情報の読取プロセスが失敗しました");
                failure("E-GPU-UNAVAILABLE", "probe_process")
            })?;
            let text = std::str::from_utf8(&output.stdout)
                .map_err(|_| failure("E-GPU-UNAVAILABLE", "probe_encoding"))?;
            parse_snapshot(text, device_uuid)
        })
    }
}
fn parse_snapshot(text: &str, requested: &str) -> Result<GpuSnapshot> {
    let rows = text
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect::<Vec<_>>();
    if rows.len() != 1 {
        return Err(failure("E-GPU-UNAVAILABLE", "probe_row_count"));
    }
    let fields = rows[0].split(',').map(str::trim).collect::<Vec<_>>();
    if fields.len() != 3 || !valid_uuid(fields[1]) || !fields[1].eq_ignore_ascii_case(requested) {
        return Err(failure("E-GPU-UNAVAILABLE", "probe_device_mismatch"));
    }
    let device_index = fields[0]
        .parse::<u32>()
        .map_err(|_| failure("E-GPU-UNAVAILABLE", "probe_index"))?;
    let free_bytes = fields[2]
        .parse::<u64>()
        .ok()
        .and_then(|mib| mib.checked_mul(1024 * 1024))
        .ok_or_else(|| failure("E-GPU-UNAVAILABLE", "probe_memory"))?;
    Ok(GpuSnapshot {
        device_uuid: fields[1].to_owned(),
        device_index,
        free_bytes,
    })
}

#[derive(Clone, Copy)]
pub struct GpuRequirement {
    pub minimum_free_bytes: u64,
    pub headroom_bytes: u64,
    pub wait_timeout: Duration,
}
impl GpuRequirement {
    fn required(&self) -> Result<u64> {
        if self.minimum_free_bytes == 0 || self.wait_timeout.is_zero() {
            return Err(failure("E-GPU-CONFIG", "requirement"));
        }
        self.minimum_free_bytes
            .checked_add(self.headroom_bytes)
            .ok_or_else(|| failure("E-GPU-CONFIG", "requirement_overflow"))
    }
}
#[derive(Default)]
struct Reservations {
    baseline: Option<u64>,
    bytes: u64,
    broken: bool,
}

/// ホストはGPU UUIDごとに1個を作り、全チャンネル・工程へcloneを注入する。
#[derive(Clone)]
pub struct GpuCoordinator {
    device_uuid: Arc<str>,
    slots: Arc<Semaphore>,
    reservations: Arc<Mutex<Reservations>>,
    probe: Arc<dyn VramProbe>,
}
impl GpuCoordinator {
    pub fn new(
        device_uuid: String,
        max_concurrent_jobs: usize,
        probe: Arc<dyn VramProbe>,
    ) -> Result<Self> {
        if !valid_uuid(&device_uuid)
            || max_concurrent_jobs == 0
            || max_concurrent_jobs > Semaphore::MAX_PERMITS
        {
            return Err(failure("E-GPU-CONFIG", "coordinator"));
        }
        Ok(Self {
            device_uuid: Arc::from(device_uuid),
            slots: Arc::new(Semaphore::new(max_concurrent_jobs)),
            reservations: Arc::new(Mutex::new(Reservations::default())),
            probe,
        })
    }
    /// 待機/照会中にfutureをdropしても枠を残さない。GPU起動は呼出側が明示する。
    pub async fn acquire(
        &self,
        channel: &ChannelId,
        requirement: &GpuRequirement,
    ) -> Result<GpuPermit> {
        let required = requirement.required()?;
        let operation = async {
            let slot = self
                .slots
                .clone()
                .acquire_owned()
                .await
                .map_err(|_| failure("E-GPU-STATE", "closed_slots"))?;
            let snapshot = self.probe.snapshot(&self.device_uuid).await?;
            if !snapshot.device_uuid.eq_ignore_ascii_case(&self.device_uuid) {
                return Err(failure("E-GPU-UNAVAILABLE", "probe_device_mismatch"));
            }
            let mut state = self
                .reservations
                .lock()
                .map_err(|_| failure("E-GPU-STATE", "poisoned_reservations"))?;
            if state.broken {
                return Err(failure("E-GPU-STATE", "broken_reservations"));
            }
            let baseline = state.baseline.unwrap_or(snapshot.free_bytes);
            let unreserved = baseline
                .checked_sub(state.bytes)
                .ok_or_else(|| failure("E-GPU-STATE", "reservation_overflow"))?;
            // 実測freeと予約前基準の残りを別々に制限し、実割当を二重控除しない。
            if snapshot.free_bytes.min(unreserved) < required {
                tracing::warn!(
                    channel_id = channel.as_str(),
                    code = "E-GPU-BUSY",
                    "GPUの空きVRAMが予約条件を満たしません"
                );
                return Err(failure("E-GPU-BUSY", "insufficient_memory"));
            }
            state.bytes = state
                .bytes
                .checked_add(required)
                .ok_or_else(|| failure("E-GPU-STATE", "reservation_overflow"))?;
            state.baseline = Some(baseline);
            drop(state);
            Ok(GpuPermit {
                channel: channel.clone(),
                snapshot,
                reserved_bytes: required,
                reservations: self.reservations.clone(),
                _slot: slot,
            })
        };
        tokio::time::timeout(requirement.wait_timeout, operation)
            .await
            .map_err(|_| failure("E-GPU-BUSY", "acquire_timeout"))?
    }
}

pub struct GpuPermit {
    channel: ChannelId,
    snapshot: GpuSnapshot,
    reserved_bytes: u64,
    reservations: Arc<Mutex<Reservations>>,
    _slot: OwnedSemaphorePermit,
}
impl GpuPermit {
    pub fn channel_id(&self) -> &ChannelId {
        &self.channel
    }
    pub fn device_index(&self) -> u32 {
        self.snapshot.device_index
    }
    pub fn device_uuid(&self) -> &str {
        &self.snapshot.device_uuid
    }
    pub fn ensure_channel(&self, channel: &ChannelId) -> Result<()> {
        if &self.channel != channel {
            return Err(failure("E-GPU-CHANNEL", "channel_mismatch"));
        }
        Ok(())
    }
}
impl Drop for GpuPermit {
    fn drop(&mut self) {
        match self.reservations.lock() {
            Ok(mut state) => {
                if let Some(remaining) = state.bytes.checked_sub(self.reserved_bytes) {
                    state.bytes = remaining;
                    if remaining == 0 {
                        state.baseline = None;
                    }
                } else {
                    state.broken = true;
                    tracing::error!(code = "E-GPU-STATE", "GPU予約の解放量が一致しません");
                }
            }
            Err(_) => tracing::error!(code = "E-GPU-STATE", "GPU予約の解放状態を確認できません"),
        }
    }
}

#[cfg(test)]
#[path = "gpu_tests.rs"]
mod tests;
