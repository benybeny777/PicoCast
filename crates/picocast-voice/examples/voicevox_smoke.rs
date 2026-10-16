//! 実行担当が明示起動する有限のローカル受入。辞書・モデルを取得しない。
use picocast_core::{
    clock::{self, Timestamp},
    fsutil, AppError, ChannelId, Result,
};
use picocast_voice::{
    CharacterStyles, CoreVoiceTransport, ReadingDictionary, ReadingMode, ReadingNormalizer,
    ReadingPolicy, SudachiAnalyzer, SudachiPaths, SynthesisRequest, VoiceMethod, VoiceRequest,
    VoiceTransport, Voicevox, VoicevoxSettings, WavePolicy,
};
use serde_json::json;
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Write,
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

fn invalid() -> AppError {
    AppError::new(
        "E-VOICE-CONFIG",
        "音声受入の引数が不正です",
        "voice-engine.md の明示引数と新しい出力先を確認してください",
    )
}
fn value<'a>(args: &'a BTreeMap<String, String>, key: &str) -> Result<&'a str> {
    args.get(key).map(String::as_str).ok_or_else(invalid)
}
fn number<T: std::str::FromStr>(args: &BTreeMap<String, String>, key: &str) -> Result<T> {
    value(args, key)?.parse().map_err(|_| invalid())
}
fn new_path(args: &BTreeMap<String, String>, key: &str) -> Result<PathBuf> {
    let path = PathBuf::from(value(args, key)?);
    if !path.is_absolute() || path.exists() {
        return Err(invalid());
    }
    Ok(path)
}
fn save_json(path: &Path, value: &serde_json::Value) -> Result<()> {
    let bytes = serde_json::to_vec_pretty(value).map_err(|_| invalid())?;
    let mut output = fsutil::new_file_writer(path)?;
    output.write_all(&bytes).map_err(|_| invalid())?;
    output.finish()
}

#[tokio::main]
async fn main() -> Result<()> {
    let mut values = std::env::args().skip(1);
    let mut args = BTreeMap::new();
    while let Some(name) = values.next() {
        let value = values.next().ok_or_else(invalid)?;
        if args.insert(name, value).is_some() {
            return Err(invalid());
        }
    }
    let required = BTreeSet::from([
        "--endpoint",
        "--channel",
        "--dictionary",
        "--resources-directory",
        "--configuration-file",
        "--text",
        "--speaker",
        "--speed",
        "--volume",
        "--tail-ms",
        "--timeout-ms",
        "--max-query-bytes",
        "--max-text-characters",
        "--max-wave-bytes",
        "--silence-threshold",
        "--minimum-noun-characters",
        "--output",
        "--report",
        "--log-root",
    ]);
    if args.keys().map(String::as_str).collect::<BTreeSet<_>>() != required {
        return Err(invalid());
    }
    let logging = picocast_core::logging::Logging::open(
        Path::new(value(&args, "--log-root")?),
        picocast_core::logging::Role::App,
        Arc::new(picocast_core::settings::Registry::new(
            picocast_core::logging::setting_definitions(),
        )?),
        picocast_core::logging::SecretRedactor::default(),
    )?;
    logging.install_global()?;
    let result = execute(args).await;
    if let Err(error) = &result {
        tracing::error!(code = error.code, "ローカル音声受入に失敗しました");
    }
    logging.shutdown()?;
    result
}

async fn execute(args: BTreeMap<String, String>) -> Result<()> {
    let output_path = new_path(&args, "--output")?;
    let report_path = new_path(&args, "--report")?;
    if output_path == report_path {
        return Err(invalid());
    }
    let channel = ChannelId::new(value(&args, "--channel")?)?;
    let dictionary_path = PathBuf::from(value(&args, "--dictionary")?);
    let analyzer = SudachiAnalyzer::open(&SudachiPaths {
        system_dictionary: dictionary_path.clone(),
        resources_directory: PathBuf::from(value(&args, "--resources-directory")?),
        configuration_file: PathBuf::from(value(&args, "--configuration-file")?),
    })?;
    let mut normalizer = ReadingNormalizer::new(
        channel.clone(),
        ReadingPolicy {
            mode: ReadingMode::SafeAuto,
            minimum_noun_characters: number(&args, "--minimum-noun-characters")?,
        },
        ReadingDictionary::default(),
        Some(analyzer),
    )?;
    let at = Timestamp::parse(&clock::now_utc_iso())?;
    let text = value(&args, "--text")?.to_owned();
    let reading = normalizer.normalize(&channel, std::slice::from_ref(&text), &at)?;
    let speech = reading.readings.get(&text).ok_or_else(invalid)?;
    let timeout = Duration::from_millis(number(&args, "--timeout-ms")?);
    let mut transport = CoreVoiceTransport::local(timeout)?;
    let endpoint = value(&args, "--endpoint")?.to_owned();
    let tail = Duration::from_millis(number(&args, "--tail-ms")?);
    let settings = VoicevoxSettings {
        endpoint,
        local_only: true,
        volume_scale: number(&args, "--volume")?,
        speed_scale: number(&args, "--speed")?,
        post_phoneme_length: tail,
        maximum_query_bytes: number(&args, "--max-query-bytes")?,
        maximum_text_characters: number(&args, "--max-text-characters")?,
        wave: WavePolicy {
            tail_silence: tail,
            silence_threshold: number(&args, "--silence-threshold")?,
            maximum_bytes: number(&args, "--max-wave-bytes")?,
        },
    };
    settings.validate()?;
    let mut version_url = reqwest::Url::parse(&settings.endpoint).map_err(|_| invalid())?;
    version_url.set_path("/version");
    let version = transport
        .send(VoiceRequest {
            method: VoiceMethod::Get,
            url: version_url.into(),
            body: None,
            maximum_response_bytes: settings.maximum_query_bytes,
        })
        .await?;
    if version.status != 200 {
        return Err(invalid());
    }
    let version: serde_json::Value =
        serde_json::from_slice(&version.body).map_err(|_| invalid())?;
    let speaker = number(&args, "--speaker")?;
    let character = CharacterStyles {
        character_id: "smoke-fixture".into(),
        normal_style: speaker,
        emotion_styles: BTreeMap::new(),
        available_styles: BTreeSet::from([speaker]),
    };
    let mut voice = Voicevox::new(channel.clone(), settings, transport)?;
    let result = voice
        .synthesize(SynthesisRequest {
            channel_id: &channel,
            text: speech,
            character: &character,
            emotion: None,
            accent: None,
        })
        .await?;
    let mut output = fsutil::new_file_writer(&output_path)?;
    output
        .write_all(&result.audio.bytes)
        .map_err(|_| invalid())?;
    output.finish()?;
    save_json(
        &report_path,
        &json!({"at":at,"engine_version":version,"sudachi_version":"0.6.11",
        "dictionary":dictionary_path,"runtime_python":false,"channel_id":channel,"style_id":result.style_id,
        "sample_rate":result.audio.sample_rate,"channels":result.audio.channels,"frames":result.audio.frames,
        "duration_seconds":result.audio.duration_seconds(),"trailing_silent_frames":result.audio.trailing_silent_frames,
        "tail_silence_seconds":result.audio.trailing_silent_frames as f64 / f64::from(result.audio.sample_rate),
        "output":output_path,"byte_count":result.audio.bytes.len(),"real_acceptance":true}),
    )
}
