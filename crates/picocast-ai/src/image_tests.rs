#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::*;
use crate::{
    image_contract::ImageProviderContract,
    image_fake::{FakeImageInspector, FakeImageProvider},
    HttpMethod, ProviderFault, Secret, Transport, TransportRequest, TransportResponse,
    GEMINI_ENDPOINT,
};
use picocast_store::{repository::CostLedger, DataMode, StoreOptions, StorePaths};
use std::{
    collections::VecDeque,
    sync::{atomic::Ordering, Arc, Mutex},
};

fn png() -> InlineImage {
    let pixels = image::RgbaImage::from_fn(16, 16, |x, y| {
        if (x + y) % 2 == 0 {
            image::Rgba([240, 120, 30, 255])
        } else {
            image::Rgba([10, 60, 180, 255])
        }
    });
    let mut output = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels)
        .write_to(&mut output, image::ImageFormat::Png)
        .unwrap();
    InlineImage {
        mime: "image/png".into(),
        bytes: output.into_inner(),
    }
}
fn limits() -> ImageLimits {
    ImageLimits {
        max_images: 1,
        max_total_bytes: 10000,
        max_width: 64,
        max_height: 64,
        max_decoded_bytes: 16384,
    }
}
fn options() -> ImageOptions {
    ImageOptions {
        max_regenerations: 1,
        timeout_ms: 100,
        max_prompt_bytes: 10000,
        daily_budget_micros: 1000,
        daily_token_budget: 10000,
        allow_paid: true,
        development: true,
        min_text_score: 80,
        min_anatomy_score: 80,
        min_content_score: 80,
        min_variance: 0.001,
        min_visible_fraction: 0.5,
        limits: limits(),
    }
}
fn style(channel: &ChannelId) -> StyleProfile {
    StyleProfile {
        channel_id: channel.clone(),
        version: 1,
        style: "原創の切り絵".into(),
        negative: "低品質".into(),
        seed: SeedPolicy::ByAttempt { base: 42, step: 1 },
        loras: Vec::new(),
        prohibited_names: vec!["既存の固有キャラ".into()],
    }
}
fn spec() -> ImageSpec {
    ImageSpec {
        width: 16,
        height: 16,
        aspect_ratio: "1:1".into(),
        image_size: Some("1K".into()),
        steps: 5,
        sampler: "Euler".into(),
        cfg_scale: 7.,
        checkpoint_hash: Some("abcd123456".into()),
    }
}
fn assessment(originality: Originality) -> Assessment {
    Assessment {
        text_score: 95,
        anatomy_score: 95,
        content_score: 95,
        originality,
    }
}
fn completion() -> ImageCompletion {
    ImageCompletion {
        image: png(),
        usage: Some(Usage {
            input_tokens: 5,
            output_tokens: 23,
        }),
        actual_seed: Some(42),
        software_version: "synthetic".into(),
    }
}
fn fixture() -> (tempfile::TempDir, Store, ChannelId) {
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
    let channel = ChannelId::new("fixture").unwrap();
    store.create_channel(&channel, "合成fixture").unwrap();
    (temp, store, channel)
}
fn request<'a>(
    channel: &'a ChannelId,
    style: &'a StyleProfile,
    spec: &'a ImageSpec,
    billing: &'a ImageBilling,
) -> ImageRequest<'a> {
    ImageRequest {
        channel,
        request_id: "fixture-request",
        topic: "資料室",
        model: "fixture-image",
        style,
        spec,
        billing,
        settings_hash: "synthetic-settings",
        template_version: 1,
        project_id: None,
        job_id: None,
    }
}
struct Recording {
    requests: Arc<Mutex<Vec<TransportRequest>>>,
    responses: VecDeque<TransportResponse>,
}
impl Transport for Recording {
    fn send<'a>(
        &'a mut self,
        request: TransportRequest,
    ) -> FutureResult<'a, ProviderResult<TransportResponse>> {
        Box::pin(async move {
            self.requests.lock().unwrap().push(request);
            self.responses
                .pop_front()
                .ok_or_else(ProviderFault::contract)
        })
    }
}
fn recording(bodies: Vec<Value>) -> (Recording, Arc<Mutex<Vec<TransportRequest>>>) {
    let requests = Arc::new(Mutex::new(Vec::new()));
    (
        Recording {
            requests: requests.clone(),
            responses: bodies
                .into_iter()
                .map(|body| TransportResponse {
                    status: 200,
                    retry_after: None,
                    body,
                })
                .collect(),
        },
        requests,
    )
}
fn wire(template: &str) -> Value {
    serde_json::from_str(&template.replace("$SYNTHETIC_PNG", &STANDARD.encode(png().bytes)))
        .unwrap()
}

