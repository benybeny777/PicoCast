//! Gemini native画像と、利用者が起動したローカルSD WebUIのwire契約。
use crate::{
    failure,
    image::{ImageCompletion, ImageInput, ImageProvider, InlineImage},
    FaultKind, FutureResult, HttpMethod, ProviderFault, ProviderId, ProviderResult, Secret,
    Transport, TransportRequest, GEMINI_ENDPOINT,
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use picocast_core::{ChannelId, Result};
use serde_json::{json, Value};
use zeroize::Zeroizing;

pub struct ImageProviderContract<T> {
    channel: ChannelId,
    id: ProviderId,
    base: String,
    secret: Option<Secret>,
    transport: T,
    max_image_bytes: usize,
}
impl<T: Transport> ImageProviderContract<T> {
    pub fn new(
        channel: ChannelId,
        id: ProviderId,
        endpoint: &str,
        secret: Option<Secret>,
        transport: T,
        max_image_bytes: usize,
    ) -> Result<Self> {
        let url = reqwest::Url::parse(endpoint).map_err(|_| failure("E-IMAGE-CONTRACT"))?;
        let valid = match id {
            ProviderId::Gemini => endpoint == GEMINI_ENDPOINT && secret.is_some(),
            ProviderId::StableDiffusionWebUi => {
                url.scheme() == "http"
                    && matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"))
                    && url.path() == "/"
                    && secret.is_none()
            }
            _ => false,
        };
        if !valid
            || max_image_bytes == 0
            || url.query().is_some()
            || url.fragment().is_some()
            || !url.username().is_empty()
            || url.password().is_some()
        {
            return Err(failure("E-IMAGE-CONTRACT"));
        }
        Ok(Self {
            channel,
            id,
            base: endpoint.trim_end_matches('/').into(),
            secret,
            transport,
            max_image_bytes,
        })
    }
    pub fn into_transport(self) -> T {
        self.transport
    }
    async fn local_catalog(&mut self, path: &str) -> ProviderResult<Value> {
        let response = self
            .transport
            .send(TransportRequest {
                method: HttpMethod::Get,
                url: format!("{}{path}", self.base),
                headers: Vec::new(),
                body: None,
            })
            .await?;
        if response.status != 200 {
            return Err(ProviderFault {
                kind: FaultKind::Http(response.status),
                retry_after: response.retry_after,
            });
        }
        Ok(response.body)
    }
    async fn validate_local(&mut self, input: &ImageInput<'_>) -> ProviderResult<()> {
        let expected = input
            .spec
            .checkpoint_hash
            .as_deref()
            .filter(|value| !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_hexdigit()))
            .ok_or_else(ProviderFault::contract)?;
        let models = self.local_catalog("/sdapi/v1/sd-models").await?;
        if !models
            .as_array()
            .ok_or_else(ProviderFault::contract)?
            .iter()
            .any(|model| {
                (model["title"] == input.model || model["model_name"] == input.model)
                    && model["hash"] == expected
            })
        {
            return Err(ProviderFault::contract());
        }
        let samplers = self.local_catalog("/sdapi/v1/samplers").await?;
        if !samplers
            .as_array()
            .ok_or_else(ProviderFault::contract)?
            .iter()
            .any(|sampler| sampler["name"] == input.spec.sampler)
        {
            return Err(ProviderFault::contract());
        }
        if !input.loras.is_empty() {
            let loras = self.local_catalog("/sdapi/v1/loras").await?;
            let loras = loras.as_array().ok_or_else(ProviderFault::contract)?;
            if input
                .loras
                .iter()
                .any(|requested| !loras.iter().any(|lora| lora["name"] == requested.name))
            {
                return Err(ProviderFault::contract());
            }
        }
        Ok(())
    }
    fn request(&self, input: &ImageInput<'_>) -> ProviderResult<TransportRequest> {
        if input.model.is_empty()
            || input.spec.width == 0
            || input.spec.height == 0
            || input.seed > i32::MAX as u64
        {
            return Err(ProviderFault::contract());
        }
        let (path, body, headers) = match self.id {
            ProviderId::Gemini => {
                let max_output_tokens = input
                    .max_output_tokens
                    .filter(|value| *value > 0)
                    .ok_or_else(ProviderFault::contract)?;
                if !input
                    .model
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))
                    || !input.loras.is_empty()
                    || input.spec.aspect_ratio.is_empty()
                {
                    return Err(ProviderFault::contract());
                }
                let mut format = json!({"aspectRatio":input.spec.aspect_ratio});
                if let Some(size) = &input.spec.image_size {
                    format["imageSize"] = json!(size);
                }
                (
                    format!("/models/{}:generateContent", input.model),
                    json!({"contents":[{"role":"user","parts":[{"text":format!("{}\n避ける要素:{}",input.prompt,input.negative)}]}],"generationConfig":{"maxOutputTokens":max_output_tokens,"responseModalities":["IMAGE"],"responseFormat":{"image":format},"seed":input.seed}}),
                    vec![(
                        "x-goog-api-key".into(),
                        Zeroizing::new(
                            self.secret
                                .as_ref()
                                .ok_or_else(ProviderFault::contract)?
                                .expose()
                                .to_owned(),
                        ),
                    )],
                )
            }
            ProviderId::StableDiffusionWebUi => {
                if input.spec.steps == 0
                    || input.spec.sampler.is_empty()
                    || !input.spec.cfg_scale.is_finite()
                    || input.spec.cfg_scale <= 0.
                {
                    return Err(ProviderFault::contract());
                }
                let mut prompt = input.prompt.to_owned();
                for lora in input.loras {
                    if !lora.original_use_confirmed
                        || lora.name.is_empty()
                        || !lora
                            .name
                            .bytes()
                            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))
                        || !lora.weight.is_finite()
                    {
                        return Err(ProviderFault::contract());
                    }
                    prompt.push_str(&format!(" <lora:{}:{}>", lora.name, lora.weight));
                }
                (
                    "/sdapi/v1/txt2img".into(),
                    json!({"prompt":prompt,"negative_prompt":input.negative,"seed":input.seed,"width":input.spec.width,"height":input.spec.height,"steps":input.spec.steps,"sampler_name":input.spec.sampler,"cfg_scale":input.spec.cfg_scale,"batch_size":1,"n_iter":1,"send_images":true,"save_images":false,"do_not_save_samples":true,"do_not_save_grid":true,"override_settings":{"sd_model_checkpoint":input.model},"override_settings_restore_afterwards":true}),
                    Vec::new(),
                )
            }
            _ => return Err(ProviderFault::contract()),
        };
        Ok(TransportRequest {
            method: HttpMethod::Post,
            url: format!("{}{path}", self.base),
            headers,
            body: Some(body),
        })
    }
    fn decode(&self, body: Value, input: &ImageInput<'_>) -> ProviderResult<ImageCompletion> {
        let (encoded, mime, usage, actual_seed, version) = match self.id {
            ProviderId::Gemini => {
                if body
                    .get("promptFeedback")
                    .and_then(|value| value.get("blockReason"))
                    .is_some()
                {
                    return Err(ProviderFault::contract());
                }
                let candidates = body["candidates"]
                    .as_array()
                    .filter(|values| values.len() == 1)
                    .ok_or_else(ProviderFault::contract)?;
                let candidate = &candidates[0];
                if candidate["finishReason"] != "STOP" {
                    return Err(ProviderFault::contract());
                }
                let parts = candidate["content"]["parts"]
                    .as_array()
                    .ok_or_else(ProviderFault::contract)?;
                let images = parts
                    .iter()
                    .filter(|part| part["thought"] != true)
                    .filter_map(|part| part.get("inlineData"))
                    .collect::<Vec<_>>();
                let image = match images.as_slice() {
                    [one] => *one,
                    _ => return Err(ProviderFault::contract()),
                };
                let usage = crate::provider::gemini_usage(&body).ok();
                (
                    image["data"].as_str().ok_or_else(ProviderFault::contract)?,
                    image["mimeType"]
                        .as_str()
                        .ok_or_else(ProviderFault::contract)?,
                    usage,
                    None,
                    body["modelVersion"]
                        .as_str()
                        .filter(|value| !value.is_empty())
                        .ok_or_else(ProviderFault::contract)?
                        .to_owned(),
                )
            }
            ProviderId::StableDiffusionWebUi => {
                let images = body["images"]
                    .as_array()
                    .filter(|values| values.len() == 1)
                    .ok_or_else(ProviderFault::contract)?;
                let info: Value = serde_json::from_str(
                    body["info"].as_str().ok_or_else(ProviderFault::contract)?,
                )
                .map_err(|_| ProviderFault::contract())?;
                let actual = info["seed"]
                    .as_u64()
                    .filter(|actual| *actual == input.seed)
                    .ok_or_else(ProviderFault::contract)?;
                if info["sd_model_hash"].as_str() != input.spec.checkpoint_hash.as_deref()
                    || info["sampler_name"] != input.spec.sampler
                {
                    return Err(ProviderFault::contract());
                }
                let version = info["version"]
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(ProviderFault::contract)?
                    .to_owned();
                (
                    images[0].as_str().ok_or_else(ProviderFault::contract)?,
                    "image/png",
                    None,
                    Some(actual),
                    version,
                )
            }
            _ => return Err(ProviderFault::contract()),
        };
        let max_encoded = self
            .max_image_bytes
            .checked_add(2)
            .and_then(|value| value.checked_div(3))
            .and_then(|value| value.checked_mul(4))
            .ok_or_else(ProviderFault::contract)?;
        if encoded.len() > max_encoded || !matches!(mime, "image/png" | "image/jpeg") {
            return Err(ProviderFault::contract());
        }
        let bytes = STANDARD
            .decode(encoded)
            .map_err(|_| ProviderFault::contract())?;
        if version.is_empty()
            || !version
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"-_.+ ".contains(&byte))
            || bytes.is_empty()
            || bytes.len() > self.max_image_bytes
            || self
                .secret
                .as_ref()
                .is_some_and(|secret| version.contains(secret.expose()))
        {
            return Err(ProviderFault::contract());
        }
        let mime = if self.id == ProviderId::StableDiffusionWebUi {
            match image::guess_format(&bytes).map_err(|_| ProviderFault::contract())? {
                image::ImageFormat::Png => "image/png",
                image::ImageFormat::Jpeg => "image/jpeg",
                _ => return Err(ProviderFault::contract()),
            }
        } else {
            mime
        };
        Ok(ImageCompletion {
            image: InlineImage {
                mime: mime.into(),
                bytes,
            },
            usage,
            actual_seed,
            software_version: version,
        })
    }
}
impl<T: Transport> ImageProvider for ImageProviderContract<T> {
    fn channel_id(&self) -> &ChannelId {
        &self.channel
    }
    fn id(&self) -> ProviderId {
        self.id
    }
    fn generate<'a>(
        &'a mut self,
        input: ImageInput<'a>,
    ) -> FutureResult<'a, ProviderResult<ImageCompletion>> {
        Box::pin(async move {
            if self.id == ProviderId::StableDiffusionWebUi {
                self.validate_local(&input).await?;
            }
            let request = self.request(&input)?;
            let response = self.transport.send(request).await?;
            if response.status != 200 {
                tracing::error!(provider=?self.id,status=response.status,stage="image_generation_response","画像サービスが要求を拒否しました");
                return Err(ProviderFault {
                    kind: FaultKind::Http(response.status),
                    retry_after: response.retry_after,
                });
            }
            self.decode(response.body, &input).inspect_err(|fault|{tracing::error!(provider=?self.id,stage="image_wire_decode",cause_code=fault.code(),"画像応答の契約を検証できませんでした");})
        })
    }
}
