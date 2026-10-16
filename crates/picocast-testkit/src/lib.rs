//! 合成録画だけで動くプロバイダとキャッシュ。製品画面には登録しない。
use picocast_ai::{
    CachedGeneration, Completion, FutureResult, HttpMethod, LlmProvider, Operation, ProviderFault,
    ProviderId, ProviderOutput, ProviderResult, ResultCache, Transport, TransportRequest,
    TransportResponse,
};
use picocast_core::{ChannelId, Result};
use serde::Deserialize;
use serde_json::Value;
use std::collections::{BTreeMap, VecDeque};
use std::time::Duration;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecordedExchange {
    pub method: String,
    pub path: String,
    pub expected_body: Option<Value>,
    pub status: u16,
    pub retry_after_ms: Option<u64>,
    pub response: Value,
}

pub struct ReplayTransport {
    exchanges: VecDeque<RecordedExchange>,
    sent: usize,
}
impl ReplayTransport {
    pub fn from_json(source: &str) -> Result<Self> {
        let exchanges = serde_json::from_str(source).map_err(|_| {
            picocast_core::AppError::new(
                "E-AI-PROVIDER",
                "合成録画が不正です",
                "録画契約を確認してください",
            )
        })?;
        Ok(Self { exchanges, sent: 0 })
    }
    pub fn remaining(&self) -> usize {
        self.exchanges.len()
    }
    pub fn sent(&self) -> usize {
        self.sent
    }
}
impl Transport for ReplayTransport {
    fn send<'a>(
        &'a mut self,
        request: TransportRequest,
    ) -> FutureResult<'a, ProviderResult<TransportResponse>> {
        Box::pin(async move {
            let exchange = self
                .exchanges
                .pop_front()
                .ok_or_else(ProviderFault::contract)?;
            self.sent += 1;
            let method = match request.method {
                HttpMethod::Get => "GET",
                HttpMethod::Post => "POST",
            };
            if method != exchange.method
                || !request.url.ends_with(&exchange.path)
                || exchange.expected_body.is_some() && request.body != exchange.expected_body
            {
                return Err(ProviderFault::contract());
            }
            Ok(TransportResponse {
                status: exchange.status,
                retry_after: exchange.retry_after_ms.map(Duration::from_millis),
                body: exchange.response,
            })
        })
    }
}

pub struct FakeProvider {
    channel_id: ChannelId,
    models: Vec<String>,
    responses: VecDeque<ProviderResult<Completion>>,
    pub calls: usize,
}
impl FakeProvider {
    pub fn new(
        channel_id: ChannelId,
        models: Vec<String>,
        responses: Vec<ProviderResult<Completion>>,
    ) -> Self {
        Self {
            channel_id,
            models,
            responses: responses.into(),
            calls: 0,
        }
    }
}
impl LlmProvider for FakeProvider {
    fn channel_id(&self) -> &ChannelId {
        &self.channel_id
    }
    fn id(&self) -> ProviderId {
        ProviderId::Fake
    }
    fn call<'a>(
        &'a mut self,
        operation: Operation<'a>,
    ) -> FutureResult<'a, ProviderResult<ProviderOutput>> {
        Box::pin(async move {
            match operation {
                Operation::Models => Ok(ProviderOutput::Models(self.models.clone())),
                Operation::Generate(_) => {
                    self.calls += 1;
                    self.responses
                        .pop_front()
                        .ok_or_else(ProviderFault::contract)?
                        .map(ProviderOutput::Completion)
                }
            }
        })
    }
}

#[derive(Default)]
pub struct MemoryCache(BTreeMap<(String, String), CachedGeneration>);
impl ResultCache for MemoryCache {
    fn get(&mut self, channel: &ChannelId, key: &str) -> Result<Option<CachedGeneration>> {
        Ok(self
            .0
            .get(&(channel.as_str().to_owned(), key.to_owned()))
            .cloned())
    }
    fn put(&mut self, channel: &ChannelId, key: &str, value: CachedGeneration) -> Result<()> {
        self.0
            .insert((channel.as_str().to_owned(), key.to_owned()), value);
        Ok(())
    }
}
