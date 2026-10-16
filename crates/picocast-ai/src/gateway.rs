use crate::{
    failure, CachedGeneration, Cancellation, CompletionInput, FaultKind, GatewayOptions,
    GenerateRequest, Generation, LlmProvider, ModelRegistry, Operation, Provenance, ProviderFault,
    ProviderId, ProviderOutput, ResultCache, StageModel,
};
use picocast_core::{
    clock::{self, Timestamp},
    ChannelId, Result,
};
use picocast_store::{
    ai_cost::{AiCostReservation, AiCostSettlement, UtcDay},
    Store,
};
use serde::de::DeserializeOwned;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, time::Duration};

pub struct Gateway {
    channel_id: ChannelId,
    registry: ModelRegistry,
    options: GatewayOptions,
    providers: BTreeMap<ProviderId, Box<dyn LlmProvider>>,
    cache: Box<dyn ResultCache>,
}
impl Gateway {
    pub fn new(
        channel_id: ChannelId,
        registry: ModelRegistry,
        options: GatewayOptions,
        providers: Vec<Box<dyn LlmProvider>>,
        cache: Box<dyn ResultCache>,
    ) -> Result<Self> {
        options.validate()?;
        let mut registered = BTreeMap::new();
        for provider in providers {
            if provider.channel_id() != &channel_id {
                return Err(failure("E-AI-CHANNEL"));
            }
            if registered.insert(provider.id(), provider).is_some() {
                return Err(failure("E-AI-MODEL"));
            }
        }
        for model in registry.stages.values() {
            model.validate()?;
            if !registered.contains_key(&model.provider)
                || (model.provider == ProviderId::Fake && !options.development)
            {
                return Err(failure("E-AI-MODEL"));
            }
        }
        Ok(Self {
            channel_id,
            registry,
            options,
            providers: registered,
            cache,
        })
    }

    pub async fn generate_json<T: DeserializeOwned>(
        &mut self,
        store: &mut Store,
        request: GenerateRequest,
        schema: &Value,
        cancel: &mut Cancellation,
    ) -> Result<Generation<T>> {
        self.generate_json_checked(store, request, schema, cancel, |_: &T| Ok(()))
            .await
    }

    pub async fn generate_json_checked<T: DeserializeOwned, F: Fn(&T) -> Result<()>>(
        &mut self,
        store: &mut Store,
        request: GenerateRequest,
        schema: &Value,
        cancel: &mut Cancellation,
        validate: F,
    ) -> Result<Generation<T>> {
        cancel.check()?;
        if request.channel_id != self.channel_id {
            return Err(failure("E-AI-CHANNEL"));
        }
        // 登録解除・アーカイブ後はcache利用やモデル一覧通信も開始しない。
        store.repository(&request.channel_id)?;
        let model = self.registry.resolve(request.stage)?.clone();
        if request.request_id.is_empty()
            || request.prompt.is_empty()
            || request.template_version < 1
            || request.settings_hash.is_empty()
            || request.prompt.len() > self.options.max_prompt_bytes
        {
            return Err(failure("E-AI-TOKENS"));
        }
        // 有料経路は明示許可と既知の料金を要求する。既定値0で課金制限を迂回しない。
        if matches!(model.provider, ProviderId::Gemini | ProviderId::OpenAi)
            && (!self.options.allow_paid || model.maximum_cost()? == 0)
        {
            return Err(failure("E-AI-BUDGET"));
        }
        let validator = jsonschema::validator_for(schema).map_err(|_| failure("E-AI-SCHEMA"))?;
        let request_hash = hash(
            &serde_json::json!({"channel":request.channel_id.as_str(),"stage":request.stage,"model":model,"prompt":request.prompt,"schema":schema,"template_version":request.template_version,"settings_hash":request.settings_hash}),
        )?;
        let mut sequence = 0u32;
        let models = self
            .call(
                store,
                &request,
                &model,
                Operation::Models,
                &mut sequence,
                cancel,
            )
            .await?;
        let ProviderOutput::Models(models) = models else {
            return Err(failure("E-AI-PROVIDER"));
        };
        if !models
            .iter()
            .any(|name| name == model.model.trim_start_matches("models/"))
        {
            return Err(failure("E-AI-MODEL"));
        }
        // cache hitでも費用・token予算の設定と現在の余裕を先に確認する。
        let totals = store.ai_cost_totals(&request.channel_id, &UtcDay::from_timestamp(&now()?))?;
        if totals_budget_exceeded(&totals, &self.options, &model)? {
            return Err(failure("E-AI-BUDGET"));
        }
        if let Some(cached) = self.cache.get(&request.channel_id, &request_hash)? {
            if cached.provenance.provider != model.provider
                || cached.provenance.model != model.model
                || cached.provenance.request_hash != request_hash
                || cached.provenance.template_version != request.template_version
                || cached.provenance.settings_hash != request.settings_hash
                || cached.usage.input_tokens > model.max_input_tokens
                || cached.usage.output_tokens > model.max_output_tokens
            {
                return Err(failure("E-AI-SCHEMA"));
            }
            if !validator.is_valid(&cached.value) {
                return Err(failure("E-AI-SCHEMA"));
            }
            let value = serde_json::from_value(cached.value).map_err(|_| failure("E-AI-SCHEMA"))?;
            validate(&value).map_err(|_| failure("E-AI-SCHEMA"))?;
            return Ok(Generation {
                value,
                usage: cached.usage,
                provenance: cached.provenance,
                cache_hit: true,
            });
        }
        for schema_attempt in 0..2 {
            let operation = Operation::Generate(CompletionInput {
                model: &model.model,
                prompt: &request.prompt,
                schema,
                max_output_tokens: model.max_output_tokens,
            });
            let output = self
                .call(store, &request, &model, operation, &mut sequence, cancel)
                .await?;
            let ProviderOutput::Completion(completion) = output else {
                return Err(failure("E-AI-PROVIDER"));
            };
            let parsed = serde_json::from_str::<Value>(&completion.text)
                .ok()
                .filter(|value| validator.is_valid(value));
            if let Some(parsed) = parsed {
                if let Ok(value) = serde_json::from_value::<T>(parsed.clone()) {
                    if validate(&value).is_err() {
                        tracing::warn!(
                            channel_id = request.channel_id.as_str(),
                            schema_attempt,
                            code = "E-AI-SCHEMA",
                            "構造化応答の文脈検証に失敗しました"
                        );
                        continue;
                    }
                    let provenance = Provenance {
                        provider: model.provider,
                        model: model.model.clone(),
                        request_hash: request_hash.clone(),
                        template_version: request.template_version,
                        settings_hash: request.settings_hash.clone(),
                        at: now()?,
                    };
                    self.cache.put(
                        &request.channel_id,
                        &request_hash,
                        CachedGeneration {
                            value: parsed,
                            usage: completion.usage,
                            provenance: provenance.clone(),
                        },
                    )?;
                    return Ok(Generation {
                        value,
                        usage: completion.usage,
                        provenance,
                        cache_hit: false,
                    });
                }
            }
            tracing::warn!(
                channel_id = request.channel_id.as_str(),
                schema_attempt,
                code = "E-AI-SCHEMA",
                "構造化応答が契約に一致しません"
            );
        }
        Err(failure("E-AI-SCHEMA"))
    }

