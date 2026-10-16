#![cfg(test)]
#![allow(clippy::unwrap_used)]
use picocast_ai::*;
use picocast_core::{clock::Timestamp, ChannelId};
use picocast_store::{
    ai_cost::{AiCostState, UtcDay},
    repository::CostLedger,
    DataMode, Store, StoreOptions, StorePaths,
};
use picocast_testkit::*;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{collections::BTreeMap, time::Duration};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Title {
    title: String,
}
fn schema() -> Value {
    json!({"type":"object","properties":{"title":{"type":"string"}},"required":["title"],"additionalProperties":false})
}
fn limits() -> ProviderLimits {
    ProviderLimits {
        max_model_pages: 5,
        max_models: 500,
    }
}
fn options() -> GatewayOptions {
    GatewayOptions {
        max_attempts: 3,
        request_timeout: Duration::from_secs(1),
        retry_base: Duration::from_millis(1),
        retry_max: Duration::from_millis(10),
        daily_budget_micros: 100_000,
        daily_token_budget: 100_000,
        max_prompt_bytes: 10_000,
        development: true,
        allow_paid: true,
    }
}
fn model(id: ProviderId, name: &str) -> StageModel {
    StageModel {
        provider: id,
        model: name.into(),
        max_input_tokens: 1024,
        max_output_tokens: 64,
        input_micros_per_million: if matches!(id, ProviderId::Gemini | ProviderId::OpenAi) {
            1_000_000
        } else {
            0
        },
        output_micros_per_million: if matches!(id, ProviderId::Gemini | ProviderId::OpenAi) {
            1_000_000
        } else {
            0
        },
    }
}
fn request(id: &str) -> GenerateRequest {
    GenerateRequest {
        channel_id: ChannelId::new("fixture").unwrap(),
        request_id: id.into(),
        project_id: None,
        job_id: None,
        stage: Stage::Title,
        prompt: "架空の題名をJSONで".into(),
        template_version: 1,
        settings_hash: "synthetic-config".into(),
    }
}
fn fixture() -> (tempfile::TempDir, Store) {
    let temp = tempfile::tempdir().unwrap();
    let paths = StorePaths::new(temp.path(), DataMode::Development).unwrap();
    let store = Store::open(
        &paths,
        StoreOptions {
            busy_timeout: Duration::from_secs(1),
            backup_pages_per_step: 8,
            backup_pause: Duration::from_millis(1),
        },
    )
    .unwrap();
    store
        .create_channel(&ChannelId::new("fixture").unwrap(), "架空チャンネル")
        .unwrap();
    (temp, store)
}
fn gateway(provider: Box<dyn LlmProvider>, model: StageModel, options: GatewayOptions) -> Gateway {
    Gateway::new(
        ChannelId::new("fixture").unwrap(),
        ModelRegistry {
            stages: BTreeMap::from([(Stage::Title, model)]),
        },
        options,
        vec![provider],
        Box::<MemoryCache>::default(),
    )
    .unwrap()
}
fn complete(text: &str) -> ProviderResult<Completion> {
    Ok(Completion {
        text: text.into(),
        usage: Usage {
            input_tokens: 5,
            output_tokens: 10,
        },
    })
}
fn totals(store: &Store) -> picocast_store::ai_cost::AiCostTotals {
    store
        .ai_cost_totals(
            &ChannelId::new("fixture").unwrap(),
            &UtcDay::from_timestamp(
                &Timestamp::parse(&picocast_core::clock::now_utc_iso()).unwrap(),
            ),
        )
        .unwrap()
}

