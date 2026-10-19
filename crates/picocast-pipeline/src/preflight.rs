//! 設定で選んだ依存だけを、工程の副作用より前に点検する。
pub mod system;
use crate::{ResourceGate, ResourcePermit, StepFailure, StepFuture};
use picocast_ai::Cancellation;
use picocast_core::{clock::Instant, proc::service::OwnedService, AppError, ChannelId, Result};
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsString,
    future::Future,
    path::PathBuf,
    pin::Pin,
    time::Duration,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Dependency {
    Voicevox,
    StableDiffusion,
    Ollama,
    GeminiCredential,
    YoutubeToken,
    Disk,
}
impl Dependency {
    fn code(self) -> &'static str {
        match self {
            Self::Voicevox | Self::StableDiffusion | Self::Ollama => "E-PREFLIGHT-SERVICE",
            Self::GeminiCredential | Self::YoutubeToken => "E-PREFLIGHT-CREDENTIAL",
            Self::Disk => "E-PREFLIGHT-DISK",
        }
    }
    fn local(self) -> bool {
        matches!(self, Self::Voicevox | Self::StableDiffusion | Self::Ollama)
    }
}
pub type ProbeFuture<'a> = Pin<Box<dyn Future<Output = Result<bool>> + 'a>>;
/// 検査実体は呼出元が注入する。認証・容量の読取失敗をfalseへ変換しない。
/// trueはサービスの応答形式、認証期限、必要空き容量まで確認した場合だけ返す。
pub trait ReadinessProbe {
    fn ready<'a>(&'a mut self, channel: &'a ChannelId, dependency: Dependency) -> ProbeFuture<'a>;
}
pub struct ServiceCommand {
    pub program: PathBuf,
    pub args: Vec<OsString>,
}
pub struct PreflightOptions {
    pub probe_timeout: Duration,
    pub startup_timeout: Duration,
    pub poll_interval: Duration,
    /// 回復を無限に繰り返さない。起動後の再起動回数だけを数える。
    pub max_restarts: u32,
}
pub struct Preflight {
    channel: ChannelId,
    required: BTreeSet<Dependency>,
    commands: BTreeMap<Dependency, ServiceCommand>,
    owned: BTreeMap<Dependency, OwnedService>,
    restarts: BTreeMap<Dependency, u32>,
    probe: Box<dyn ReadinessProbe>,
    options: PreflightOptions,
}
impl Preflight {
    pub fn new(
        channel: ChannelId,
        required: BTreeSet<Dependency>,
        commands: BTreeMap<Dependency, ServiceCommand>,
        probe: Box<dyn ReadinessProbe>,
        options: PreflightOptions,
    ) -> Result<Self> {
        if required.is_empty()
            || options.probe_timeout.is_zero()
            || options.startup_timeout.is_zero()
            || options.poll_interval.is_zero()
            || options.poll_interval > options.startup_timeout
            || commands.iter().any(|(kind, command)| {
                !kind.local() || !required.contains(kind) || !command.program.is_absolute()
            })
        {
            return Err(failure("E-PREFLIGHT-SETTINGS"));
        }
        Ok(Self {
            channel,
            required,
            commands,
            owned: BTreeMap::new(),
            restarts: BTreeMap::new(),
            probe,
            options,
        })
    }
    async fn probe(&mut self, kind: Dependency) -> Result<bool> {
        match tokio::time::timeout(
            self.options.probe_timeout,
            self.probe.ready(&self.channel, kind),
        )
        .await
        {
            Ok(result) => result
                .inspect_err(|error| tracing::error!(code = %error.code, "事前点検の読取りに失敗")),
            Err(_) => Err(failure("E-PREFLIGHT-TIMEOUT")),
        }
    }
    async fn ensure(&mut self, kind: Dependency) -> Result<()> {
        let running = match self.owned.get_mut(&kind) {
            Some(service) => service.running()?,
            None => true,
        };
        if !running {
            if let Some(service) = self.owned.get_mut(&kind) {
                service.stop().await?;
            }
            self.owned.remove(&kind);
        }
        if self.probe(kind).await? {
            return Ok(());
        }
        let Some(command) = self.commands.get(&kind) else {
            return Err(failure(kind.code()));
        };
        if let Some(restarts) = self.restarts.get_mut(&kind) {
            if *restarts >= self.options.max_restarts {
                return Err(failure("E-PREFLIGHT-RESTART"));
            }
            *restarts += 1;
        } else {
            self.restarts.insert(kind, 0);
        }
        if let Some(service) = self.owned.get_mut(&kind) {
            service.stop().await?;
            self.owned.remove(&kind);
        }
        // 起動待ちのFutureが破棄された場合も、この局所所有権が即座に回収する。
        let mut service = OwnedService::start(&command.program, &command.args)?;
        let started = Instant::now();
        loop {
            if !service.running()? {
                return Err(failure("E-PREFLIGHT-SERVICE"));
            }
            let remaining = self
                .options
                .startup_timeout
                .saturating_sub(started.elapsed());
            if remaining.is_zero() {
                return Err(failure("E-PREFLIGHT-TIMEOUT"));
            }
            match tokio::time::timeout(remaining, self.probe(kind)).await {
                Ok(Ok(true)) => {
                    self.owned.insert(kind, service);
                    return Ok(());
                }
                Ok(Ok(false)) => {}
                Ok(Err(error)) => return Err(error),
                Err(_) => return Err(failure("E-PREFLIGHT-TIMEOUT")),
            }
            tokio::time::sleep(
                self.options.poll_interval.min(
                    self.options
                        .startup_timeout
                        .saturating_sub(started.elapsed()),
                ),
            )
            .await;
        }
    }
    /// 全検査の不合格をまとめる。いずれか失敗なら呼出元は工程を開始しない。
    pub async fn check(
        &mut self,
        channel: &ChannelId,
        cancel: &Cancellation,
    ) -> std::result::Result<(), Vec<AppError>> {
        if channel != &self.channel {
            return Err(vec![failure("E-PREFLIGHT-CHANNEL")]);
        }
        let mut failures = Vec::new();
        for kind in self.required.clone() {
            let mut cancellation = cancel.clone();
            let result = tokio::select! {
                biased;
                _ = cancellation.cancelled() => Err(failure("E-AI-CANCELLED")),
                result = self.ensure(kind) => result,
            };
            if let Err(error) = result {
                let cancelled = error.code == "E-AI-CANCELLED";
                failures.push(error);
                if cancelled {
                    break;
                }
            }
        }
        if failures.is_empty() {
            if let Err(error) = cancel.check() {
                failures.push(error);
            }
        }
        if failures.is_empty() {
            Ok(())
        } else {
            if let Err(error) = self.shutdown().await {
                failures.push(error);
            }
            Err(failures)
        }
    }
    pub async fn shutdown(&mut self) -> Result<()> {
        let mut first = None;
        let kinds: Vec<_> = self.owned.keys().copied().collect();
        for kind in kinds {
            if let Some(service) = self.owned.get_mut(&kind) {
                match service.stop().await {
                    Ok(()) => {
                        self.owned.remove(&kind);
                    }
                    Err(error) => {
                        if first.is_none() {
                            first = Some(error);
                        }
                    }
                }
            }
        }
        match first {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }
}
/// runnerの資源取得口に挿し、事前点検失敗時にはsleep/GPUも工程も開始しない。
pub struct PreflightResources {
    pub preflight: Preflight,
    pub inner: Box<dyn ResourceGate>,
}
impl ResourceGate for PreflightResources {
    fn acquire<'a>(
        &'a mut self,
        channel: &'a ChannelId,
        uses_gpu: bool,
        cancel: &'a Cancellation,
    ) -> StepFuture<'a, Box<dyn ResourcePermit>> {
        Box::pin(async move {
            if let Err(errors) = self.preflight.check(channel, cancel).await {
                if errors.iter().any(|error| error.code == "E-AI-CANCELLED") {
                    return Err(StepFailure::Cancelled);
                }
                let error = errors
                    .into_iter()
                    .next()
                    .ok_or_else(|| StepFailure::Failed(failure("E-PREFLIGHT-SERVICE")))?;
                return Err(StepFailure::Failed(error));
            }
            self.inner.acquire(channel, uses_gpu, cancel).await
        })
    }
}
fn failure(code: &str) -> AppError {
    tracing::error!(code, "事前点検で生成の開始を停止しました");
    // カタログの読取失敗もそのまま伝播する。
    match AppError::from_code(code) {
        Ok(error) => error,
        Err(error) => error,
    }
}
