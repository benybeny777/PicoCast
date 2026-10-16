use crate::{failure, FutureResult, ProviderId, Secret, Usage};
use picocast_core::{http, ChannelId, Result};
use serde_json::{json, Value};
use std::time::Duration;
use zeroize::Zeroizing;

/// 認証情報を送信できる公式接続先の正本。
pub const GEMINI_ENDPOINT: &str = "https://generativelanguage.googleapis.com/v1beta";
pub const OPENAI_ENDPOINT: &str = "https://api.openai.com/v1";

/// 例外本文・URL・認証情報を含めない通信結果。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FaultKind {
    Disconnected,
    Timeout,
    Http(u16),
    Contract,
}
#[derive(Debug, Clone, Copy)]
pub struct ProviderFault {
    pub kind: FaultKind,
    pub retry_after: Option<Duration>,
}
impl ProviderFault {
    pub fn cost_settlement(self) -> picocast_store::ai_cost::AiCostSettlement {
        if matches!(
            self.kind,
            FaultKind::Http(400 | 401 | 403 | 404 | 422 | 429)
        ) {
            picocast_store::ai_cost::AiCostSettlement::Failed {
                actual_cost_micros: 0,
                error_code: self.code().into(),
            }
        } else {
            picocast_store::ai_cost::AiCostSettlement::Unknown {
                error_code: self.code().into(),
            }
        }
    }
    pub fn contract() -> Self {
        Self {
            kind: FaultKind::Contract,
            retry_after: None,
        }
    }
    pub fn code(self) -> &'static str {
        match self.kind {
            FaultKind::Http(401 | 403) => "E-AI-AUTH",
            FaultKind::Http(429) => "E-AI-RATE",
            FaultKind::Disconnected => "E-AI-OFFLINE",
            FaultKind::Timeout => "E-AI-TIMEOUT",
            _ => "E-AI-PROVIDER",
        }
    }
    pub fn retryable(self) -> bool {
        matches!(
            self.kind,
            FaultKind::Disconnected | FaultKind::Http(429 | 503)
        )
    }
}
pub type ProviderResult<T> = std::result::Result<T, ProviderFault>;
pub(crate) fn gemini_usage(body: &Value) -> ProviderResult<Usage> {
    let input = body["usageMetadata"]["promptTokenCount"]
        .as_u64()
        .ok_or_else(ProviderFault::contract)?;
    let total = body["usageMetadata"]["totalTokenCount"]
        .as_u64()
        .ok_or_else(ProviderFault::contract)?;
    Ok(Usage {
        input_tokens: input,
        output_tokens: total
            .checked_sub(input)
            .ok_or_else(ProviderFault::contract)?,
    })
}

pub struct CompletionInput<'a> {
    pub images: &'a [crate::image::InlineImage],
    pub model: &'a str,
    pub prompt: &'a str,
    pub schema: &'a Value,
    pub max_output_tokens: u64,
}
pub enum Operation<'a> {
    Models,
    Generate(CompletionInput<'a>),
}
pub struct Completion {
    pub text: String,
    pub usage: Usage,
}
pub enum ProviderOutput {
    Models(Vec<String>),
    Completion(Completion),
}

/// 本番・偽実装・録画再生で共通の契約。呼出側はGatewayを使用する。
pub trait LlmProvider {
    fn channel_id(&self) -> &ChannelId;
    fn id(&self) -> ProviderId;
    fn call<'a>(
        &'a mut self,
        operation: Operation<'a>,
    ) -> FutureResult<'a, ProviderResult<ProviderOutput>>;
}

pub struct TransportRequest {
    pub method: HttpMethod,
    pub url: String,
    pub headers: Vec<(String, Zeroizing<String>)>,
    pub body: Option<Value>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HttpMethod {
    Get,
    Post,
}
pub struct TransportResponse {
    pub status: u16,
    pub retry_after: Option<Duration>,
    pub body: Value,
}
pub trait Transport {
    fn send<'a>(
        &'a mut self,
        request: TransportRequest,
    ) -> FutureResult<'a, ProviderResult<TransportResponse>>;
}