#[tokio::test]
async fn both_official_wire_contracts_decode_synthetic_recordings() {
    let channel = ChannelId::new("fixture").unwrap();
    let spec = spec();
    let (transport, requests) = recording(vec![wire(include_str!("image_fixtures/gemini.json"))]);
    let mut provider = ImageProviderContract::new(
        channel.clone(),
        ProviderId::Gemini,
        GEMINI_ENDPOINT,
        Some(Secret::from_bytes(b"fixture-secret").unwrap()),
        transport,
        10000,
    )
    .unwrap();
    let result = provider
        .generate(ImageInput {
            max_output_tokens: Some(100),
            model: "fixture-image",
            prompt: "独自の図書館",
            negative: "著名キャラ",
            seed: 42,
            spec: &spec,
            loras: &[],
        })
        .await
        .unwrap();
    assert_eq!(result.usage.unwrap().output_tokens, 23);
    assert_eq!(result.image.bytes, png().bytes);
    {
        let sent = requests.lock().unwrap();
        let body = sent[0].body.as_ref().unwrap();
        assert_eq!(
            body["generationConfig"]["responseFormat"]["image"]["imageSize"],
            "1K"
        );
        assert_eq!(sent[0].method, HttpMethod::Post);
        assert_eq!(sent[0].headers[0].0, "x-goog-api-key");
    }
    let (transport, requests) = recording(vec![
        json!([{"title":"fixture-image","hash":"abcd123456"}]),
        json!([{"name":"Euler"}]),
        wire(include_str!("image_fixtures/sd-webui.json")),
    ]);
    let mut provider = ImageProviderContract::new(
        channel,
        ProviderId::StableDiffusionWebUi,
        "http://127.0.0.1:7860/",
        None,
        transport,
        10000,
    )
    .unwrap();
    let result = provider
        .generate(ImageInput {
            max_output_tokens: None,
            model: "fixture-image",
            prompt: "図書館",
            negative: "low quality",
            seed: 42,
            spec: &spec,
            loras: &[],
        })
        .await
        .unwrap();
    assert_eq!(result.actual_seed, Some(42));
    let sent = requests.lock().unwrap();
    assert_eq!(sent.len(), 3);
    assert_eq!(
        sent[2].body.as_ref().unwrap()["override_settings_restore_afterwards"],
        true
    );
    assert_eq!(sent[2].body.as_ref().unwrap()["save_images"], false);
}
#[tokio::test]
async fn bounded_quality_retry_holds_and_counts_every_generated_image() {
    let (_temp, mut store, channel) = fixture();
    let mut second = completion();
    second.actual_seed = Some(43);
    let provider = FakeImageProvider::new(channel.clone(), vec![Ok(completion()), Ok(second)]);
    let calls = provider.calls.clone();
    let inspector = FakeImageInspector::new(vec![
        assessment(Originality::Suspected),
        assessment(Originality::Uncertain),
    ]);
    let mut gateway = ImageGateway::new(
        channel.clone(),
        Box::new(provider),
        Box::new(inspector),
        options(),
    )
    .unwrap();
    let (_handle, mut cancel) = Cancellation::pair();
    let result = gateway
        .generate(
            &mut store,
            request(
                &channel,
                &style(&channel),
                &spec(),
                &ImageBilling::PerImage { micros: 0 },
            ),
            &mut cancel,
        )
        .await
        .unwrap();
    let held = match result {
        ImageOutcome::Hold {
            attempts, issues, ..
        } => Some((attempts, issues)),
        _ => None,
    }
    .unwrap();
    assert_eq!(held, (2, vec![ImageIssue::Uncertain]));
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    let rows = store
        .repository(&channel)
        .unwrap()
        .list::<CostLedger>()
        .unwrap();
    assert_eq!(rows.len(), 2);
    let totals = store
        .ai_cost_totals(
            &channel,
            &UtcDay::from_timestamp(&Timestamp::parse(&clock::now_utc_iso()).unwrap()),
        )
        .unwrap();
    assert_eq!(totals.images, 2);
    assert_eq!(totals.held_tokens, 0);
}
#[tokio::test]
async fn accepted_image_keeps_channel_style_seed_hash_and_model_provenance() {
    let (_temp, mut store, channel) = fixture();
    let provider = FakeImageProvider::new(channel.clone(), vec![Ok(completion())]);
    let inspector = FakeImageInspector::new(vec![assessment(Originality::Clear)]);
    let mut gateway = ImageGateway::new(
        channel.clone(),
        Box::new(provider),
        Box::new(inspector),
        options(),
    )
    .unwrap();
    let (_handle, mut cancel) = Cancellation::pair();
    let result = gateway
        .generate(
            &mut store,
            request(
                &channel,
                &style(&channel),
                &spec(),
                &ImageBilling::PerImage { micros: 0 },
            ),
            &mut cancel,
        )
        .await
        .unwrap();
    let provenance = match result {
        ImageOutcome::Ready { provenance, .. } => Some(provenance),
        _ => None,
    }
    .unwrap();
    assert_eq!(provenance.requested_seed, 42);
    assert_eq!(provenance.image_sha256, digest(&png().bytes));
    assert_eq!(provenance.style_version, 1);
}
#[tokio::test]
async fn unknown_paid_result_holds_budget_and_blocks_repeat_request() {
    let (_temp, mut store, channel) = fixture();
    let (mut transport, _) = recording(Vec::new());
    transport.responses.push_back(TransportResponse {
        status: 503,
        retry_after: None,
        body: Value::Null,
    });
    let provider = ImageProviderContract::new(
        channel.clone(),
        ProviderId::Gemini,
        GEMINI_ENDPOINT,
        Some(Secret::from_bytes(b"fixture-secret").unwrap()),
        transport,
        10000,
    )
    .unwrap();
    let mut gateway = ImageGateway::new(
        channel.clone(),
        Box::new(provider),
        Box::new(FakeImageInspector::new(Vec::new())),
        options(),
    )
    .unwrap();
    let (_handle, mut cancel) = Cancellation::pair();
    let billing = ImageBilling::Tokens {
        model: StageModel {
            provider: ProviderId::Gemini,
            model: "fixture-image".into(),
            max_input_tokens: 50,
            max_output_tokens: 100,
            input_micros_per_million: 1_000_000,
            output_micros_per_million: 1_000_000,
        },
    };
    assert!(gateway
        .generate(
            &mut store,
            request(&channel, &style(&channel), &spec(), &billing),
            &mut cancel
        )
        .await
        .is_err());
    let day = UtcDay::from_timestamp(&Timestamp::parse(&clock::now_utc_iso()).unwrap());
    assert_eq!(
        store.ai_cost_totals(&channel, &day).unwrap().held_micros,
        150
    );
    assert_eq!(
        gateway
            .generate(
                &mut store,
                request(&channel, &style(&channel), &spec(), &billing),
                &mut cancel
            )
            .await
            .err()
            .unwrap()
            .code,
        "E-AI-RESERVATION"
    );
}
#[test]
fn limits_policy_and_registry_refuse_invalid_or_cross_channel_contracts() {
    let image = png();
    assert_eq!(
        openai_input("採点", std::slice::from_ref(&image))[0]["content"][1]["type"],
        "input_image"
    );
    assert_eq!(
        ollama_input(
            "fixture",
            "採点",
            &json!({}),
            100,
            std::slice::from_ref(&image)
        )["images"][0],
        STANDARD.encode(&image.bytes)
    );
    let channel = ChannelId::new("fixture").unwrap();
    let other = ChannelId::new("other").unwrap();
    let profile = style(&channel);
    assert!(profile.prompt(&other, "資料", 0).is_err());
    assert!(profile
        .prompt(&channel, "既存の固有キャラを描く", 0)
        .is_err());
    let mut bad = limits();
    bad.max_width = 1;
    assert!(bad.validate_images(&[png()]).is_err());
    let mut bad = png();
    bad.mime = "image/jpeg".into();
    assert!(limits().validate_images(&[bad]).is_err());
    let (transport, _) = recording(Vec::new());
    assert!(ImageProviderContract::new(
        channel.clone(),
        ProviderId::Gemini,
        "https://example.invalid/",
        Some(Secret::from_bytes(b"secret").unwrap()),
        transport,
        100
    )
    .is_err());
    let model = StageModel {
        provider: ProviderId::StableDiffusionWebUi,
        model: "local".into(),
        max_input_tokens: 1,
        max_output_tokens: 1,
        input_micros_per_million: 0,
        output_micros_per_million: 0,
    };
    assert!(model.validate().is_err());
    let mut production = options();
    production.development = false;
    assert!(ImageGateway::new(
        channel.clone(),
        Box::new(FakeImageProvider::new(channel, Vec::new())),
        Box::new(FakeImageInspector::new(Vec::new())),
        production
    )
    .is_err());
}

