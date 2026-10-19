//! HTTP・保存先は既存共通境界で点検し、秘密値は認証の所有者へ委譲する。
use super::{failure, Dependency, ProbeFuture, ReadinessProbe};
use picocast_core::{fsutil, http, ChannelId, Result};
use std::{collections::BTreeMap, path::PathBuf, time::Duration};

pub trait CredentialProbe {
    fn valid<'a>(&'a mut self, channel: &'a ChannelId, kind: Dependency) -> ProbeFuture<'a>;
}
pub struct DiskCheck {
    pub directory: PathBuf,
    pub minimum_free_bytes: u64,
}
pub struct SystemProbe {
    channel: ChannelId,
    endpoints: BTreeMap<Dependency, String>,
    credentials: Option<Box<dyn CredentialProbe>>,
    disk: Option<DiskCheck>,
    client: http::Client,
    max_response_bytes: usize,
}
impl SystemProbe {
    pub fn new(
        channel: ChannelId,
        endpoints: BTreeMap<Dependency, String>,
        credentials: Option<Box<dyn CredentialProbe>>,
        disk: Option<DiskCheck>,
        timeout: Duration,
        max_response_bytes: usize,
    ) -> Result<Self> {
        if max_response_bytes == 0
            || endpoints.keys().any(|kind| !kind.local())
            || disk
                .as_ref()
                .is_some_and(|disk| !disk.directory.is_absolute() || disk.minimum_free_bytes == 0)
        {
            return Err(failure("E-PREFLIGHT-SETTINGS"));
        }
        Ok(Self {
            channel,
            endpoints,
            credentials,
            disk,
            client: http::local_client(timeout)?,
            max_response_bytes,
        })
    }
}
impl ReadinessProbe for SystemProbe {
    fn ready<'a>(&'a mut self, channel: &'a ChannelId, kind: Dependency) -> ProbeFuture<'a> {
        Box::pin(async move {
            if channel != &self.channel {
                return Err(failure("E-PREFLIGHT-CHANNEL"));
            }
            match kind {
                Dependency::GeminiCredential | Dependency::YoutubeToken => {
                    self.credentials
                        .as_mut()
                        .ok_or_else(|| failure("E-PREFLIGHT-SETTINGS"))?
                        .valid(channel, kind)
                        .await
                }
                Dependency::Disk => {
                    let disk = self
                        .disk
                        .as_ref()
                        .ok_or_else(|| failure("E-PREFLIGHT-SETTINGS"))?;
                    fsutil::check_output_capacity(&disk.directory, disk.minimum_free_bytes)
                }
                _ => {
                    let endpoint = self
                        .endpoints
                        .get(&kind)
                        .ok_or_else(|| failure("E-PREFLIGHT-SETTINGS"))?;
                    let Some(body) =
                        http::local_health_json(&self.client, endpoint, self.max_response_bytes)
                            .await?
                    else {
                        return Ok(false);
                    };
                    let valid = match kind {
                        Dependency::Voicevox => body
                            .as_str()
                            .is_some_and(|version| !version.trim().is_empty()),
                        Dependency::StableDiffusion => body
                            .as_object()
                            .is_some_and(|options| options.contains_key("sd_model_checkpoint")),
                        Dependency::Ollama => {
                            body.get("models").is_some_and(|models| models.is_array())
                        }
                        _ => false,
                    };
                    if valid {
                        Ok(true)
                    } else {
                        Err(failure("E-PREFLIGHT-SERVICE"))
                    }
                }
            }
        })
    }
}
