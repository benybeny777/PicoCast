use crate::failure;
use picocast_core::{clock::Timestamp, ChannelId, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, future::Future, pin::Pin, time::Duration};
use tokio::sync::watch;
use zeroize::Zeroizing;

pub type FutureResult<'a, T> = Pin<Box<dyn Future<Output = T> + 'a>>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderId {
    Gemini,
    Ollama,
    OpenAi,
    Fake,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Stage {
    Planning,
    Script,
    Title,
    Review,
    ImagePrompt,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StageModel {
    pub provider: ProviderId,
    pub model: String,
    pub max_input_tokens: u64,
    pub max_output_tokens: u64,
    pub input_micros_per_million: u64,
    pub output_micros_per_million: u64,
}
impl StageModel {
    pub fn validate(&self) -> Result<()> {
        if self.model.is_empty()
            || self.model.contains("..")
            || !self
                .model
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.:/".contains(&b))
            || self.max_input_tokens == 0
            || self.max_output_tokens == 0
        {
            return Err(failure("E-AI-MODEL"));
        }
        if matches!(self.provider, ProviderId::Ollama | ProviderId::Fake)
            && (self.input_micros_per_million != 0 || self.output_micros_per_million != 0)
        {
            return Err(failure("E-AI-BUDGET"));
        }
        self.maximum_cost()?;
        Ok(())
    }
    pub fn cost(&self, usage: Usage) -> Result<i64> {
        let numerator = u128::from(usage.input_tokens)
            .checked_mul(self.input_micros_per_million.into())
            .and_then(|n| {
                u128::from(usage.output_tokens)
                    .checked_mul(self.output_micros_per_million.into())
                    .and_then(|m| n.checked_add(m))
            })
            .ok_or_else(|| failure("E-AI-BUDGET"))?;
        i64::try_from(numerator.div_ceil(1_000_000)).map_err(|_| failure("E-AI-BUDGET"))
    }
    pub fn maximum_cost(&self) -> Result<i64> {
        self.cost(Usage {
            input_tokens: self.max_input_tokens,
            output_tokens: self.max_output_tokens,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelRegistry {
    pub stages: BTreeMap<Stage, StageModel>,
}
impl ModelRegistry {
    pub fn resolve(&self, stage: Stage) -> Result<&StageModel> {
        let model = self
            .stages
            .get(&stage)
            .ok_or_else(|| failure("E-AI-MODEL"))?;
        model.validate()?;
        Ok(model)
    }
}

// 本文・鍵をDebugへ渡さない。
pub struct GenerateRequest {
    pub channel_id: ChannelId,
    pub request_id: String,
    pub project_id: Option<String>,
    pub job_id: Option<String>,
    pub stage: Stage,
    pub prompt: String,
    pub template_version: i64,
    pub settings_hash: String,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Usage {
    pub input_tokens: u64,
    pub output_tokens: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Provenance {
    pub provider: ProviderId,
    pub model: String,
    pub request_hash: String,
    pub template_version: i64,
    pub settings_hash: String,
    pub at: Timestamp,
}

pub struct Generation<T> {
    pub value: T,
    pub usage: Usage,
    pub provenance: Provenance,
    pub cache_hit: bool,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CachedGeneration {
    pub value: Value,
    pub usage: Usage,
    pub provenance: Provenance,
}

/// キャッシュの永続化はパイプラインが所有する。チャンネルを必ずキーに含める。
pub trait ResultCache {
    fn get(&mut self, channel: &ChannelId, key: &str) -> Result<Option<CachedGeneration>>;
    fn put(&mut self, channel: &ChannelId, key: &str, value: CachedGeneration) -> Result<()>;
}

pub struct NoCache;
impl ResultCache for NoCache {
    fn get(&mut self, _channel: &ChannelId, _key: &str) -> Result<Option<CachedGeneration>> {
        Ok(None)
    }
    fn put(&mut self, _channel: &ChannelId, _key: &str, _value: CachedGeneration) -> Result<()> {
        Ok(())
    }
}

pub struct Secret(Zeroizing<String>);
impl Secret {
    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        let value = std::str::from_utf8(bytes).map_err(|_| failure("E-AI-AUTH"))?;
        if value.is_empty() || value.contains(['\r', '\n']) {
            return Err(failure("E-AI-AUTH"));
        }
        Ok(Self(Zeroizing::new(value.to_owned())))
    }
    pub(crate) fn expose(&self) -> &str {
        &self.0
    }
}

#[derive(Clone)]
pub struct CancelHandle(watch::Sender<bool>);
pub struct Cancellation(watch::Receiver<bool>);
impl Cancellation {
    pub fn pair() -> (CancelHandle, Self) {
        let (send, receive) = watch::channel(false);
        (CancelHandle(send), Self(receive))
    }
    pub fn check(&self) -> Result<()> {
        if *self.0.borrow() {
            Err(failure("E-AI-CANCELLED"))
        } else {
            Ok(())
        }
    }
    pub(crate) async fn cancelled(&mut self) {
        loop {
            if *self.0.borrow_and_update() {
                return;
            }
            if self.0.changed().await.is_err() {
                std::future::pending::<()>().await;
            }
        }
    }
}
impl CancelHandle {
    pub fn cancel(&self) {
        self.0.send_replace(true);
    }
}

pub struct GatewayOptions {
    pub max_attempts: u32,
    pub request_timeout: Duration,
    pub retry_base: Duration,
    pub retry_max: Duration,
    pub daily_budget_micros: u64,
    pub daily_token_budget: u64,
    pub max_prompt_bytes: usize,
    pub development: bool,
    pub allow_paid: bool,
}
impl GatewayOptions {
    pub fn validate(&self) -> Result<()> {
        if self.max_attempts == 0
            || self.request_timeout.is_zero()
            || self.retry_base.is_zero()
            || self.retry_max < self.retry_base
            || self.daily_token_budget == 0
            || self.max_prompt_bytes == 0
        {
            return Err(failure("E-AI-BUDGET"));
        }
        Ok(())
    }
}