#[tokio::test]
async fn all_recorded_providers_and_fake_share_gateway_contract_and_channel_cache() {
    let cases = [
        (
            ProviderId::Gemini,
            "synthetic-gemini",
            GEMINI_ENDPOINT,
            include_str!("fixtures/gemini.json"),
        ),
        (
            ProviderId::OpenAi,
            "synthetic-openai",
            OPENAI_ENDPOINT,
            include_str!("fixtures/openai.json"),
        ),
        (
            ProviderId::Ollama,
            "synthetic-ollama",
            "http://127.0.0.1:11434",
            include_str!("fixtures/ollama.json"),
        ),
    ];
    for (id, name, url, recording) in cases {
        let (_temp, mut store) = fixture();
        // 二回目はmodel一覧だけを照合して、生成結果はcacheから返す。
        let mut frames: Vec<Value> = serde_json::from_str(recording).unwrap();
        frames.push(frames[0].clone());
        let replay = ReplayTransport::from_json(&serde_json::to_string(&frames).unwrap()).unwrap();
        let provider = ProviderContract::new(
            ChannelId::new("fixture").unwrap(),
            id,
            url,
            if id == ProviderId::Ollama {
                None
            } else {
                Some(Secret::from_bytes(b"synthetic-credential").unwrap())
            },
            replay,
            limits(),
        )
        .unwrap();
        let mut gateway = gateway(Box::new(provider), model(id, name), options());
        let (_handle, mut cancel) = Cancellation::pair();
        let result = gateway
            .generate_json::<Title>(&mut store, request("recorded-1"), &schema(), &mut cancel)
            .await
            .unwrap();
        assert_eq!(result.value.title, "架空の題名");
        assert_eq!(result.usage.output_tokens, 10);
        assert!(!result.cache_hit);
        assert!(
            gateway
                .generate_json::<Title>(&mut store, request("recorded-2"), &schema(), &mut cancel)
                .await
                .unwrap()
                .cache_hit
        );
        assert_eq!(
            store
                .repository(&ChannelId::new("fixture").unwrap())
                .unwrap()
                .list::<CostLedger>()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(totals(&store).held_tokens, 0);
    }
    let (_temp, mut store) = fixture();
    let mut gateway = gateway(
        Box::new(FakeProvider::new(
            ChannelId::new("fixture").unwrap(),
            vec!["fake".into()],
            vec![complete("{\"title\":\"架空の題名\"}")],
        )),
        model(ProviderId::Fake, "fake"),
        options(),
    );
    let (_handle, mut cancel) = Cancellation::pair();
    assert_eq!(
        gateway
            .generate_json::<Title>(&mut store, request("fake-1"), &schema(), &mut cancel)
            .await
            .unwrap()
            .value
            .title,
        "架空の題名"
    );
}

#[tokio::test]
async fn retries_only_429_503_disconnect_and_records_every_attempt() {
    let (_temp, mut store) = fixture();
    let responses = vec![
        Err(ProviderFault {
            kind: FaultKind::Http(429),
            retry_after: Some(Duration::from_millis(2)),
        }),
        Err(ProviderFault {
            kind: FaultKind::Http(503),
            retry_after: None,
        }),
        complete("{\"title\":\"成功\"}"),
    ];
    let mut gateway = gateway(
        Box::new(FakeProvider::new(
            ChannelId::new("fixture").unwrap(),
            vec!["fake".into()],
            responses,
        )),
        model(ProviderId::Fake, "fake"),
        options(),
    );
    let (_handle, mut cancel) = Cancellation::pair();
    assert_eq!(
        gateway
            .generate_json::<Title>(&mut store, request("retry"), &schema(), &mut cancel)
            .await
            .unwrap()
            .value
            .title,
        "成功"
    );
    let rows = store
        .repository(&ChannelId::new("fixture").unwrap())
        .unwrap()
        .list::<CostLedger>()
        .unwrap();
    assert_eq!(rows.len(), 3);
    assert_eq!(totals(&store).held_tokens, 1088);
    assert_eq!(totals(&store).output_tokens, 10);
}

#[tokio::test]
async fn auth_failure_is_single_attempt_and_schema_failure_retries_exactly_once() {
    for (responses, expected, count) in [
        (
            vec![Err(ProviderFault {
                kind: FaultKind::Http(401),
                retry_after: None,
            })],
            "E-AI-AUTH",
            1,
        ),
        (
            vec![
                complete("{\"unexpected\":true}"),
                complete("{\"title\":123}"),
            ],
            "E-AI-SCHEMA",
            2,
        ),
    ] {
        let (_temp, mut store) = fixture();
        let mut gateway = gateway(
            Box::new(FakeProvider::new(
                ChannelId::new("fixture").unwrap(),
                vec!["fake".into()],
                responses,
            )),
            model(ProviderId::Fake, "fake"),
            options(),
        );
        let (_handle, mut cancel) = Cancellation::pair();
        assert_eq!(
            gateway
                .generate_json::<Title>(&mut store, request("fail"), &schema(), &mut cancel)
                .await
                .err()
                .unwrap()
                .code,
            expected
        );
        assert_eq!(
            store
                .repository(&ChannelId::new("fixture").unwrap())
                .unwrap()
                .list::<CostLedger>()
                .unwrap()
                .len(),
            count
        );
    }
}

#[tokio::test]
async fn model_missing_paid_denied_and_token_budget_stop_before_generation() {
    for (name, mut settings, expected) in [
        ("missing", options(), "E-AI-MODEL"),
        (
            "fake",
            {
                let mut settings = options();
                settings.daily_token_budget = 1;
                settings
            },
            "E-AI-BUDGET",
        ),
    ] {
        settings.allow_paid = false;
        let (_temp, mut store) = fixture();
        let mut gateway = gateway(
            Box::new(FakeProvider::new(
                ChannelId::new("fixture").unwrap(),
                vec!["fake".into()],
                vec![],
            )),
            model(ProviderId::Fake, name),
            settings,
        );
        let (_handle, mut cancel) = Cancellation::pair();
        assert_eq!(
            gateway
                .generate_json::<Title>(&mut store, request("blocked"), &schema(), &mut cancel)
                .await
                .err()
                .unwrap()
                .code,
            expected
        );
        assert_eq!(
            store
                .repository(&ChannelId::new("fixture").unwrap())
                .unwrap()
                .list::<CostLedger>()
                .unwrap()
                .len(),
            0
        );
    }
    let (_temp, mut store) = fixture();
    let provider = ProviderContract::new(
        ChannelId::new("fixture").unwrap(),
        ProviderId::OpenAi,
        OPENAI_ENDPOINT,
        Some(Secret::from_bytes(b"synthetic-key").unwrap()),
        ReplayTransport::from_json("[]").unwrap(),
        limits(),
    )
    .unwrap();
    let mut settings = options();
    settings.allow_paid = false;
    let mut gateway = gateway(
        Box::new(provider),
        model(ProviderId::OpenAi, "synthetic-openai"),
        settings,
    );
    let (_handle, mut cancel) = Cancellation::pair();
    assert_eq!(
        gateway
            .generate_json::<Title>(&mut store, request("paid"), &schema(), &mut cancel)
            .await
            .err()
            .unwrap()
            .code,
        "E-AI-BUDGET"
    );
}

struct PendingProvider(ChannelId);
impl LlmProvider for PendingProvider {
    fn channel_id(&self) -> &ChannelId {
        &self.0
    }
    fn id(&self) -> ProviderId {
        ProviderId::Fake
    }
    fn call<'a>(
        &'a mut self,
        op: Operation<'a>,
    ) -> FutureResult<'a, ProviderResult<ProviderOutput>> {
        Box::pin(async move {
            match op {
                Operation::Models => Ok(ProviderOutput::Models(vec!["fake".into()])),
                Operation::Generate(_) => std::future::pending().await,
            }
        })
    }
}

