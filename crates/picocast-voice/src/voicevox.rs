use crate::{ensure_trailing_silence, failure, WaveAudio, WavePolicy};
use picocast_core::{fsutil, http, ChannelId, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    future::Future,
    path::Path,
    pin::Pin,
    time::Duration,
};

pub type VoiceFuture<'a, T> = Pin<Box<dyn Future<Output = Result<T>> + Send + 'a>>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VoiceMethod {
    Get,
    Post,
}

/// 要求本文・台詞を Debug/log に出さない。
pub struct VoiceRequest {
    pub method: VoiceMethod,
    pub url: String,
    pub body: Option<Value>,
    pub maximum_response_bytes: usize,
}
pub struct VoiceResponse {
    pub status: u16,
    pub body: Vec<u8>,
}

pub trait VoiceTransport {
    fn send<'a>(&'a mut self, request: VoiceRequest) -> VoiceFuture<'a, VoiceResponse>;
}

pub struct CoreVoiceTransport {
    client: http::Client,
}
impl CoreVoiceTransport {
    pub fn new(timeout: Duration) -> Result<Self> {
        Ok(Self {
            client: http::client(timeout)?,
        })
    }
    pub fn local(timeout: Duration) -> Result<Self> {
        Ok(Self {
            client: http::local_client(timeout)?,
        })
    }
}
impl VoiceTransport for CoreVoiceTransport {
    fn send<'a>(&'a mut self, request: VoiceRequest) -> VoiceFuture<'a, VoiceResponse> {
        Box::pin(async move {
            let method = match request.method {
                VoiceMethod::Get => reqwest::Method::GET,
                VoiceMethod::Post => reqwest::Method::POST,
            };
            let response = http::request_bytes(
                &self.client,
                method,
                &request.url,
                &[],
                request.body.as_ref(),
                request.maximum_response_bytes,
            )
            .await?;
            Ok(VoiceResponse {
                status: response.status,
                body: response.body,
            })
        })
    }
}

#[derive(Clone)]
pub struct VoicevoxSettings {
    pub endpoint: String,
    pub local_only: bool,
    pub volume_scale: f64,
    pub speed_scale: f64,
    pub post_phoneme_length: Duration,
    pub maximum_query_bytes: usize,
    pub maximum_text_characters: usize,
    pub wave: WavePolicy,
}