#[tokio::test]
async fn vision_inspector_uses_existing_gateway_budget_and_image_wire() {
    use crate::{GatewayOptions, ModelRegistry, NoCache, ProviderContract, ProviderLimits};
    use std::collections::BTreeMap;
    let (_temp, mut store, channel) = fixture();
    let assessment = assessment(Originality::Clear);
    let models = json!({"models":[{"name":"models/review-model","supportedGenerationMethods":["generateContent"]}]});
    let answer = json!({"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":serde_json::to_string(&assessment).unwrap()}]}}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":10,"totalTokenCount":15}});
    let (transport, requests) = recording(vec![models, answer]);
    let provider = ProviderContract::new(
        channel.clone(),
        ProviderId::Gemini,
        GEMINI_ENDPOINT,
        Some(Secret::from_bytes(b"fixture-secret").unwrap()),
        transport,
        ProviderLimits {
            max_model_pages: 1,
            max_models: 5,
        },
    )
    .unwrap();
    let mut gateway = Gateway::new(
        channel.clone(),
        ModelRegistry {
            stages: BTreeMap::from([(
                Stage::Review,
                StageModel {
                    provider: ProviderId::Gemini,
                    model: "review-model".into(),
                    max_input_tokens: 100,
                    max_output_tokens: 100,
                    input_micros_per_million: 1_000_000,
                    output_micros_per_million: 1_000_000,
                },
            )]),
        },
        GatewayOptions {
            max_attempts: 1,
            request_timeout: Duration::from_secs(1),
            retry_base: Duration::from_millis(1),
            retry_max: Duration::from_millis(1),
            daily_budget_micros: 1000,
            daily_token_budget: 1000,
            max_prompt_bytes: 10000,
            development: true,
            allow_paid: true,
        },
        vec![Box::new(provider)],
        Box::new(NoCache),
    )
    .unwrap();
    let mut inspector = GatewayImageInspector {
        gateway: &mut gateway,
        limits: limits(),
    };
    let (_handle, mut cancel) = Cancellation::pair();
    let result = inspector
        .inspect(
            &mut store,
            &png(),
            ReviewContext {
                channel: &channel,
                request_id: "vision-fixture",
                topic: "資料室",
                settings_hash: "fixture",
                template_version: 1,
            },
            &mut cancel,
        )
        .await
        .unwrap();
    assert_eq!(result.content_score, 95);
    let requests = requests.lock().unwrap();
    let body = requests[1].body.as_ref().unwrap();
    assert_eq!(
        body["contents"][0]["parts"][1]["inlineData"]["mimeType"],
        "image/png"
    );
    assert_eq!(
        body["contents"][0]["parts"][1]["inlineData"]["data"],
        STANDARD.encode(png().bytes)
    );
    let totals = store
        .ai_cost_totals(
            &channel,
            &UtcDay::from_timestamp(&Timestamp::parse(&clock::now_utc_iso()).unwrap()),
        )
        .unwrap();
    assert_eq!(totals.charged_micros, 15);
    assert_eq!(totals.held_micros, 0);
}