#[tokio::test]
async fn cancelled_and_timed_out_sent_calls_keep_unknown_reservation() {
    for should_cancel in [false, true] {
        let (_temp, mut store) = fixture();
        let mut settings = options();
        settings.request_timeout = Duration::from_millis(15);
        let mut gateway = gateway(
            Box::new(PendingProvider(ChannelId::new("fixture").unwrap())),
            model(ProviderId::Fake, "fake"),
            settings,
        );
        let (handle, mut cancel) = Cancellation::pair();
        let input_schema = schema();
        let operation = gateway.generate_json::<Title>(
            &mut store,
            request("pending"),
            &input_schema,
            &mut cancel,
        );
        let error = if should_cancel {
            tokio::pin!(operation);
            tokio::select! {biased; _=tokio::time::sleep(Duration::from_millis(1))=>{handle.cancel();operation.await.err().unwrap()},result=&mut operation=>result.err().unwrap()}
        } else {
            operation.await.err().unwrap()
        };
        assert_eq!(
            error.code,
            if should_cancel {
                "E-AI-CANCELLED"
            } else {
                "E-AI-TIMEOUT"
            }
        );
        assert_eq!(totals(&store).held_tokens, 1088);
        let record = store
            .repository(&ChannelId::new("fixture").unwrap())
            .unwrap()
            .list::<CostLedger>()
            .unwrap()
            .pop()
            .unwrap();
        assert_eq!(
            record.units_json["ai_cost"]["state"],
            serde_json::to_value(AiCostState::Unknown).unwrap()
        );
    }
}