    async fn call(
        &mut self,
        store: &mut Store,
        request: &GenerateRequest,
        model: &StageModel,
        operation: Operation<'_>,
        sequence: &mut u32,
        cancel: &mut Cancellation,
    ) -> Result<ProviderOutput> {
        for attempt in 0..self.options.max_attempts {
            cancel.check()?;
            let generation = matches!(operation, Operation::Generate(_));
            let request_id = if generation {
                *sequence = sequence
                    .checked_add(1)
                    .ok_or_else(|| failure("E-AI-BUDGET"))?;
                let id = format!("{}:ai:{}", request.request_id, sequence);
                let at = now()?;
                store.reserve_ai_cost(&AiCostReservation {
                    channel_id: request.channel_id.clone(),
                    request_id: id.clone(),
                    day: UtcDay::from_timestamp(&at),
                    daily_budget_micros: self.options.daily_budget_micros,
                    max_cost_micros: Some(
                        u64::try_from(model.maximum_cost()?).map_err(|_| failure("E-AI-BUDGET"))?,
                    ),
                    provider: provider_name(model.provider).into(),
                    model: model.model.clone(),
                    at,
                    project_id: request.project_id.clone(),
                    job_id: request.job_id.clone(),
                    daily_token_budget: self.options.daily_token_budget,
                    max_input_tokens: model.max_input_tokens,
                    max_output_tokens: model.max_output_tokens,
                })?;
                Some(id)
            } else {
                None
            };
            let provider = self
                .providers
                .get_mut(&model.provider)
                .ok_or_else(|| failure("E-AI-MODEL"))?;
            let operation = match &operation {
                Operation::Models => Operation::Models,
                Operation::Generate(input) => Operation::Generate(CompletionInput {
                    model: input.model,
                    prompt: input.prompt,
                    schema: input.schema,
                    max_output_tokens: input.max_output_tokens,
                }),
            };
            let result = tokio::select! {
                biased;
                _=cancel.cancelled()=>Err(failure("E-AI-CANCELLED")),
                result=tokio::time::timeout(self.options.request_timeout,provider.call(operation))=>Ok(match result {Ok(value)=>value,Err(_)=>Err(ProviderFault {kind:FaultKind::Timeout,retry_after:None})}),
            };
            match result {
                Err(error) => {
                    if let Some(id) = request_id {
                        store.settle_ai_cost(
                            &request.channel_id,
                            &id,
                            &AiCostSettlement::Unknown {
                                error_code: error.code.clone(),
                            },
                        )?;
                    }
                    return Err(error);
                }
                Ok(Ok(output)) => {
                    if let (Some(id), ProviderOutput::Completion(completion)) =
                        (&request_id, &output)
                    {
                        store.settle_ai_cost(
                            &request.channel_id,
                            id,
                            &AiCostSettlement::Succeeded {
                                actual_cost_micros: u64::try_from(model.cost(completion.usage)?)
                                    .map_err(|_| failure("E-AI-BUDGET"))?,
                                input_tokens: completion.usage.input_tokens,
                                output_tokens: completion.usage.output_tokens,
                            },
                        )?;
                        if completion.usage.input_tokens > model.max_input_tokens
                            || completion.usage.output_tokens > model.max_output_tokens
                        {
                            return Err(failure("E-AI-TOKENS"));
                        }
                    } else if let Some(id) = request_id {
                        store.settle_ai_cost(
                            &request.channel_id,
                            &id,
                            &AiCostSettlement::Unknown {
                                error_code: "E-AI-PROVIDER".into(),
                            },
                        )?;
                        return Err(failure("E-AI-PROVIDER"));
                    }
                    return Ok(output);
                }
                Ok(Err(fault)) => {
                    if let Some(id) = request_id {
                        let settlement = if matches!(
                            fault.kind,
                            FaultKind::Http(400 | 401 | 403 | 404 | 422 | 429)
                        ) {
                            AiCostSettlement::Failed {
                                actual_cost_micros: 0,
                                error_code: fault.code().into(),
                            }
                        } else {
                            AiCostSettlement::Unknown {
                                error_code: fault.code().into(),
                            }
                        };
                        store.settle_ai_cost(&request.channel_id, &id, &settlement)?;
                    }
                    if !fault.retryable() || attempt + 1 >= self.options.max_attempts {
                        return Err(failure(fault.code()));
                    }
                    let delay = retry_delay(attempt, fault.retry_after, &self.options)?;
                    tracing::warn!(
                        channel_id = request.channel_id.as_str(),
                        attempt,
                        code = fault.code(),
                        "AI要求を再試行します"
                    );
                    tokio::select! {biased; _=cancel.cancelled()=>return Err(failure("E-AI-CANCELLED")), _=tokio::time::sleep(delay)=>{}}
                }
            }
        }
        Err(failure("E-AI-PROVIDER"))
    }
}