struct PendingProvider {
    channel: ChannelId,
}
impl ImageProvider for PendingProvider {
    fn channel_id(&self) -> &ChannelId {
        &self.channel
    }
    fn id(&self) -> ProviderId {
        ProviderId::Gemini
    }
    fn generate<'a>(
        &'a mut self,
        _input: ImageInput<'a>,
    ) -> FutureResult<'a, ProviderResult<ImageCompletion>> {
        Box::pin(std::future::pending())
    }
}
fn token_billing() -> ImageBilling {
    ImageBilling::Tokens {
        model: StageModel {
            provider: ProviderId::Gemini,
            model: "fixture-image".into(),
            max_input_tokens: 50,
            max_output_tokens: 100,
            input_micros_per_million: 1_000_000,
            output_micros_per_million: 1_000_000,
        },
    }
}

#[tokio::test]
async fn cancellation_and_timeout_preserve_unknown_money_without_publishing_image() {
    for cancel_during_send in [false, true] {
        let (_temp, mut store, channel) = fixture();
        let mut config = options();
        config.timeout_ms = 5;
        let mut gateway = ImageGateway::new(
            channel.clone(),
            Box::new(PendingProvider {
                channel: channel.clone(),
            }),
            Box::new(FakeImageInspector::new(Vec::new())),
            config,
        )
        .unwrap();
        let (handle, mut cancel) = Cancellation::pair();
        let style = style(&channel);
        let spec = spec();
        let billing = token_billing();
        let operation = gateway.generate(
            &mut store,
            request(&channel, &style, &spec, &billing),
            &mut cancel,
        );
        let trigger = async {
            if cancel_during_send {
                tokio::task::yield_now().await;
                handle.cancel();
            }
        };
        let (result, ()) = tokio::join!(operation, trigger);
        assert_eq!(
            result.err().unwrap().code,
            if cancel_during_send {
                "E-AI-CANCELLED"
            } else {
                "E-AI-TIMEOUT"
            }
        );
        let rows = store
            .repository(&channel)
            .unwrap()
            .list::<CostLedger>()
            .unwrap();
        assert_eq!(rows[0].units_json["ai_cost"]["state"], "unknown");
        assert_eq!(
            store
                .ai_cost_totals(
                    &channel,
                    &UtcDay::from_timestamp(&Timestamp::parse(&clock::now_utc_iso()).unwrap())
                )
                .unwrap()
                .held_micros,
            150
        );
    }
}