#[tokio::test]
async fn protocol_rejects_missing_usage_refusal_and_credential_echo_without_leaking_values() {
    for body in [
        json!({"status":"completed","output":[],"usage":{}}),
        json!({"status":"completed","error":null,"output":[{"type":"message","content":[{"type":"refusal","refusal":"synthetic-key"}]}],"usage":{"input_tokens":1,"output_tokens":1}}),
        json!({"status":"completed","error":null,"output":[{"type":"message","content":[{"type":"output_text","text":"synthetic-key"}]}],"usage":{"input_tokens":1,"output_tokens":1}}),
    ] {
        let frames = json!([{"method":"POST","path":"/responses","expected_body":null,"status":200,"retry_after_ms":null,"response":body}]);
        let mut provider = ProviderContract::new(
            ChannelId::new("fixture").unwrap(),
            ProviderId::OpenAi,
            OPENAI_ENDPOINT,
            Some(Secret::from_bytes(b"synthetic-key").unwrap()),
            ReplayTransport::from_json(&frames.to_string()).unwrap(),
            limits(),
        )
        .unwrap();
        let input_schema = schema();
        let error = provider
            .call(Operation::Generate(CompletionInput {
                images: &[],
                model: "fixture",
                prompt: "架空",
                schema: &input_schema,
                max_output_tokens: 64,
            }))
            .await
            .err()
            .unwrap();
        assert!(!format!("{error:?}").contains("synthetic-key"));
    }
}

#[tokio::test]
async fn japanese_bytes_are_not_tokens_and_paid_actual_usage_is_recorded() {
    let (_temp, mut store) = fixture();
    let provider = ProviderContract::new(
        ChannelId::new("fixture").unwrap(),
        ProviderId::OpenAi,
        OPENAI_ENDPOINT,
        Some(Secret::from_bytes(b"synthetic-key").unwrap()),
        ReplayTransport::from_json(include_str!("fixtures/openai.json")).unwrap(),
        limits(),
    )
    .unwrap();
    let mut selected = model(ProviderId::OpenAi, "synthetic-openai");
    selected.max_input_tokens = 5;
    let mut gateway = gateway(Box::new(provider), selected, options());
    let (_handle, mut cancel) = Cancellation::pair();
    gateway
        .generate_json::<Title>(&mut store, request("japanese"), &schema(), &mut cancel)
        .await
        .unwrap();
    assert_eq!(totals(&store).charged_micros, 15);
    assert_eq!(totals(&store).input_tokens, 5);
}