fn now() -> Result<Timestamp> {
    Timestamp::parse(&clock::now_utc_iso())
}
pub fn provider_name(id: ProviderId) -> &'static str {
    match id {
        ProviderId::Gemini => "gemini",
        ProviderId::OpenAi => "openai",
        ProviderId::Ollama => "ollama",
        ProviderId::Fake => "fake",
    }
}
fn hash(value: &Value) -> Result<String> {
    let digest = Sha256::digest(serde_json::to_vec(value).map_err(|_| failure("E-AI-PROVIDER"))?);
    Ok(digest.iter().map(|byte| format!("{byte:02x}")).collect())
}
fn retry_delay(
    attempt: u32,
    retry_after: Option<Duration>,
    options: &GatewayOptions,
) -> Result<Duration> {
    let multiplier = 2u32.checked_pow(attempt).unwrap_or(u32::MAX);
    let backoff = options
        .retry_base
        .saturating_mul(multiplier)
        .min(options.retry_max);
    let delay = retry_after.map_or(backoff, |specified| specified.max(backoff));
    if delay > options.retry_max {
        return Err(failure("E-AI-RATE"));
    }
    Ok(delay)
}
fn totals_budget_exceeded(
    totals: &picocast_store::ai_cost::AiCostTotals,
    options: &GatewayOptions,
    model: &StageModel,
) -> Result<bool> {
    // 同じ台帳の確定・不明・予約を合計する。原子的な最終判定はreserve側でも行う。
    let money = totals
        .charged_micros
        .checked_add(totals.held_micros)
        .ok_or_else(|| failure("E-AI-BUDGET"))?;
    let tokens = totals
        .input_tokens
        .checked_add(totals.output_tokens)
        .and_then(|n| n.checked_add(totals.held_tokens))
        .ok_or_else(|| failure("E-AI-BUDGET"))?;
    Ok(totals.unpriced_entries > 0
        || money
            .checked_add(u64::try_from(model.maximum_cost()?).map_err(|_| failure("E-AI-BUDGET"))?)
            .is_none_or(|n| n > options.daily_budget_micros)
        || tokens
            .checked_add(model.max_input_tokens)
            .and_then(|n| n.checked_add(model.max_output_tokens))
            .is_none_or(|n| n > options.daily_token_budget))
}