#[tokio::test]
async fn auth_and_rate_rejection_release_confirmed_zero_charge_without_retry() {
    for (status, code) in [(401, "E-AI-AUTH"), (429, "E-AI-RATE")] {
        let (_temp, mut store, channel) = fixture();
        let (mut transport, requests) = recording(Vec::new());
        transport.responses.push_back(TransportResponse {
            status,
            retry_after: Some(Duration::from_secs(3)),
            body: Value::Null,
        });
        let provider = ImageProviderContract::new(
            channel.clone(),
            ProviderId::Gemini,
            GEMINI_ENDPOINT,
            Some(Secret::from_bytes(b"fixture-secret").unwrap()),
            transport,
            10000,
        )
        .unwrap();
        let mut gateway = ImageGateway::new(
            channel.clone(),
            Box::new(provider),
            Box::new(FakeImageInspector::new(Vec::new())),
            options(),
        )
        .unwrap();
        let (_handle, mut cancel) = Cancellation::pair();
        assert_eq!(
            gateway
                .generate(
                    &mut store,
                    request(&channel, &style(&channel), &spec(), &token_billing()),
                    &mut cancel
                )
                .await
                .err()
                .unwrap()
                .code,
            code
        );
        let totals = store
            .ai_cost_totals(
                &channel,
                &UtcDay::from_timestamp(&Timestamp::parse(&clock::now_utc_iso()).unwrap()),
            )
            .unwrap();
        assert_eq!((totals.charged_micros, totals.held_micros), (0, 0));
        assert_eq!(requests.lock().unwrap().len(), 1);
    }
}

#[tokio::test]
async fn sd_missing_model_or_substituted_hash_never_produces_accepted_image() {
    let channel = ChannelId::new("fixture").unwrap();
    let spec = spec();
    let (transport, requests) = recording(vec![json!([{"title":"different","hash":"abcd123456"}])]);
    let mut provider = ImageProviderContract::new(
        channel.clone(),
        ProviderId::StableDiffusionWebUi,
        "http://127.0.0.1:7860/",
        None,
        transport,
        10000,
    )
    .unwrap();
    assert!(provider
        .generate(ImageInput {
            max_output_tokens: None,
            model: "fixture-image",
            prompt: "独自の図書館",
            negative: "低品質",
            seed: 42,
            spec: &spec,
            loras: &[]
        })
        .await
        .is_err());
    assert_eq!(requests.lock().unwrap().len(), 1);
    let response = include_str!("image_fixtures/sd-webui.json").replace("abcd123456", "ffffffff00");
    let (transport, _) = recording(vec![
        json!([{"title":"fixture-image","hash":"abcd123456"}]),
        json!([{"name":"Euler"}]),
        wire(&response),
    ]);
    let mut provider = ImageProviderContract::new(
        channel,
        ProviderId::StableDiffusionWebUi,
        "http://127.0.0.1:7860/",
        None,
        transport,
        10000,
    )
    .unwrap();
    assert!(provider
        .generate(ImageInput {
            max_output_tokens: None,
            model: "fixture-image",
            prompt: "独自の図書館",
            negative: "低品質",
            seed: 42,
            spec: &spec,
            loras: &[]
        })
        .await
        .is_err());
}