#[tokio::test]
async fn contextual_validation_reuses_single_schema_retry_and_channel_cache_is_isolated() {
    let (_temp, mut store) = fixture();
    let other = ChannelId::new("other").unwrap();
    store.create_channel(&other, "別チャンネル").unwrap();
    let responses = vec![
        complete("{\"title\":\"短\"}"),
        complete("{\"title\":\"合格の題名\"}"),
        complete("{\"title\":\"別の題名\"}"),
    ];
    let mut gateway = gateway(
        Box::new(FakeProvider::new(
            ChannelId::new("fixture").unwrap(),
            vec!["fake".into()],
            responses,
        )),
        model(ProviderId::Fake, "fake"),
        options(),
    );
    let (_handle, mut cancel) = Cancellation::pair();
    let value = gateway
        .generate_json_checked::<Title, _>(
            &mut store,
            request("context"),
            &schema(),
            &mut cancel,
            |title| {
                if title.title.chars().count() > 1 {
                    Ok(())
                } else {
                    Err(picocast_core::AppError::new(
                        "E-AI-SCHEMA",
                        "短すぎます",
                        "題名を確認してください",
                    ))
                }
            },
        )
        .await
        .unwrap();
    assert_eq!(value.value.title, "合格の題名");
    assert_eq!(
        store
            .repository(&ChannelId::new("fixture").unwrap())
            .unwrap()
            .list::<CostLedger>()
            .unwrap()
            .len(),
        2
    );
    let mut another = request("other");
    another.channel_id = other.clone();
    let error = gateway
        .generate_json::<Title>(&mut store, another, &schema(), &mut cancel)
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, "E-AI-CHANNEL");
    assert_eq!(totals(&store).output_tokens, 20);
    assert!(store
        .repository(&other)
        .unwrap()
        .list::<CostLedger>()
        .unwrap()
        .is_empty());
}

#[tokio::test]
async fn disconnected_retry_preserves_uncertain_cost_and_honors_retry_after_upper_bound() {
    let (_temp, mut store) = fixture();
    let responses = vec![
        Err(ProviderFault {
            kind: FaultKind::Disconnected,
            retry_after: None,
        }),
        complete("{\"title\":\"再接続\"}"),
    ];
    let mut gateway = gateway(
        Box::new(FakeProvider::new(
            ChannelId::new("fixture").unwrap(),
            vec!["fake".into()],
            responses,
        )),
        model(ProviderId::Fake, "fake"),
        options(),
    );
    let (_handle, mut cancel) = Cancellation::pair();
    gateway
        .generate_json::<Title>(&mut store, request("offline"), &schema(), &mut cancel)
        .await
        .unwrap();
    assert_eq!(totals(&store).held_tokens, 1088);
    let responses = vec![
        Err(ProviderFault {
            kind: FaultKind::Http(429),
            retry_after: Some(Duration::from_secs(60)),
        }),
        complete("{\"title\":\"送ってはいけない\"}"),
    ];
    let mut gateway = Gateway::new(
        ChannelId::new("fixture").unwrap(),
        ModelRegistry {
            stages: BTreeMap::from([(Stage::Title, model(ProviderId::Fake, "fake"))]),
        },
        options(),
        vec![Box::new(FakeProvider::new(
            ChannelId::new("fixture").unwrap(),
            vec!["fake".into()],
            responses,
        ))],
        Box::new(NoCache),
    )
    .unwrap();
    assert_eq!(
        gateway
            .generate_json::<Title>(&mut store, request("long-retry"), &schema(), &mut cancel)
            .await
            .err()
            .unwrap()
            .code,
        "E-AI-RATE"
    );
    assert_eq!(
        store
            .repository(&ChannelId::new("fixture").unwrap())
            .unwrap()
            .list::<CostLedger>()
            .unwrap()
            .len(),
        3
    );
}