impl VoicevoxSettings {
    pub fn validate(&self) -> Result<()> {
        let endpoint =
            reqwest::Url::parse(&self.endpoint).map_err(|_| failure("E-VOICE-CONFIG"))?;
        if !matches!(endpoint.scheme(), "http" | "https")
            || endpoint.host_str().is_none()
            || !endpoint.username().is_empty()
            || endpoint.password().is_some()
            || endpoint.query().is_some()
            || endpoint.fragment().is_some()
            || endpoint.path() != "/"
            || self.maximum_query_bytes == 0
            || self.maximum_text_characters == 0
            || !self.volume_scale.is_finite()
            || self.volume_scale < 0.0
            || !self.speed_scale.is_finite()
            || self.speed_scale <= 0.0
            || self.post_phoneme_length.is_zero()
            || self.wave.tail_silence.is_zero()
            || self.wave.silence_threshold < 0
            || self.wave.maximum_bytes == 0
        {
            return Err(failure("E-VOICE-CONFIG"));
        }
        if self.local_only && !matches!(endpoint.host_str(), Some("127.0.0.1" | "[::1]" | "::1")) {
            return Err(failure("E-VOICE-CONFIG"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CharacterStyles {
    pub character_id: String,
    pub normal_style: u32,
    pub emotion_styles: BTreeMap<String, u32>,
    pub available_styles: BTreeSet<u32>,
}
impl CharacterStyles {
    pub fn select(&self, emotion: Option<&str>) -> Result<u32> {
        if self.character_id.trim().is_empty()
            || !self.available_styles.contains(&self.normal_style)
        {
            return Err(failure("E-VOICE-STYLE"));
        }
        let selected = match emotion {
            None => self.normal_style,
            Some(name) => *self
                .emotion_styles
                .get(name)
                .ok_or_else(|| failure("E-VOICE-STYLE"))?,
        };
        if !self.available_styles.contains(&selected) {
            return Err(failure("E-VOICE-STYLE"));
        }
        Ok(selected)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AccentOverride {
    pub phrase_index: usize,
    pub accent: usize,
}

/// reading_entries.accent_json に保存できる版付きの上書き。
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct AccentPlan {
    pub version: u32,
    pub overrides: Vec<AccentOverride>,
}
impl AccentPlan {
    pub fn from_json(value: &Value) -> Result<Self> {
        let plan: Self =
            serde_json::from_value(value.clone()).map_err(|_| failure("E-VOICE-ACCENT"))?;
        if plan.version != 1 {
            return Err(failure("E-VOICE-ACCENT"));
        }
        Ok(plan)
    }
    pub fn load_entry(
        store: &picocast_store::Store,
        surface: &str,
        source: &str,
    ) -> Result<Option<Self>> {
        let key = picocast_store::repository::ReadingEntryKey {
            surface: surface.to_owned(),
            source: source.to_owned(),
        };
        let entry = store
            .global_repository()
            .get::<picocast_store::repository::ReadingEntry>(&key)?
            .ok_or_else(|| failure("E-VOICE-DICTIONARY"))?;
        if entry.accent_json.is_null() {
            return Ok(None);
        }
        Self::from_json(&entry.accent_json).map(Some)
    }
    pub fn save_entry(
        &self,
        store: &picocast_store::Store,
        surface: &str,
        source: &str,
        at: &picocast_core::clock::Timestamp,
    ) -> Result<()> {
        if self.version != 1 {
            return Err(failure("E-VOICE-ACCENT"));
        }
        let key = picocast_store::repository::ReadingEntryKey {
            surface: surface.to_owned(),
            source: source.to_owned(),
        };
        let mut entry = store
            .global_repository()
            .get::<picocast_store::repository::ReadingEntry>(&key)?
            .ok_or_else(|| failure("E-VOICE-DICTIONARY"))?;
        entry.accent_json = serde_json::to_value(self).map_err(|_| failure("E-VOICE-ACCENT"))?;
        entry.updated_at = at.clone();
        store.global_repository().save(&entry)
    }
}

pub struct SynthesisRequest<'a> {
    pub channel_id: &'a ChannelId,
    pub text: &'a str,
    pub character: &'a CharacterStyles,
    pub emotion: Option<&'a str>,
    pub accent: Option<&'a AccentPlan>,
}

pub struct SynthesisResult {
    pub channel_id: ChannelId,
    pub style_id: u32,
    pub query: Value,
    pub kana: String,
    pub audio: WaveAudio,
}
impl SynthesisResult {
    pub fn save_new(&self, path: &Path) -> Result<()> {
        fsutil::atomic_write_new(path, &self.audio.bytes)
    }
}

pub struct Voicevox<T> {
    channel: ChannelId,
    settings: VoicevoxSettings,
    transport: T,
}
impl<T: VoiceTransport> Voicevox<T> {
    pub fn new(channel: ChannelId, settings: VoicevoxSettings, transport: T) -> Result<Self> {
        settings.validate()?;
        Ok(Self {
            channel,
            settings,
            transport,
        })
    }
    pub fn into_transport(self) -> T {
        self.transport
    }

    fn url(&self, path: &str, parameters: &[(&str, String)]) -> Result<String> {
        let mut url =
            reqwest::Url::parse(&self.settings.endpoint).map_err(|_| failure("E-VOICE-CONFIG"))?;
        url.set_path(path);
        for (key, value) in parameters {
            url.query_pairs_mut().append_pair(key, value);
        }
        Ok(url.into())
    }

    async fn call(&mut self, request: VoiceRequest) -> Result<Vec<u8>> {
        let maximum = request.maximum_response_bytes;
        let response = self.transport.send(request).await?;
        if response.status != 200 {
            return Err(failure("E-VOICE-ENGINE"));
        }
        if response.body.len() > maximum {
            return Err(failure("E-VOICE-ENGINE"));
        }
        Ok(response.body)
    }

    pub async fn synthesize(&mut self, request: SynthesisRequest<'_>) -> Result<SynthesisResult> {
        if request.channel_id != &self.channel {
            return Err(failure("E-VOICE-CHANNEL"));
        }
        if request.text.trim().is_empty()
            || request.text.chars().count() > self.settings.maximum_text_characters
            || request.text.contains('\0')
        {
            return Err(failure("E-VOICE-READING"));
        }
        let style = request.character.select(request.emotion)?;
        let parameters = [("speaker", style.to_string())];
        let url = self.url(
            "/audio_query",
            &[
                ("text", request.text.to_owned()),
                ("speaker", style.to_string()),
            ],
        )?;
        let bytes = self
            .call(VoiceRequest {
                method: VoiceMethod::Post,
                url,
                body: None,
                maximum_response_bytes: self.settings.maximum_query_bytes,
            })
            .await?;
        let mut query: Value =
            serde_json::from_slice(&bytes).map_err(|_| failure("E-VOICE-ENGINE"))?;
        validate_query(&query)?;
        let object = query
            .as_object_mut()
            .ok_or_else(|| failure("E-VOICE-ENGINE"))?;
        object.insert(
            "volumeScale".into(),
            Value::from(self.settings.volume_scale),
        );
        object.insert("speedScale".into(), Value::from(self.settings.speed_scale));
        object.insert(
            "postPhonemeLength".into(),
            Value::from(self.settings.post_phoneme_length.as_secs_f64()),
        );
        if let Some(plan) = request.accent {
            apply_accents(&mut query, plan)?;
            let url = self.url("/mora_data", &parameters)?;
            let bytes = self
                .call(VoiceRequest {
                    method: VoiceMethod::Post,
                    url,
                    body: Some(query["accent_phrases"].clone()),
                    maximum_response_bytes: self.settings.maximum_query_bytes,
                })
                .await?;
            let phrases: Value =
                serde_json::from_slice(&bytes).map_err(|_| failure("E-VOICE-ACCENT"))?;
            if phrases.as_array().map(Vec::len) != query["accent_phrases"].as_array().map(Vec::len)
            {
                return Err(failure("E-VOICE-ACCENT"));
            }
            query["accent_phrases"] = phrases;
            validate_query(&query)?;
            // エンジンが上書きを受理したことも確認し、編集を無言で捨てない。
            for change in &plan.overrides {
                if query["accent_phrases"][change.phrase_index]["accent"].as_u64()
                    != Some(change.accent as u64)
                {
                    return Err(failure("E-VOICE-ACCENT"));
                }
            }
        }
        let kana = query
            .get("kana")
            .and_then(Value::as_str)
            .ok_or_else(|| failure("E-VOICE-ENGINE"))?
            .to_owned();
        let rate = query["outputSamplingRate"]
            .as_u64()
            .ok_or_else(|| failure("E-VOICE-ENGINE"))?;
        let channels = if query["outputStereo"]
            .as_bool()
            .ok_or_else(|| failure("E-VOICE-ENGINE"))?
        {
            2
        } else {
            1
        };
        let url = self.url("/synthesis", &parameters)?;
        let bytes = self
            .call(VoiceRequest {
                method: VoiceMethod::Post,
                url,
                body: Some(query.clone()),
                maximum_response_bytes: self.settings.wave.maximum_bytes,
            })
            .await?;
        let audio = ensure_trailing_silence(&bytes, &self.settings.wave)?;
        if u64::from(audio.sample_rate) != rate || audio.channels != channels {
            return Err(failure("E-VOICE-AUDIO"));
        }
        Ok(SynthesisResult {
            channel_id: self.channel.clone(),
            style_id: style,
            query,
            kana,
            audio,
        })
    }
}

fn validate_query(query: &Value) -> Result<()> {
    let phrases = query
        .get("accent_phrases")
        .and_then(Value::as_array)
        .ok_or_else(|| failure("E-VOICE-ENGINE"))?;
    if phrases.is_empty()
        || query.get("kana").and_then(Value::as_str).is_none()
        || query
            .get("outputSamplingRate")
            .and_then(Value::as_u64)
            .is_none_or(|rate| rate == 0 || rate > u64::from(u32::MAX))
        || query.get("outputStereo").and_then(Value::as_bool).is_none()
    {
        return Err(failure("E-VOICE-ENGINE"));
    }
    for phrase in phrases {
        let moras = phrase
            .get("moras")
            .and_then(Value::as_array)
            .ok_or_else(|| failure("E-VOICE-ENGINE"))?;
        if moras.is_empty()
            || phrase
                .get("accent")
                .and_then(Value::as_u64)
                .is_none_or(|accent| accent == 0 || accent > moras.len() as u64)
        {
            return Err(failure("E-VOICE-ACCENT"));
        }
    }
    Ok(())
}

pub(crate) fn apply_accents(query: &mut Value, plan: &AccentPlan) -> Result<()> {
    if plan.version != 1 {
        return Err(failure("E-VOICE-ACCENT"));
    }
    let phrases = query
        .get_mut("accent_phrases")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| failure("E-VOICE-ACCENT"))?;
    let mut seen = BTreeSet::new();
    for change in &plan.overrides {
        if !seen.insert(change.phrase_index) {
            return Err(failure("E-VOICE-ACCENT"));
        }
        let phrase = phrases
            .get_mut(change.phrase_index)
            .ok_or_else(|| failure("E-VOICE-ACCENT"))?;
        let length = phrase["moras"]
            .as_array()
            .ok_or_else(|| failure("E-VOICE-ACCENT"))?
            .len();
        if change.accent == 0 || change.accent > length {
            return Err(failure("E-VOICE-ACCENT"));
        }
        phrase
            .as_object_mut()
            .ok_or_else(|| failure("E-VOICE-ACCENT"))?
            .insert("accent".into(), Value::from(change.accent));
    }
    Ok(())
}