struct Cache(std::collections::BTreeMap<(String, String), crate::CachedGeneration>);
impl crate::ResultCache for Cache {
    fn get(&mut self, channel: &ChannelId, key: &str) -> Result<Option<crate::CachedGeneration>> {
        Ok(self.0.get(&(channel.as_str().into(), key.into())).cloned())
    }
    fn put(
        &mut self,
        channel: &ChannelId,
        key: &str,
        value: crate::CachedGeneration,
    ) -> Result<()> {
        self.0.insert((channel.as_str().into(), key.into()), value);
        Ok(())
    }
}
struct VisionFake {
    channel: ChannelId,
    calls: Arc<std::sync::atomic::AtomicUsize>,
}
impl crate::LlmProvider for VisionFake {
    fn channel_id(&self) -> &ChannelId {
        &self.channel
    }
    fn id(&self) -> ProviderId {
        ProviderId::Fake
    }
    fn call<'a>(
        &'a mut self,
        operation: crate::Operation<'a>,
    ) -> FutureResult<'a, ProviderResult<crate::ProviderOutput>> {
        Box::pin(async move {
            match operation {
                crate::Operation::Models => {
                    Ok(crate::ProviderOutput::Models(vec!["review-model".into()]))
                }
                crate::Operation::Generate(input) => {
                    assert_eq!(input.images.len(), 1);
                    self.calls.fetch_add(1, Ordering::SeqCst);
                    Ok(crate::ProviderOutput::Completion(crate::Completion {
                        text: "{\"ok\":true}".into(),
                        usage: Usage {
                            input_tokens: 5,
                            output_tokens: 5,
                        },
                    }))
                }
            }
        })
    }
}
#[tokio::test]
async fn multimodal_cache_hash_changes_with_actual_image_content() {
    use crate::{GatewayOptions, ModelRegistry};
    use std::collections::BTreeMap;
    let (_temp, mut store, channel) = fixture();
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut gateway = Gateway::new(
        channel.clone(),
        ModelRegistry {
            stages: BTreeMap::from([(
                Stage::Review,
                StageModel {
                    provider: ProviderId::Fake,
                    model: "review-model".into(),
                    max_input_tokens: 100,
                    max_output_tokens: 100,
                    input_micros_per_million: 0,
                    output_micros_per_million: 0,
                },
            )]),
        },
        GatewayOptions {
            max_attempts: 1,
            request_timeout: Duration::from_secs(1),
            retry_base: Duration::from_millis(1),
            retry_max: Duration::from_millis(1),
            daily_budget_micros: 1000,
            daily_token_budget: 1000,
            max_prompt_bytes: 10000,
            development: true,
            allow_paid: false,
        },
        vec![Box::new(VisionFake {
            channel: channel.clone(),
            calls: calls.clone(),
        })],
        Box::new(Cache(BTreeMap::new())),
    )
    .unwrap();
    let first = png();
    let mut pixels = limits().decode(&first).unwrap().to_rgba8();
    pixels.put_pixel(0, 0, image::Rgba([0, 255, 0, 255]));
    let mut bytes = Cursor::new(Vec::new());
    image::DynamicImage::ImageRgba8(pixels)
        .write_to(&mut bytes, image::ImageFormat::Png)
        .unwrap();
    let second = InlineImage {
        mime: "image/png".into(),
        bytes: bytes.into_inner(),
    };
    let (_handle, mut cancel) = Cancellation::pair();
    let mut hashes = Vec::new();
    let mut cache_hits = Vec::new();
    for (index, image) in [first.clone(), second, first].into_iter().enumerate() {
        let images = [image];
        let result:crate::Generation<Value>=gateway.generate_json_with_images(&mut store,GenerateRequest{channel_id:channel.clone(),request_id:format!("image-{index}"),project_id:None,job_id:None,stage:Stage::Review,prompt:"採点".into(),template_version:1,settings_hash:"fixture".into()},&json!({"type":"object","required":["ok"],"additionalProperties":false,"properties":{"ok":{"type":"boolean"}}}),&mut cancel,MultimodalInput{images:&images,limits:&limits()}).await.unwrap();
        hashes.push(result.provenance.request_hash);
        cache_hits.push(result.cache_hit);
    }
    assert_ne!(hashes[0], hashes[1]);
    assert_eq!(hashes[0], hashes[2]);
    assert_eq!(cache_hits, vec![false, false, true]);
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}