#[tokio::test]
async fn gemini_model_pages_are_bounded_encoded_and_filter_unsupported_models() {
    let recording = json!([
        {"method":"GET","path":"/models","expected_body":null,"status":200,"retry_after_ms":null,"response":{"models":[{"name":"models/embed","supportedGenerationMethods":["embedContent"]}],"nextPageToken":"next + page"}},
        {"method":"GET","path":"/models?pageToken=next+%2B+page","expected_body":null,"status":200,"retry_after_ms":null,"response":{"models":[{"name":"models/text","supportedGenerationMethods":["generateContent"]}]}}
    ]);
    let mut provider = ProviderContract::new(
        ChannelId::new("fixture").unwrap(),
        ProviderId::Gemini,
        GEMINI_ENDPOINT,
        Some(Secret::from_bytes(b"synthetic-key").unwrap()),
        ReplayTransport::from_json(&recording.to_string()).unwrap(),
        limits(),
    )
    .unwrap();
    let result = provider.call(Operation::Models).await.unwrap();
    let ProviderOutput::Models(models) = result else {
        unreachable!()
    };
    assert_eq!(models, vec!["text"]);
    assert_eq!(provider.into_transport().remaining(), 0);
}

#[test]
fn secrets_cannot_be_in_urls_and_retry_after_dates_use_injected_time() {
    assert!(ProviderContract::new(
        ChannelId::new("fixture").unwrap(),
        ProviderId::OpenAi,
        "https://attacker.example/v1",
        Some(Secret::from_bytes(b"synthetic").unwrap()),
        ReplayTransport::from_json("[]").unwrap(),
        limits()
    )
    .is_err());
    assert!(Secret::from_bytes(b"bad\r\nheader").is_err());
    assert_eq!(
        retry_after("3", "2026-10-16T00:00:00Z"),
        Some(Duration::from_secs(3))
    );
    assert_eq!(
        retry_after("Fri, 16 Oct 2026 00:00:05 GMT", "2026-10-16T00:00:00Z"),
        Some(Duration::from_secs(5))
    );
}

#[tokio::test]
async fn server_503_keeps_paid_reservation_and_stops_retry_when_budget_is_full() {
    let (_temp, mut store) = fixture();
    let mut frames: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/openai.json")).unwrap();
    frames[1]["status"] = json!(503);
    frames[1]["response"] = Value::Null;
    let provider = ProviderContract::new(
        ChannelId::new("fixture").unwrap(),
        ProviderId::OpenAi,
        OPENAI_ENDPOINT,
        Some(Secret::from_bytes(b"synthetic-A").unwrap()),
        ReplayTransport::from_json(&serde_json::to_string(&frames).unwrap()).unwrap(),
        limits(),
    )
    .unwrap();
    let mut settings = options();
    settings.daily_budget_micros = 1088;
    let mut gateway = gateway(
        Box::new(provider),
        model(ProviderId::OpenAi, "synthetic-openai"),
        settings,
    );
    let (_handle, mut cancel) = Cancellation::pair();
    assert_eq!(
        gateway
            .generate_json::<Title>(&mut store, request("503"), &schema(), &mut cancel)
            .await
            .err()
            .unwrap()
            .code,
        "E-AI-BUDGET"
    );
    assert_eq!(totals(&store).held_micros, 1088);
    assert_eq!(totals(&store).held_tokens, 1088);
    assert_eq!(
        store
            .repository(&ChannelId::new("fixture").unwrap())
            .unwrap()
            .list::<CostLedger>()
            .unwrap()
            .len(),
        1
    );
}

struct CredentialCheckingTransport {
    replay: ReplayTransport,
    expected: &'static str,
    calls: std::rc::Rc<std::cell::Cell<usize>>,
}
impl Transport for CredentialCheckingTransport {
    fn send<'a>(
        &'a mut self,
        request: TransportRequest,
    ) -> FutureResult<'a, ProviderResult<TransportResponse>> {
        self.calls.set(self.calls.get() + 1);
        assert!(!request.url.contains("synthetic-"));
        assert!(request
            .headers
            .iter()
            .any(|(name, value)| name == "authorization" && value.as_str() == self.expected));
        self.replay.send(request)
    }
}
#[derive(Clone, Default)]
struct SharedCache(std::rc::Rc<std::cell::RefCell<MemoryCache>>);
impl ResultCache for SharedCache {
    fn get(
        &mut self,
        channel: &ChannelId,
        key: &str,
    ) -> picocast_core::Result<Option<CachedGeneration>> {
        self.0.borrow_mut().get(channel, key)
    }
    fn put(
        &mut self,
        channel: &ChannelId,
        key: &str,
        value: CachedGeneration,
    ) -> picocast_core::Result<()> {
        self.0.borrow_mut().put(channel, key, value)
    }
}