pub struct HttpTransport {
    client: http::Client,
    local_client: http::Client,
    max_response_bytes: usize,
}
impl HttpTransport {
    pub fn new(timeout: Duration, max_response_bytes: usize) -> Result<Self> {
        if max_response_bytes == 0 {
            return Err(failure("E-AI-PROVIDER"));
        }
        Ok(Self {
            client: http::client(timeout)?,
            local_client: http::local_client(timeout)?,
            max_response_bytes,
        })
    }
}
impl Transport for HttpTransport {
    fn send<'a>(
        &'a mut self,
        request: TransportRequest,
    ) -> FutureResult<'a, ProviderResult<TransportResponse>> {
        Box::pin(async move {
            let method = match request.method {
                HttpMethod::Get => reqwest::Method::GET,
                HttpMethod::Post => reqwest::Method::POST,
            };
            let headers = Zeroizing::new(
                request
                    .headers
                    .iter()
                    .map(|(k, v)| (k.clone(), v.to_string()))
                    .collect::<Vec<_>>(),
            );
            let local = reqwest::Url::parse(&request.url).ok().is_some_and(|url| {
                matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"))
            });
            let client = if local {
                &self.local_client
            } else {
                &self.client
            };
            let response = http::request_json(
                client,
                method,
                &request.url,
                &headers,
                request.body.as_ref(),
                self.max_response_bytes,
            )
            .await
            .map_err(|error| ProviderFault {
                kind: match error.code.as_str() {
                    "E-HTTP-OFFLINE" => FaultKind::Disconnected,
                    "E-HTTP-DEADLINE" => FaultKind::Timeout,
                    _ => FaultKind::Contract,
                },
                retry_after: None,
            })?;
            let retry_after = response
                .retry_after
                .as_deref()
                .and_then(|value| retry_after(value, &picocast_core::clock::now_utc_iso()));
            Ok(TransportResponse {
                status: response.status,
                retry_after,
                body: response.body,
            })
        })
    }
}

/// HTTP-dateも共通UTC時計と比較する。上限を超える待機はGatewayが停止する。
pub fn retry_after(value: &str, now: &str) -> Option<Duration> {
    if let Ok(seconds) = value.parse::<u64>() {
        return Some(Duration::from_secs(seconds));
    }
    let deadline = chrono::DateTime::parse_from_rfc2822(value).ok()?;
    let now = chrono::DateTime::parse_from_rfc3339(now).ok()?;
    Some(
        deadline
            .signed_duration_since(now)
            .to_std()
            .unwrap_or(Duration::ZERO),
    )
}

