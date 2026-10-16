//! 画像の契約・画風・受入検査。品質判定も共通LLM Gatewayを利用する。
use crate::{
    failure, Cancellation, FutureResult, Gateway, GenerateRequest, ProviderId, ProviderResult,
    Stage, StageModel, Usage,
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use picocast_core::{
    clock::{self, Timestamp},
    ChannelId, Result,
};
use picocast_store::{
    ai_cost::{AiCostReservation, AiCostSettlement, UtcDay},
    Store,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{io::Cursor, time::Duration};

/// 本文をDebugへ渡さない。
#[derive(Clone)]
pub struct InlineImage {
    pub mime: String,
    pub bytes: Vec<u8>,
}
impl InlineImage {
    pub fn fingerprint(&self) -> Value {
        json!({"mime":self.mime,"sha256":digest(&self.bytes)})
    }
}
pub(crate) fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImageLimits {
    pub max_images: usize,
    pub max_total_bytes: usize,
    pub max_width: u32,
    pub max_height: u32,
    pub max_decoded_bytes: u64,
}
pub struct MultimodalInput<'a> {
    pub images: &'a [InlineImage],
    pub limits: &'a ImageLimits,
}
impl ImageLimits {
    pub fn validate(&self) -> Result<()> {
        if self.max_images == 0
            || self.max_total_bytes == 0
            || self.max_width == 0
            || self.max_height == 0
            || self.max_decoded_bytes == 0
        {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        Ok(())
    }
    pub fn validate_images(&self, images: &[InlineImage]) -> Result<()> {
        self.validate()?;
        if images.is_empty() || images.len() > self.max_images {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        let mut bytes = 0usize;
        for image in images {
            bytes = bytes
                .checked_add(image.bytes.len())
                .ok_or_else(|| failure("E-IMAGE-CONTRACT"))?;
            if bytes > self.max_total_bytes {
                return Err(failure("E-IMAGE-CONTRACT"));
            }
            self.decode(image)?;
        }
        Ok(())
    }
    pub fn decode(&self, image: &InlineImage) -> Result<image::DynamicImage> {
        self.validate()?;
        if image.bytes.is_empty() || image.bytes.len() > self.max_total_bytes {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        let format = match image.mime.as_str() {
            "image/png" => image::ImageFormat::Png,
            "image/jpeg" => image::ImageFormat::Jpeg,
            _ => return Err(failure("E-IMAGE-CONTRACT")),
        };
        if image::guess_format(&image.bytes).map_err(|_| failure("E-IMAGE-CONTRACT"))? != format {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        let (width, height) = image::ImageReader::with_format(Cursor::new(&image.bytes), format)
            .into_dimensions()
            .map_err(|_| failure("E-IMAGE-CONTRACT"))?;
        if width == 0
            || height == 0
            || width > self.max_width
            || height > self.max_height
            || u64::from(width)
                .checked_mul(u64::from(height))
                .and_then(|value| value.checked_mul(4))
                .is_none_or(|bytes| bytes > self.max_decoded_bytes)
        {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        let mut reader = image::ImageReader::with_format(Cursor::new(&image.bytes), format);
        let mut limits = image::Limits::default();
        limits.max_image_width = Some(self.max_width);
        limits.max_image_height = Some(self.max_height);
        limits.max_alloc = Some(self.max_decoded_bytes);
        reader.limits(limits);
        reader.decode().map_err(|_| failure("E-IMAGE-CONTRACT"))
    }
}
pub(crate) fn gemini_parts(prompt: &str, images: &[InlineImage]) -> Value {
    let mut parts = vec![json!({"text":prompt})];
    parts.extend(images.iter().map(
        |image| json!({"inlineData":{"mimeType":image.mime,"data":STANDARD.encode(&image.bytes)}}),
    ));
    json!(parts)
}
pub(crate) fn openai_input(prompt: &str, images: &[InlineImage]) -> Value {
    if images.is_empty() {
        return json!(prompt);
    }
    let mut parts = vec![json!({"type":"input_text","text":prompt})];
    parts.extend(images.iter().map(|image|json!({"type":"input_image","image_url":format!("data:{};base64,{}",image.mime,STANDARD.encode(&image.bytes))})));
    json!([{"role":"user","content":parts}])
}
pub(crate) fn ollama_input(
    model: &str,
    prompt: &str,
    schema: &Value,
    max_tokens: u64,
    images: &[InlineImage],
) -> Value {
    let mut body = json!({"model":model,"prompt":prompt,"stream":false,"format":schema,"options":{"num_predict":max_tokens}});
    if !images.is_empty() {
        body["images"] = json!(images
            .iter()
            .map(|image| STANDARD.encode(&image.bytes))
            .collect::<Vec<_>>());
    }
    body
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lora {
    pub name: String,
    pub weight: f64,
    pub original_use_confirmed: bool,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SeedPolicy {
    Fixed { seed: u64 },
    ByAttempt { base: u64, step: u64 },
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StyleProfile {
    pub channel_id: ChannelId,
    pub version: i64,
    pub style: String,
    pub negative: String,
    pub seed: SeedPolicy,
    pub loras: Vec<Lora>,
    pub prohibited_names: Vec<String>,
}
impl StyleProfile {
    pub fn prompt(
        &self,
        channel: &ChannelId,
        topic: &str,
        attempt: u32,
    ) -> Result<(String, String, u64)> {
        if &self.channel_id != channel {
            return Err(failure("E-AI-CHANNEL"));
        }
        if self.version < 1 || self.style.trim().is_empty() || topic.trim().is_empty() {
            return Err(failure("E-IMAGE-POLICY"));
        }
        let text=format!("{topic}\n{}\n独自の造形と構図を作る。有名キャラクター・既存作品・実在の人物に似せず、固有の衣装・顔・ロゴ・署名を再現しない。",self.style);
        let lowered = text.to_lowercase();
        if text.contains(['<', '>']) || self.negative.contains(['<', '>']) {
            return Err(failure("E-IMAGE-POLICY"));
        }
        if self
            .prohibited_names
            .iter()
            .any(|name| name.trim().is_empty() || lowered.contains(&name.to_lowercase()))
        {
            return Err(failure("E-IMAGE-POLICY"));
        }
        for lora in &self.loras {
            if !lora.original_use_confirmed
                || lora.name.is_empty()
                || !lora
                    .name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))
                || !lora.weight.is_finite()
                || self
                    .prohibited_names
                    .iter()
                    .any(|name| lora.name.to_lowercase().contains(&name.to_lowercase()))
            {
                return Err(failure("E-IMAGE-POLICY"));
            }
        }
        let seed = match self.seed {
            SeedPolicy::Fixed { seed } => seed,
            SeedPolicy::ByAttempt { base, step } => step
                .checked_mul(u64::from(attempt))
                .and_then(|value| value.checked_add(base))
                .ok_or_else(|| failure("E-IMAGE-POLICY"))?,
        };
        if seed > i32::MAX as u64 {
            return Err(failure("E-IMAGE-POLICY"));
        }
        Ok((text,format!("{}\nfamous copyrighted character, recognizable franchise, celebrity likeness, logo, signature",self.negative),seed))
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImageSpec {
    pub width: u32,
    pub height: u32,
    pub aspect_ratio: String,
    pub image_size: Option<String>,
    pub steps: u32,
    pub sampler: String,
    pub cfg_scale: f64,
    pub checkpoint_hash: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ImageBilling {
    PerImage { micros: u64 },
    Tokens { model: StageModel },
}
impl ImageBilling {
    fn maximum(&self) -> Result<u64> {
        match self {
            Self::PerImage { micros } => Ok(*micros),
            Self::Tokens { model } => {
                u64::try_from(model.maximum_cost()?).map_err(|_| failure("E-AI-BUDGET"))
            }
        }
    }
}
pub struct ImageInput<'a> {
    pub max_output_tokens: Option<u64>,
    pub model: &'a str,
    pub prompt: &'a str,
    pub negative: &'a str,
    pub seed: u64,
    pub spec: &'a ImageSpec,
    pub loras: &'a [Lora],
}
pub struct ImageCompletion {
    pub image: InlineImage,
    pub usage: Option<Usage>,
    pub actual_seed: Option<u64>,
    pub software_version: String,
}
pub trait ImageProvider {
    fn channel_id(&self) -> &ChannelId;
    fn id(&self) -> ProviderId;
    fn generate<'a>(
        &'a mut self,
        input: ImageInput<'a>,
    ) -> FutureResult<'a, ProviderResult<ImageCompletion>>;
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Originality {
    Clear,
    Suspected,
    Uncertain,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ImageIssue {
    Dimensions,
    DegeneratePixels,
    GarbledText,
    Anatomy,
    Unrelated,
    SimilarityRisk,
    Uncertain,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Assessment {
    pub text_score: u8,
    pub anatomy_score: u8,
    pub content_score: u8,
    pub originality: Originality,
}
pub struct ReviewContext<'a> {
    pub channel: &'a ChannelId,
    pub request_id: &'a str,
    pub topic: &'a str,
    pub settings_hash: &'a str,
    pub template_version: i64,
}
pub trait ImageInspector {
    fn synthetic(&self) -> bool;
    fn inspect<'a>(
        &'a mut self,
        store: &'a mut Store,
        image: &'a InlineImage,
        context: ReviewContext<'a>,
        cancel: &'a mut Cancellation,
    ) -> FutureResult<'a, Result<Assessment>>;
}
pub struct GatewayImageInspector<'a> {
    pub gateway: &'a mut Gateway,
    pub limits: ImageLimits,
}
impl ImageInspector for GatewayImageInspector<'_> {
    fn synthetic(&self) -> bool {
        false
    }
    fn inspect<'a>(
        &'a mut self,
        store: &'a mut Store,
        image: &'a InlineImage,
        context: ReviewContext<'a>,
        cancel: &'a mut Cancellation,
    ) -> FutureResult<'a, Result<Assessment>> {
        Box::pin(async move {
            let prompt=format!("添付画像を採点する。文字化け・崩れた手や顔・主題との関係を各0から100で評価する。有名キャラクター/実在人物に似ている疑いはsuspected、判断できなければuncertain、疑いが見当たらなければclearとする。法的な安全や画質を保証する判断ではない。主題は次のJSON文字列の内容:{}",serde_json::to_string(context.topic).map_err(|_|failure("E-IMAGE-CONTRACT"))?);
            let schema = json!({"type":"object","additionalProperties":false,"required":["text_score","anatomy_score","content_score","originality"],"properties":{"text_score":{"type":"integer","minimum":0,"maximum":100},"anatomy_score":{"type":"integer","minimum":0,"maximum":100},"content_score":{"type":"integer","minimum":0,"maximum":100},"originality":{"type":"string","enum":["clear","suspected","uncertain"]}}});
            let images = [image.clone()];
            let result = self
                .gateway
                .generate_json_with_images(
                    store,
                    GenerateRequest {
                        channel_id: context.channel.clone(),
                        request_id: context.request_id.into(),
                        project_id: None,
                        job_id: None,
                        stage: Stage::Review,
                        prompt,
                        template_version: context.template_version,
                        settings_hash: context.settings_hash.into(),
                    },
                    &schema,
                    cancel,
                    MultimodalInput {
                        images: &images,
                        limits: &self.limits,
                    },
                )
                .await?;
            Ok(result.value)
        })
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImageOptions {
    pub max_regenerations: u32,
    pub timeout_ms: u64,
    pub max_prompt_bytes: usize,
    pub daily_budget_micros: u64,
    pub daily_token_budget: u64,
    pub allow_paid: bool,
    pub development: bool,
    pub min_text_score: u8,
    pub min_anatomy_score: u8,
    pub min_content_score: u8,
    pub min_variance: f64,
    pub min_visible_fraction: f64,
    pub limits: ImageLimits,
}
pub struct ImageRequest<'a> {
    pub channel: &'a ChannelId,
    pub request_id: &'a str,
    pub topic: &'a str,
    pub model: &'a str,
    pub style: &'a StyleProfile,
    pub spec: &'a ImageSpec,
    pub billing: &'a ImageBilling,
    pub settings_hash: &'a str,
    pub template_version: i64,
    pub project_id: Option<String>,
    pub job_id: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImageProvenance {
    pub provider: ProviderId,
    pub model: String,
    pub request_hash: String,
    pub style_version: i64,
    pub requested_seed: u64,
    pub actual_seed: Option<u64>,
    pub software_version: String,
    pub at: Timestamp,
    pub settings_hash: String,
    pub template_version: i64,
    pub attempt: u32,
    pub image_sha256: String,
}
pub enum ImageOutcome {
    Ready {
        image: InlineImage,
        assessment: Assessment,
        provenance: ImageProvenance,
    },
    Hold {
        code: String,
        attempts: u32,
        issues: Vec<ImageIssue>,
    },
}
pub struct ImageGateway<'a> {
    channel: ChannelId,
    provider: Box<dyn ImageProvider>,
    inspector: Box<dyn ImageInspector + 'a>,
    options: ImageOptions,
}
impl<'a> ImageGateway<'a> {
    pub fn new(
        channel: ChannelId,
        provider: Box<dyn ImageProvider>,
        inspector: Box<dyn ImageInspector + 'a>,
        options: ImageOptions,
    ) -> Result<Self> {
        options.limits.validate()?;
        if provider.channel_id() != &channel {
            return Err(failure("E-AI-CHANNEL"));
        }
        if !matches!(
            provider.id(),
            ProviderId::Gemini | ProviderId::StableDiffusionWebUi | ProviderId::Fake
        ) || ((provider.id() == ProviderId::Fake || inspector.synthetic())
            && !options.development)
            || options.timeout_ms == 0
            || options.max_prompt_bytes == 0
            || options.min_text_score > 100
            || options.min_anatomy_score > 100
            || options.min_content_score > 100
            || !options.min_variance.is_finite()
            || options.min_variance < 0.
            || !options.min_visible_fraction.is_finite()
            || !(0. ..=1.).contains(&options.min_visible_fraction)
        {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        Ok(Self {
            channel,
            provider,
            inspector,
            options,
        })
    }
    #[tracing::instrument(skip_all,fields(channel_id=request.channel.as_str(),request_id=request.request_id))]
    pub async fn generate(
        &mut self,
        store: &mut Store,
        request: ImageRequest<'_>,
        cancel: &mut Cancellation,
    ) -> Result<ImageOutcome> {
        if request.channel != &self.channel {
            return Err(failure("E-AI-CHANNEL"));
        }
        store.repository(request.channel)?;
        cancel.check()?;
        if request.request_id.is_empty()
            || request.settings_hash.is_empty()
            || request.template_version < 1
            || request.model.is_empty()
            || request.spec.width == 0
            || request.spec.height == 0
            || request.spec.width > self.options.limits.max_width
            || request.spec.height > self.options.limits.max_height
        {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        let paid = self.provider.id() == ProviderId::Gemini;
        if u64::from(request.spec.width)
            .checked_mul(u64::from(request.spec.height))
            .and_then(|value| value.checked_mul(4))
            .is_none_or(|size| size > self.options.limits.max_decoded_bytes)
            || request
                .spec
                .aspect_ratio
                .split_once(':')
                .is_none_or(|(width, height)| {
                    width.parse::<u32>().ok().is_none_or(|value| value == 0)
                        || height.parse::<u32>().ok().is_none_or(|value| value == 0)
                })
            || request
                .spec
                .image_size
                .as_ref()
                .is_some_and(|size| size.trim().is_empty())
            || (paid
                && (!request.style.loras.is_empty()
                    || !request
                        .model
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))))
            || (!paid
                && self.provider.id() == ProviderId::StableDiffusionWebUi
                && (request.spec.steps == 0
                    || request.spec.sampler.is_empty()
                    || !request.spec.cfg_scale.is_finite()
                    || request.spec.cfg_scale <= 0.
                    || request
                        .spec
                        .checkpoint_hash
                        .as_ref()
                        .is_none_or(|value| value.is_empty())))
        {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        match request.billing {
            ImageBilling::Tokens { model }
                if paid && model.provider == ProviderId::Gemini && model.model == request.model =>
            {
                model.validate()?
            }
            ImageBilling::PerImage { micros } if !paid && *micros == 0 => {}
            _ => return Err(failure("E-AI-BUDGET")),
        }
        let maximum = request.billing.maximum()?;
        if paid && (!self.options.allow_paid || maximum == 0) {
            return Err(failure("E-AI-BUDGET"));
        }
        let attempts = self
            .options
            .max_regenerations
            .checked_add(1)
            .ok_or_else(|| failure("E-IMAGE-CONTRACT"))?;
        let mut issues = Vec::new();
        for attempt in 0..attempts {
            cancel.check()?;
            let (prompt, negative, seed) =
                request
                    .style
                    .prompt(request.channel, request.topic, attempt)?;
            let lora_bytes = request
                .style
                .loras
                .iter()
                .try_fold(0usize, |sum, lora| {
                    sum.checked_add(format!(" <lora:{}:{}>", lora.name, lora.weight).len())
                })
                .ok_or_else(|| failure("E-IMAGE-CONTRACT"))?;
            if prompt
                .len()
                .checked_add(negative.len())
                .and_then(|size| size.checked_add(lora_bytes))
                .is_none_or(|size| size > self.options.max_prompt_bytes)
            {
                return Err(failure("E-IMAGE-CONTRACT"));
            }
            let id = format!("{}:image:{}", request.request_id, attempt);
            let at = Timestamp::parse(&clock::now_utc_iso())?;
            let (max_input_tokens, max_output_tokens) = match request.billing {
                ImageBilling::Tokens { model } => (model.max_input_tokens, model.max_output_tokens),
                _ => (0, 0),
            };
            let reservation = AiCostReservation {
                channel_id: request.channel.clone(),
                request_id: id.clone(),
                day: UtcDay::from_timestamp(&at),
                daily_budget_micros: self.options.daily_budget_micros,
                max_cost_micros: Some(maximum),
                daily_token_budget: self.options.daily_token_budget,
                max_input_tokens,
                max_output_tokens,
                provider: crate::gateway::provider_name(self.provider.id()).into(),
                model: request.model.into(),
                at,
                project_id: request.project_id.clone(),
                job_id: request.job_id.clone(),
            };
            match request.billing {
                ImageBilling::Tokens { .. } => {
                    store.reserve_ai_cost(&reservation)?;
                }
                _ => {
                    store.reserve_ai_image_cost(&reservation, 1)?;
                }
            }
            let input = ImageInput {
                max_output_tokens: match request.billing {
                    ImageBilling::Tokens { model } => Some(model.max_output_tokens),
                    _ => None,
                },
                model: request.model,
                prompt: &prompt,
                negative: &negative,
                seed,
                spec: request.spec,
                loras: &request.style.loras,
            };
            let result = tokio::select! {biased;_=cancel.cancelled()=>Err(failure("E-AI-CANCELLED")),result=tokio::time::timeout(Duration::from_millis(self.options.timeout_ms),self.provider.generate(input))=>match result{Ok(Ok(value))=>Ok(value),Ok(Err(fault))=>{store.settle_ai_cost(request.channel,&id,&fault.cost_settlement())?;return Err(failure(fault.code()));},Err(_)=>Err(failure("E-AI-TIMEOUT"))}};
            let completion = match result {
                Ok(value) => value,
                Err(error) => {
                    store.settle_ai_cost(
                        request.channel,
                        &id,
                        &AiCostSettlement::Unknown {
                            error_code: error.code.clone(),
                        },
                    )?;
                    return Err(error);
                }
            };
            let settlement = match request.billing {
                ImageBilling::PerImage { micros } => AiCostSettlement::ImagesSucceeded {
                    actual_cost_micros: *micros,
                    images: 1,
                },
                ImageBilling::Tokens { model } => {
                    let Some(usage) = completion.usage else {
                        store.settle_ai_cost(
                            request.channel,
                            &id,
                            &AiCostSettlement::Unknown {
                                error_code: "E-AI-USAGE".into(),
                            },
                        )?;
                        return Err(failure("E-AI-USAGE"));
                    };
                    AiCostSettlement::Succeeded {
                        actual_cost_micros: u64::try_from(model.cost(usage)?)
                            .map_err(|_| failure("E-AI-BUDGET"))?,
                        input_tokens: usage.input_tokens,
                        output_tokens: usage.output_tokens,
                    }
                }
            };
            store.settle_ai_cost(request.channel, &id, &settlement)?;
            cancel.check()?;
            if completion.actual_seed.is_some_and(|actual| actual != seed)
                || completion.software_version.trim().is_empty()
            {
                return Err(failure("E-IMAGE-CONTRACT"));
            }
            self.options
                .limits
                .validate_images(std::slice::from_ref(&completion.image))?;
            let decoded = self.options.limits.decode(&completion.image)?;
            issues = Vec::new();
            if decoded.width() != request.spec.width || decoded.height() != request.spec.height {
                issues.push(ImageIssue::Dimensions);
            }
            let pixels = decoded.to_rgba8();
            let count = f64::from(pixels.width()) * f64::from(pixels.height());
            let mut sum = 0.;
            let mut squares = 0.;
            let mut visible = 0.;
            for pixel in pixels.pixels() {
                let luminance =
                    (f64::from(pixel[0]) + f64::from(pixel[1]) + f64::from(pixel[2])) / (3. * 255.);
                sum += luminance;
                squares += luminance * luminance;
                if pixel[3] > 0 {
                    visible += 1.;
                }
            }
            if squares / count - (sum / count).powi(2) < self.options.min_variance
                || visible / count < self.options.min_visible_fraction
            {
                issues.push(ImageIssue::DegeneratePixels);
            }
            if issues.is_empty() {
                let review_id = format!("{id}:review");
                let assessment = self
                    .inspector
                    .inspect(
                        store,
                        &completion.image,
                        ReviewContext {
                            channel: request.channel,
                            request_id: &review_id,
                            topic: request.topic,
                            settings_hash: request.settings_hash,
                            template_version: request.template_version,
                        },
                        cancel,
                    )
                    .await?;
                cancel.check()?;
                if assessment.text_score > 100
                    || assessment.anatomy_score > 100
                    || assessment.content_score > 100
                {
                    return Err(failure("E-IMAGE-CONTRACT"));
                }
                if assessment.text_score < self.options.min_text_score {
                    issues.push(ImageIssue::GarbledText);
                }
                if assessment.anatomy_score < self.options.min_anatomy_score {
                    issues.push(ImageIssue::Anatomy);
                }
                if assessment.content_score < self.options.min_content_score {
                    issues.push(ImageIssue::Unrelated);
                }
                match assessment.originality {
                    Originality::Clear => {}
                    Originality::Suspected => issues.push(ImageIssue::SimilarityRisk),
                    Originality::Uncertain => issues.push(ImageIssue::Uncertain),
                };
                if issues.is_empty() {
                    let request_hash=digest(&serde_json::to_vec(&json!({"channel":request.channel,"prompt":prompt,"negative":negative,"seed":seed,"spec":request.spec,"style":request.style,"settings_hash":request.settings_hash,"model":request.model})).map_err(|_|failure("E-IMAGE-CONTRACT"))?);
                    let provenance = ImageProvenance {
                        provider: self.provider.id(),
                        model: request.model.into(),
                        request_hash,
                        style_version: request.style.version,
                        requested_seed: seed,
                        actual_seed: completion.actual_seed,
                        software_version: completion.software_version,
                        at: Timestamp::parse(&clock::now_utc_iso())?,
                        settings_hash: request.settings_hash.into(),
                        template_version: request.template_version,
                        attempt,
                        image_sha256: digest(&completion.image.bytes),
                    };
                    return Ok(ImageOutcome::Ready {
                        image: completion.image,
                        assessment,
                        provenance,
                    });
                }
            }
            tracing::warn!(attempt,issues=?issues,"画像検査が不合格のため上限内で再生成します");
        }
        tracing::warn!(code="E-IMAGE-HOLD",attempts,issues=?issues,"画像検査の上限に達したため保留しました");
        Ok(ImageOutcome::Hold {
            code: "E-IMAGE-HOLD".into(),
            attempts,
            issues,
        })
    }
}

#[cfg(test)]
#[path = "image_tests.rs"]
mod tests;