#[tokio::test]
async fn channel_bound_credentials_cache_and_ledger_never_cross_channels() {
    let (_temp, mut store) = fixture();
    let channel_a = ChannelId::new("fixture").unwrap();
    let channel_b = ChannelId::new("other").unwrap();
    store.create_channel(&channel_b, "別チャンネル").unwrap();
    let calls_a = std::rc::Rc::new(std::cell::Cell::new(0));
    let calls_b = std::rc::Rc::new(std::cell::Cell::new(0));
    let cache = SharedCache::default();
    let registry = || ModelRegistry {
        stages: BTreeMap::from([(Stage::Title, model(ProviderId::OpenAi, "synthetic-openai"))]),
    };
    let provider = |channel: ChannelId, secret: &[u8], expected, calls| {
        ProviderContract::new(
            channel,
            ProviderId::OpenAi,
            OPENAI_ENDPOINT,
            Some(Secret::from_bytes(secret).unwrap()),
            CredentialCheckingTransport {
                replay: ReplayTransport::from_json(include_str!("fixtures/openai.json")).unwrap(),
                expected,
                calls,
            },
            limits(),
        )
        .unwrap()
    };
    let mut a = Gateway::new(
        channel_a.clone(),
        registry(),
        options(),
        vec![Box::new(provider(
            channel_a.clone(),
            b"synthetic-A",
            "Bearer synthetic-A",
            calls_a.clone(),
        ))],
        Box::new(cache.clone()),
    )
    .unwrap();
    let (_handle, mut cancel) = Cancellation::pair();
    let mut wrong = request("wrong");
    wrong.channel_id = channel_b.clone();
    assert_eq!(
        a.generate_json::<Title>(&mut store, wrong, &schema(), &mut cancel)
            .await
            .err()
            .unwrap()
            .code,
        "E-AI-CHANNEL"
    );
    assert_eq!(calls_a.get(), 0);
    assert_eq!(totals(&store).charged_micros, 0);
    assert!(Gateway::new(
        channel_b.clone(),
        registry(),
        options(),
        vec![Box::new(provider(
            channel_a.clone(),
            b"synthetic-A",
            "Bearer synthetic-A",
            calls_a.clone()
        ))],
        Box::new(NoCache)
    )
    .is_err());
    assert!(
        !a.generate_json::<Title>(&mut store, request("a"), &schema(), &mut cancel)
            .await
            .unwrap()
            .cache_hit
    );
    let mut b = Gateway::new(
        channel_b.clone(),
        registry(),
        options(),
        vec![Box::new(provider(
            channel_b.clone(),
            b"synthetic-B",
            "Bearer synthetic-B",
            calls_b.clone(),
        ))],
        Box::new(cache),
    )
    .unwrap();
    let mut second = request("b");
    second.channel_id = channel_b.clone();
    assert!(
        !b.generate_json::<Title>(&mut store, second, &schema(), &mut cancel)
            .await
            .unwrap()
            .cache_hit
    );
    assert_eq!(calls_a.get(), 2);
    assert_eq!(calls_b.get(), 2);
    assert_eq!(totals(&store).charged_micros, 15);
    assert_eq!(
        store
            .ai_cost_totals(
                &channel_b,
                &UtcDay::from_timestamp(
                    &Timestamp::parse(&picocast_core::clock::now_utc_iso()).unwrap()
                )
            )
            .unwrap()
            .charged_micros,
        15
    );
}