pub struct ProviderLimits {
    pub max_model_pages: usize,
    pub max_models: usize,
}
pub struct ProviderContract<T> {
    channel_id: ChannelId,
    id: ProviderId,
    base: String,
    secret: Option<Secret>,
    transport: T,
    limits: ProviderLimits,
}
impl<T: Transport> ProviderContract<T> {
    pub fn new(
        channel_id: ChannelId,
        id: ProviderId,
        endpoint: &str,
        secret: Option<Secret>,
        transport: T,
        limits: ProviderLimits,
    ) -> Result<Self> {
        let url = reqwest::Url::parse(endpoint).map_err(|_| failure("E-AI-MODEL"))?;
        let valid = match id {
            ProviderId::Gemini => endpoint == GEMINI_ENDPOINT,
            ProviderId::OpenAi => endpoint == OPENAI_ENDPOINT,
            ProviderId::Ollama => {
                url.scheme() == "http"
                    && matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"))
                    && url.path() == "/"
            }
            ProviderId::Fake | ProviderId::StableDiffusionWebUi => false,
        };
        if !valid
            || url.query().is_some()
            || url.fragment().is_some()
            || !url.username().is_empty()
            || url.password().is_some()
            || (id != ProviderId::Ollama && secret.is_none())
        {
            return Err(failure("E-AI-AUTH"));
        }
        if limits.max_model_pages == 0 || limits.max_models == 0 {
            return Err(failure("E-AI-MODEL"));
        }
        Ok(Self {
            channel_id,
            id,
            base: endpoint.trim_end_matches('/').to_owned(),
            secret,
            transport,
            limits,
        })
    }
    pub fn into_transport(self) -> T {
        self.transport
    }
    fn request(&self, operation: &Operation<'_>) -> TransportRequest {
        let mut headers = Vec::new();
        if let Some(secret) = &self.secret {
            let (name, value) = match self.id {
                ProviderId::Gemini => ("x-goog-api-key", secret.expose().to_owned()),
                _ => ("authorization", format!("Bearer {}", secret.expose())),
            };
            headers.push((name.to_owned(), Zeroizing::new(value)));
        }
        let (path, body) = match operation {
            Operation::Models => (
                match self.id {
                    ProviderId::Ollama => "/api/tags",
                    _ => "/models",
                }
                .to_owned(),
                None,
            ),
            Operation::Generate(input) => match self.id {
                ProviderId::Gemini => (
                    format!(
                        "/models/{}:generateContent",
                        input.model.trim_start_matches("models/")
                    ),
                    Some(
                        json!({"contents":[{"role":"user","parts":crate::image::gemini_parts(input.prompt,input.images)}],"generationConfig":{"maxOutputTokens":input.max_output_tokens,"responseMimeType":"application/json","responseJsonSchema":input.schema}}),
                    ),
                ),
                ProviderId::OpenAi => (
                    "/responses".into(),
                    Some(
                        json!({"model":input.model,"input":crate::image::openai_input(input.prompt,input.images),"store":false,"max_output_tokens":input.max_output_tokens,"text":{"format":{"type":"json_schema","name":"picocast_output","strict":true,"schema":input.schema}}}),
                    ),
                ),
                _ => (
                    "/api/generate".into(),
                    Some(crate::image::ollama_input(
                        input.model,
                        input.prompt,
                        input.schema,
                        input.max_output_tokens,
                        input.images,
                    )),
                ),
            },
        };
        TransportRequest {
            method: if body.is_some() {
                HttpMethod::Post
            } else {
                HttpMethod::Get
            },
            url: format!("{}{path}", self.base),
            headers,
            body,
        }
    }
    fn decode(&self, operation: &Operation<'_>, body: Value) -> ProviderResult<ProviderOutput> {
        if matches!(operation, Operation::Models) {
            if body.get("has_more") == Some(&Value::Bool(true)) {
                return Err(ProviderFault::contract());
            }
            let (list, key) = match self.id {
                ProviderId::OpenAi => ("data", "id"),
                ProviderId::Gemini => ("models", "name"),
                _ => ("models", "name"),
            };
            let models = body
                .get(list)
                .and_then(Value::as_array)
                .ok_or_else(ProviderFault::contract)?;
            let models =
                models
                    .iter()
                    .filter(|model| {
                        self.id != ProviderId::Gemini
                            || model["supportedGenerationMethods"].as_array().is_some_and(
                                |methods| methods.iter().any(|method| method == "generateContent"),
                            )
                    })
                    .map(|model| {
                        model
                            .get(key)
                            .and_then(Value::as_str)
                            .map(|s| s.trim_start_matches("models/").to_owned())
                            .ok_or_else(ProviderFault::contract)
                    })
                    .collect::<ProviderResult<Vec<_>>>()?;
            return Ok(ProviderOutput::Models(models));
        }
        let (text, input, output) = match self.id {
            ProviderId::Gemini => {
                let candidates = body["candidates"]
                    .as_array()
                    .ok_or_else(ProviderFault::contract)?;
                if candidates.len() != 1 || candidates[0]["finishReason"] != "STOP" {
                    return Err(ProviderFault::contract());
                }
                let parts = candidates[0]["content"]["parts"]
                    .as_array()
                    .ok_or_else(ProviderFault::contract)?;
                let mut text = String::new();
                for part in parts {
                    if part["thought"] == true {
                        continue;
                    }
                    text.push_str(part["text"].as_str().ok_or_else(ProviderFault::contract)?);
                }
                // thinkingも出力の費用・token上限に含める。
                let usage = gemini_usage(&body)?;
                (text, usage.input_tokens, usage.output_tokens)
            }
            ProviderId::OpenAi => {
                if body["status"] != "completed" || !body["error"].is_null() {
                    return Err(ProviderFault::contract());
                }
                let mut text = String::new();
                for item in body["output"]
                    .as_array()
                    .ok_or_else(ProviderFault::contract)?
                {
                    if item["type"] == "reasoning" {
                        continue;
                    }
                    if item["type"] != "message" {
                        return Err(ProviderFault::contract());
                    }
                    for part in item["content"]
                        .as_array()
                        .ok_or_else(ProviderFault::contract)?
                    {
                        if part["type"] != "output_text" {
                            return Err(ProviderFault::contract());
                        }
                        text.push_str(part["text"].as_str().ok_or_else(ProviderFault::contract)?);
                    }
                }
                (
                    text,
                    body["usage"]["input_tokens"]
                        .as_u64()
                        .ok_or_else(ProviderFault::contract)?,
                    body["usage"]["output_tokens"]
                        .as_u64()
                        .ok_or_else(ProviderFault::contract)?,
                )
            }
            _ => {
                if body["done"] != true || body["done_reason"] != "stop" {
                    return Err(ProviderFault::contract());
                }
                (
                    body["response"]
                        .as_str()
                        .ok_or_else(ProviderFault::contract)?
                        .to_owned(),
                    body["prompt_eval_count"]
                        .as_u64()
                        .ok_or_else(ProviderFault::contract)?,
                    body["eval_count"]
                        .as_u64()
                        .ok_or_else(ProviderFault::contract)?,
                )
            }
        };
        if text.is_empty() {
            return Err(ProviderFault::contract());
        }
        if self
            .secret
            .as_ref()
            .is_some_and(|secret| text.contains(secret.expose()))
        {
            return Err(ProviderFault::contract());
        }
        Ok(ProviderOutput::Completion(Completion {
            text,
            usage: Usage {
                input_tokens: input,
                output_tokens: output,
            },
        }))
    }
}
impl<T: Transport> LlmProvider for ProviderContract<T> {
    fn channel_id(&self) -> &ChannelId {
        &self.channel_id
    }
    fn id(&self) -> ProviderId {
        self.id
    }
    fn call<'a>(
        &'a mut self,
        operation: Operation<'a>,
    ) -> FutureResult<'a, ProviderResult<ProviderOutput>> {
        Box::pin(async move {
            if matches!(operation, Operation::Models) {
                let mut models = Vec::new();
                let mut token: Option<String> = None;
                let mut seen = std::collections::BTreeSet::new();
                for _ in 0..self.limits.max_model_pages {
                    let mut request = self.request(&operation);
                    if let Some(token) = &token {
                        let mut url = reqwest::Url::parse(&request.url)
                            .map_err(|_| ProviderFault::contract())?;
                        url.query_pairs_mut().append_pair("pageToken", token);
                        request.url = url.into();
                    }
                    let response = self.transport.send(request).await?;
                    if response.status != 200 {
                        return Err(ProviderFault {
                            kind: FaultKind::Http(response.status),
                            retry_after: response.retry_after,
                        });
                    }
                    let next = response
                        .body
                        .get("nextPageToken")
                        .and_then(Value::as_str)
                        .filter(|s| !s.is_empty())
                        .map(str::to_owned);
                    let ProviderOutput::Models(page) = self.decode(&operation, response.body)?
                    else {
                        return Err(ProviderFault::contract());
                    };
                    models.extend(page);
                    if models.len() > self.limits.max_models {
                        return Err(ProviderFault::contract());
                    }
                    match next {
                        None => return Ok(ProviderOutput::Models(models)),
                        Some(next) => {
                            if self.id != ProviderId::Gemini || !seen.insert(next.clone()) {
                                return Err(ProviderFault::contract());
                            }
                            token = Some(next);
                        }
                    }
                }
                return Err(ProviderFault::contract());
            }
            let request = self.request(&operation);
            let response = self.transport.send(request).await?;
            if response.status != 200 {
                return Err(ProviderFault {
                    kind: FaultKind::Http(response.status),
                    retry_after: response.retry_after,
                });
            }
            self.decode(&operation, response.body)
        })
    }
}
