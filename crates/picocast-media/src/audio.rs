//! 計測した音声だけを、来歴と一緒に排他的に公開する音声mix。
use picocast_core::{
    clock::{self, Timestamp},
    fsutil, proc, AppError, ChannelId, Result,
};
use serde::{Deserialize, Serialize};
use std::{
    ffi::OsString,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::sync::watch;

#[track_caller]
fn failure() -> AppError {
    let location = std::panic::Location::caller();
    tracing::error!(
        source = location.file(),
        line = location.line(),
        code = "E-AUDIO-MIX",
        "音声mixの入力・計測・公開条件が成立しません"
    );
    AppError::new(
        "E-AUDIO-MIX",
        "音声ミックスまたは音量の検証に失敗しました。",
        "音源・ffmpeg設定・測定結果を確認し、新しい出力先で再実行してください。",
    )
}
fn cancelled() -> AppError {
    tracing::warn!(code = "E-AUDIO-CANCELLED", "音声mixを中断しました");
    AppError::new(
        "E-AUDIO-CANCELLED",
        "音声ミックスを中断しました。",
        "再開する場合は新しい出力先で実行してください。",
    )
}

#[derive(Debug, Clone)]
pub struct MediaTools {
    pub ffmpeg: PathBuf,
    pub ffprobe: PathBuf,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AudioRunLimits {
    pub timeout_ms: u64,
    pub max_output_bytes: usize,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DuckingOptions {
    pub threshold: f64,
    pub ratio: f64,
    pub attack_ms: f64,
    pub release_ms: f64,
    pub voice_gain: f64,
    pub bgm_gain: f64,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AudioMixOptions {
    pub sample_rate: u32,
    pub channels: u16,
    pub target_lufs: f64,
    pub true_peak_dbtp: f64,
    pub true_peak_headroom_db: f64,
    pub loudness_range_lu: f64,
    pub integrated_tolerance_lu: f64,
    pub linear_normalization: bool,
    pub duration_tolerance_ms: u64,
    pub max_clips: usize,
    pub max_duration_ms: u64,
    pub max_filter_bytes: usize,
    pub filter_threads: u32,
    pub encoding_threads: u32,
    pub ducking: DuckingOptions,
    pub run: AudioRunLimits,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PauseProfile {
    pub genre: String,
    pub base_ms: u64,
    pub comma_ms: u64,
    pub terminal_ms: u64,
    pub newline_ms: u64,
    pub speaker_change_ms: u64,
}
#[derive(Debug, Clone)]
pub struct SpokenClip {
    pub path: PathBuf,
    pub speaker_id: String,
    pub text: String,
    pub duration_ms: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClipTimeline {
    pub index: usize,
    pub speaker_id: String,
    pub start_ms: u64,
    pub end_ms: u64,
    pub pause_after_ms: u64,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Measurement {
    pub integrated_lufs: f64,
    pub true_peak_dbtp: f64,
    pub loudness_range_lu: f64,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoudnormStats {
    pub input_i: f64,
    pub input_tp: f64,
    pub input_lra: f64,
    pub input_thresh: f64,
    pub target_offset: f64,
    pub normalization_type: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolProvenance {
    pub ffmpeg_version: String,
    pub ffprobe_version: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioReport {
    pub schema_version: u32,
    pub channel_id: ChannelId,
    pub at: Timestamp,
    pub tools: ToolProvenance,
    pub options: AudioMixOptions,
    pub pause_profile: PauseProfile,
    pub timeline: Vec<ClipTimeline>,
    pub duration_ms: u64,
    pub has_bgm: bool,
    pub first_pass: LoudnormStats,
    pub second_pass: LoudnormStats,
    pub measured: Measurement,
}
pub struct AudioOutput {
    pub audio_path: PathBuf,
    pub report_path: PathBuf,
    pub report: AudioReport,
}

impl AudioMixOptions {
    pub fn validate(&self) -> Result<()> {
        let d = &self.ducking;
        if !(8000..=192000).contains(&self.sample_rate)
            || !matches!(self.channels, 1 | 2)
            || !finite_in(self.target_lufs, -70., -5.)
            || !finite_in(self.true_peak_dbtp, -9., 0.)
            || !finite_in(self.true_peak_headroom_db, 0., 8.)
            || self.true_peak_dbtp - self.true_peak_headroom_db < -9.
            || !finite_in(self.loudness_range_lu, 1., 50.)
            || !finite_in(self.integrated_tolerance_lu, 0., 1.)
            || self.max_clips == 0
            || self.max_duration_ms == 0
            || self.max_filter_bytes == 0
            || self.filter_threads == 0
            || self.encoding_threads == 0
            || self.run.timeout_ms == 0
            || self.run.max_output_bytes == 0
            || !finite_in(d.threshold, 0.00097563, 1.)
            || !finite_in(d.ratio, 1., 20.)
            || !finite_in(d.attack_ms, 0.01, 2000.)
            || !finite_in(d.release_ms, 0.01, 9000.)
            || !finite_in(d.voice_gain, 0.000001, 64.)
            || !finite_in(d.bgm_gain, 0., 64.)
        {
            return Err(failure());
        }
        Ok(())
    }
}
fn finite_in(value: f64, min: f64, max: f64) -> bool {
    value.is_finite() && (min..=max).contains(&value)
}
fn regular(path: &Path) -> Result<()> {
    if !path.is_absolute() {
        return Err(failure());
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|_| failure())?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(failure());
    }
    Ok(())
}
fn check(cancel: &watch::Receiver<bool>) -> Result<()> {
    if *cancel.borrow() {
        Err(cancelled())
    } else {
        Ok(())
    }
}
async fn run(
    tool: &Path,
    args: Vec<OsString>,
    limits: &AudioRunLimits,
    cancel: &mut watch::Receiver<bool>,
) -> Result<std::process::Output> {
    check(cancel)?;
    regular(tool)?;
    let operation = proc::run(
        tool,
        &args,
        proc::RunOptions {
            timeout: Duration::from_millis(limits.timeout_ms),
            max_output_bytes: limits.max_output_bytes,
        },
    );
    tokio::pin!(operation);
    loop {
        tokio::select! {result=&mut operation=>{check(cancel)?;return result;},changed=cancel.changed()=>{
            if changed.is_err()||*cancel.borrow(){return Err(cancelled());}
        }}
    }
}
fn args(values: &[&str]) -> Vec<OsString> {
    values.iter().map(OsString::from).collect()
}
fn sec(ms: u64) -> String {
    format!("{}.{:03}", ms / 1000, ms % 1000)
}

pub fn pause_after(text: &str, speaker_change: bool, profile: &PauseProfile) -> Result<u64> {
    if profile.genre.trim().is_empty() {
        return Err(failure());
    }
    let punctuation = if text.ends_with(['\n', '\r']) {
        profile.newline_ms
    } else {
        match text
            .trim_end()
            .trim_end_matches(['」', '』', '）', ')', ']', '】', '"', '\''])
            .chars()
            .last()
        {
            Some('、' | ',' | '，' | ';' | '；') => profile.comma_ms,
            Some('。' | '.' | '！' | '!' | '？' | '?') => profile.terminal_ms,
            _ => 0,
        }
    };
    profile
        .base_ms
        .checked_add(punctuation)
        .and_then(|value| {
            value.checked_add(if speaker_change {
                profile.speaker_change_ms
            } else {
                0
            })
        })
        .ok_or_else(failure)
}

/// 句読点の内側の間も必要な場合は、合成前にこの単位へ分割して各音声を作る。
pub fn phrases(text: &str) -> Vec<String> {
    let mut output: Vec<String> = Vec::new();
    let mut current = String::new();
    let mut characters = text.chars().peekable();
    let mut previous = None;
    while let Some(character) = characters.next() {
        if current.is_empty() && matches!(character, '」' | '』' | '）' | ')' | ']' | '】') {
            if let Some(last) = output.last_mut() {
                last.push(character);
                previous = Some(character);
                continue;
            }
        }
        current.push(character);
        let numeric_separator = matches!(character, '.' | ',')
            && previous.is_some_and(|value: char| value.is_ascii_digit())
            && characters.peek().is_some_and(char::is_ascii_digit);
        if !numeric_separator
            && matches!(
                character,
                '、' | ',' | '，' | ';' | '；' | '。' | '.' | '！' | '!' | '？' | '?' | '\n'
            )
        {
            if !current.trim().is_empty() {
                output.push(std::mem::take(&mut current));
            } else {
                if let Some(last) = output.last_mut() {
                    last.push_str(&current);
                }
                current.clear();
            }
        }
        previous = Some(character);
    }
    if !current.trim().is_empty() {
        output.push(current);
    }
    output
}
pub fn timeline(
    clips: &[SpokenClip],
    profile: &PauseProfile,
    options: &AudioMixOptions,
) -> Result<Vec<ClipTimeline>> {
    options.validate()?;
    if clips.is_empty() || clips.len() > options.max_clips {
        return Err(failure());
    }
    let mut result = Vec::new();
    let mut cursor = 0u64;
    for (index, clip) in clips.iter().enumerate() {
        if clip.duration_ms == 0 || clip.speaker_id.is_empty() || clip.text.trim().is_empty() {
            return Err(failure());
        }
        let end = cursor.checked_add(clip.duration_ms).ok_or_else(failure)?;
        let pause = pause_after(
            &clip.text,
            clips
                .get(index + 1)
                .is_some_and(|next| next.speaker_id != clip.speaker_id),
            profile,
        )?;
        result.push(ClipTimeline {
            index,
            speaker_id: clip.speaker_id.clone(),
            start_ms: cursor,
            end_ms: end,
            pause_after_ms: pause,
        });
        cursor = end.checked_add(pause).ok_or_else(failure)?;
        if cursor > options.max_duration_ms {
            return Err(failure());
        }
    }
    Ok(result)
}

pub async fn tool_versions(
    tools: &MediaTools,
    limits: &AudioRunLimits,
    cancel: &mut watch::Receiver<bool>,
) -> Result<ToolProvenance> {
    let mut versions = Vec::new();
    for tool in [&tools.ffmpeg, &tools.ffprobe] {
        let output = run(tool, args(&["-version"]), limits, cancel).await?;
        let text = std::str::from_utf8(&output.stdout).map_err(|_| failure())?;
        let version = text
            .lines()
            .next()
            .filter(|value| !value.is_empty())
            .ok_or_else(failure)?;
        versions.push(version.to_owned());
    }
    Ok(ToolProvenance {
        ffmpeg_version: versions.remove(0),
        ffprobe_version: versions.remove(0),
    })
}
async fn duration(
    tools: &MediaTools,
    path: &Path,
    limits: &AudioRunLimits,
    cancel: &mut watch::Receiver<bool>,
) -> Result<f64> {
    regular(path)?;
    let mut command = args(&[
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
    ]);
    command.push(path.as_os_str().into());
    let output = run(&tools.ffprobe, command, limits, cancel).await?;
    let value: serde_json::Value = serde_json::from_slice(&output.stdout).map_err(|_| failure())?;
    let duration = value["format"]["duration"]
        .as_str()
        .ok_or_else(failure)?
        .parse::<f64>()
        .map_err(|_| failure())?;
    if !duration.is_finite() || duration <= 0. {
        return Err(failure());
    }
    Ok(duration)
}
pub fn parse_loudnorm(text: &str) -> Result<LoudnormStats> {
    let start = text.rfind('{').ok_or_else(failure)?;
    let end = text
        .rfind('}')
        .filter(|end| *end > start)
        .ok_or_else(failure)?;
    let value: serde_json::Value =
        serde_json::from_str(&text[start..=end]).map_err(|_| failure())?;
    let number = |key: &str| -> Result<f64> {
        let value = value[key]
            .as_str()
            .ok_or_else(failure)?
            .parse::<f64>()
            .map_err(|_| failure())?;
        if !value.is_finite() {
            return Err(failure());
        }
        Ok(value)
    };
    let normalization_type = value["normalization_type"]
        .as_str()
        .filter(|value| matches!(*value, "linear" | "dynamic"))
        .ok_or_else(failure)?
        .into();
    Ok(LoudnormStats {
        input_i: number("input_i")?,
        input_tp: number("input_tp")?,
        input_lra: number("input_lra")?,
        input_thresh: number("input_thresh")?,
        target_offset: number("target_offset")?,
        normalization_type,
    })
}
pub fn parse_ebur128(text: &str) -> Result<Measurement> {
    let summary = text
        .rsplit("Summary:")
        .next()
        .filter(|value| *value != text)
        .ok_or_else(failure)?;
    let number = |label: &str| -> Result<f64> {
        let line = summary
            .lines()
            .map(str::trim)
            .find_map(|line| line.strip_prefix(label))
            .ok_or_else(failure)?;
        let value = line
            .split_whitespace()
            .next()
            .ok_or_else(failure)?
            .parse::<f64>()
            .map_err(|_| failure())?;
        if !value.is_finite() {
            return Err(failure());
        }
        Ok(value)
    };
    let true_peak = summary
        .split_once("True peak:")
        .ok_or_else(failure)?
        .1
        .lines()
        .map(str::trim)
        .find_map(|line| line.strip_prefix("Peak:"))
        .ok_or_else(failure)?;
    let peak = true_peak
        .split_whitespace()
        .next()
        .ok_or_else(failure)?
        .parse::<f64>()
        .map_err(|_| failure())?;
    if !peak.is_finite() {
        return Err(failure());
    }
    Ok(Measurement {
        integrated_lufs: number("I:")?,
        true_peak_dbtp: peak,
        loudness_range_lu: number("LRA:")?,
    })
}
pub async fn measure_audio(
    tools: &MediaTools,
    path: &Path,
    limits: &AudioRunLimits,
    cancel: &mut watch::Receiver<bool>,
) -> Result<Measurement> {
    regular(path)?;
    let mut command = args(&["-hide_banner", "-nostdin", "-nostats", "-i"]);
    command.push(path.as_os_str().into());
    command.extend(args(&[
        "-af",
        "ebur128=peak=true:framelog=verbose",
        "-f",
        "null",
        "-",
    ]));
    let output = run(&tools.ffmpeg, command, limits, cancel).await?;
    parse_ebur128(std::str::from_utf8(&output.stderr).map_err(|_| failure())?)
}

fn graph(
    clips: &[SpokenClip],
    timeline: &[ClipTimeline],
    bgm: bool,
    options: &AudioMixOptions,
) -> Result<String> {
    let layout = if options.channels == 1 {
        "mono"
    } else {
        "stereo"
    };
    let mut filter = String::new();
    for row in timeline {
        filter.push_str(&format!("[{}:a:0]aresample={},aformat=sample_fmts=fltp:channel_layouts={layout},atrim=duration={},asetpts=PTS-STARTPTS,apad=pad_dur={},atrim=duration={}[clip{}];",row.index,options.sample_rate,sec(clips[row.index].duration_ms),sec(row.pause_after_ms),sec(clips[row.index].duration_ms.checked_add(row.pause_after_ms).ok_or_else(failure)?),row.index));
    }
    for row in timeline {
        filter.push_str(&format!("[clip{}]", row.index));
    }
    filter.push_str(&format!(
        "concat=n={}:v=0:a=1,volume={}",
        clips.len(),
        options.ducking.voice_gain
    ));
    if bgm {
        let total = timeline
            .last()
            .ok_or_else(failure)?
            .end_ms
            .checked_add(timeline.last().ok_or_else(failure)?.pause_after_ms)
            .ok_or_else(failure)?;
        let d = &options.ducking;
        filter.push_str(&format!(",asplit=2[side][voice];[{}:a:0]aresample={},aformat=sample_fmts=fltp:channel_layouts={layout},atrim=duration={},asetpts=PTS-STARTPTS,volume={}[bg];[bg][side]sidechaincompress=threshold={}:ratio={}:attack={}:release={}[duck];[voice][duck]amix=inputs=2:normalize=0:duration=first[mix]",clips.len(),options.sample_rate,sec(total),d.bgm_gain,d.threshold,d.ratio,d.attack_ms,d.release_ms));
    } else {
        filter.push_str("[mix]");
    }
    if filter.len() > options.max_filter_bytes {
        return Err(failure());
    }
    Ok(filter)
}

pub struct MixRequest<'a> {
    pub clips: &'a [SpokenClip],
    pub bgm: Option<&'a Path>,
    pub options: &'a AudioMixOptions,
    pub pause_profile: &'a PauseProfile,
    pub output_directory: &'a Path,
}
#[tracing::instrument(skip_all,fields(channel_id=channel.as_str()))]
pub async fn mix(
    channel: &ChannelId,
    tools: &MediaTools,
    request: MixRequest<'_>,
    cancel: &mut watch::Receiver<bool>,
) -> Result<AudioOutput> {
    let mut stage = "validate";
    mix_inner(channel, tools, request, cancel, &mut stage)
        .await
        .inspect_err(|error| {
            tracing::error!(stage,cause_code=%error.code,"音声mixが失敗した工程を記録しました");
        })
}
async fn mix_inner(
    channel: &ChannelId,
    tools: &MediaTools,
    request: MixRequest<'_>,
    cancel: &mut watch::Receiver<bool>,
    phase: &mut &'static str,
) -> Result<AudioOutput> {
    let MixRequest {
        clips,
        bgm,
        options,
        pause_profile,
        output_directory,
    } = request;
    let rows = timeline(clips, pause_profile, options)?;
    check(cancel)?;
    if !output_directory.is_absolute() || output_directory.try_exists().map_err(|_| failure())? {
        return Err(failure());
    }
    let parent = output_directory.parent().ok_or_else(failure)?;
    *phase = "prepare_private_stage";
    let stage = tempfile::Builder::new()
        .prefix("audio-mix-stage-")
        .tempdir_in(parent)
        .map_err(|_| failure())?;
    let work = tempfile::Builder::new()
        .prefix("audio-mix-work-")
        .tempdir_in(parent)
        .map_err(|_| failure())?;
    *phase = "tool_versions";
    let provenance = tool_versions(tools, &options.run, cancel).await?;
    *phase = "probe_sources";
    for (index, clip) in clips.iter().enumerate() {
        let actual = duration(tools, &clip.path, &options.run, cancel).await? * 1000.;
        if (actual - clip.duration_ms as f64).abs() > options.duration_tolerance_ms as f64 {
            tracing::error!(
                index,
                actual_ms = actual,
                expected_ms = clip.duration_ms,
                "音源長とtimelineの指定が一致しません"
            );
            return Err(failure());
        }
    }
    if let Some(path) = bgm {
        duration(tools, path, &options.run, cancel).await?;
    }
    let mut command = args(&["-hide_banner", "-nostdin", "-nostats", "-n"]);
    for clip in clips {
        command.push("-i".into());
        command.push(clip.path.as_os_str().into());
    }
    if let Some(path) = bgm {
        command.extend(args(&["-stream_loop", "-1", "-i"]));
        command.push(path.as_os_str().into());
    }
    let filter = graph(clips, &rows, bgm.is_some(), options)?;
    let premix = work.path().join("premix.wav");
    command.extend(args(&[
        "-filter_complex_threads",
        &options.filter_threads.to_string(),
        "-filter_complex",
        &filter,
        "-map",
        "[mix]",
        "-threads",
        &options.encoding_threads.to_string(),
        "-c:a",
        "pcm_s24le",
    ]));
    command.push(premix.as_os_str().into());
    *phase = "premix_and_duck";
    run(&tools.ffmpeg, command, &options.run, cancel).await?;
    let target_peak = options.true_peak_dbtp - options.true_peak_headroom_db;
    let first_filter = format!(
        "loudnorm=I={}:TP={}:LRA={}:print_format=json",
        options.target_lufs, target_peak, options.loudness_range_lu
    );
    let mut first = args(&["-hide_banner", "-nostdin", "-nostats", "-i"]);
    first.push(premix.as_os_str().into());
    first.extend(args(&["-af", &first_filter, "-f", "null", "-"]));
    *phase = "loudnorm_measure";
    let first = run(&tools.ffmpeg, first, &options.run, cancel).await?;
    let first_pass = parse_loudnorm(std::str::from_utf8(&first.stderr).map_err(|_| failure())?)?;
    let second_filter=format!("loudnorm=I={}:TP={}:LRA={}:measured_I={}:measured_TP={}:measured_LRA={}:measured_thresh={}:offset={}:linear={}:print_format=json",options.target_lufs,target_peak,options.loudness_range_lu,first_pass.input_i,first_pass.input_tp,first_pass.input_lra,first_pass.input_thresh,first_pass.target_offset,options.linear_normalization);
    let audio = stage.path().join("mix.wav");
    let mut second = args(&["-hide_banner", "-nostdin", "-nostats", "-n", "-i"]);
    second.push(premix.as_os_str().into());
    second.extend(args(&[
        "-af",
        &second_filter,
        "-ar",
        &options.sample_rate.to_string(),
        "-ac",
        &options.channels.to_string(),
        "-threads",
        &options.encoding_threads.to_string(),
        "-c:a",
        "pcm_s24le",
    ]));
    second.push(audio.as_os_str().into());
    *phase = "loudnorm_correct";
    let second = run(&tools.ffmpeg, second, &options.run, cancel).await?;
    let second_pass = parse_loudnorm(std::str::from_utf8(&second.stderr).map_err(|_| failure())?)?;
    if options.linear_normalization && second_pass.normalization_type != "linear" {
        tracing::error!(actual_mode=%second_pass.normalization_type,"指定した線形補正をffmpegが適用できませんでした");
        return Err(failure());
    }
    *phase = "ebur128_acceptance";
    let measured = measure_audio(tools, &audio, &options.run, cancel).await?;
    if (measured.integrated_lufs - options.target_lufs).abs() > options.integrated_tolerance_lu
        || measured.true_peak_dbtp > options.true_peak_dbtp
    {
        tracing::error!(
            integrated_lufs = measured.integrated_lufs,
            true_peak_dbtp = measured.true_peak_dbtp,
            "補正後の音量が受入範囲に入りませんでした"
        );
        return Err(failure());
    }
    let last = rows.last().ok_or_else(failure)?;
    let duration_ms = last
        .end_ms
        .checked_add(last.pause_after_ms)
        .ok_or_else(failure)?;
    *phase = "probe_completed_duration";
    let actual_duration = duration(tools, &audio, &options.run, cancel).await? * 1000.;
    if (actual_duration - duration_ms as f64).abs() > options.duration_tolerance_ms as f64 {
        tracing::error!(
            actual_ms = actual_duration,
            expected_ms = duration_ms,
            "完成音源長がtimelineと一致しませんでした"
        );
        return Err(failure());
    }
    let report = AudioReport {
        schema_version: 1,
        channel_id: channel.clone(),
        at: Timestamp::parse(&clock::now_utc_iso())?,
        tools: provenance,
        options: options.clone(),
        pause_profile: pause_profile.clone(),
        timeline: rows,
        duration_ms,
        has_bgm: bgm.is_some(),
        first_pass,
        second_pass,
        measured,
    };
    *phase = "write_versioned_report";
    fsutil::atomic_write_new(
        &stage.path().join("report.json"),
        &serde_json::to_vec_pretty(&report).map_err(|_| failure())?,
    )?;
    check(cancel)?;
    *phase = "cleanup_premix";
    work.close().map_err(|_| failure())?;
    *phase = "publish_complete_bundle";
    fsutil::publish_new_directory(stage.path(), output_directory)?;
    let _published_stage = stage.keep();
    Ok(AudioOutput {
        audio_path: output_directory.join("mix.wav"),
        report_path: output_directory.join("report.json"),
        report,
    })
}

#[cfg(test)]
#[path = "audio_tests.rs"]
mod tests;
