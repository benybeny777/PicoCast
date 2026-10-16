//! 実測した字幕とキャラクターを同じRGBAフレームへ合成し、有限ffmpegへ流す。
use crate::{
    audio::{AudioOutput, AudioRunLimits, MediaTools, ToolProvenance},
    character::{
        self, CharacterFrameRequest, CharacterLimits, CharacterMotion, FrameRate, MouthShape,
        PhonemeTimeline, PreparedCharacter,
    },
    subtitle::{RasterizedSubtitle, SubtitleLayout, SubtitleRasterOptions, TextLayoutEngine},
};
use image::{Rgba, RgbaImage};
use picocast_core::{
    clock::{self, Timestamp},
    fsutil,
    gpu::GpuPermit,
    paths, proc, AppError, ChannelId, Result,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsString,
    future::Future,
    io::Write,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::sync::{mpsc, watch};

#[path = "render_process.rs"]
mod process;
pub use process::{
    CoreRenderProcess, RenderCommand, RenderCommandKind, RenderProcess, RenderProcessFuture,
    RenderProcessOutput,
};
const VIDEO_FILENAME: &str = "video.mp4";
const REPORT_FILENAME: &str = "render.json";

fn failure(code: &str) -> AppError {
    tracing::error!(code, "タイムラインの描画を停止しました");
    AppError::new(
        code,
        "タイムラインまたは動画を書き出せませんでした",
        "チャンネル・素材・字幕・時間と解像度・エンコーダ・新しい保存先を確認してください",
    )
}
fn check(cancel: &watch::Receiver<bool>) -> Result<()> {
    if *cancel.borrow() {
        Err(failure("E-RENDER-CANCELLED"))
    } else {
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct VideoSize {
    pub width: u32,
    pub height: u32,
}
impl VideoSize {
    fn pixels(self) -> Result<u64> {
        if self.width == 0
            || self.height == 0
            || !self.width.is_multiple_of(2)
            || !self.height.is_multiple_of(2)
        {
            return Err(failure("E-RENDER-SETTINGS"));
        }
        Ok(u64::from(self.width) * u64::from(self.height))
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RenderMode {
    Final,
    Preview { size: VideoSize },
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum VideoEncoder {
    Libx264,
    H264Nvenc,
}
impl VideoEncoder {
    fn name(self) -> &'static str {
        match self {
            Self::Libx264 => "libx264",
            Self::H264Nvenc => "h264_nvenc",
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EncoderCandidate {
    pub encoder: VideoEncoder,
    pub preset: String,
    pub quality: u8,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EncoderSelection {
    pub encoder: VideoEncoder,
    pub preset: String,
    pub quality: u8,
    pub gpu_device: Option<u32>,
    pub gpu_uuid: Option<String>,
    pub skipped: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct RenderOptions {
    pub source_size: VideoSize,
    pub mode: RenderMode,
    pub frame_rate: FrameRate,
    pub maximum_pixels: u64,
    pub maximum_frames: u64,
    pub maximum_duration_ms: u64,
    pub maximum_cached_bytes: u64,
    pub frame_queue_capacity: usize,
    pub duration_tolerance_ms: u64,
    pub encoding_threads: u32,
    pub audio_bitrate_kbps: u32,
    pub encoder_candidates: Vec<EncoderCandidate>,
    pub run: AudioRunLimits,
    pub expected_ffmpeg_version: Option<String>,
    pub expected_ffprobe_version: Option<String>,
    pub background_fill_rgba: [u8; 4],
    pub character_limits: CharacterLimits,
}
impl RenderOptions {
    pub fn target_size(&self) -> VideoSize {
        match self.mode {
            RenderMode::Final => self.source_size,
            RenderMode::Preview { size } => size,
        }
    }
    pub fn validate(&self) -> Result<()> {
        let source = self.source_size.pixels()?;
        let target = self.target_size();
        let target_pixels = target.pixels()?;
        self.frame_rate.timestamp(1)?;
        if source > self.maximum_pixels
            || target_pixels > self.maximum_pixels
            || self.maximum_frames == 0
            || self.maximum_duration_ms == 0
            || self.maximum_cached_bytes == 0
            || self.frame_queue_capacity == 0
            || self.encoding_threads == 0
            || self.audio_bitrate_kbps == 0
            || self.encoder_candidates.is_empty()
            || self.run.timeout_ms == 0
            || self.run.max_output_bytes == 0
            || self.background_fill_rgba[3] != 255
            || u64::from(target.width) * u64::from(self.source_size.height)
                != u64::from(target.height) * u64::from(self.source_size.width)
            || matches!(self.mode, RenderMode::Preview { .. })
                && (target.width > self.source_size.width
                    || target.height > self.source_size.height)
        {
            return Err(failure("E-RENDER-SETTINGS"));
        }
        let mut candidates = BTreeSet::new();
        for candidate in &self.encoder_candidates {
            if !candidates.insert(candidate.encoder)
                || candidate.preset.is_empty()
                || !candidate
                    .preset
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
                || candidate.quality > 51
            {
                return Err(failure("E-RENDER-SETTINGS"));
            }
        }
        let queue_bytes = target_pixels
            .checked_mul(4)
            .and_then(|bytes| {
                (self.frame_queue_capacity as u64)
                    .checked_add(2)
                    .and_then(|count| bytes.checked_mul(count))
            })
            .ok_or_else(|| failure("E-RENDER-SETTINGS"))?;
        if queue_bytes > self.maximum_cached_bytes {
            return Err(failure("E-RENDER-SETTINGS"));
        }
        Ok(())
    }
    pub fn frame_count(&self, duration_ms: u64) -> Result<u64> {
        self.frame_rate.timestamp(1)?;
        if duration_ms == 0 || duration_ms > self.maximum_duration_ms {
            return Err(failure("E-RENDER-TIMELINE"));
        }
        let count = (u128::from(duration_ms) * u128::from(self.frame_rate.numerator))
            .div_ceil(1000 * u128::from(self.frame_rate.denominator));
        let count = u64::try_from(count).map_err(|_| failure("E-RENDER-TIMELINE"))?;
        if count > self.maximum_frames {
            return Err(failure("E-RENDER-TIMELINE"));
        }
        Ok(count)
    }
}

/// 画像プロバイダが所有確認した復号済み画像をチャンネルとともに明示注入する。
pub struct RenderBackground {
    pub channel_id: ChannelId,
    pub source_id: String,
    pub image: RgbaImage,
}
#[derive(Clone, Debug)]
pub struct ZoomPan {
    pub start_zoom: f64,
    pub end_zoom: f64,
    pub start_pan: [f64; 2],
    pub end_pan: [f64; 2],
}
pub struct BackgroundClip<'a> {
    pub start_ms: u64,
    pub end_ms: u64,
    pub source: &'a RenderBackground,
    pub motion: ZoomPan,
    pub transition_ms: u64,
}
pub struct CharacterCue<'a> {
    pub start_ms: u64,
    pub end_ms: u64,
    pub speaking: bool,
    pub expression: Option<String>,
    pub phonemes: &'a PhonemeTimeline,
    pub motion: &'a CharacterMotion,
}
pub struct RenderCharacter<'a> {
    pub character_id: String,
    pub prepared: &'a PreparedCharacter,
    pub left: i64,
    pub top: i64,
    pub scale: f64,
    pub allow_clipping: bool,
    pub mouth_map: BTreeMap<String, MouthShape>,
    pub cues: Vec<CharacterCue<'a>>,
}
pub struct RenderSubtitles {
    pub channel_id: ChannelId,
    pub layout: SubtitleLayout,
    pub left: i64,
    pub top: i64,
    pub raster: SubtitleRasterOptions,
}
pub struct RenderTimeline<'a> {
    pub channel_id: ChannelId,
    pub duration_ms: u64,
    pub audio: &'a AudioOutput,
    pub backgrounds: Vec<BackgroundClip<'a>>,
    pub characters: Vec<RenderCharacter<'a>>,
    pub subtitles: Vec<RenderSubtitles>,
}
impl RenderTimeline<'_> {
    fn working_bytes(&self, options: &RenderOptions) -> Result<u64> {
        let source_pixels = self
            .backgrounds
            .iter()
            .map(|clip| {
                u64::from(clip.source.image.width()) * u64::from(clip.source.image.height())
            })
            .max()
            .unwrap_or(0);
        // RGBA32Fの入力・中間・出力、クロスフェード、完成/待機フレームを予約する。
        source_pixels
            .checked_mul(24)
            .and_then(|bytes| {
                options.target_size().pixels().ok().and_then(|pixels| {
                    pixels
                        .checked_mul(80)
                        .and_then(|frames| bytes.checked_add(frames))
                })
            })
            .and_then(|bytes| {
                (options.frame_queue_capacity as u64)
                    .checked_mul(options.target_size().pixels().ok()?.checked_mul(4)?)
                    .and_then(|queue| bytes.checked_add(queue))
            })
            .ok_or_else(|| failure("E-RENDER-SETTINGS"))
    }
    pub fn validate(&self, options: &RenderOptions) -> Result<()> {
        options.validate()?;
        options.frame_count(self.duration_ms)?;
        if self.audio.report.channel_id != self.channel_id
            || self.audio.report.duration_ms.abs_diff(self.duration_ms)
                > options.duration_tolerance_ms
            || self.backgrounds.is_empty()
        {
            return Err(failure("E-RENDER-TIMELINE"));
        }
        paths::require_regular_file(&self.audio.audio_path)?;
        let mut end = 0;
        for (index, clip) in self.backgrounds.iter().enumerate() {
            if clip.source.channel_id != self.channel_id
                || clip.source.source_id.is_empty()
                || clip.start_ms != end
                || clip.start_ms >= clip.end_ms
                || clip.end_ms > self.duration_ms
                || clip.transition_ms > clip.end_ms - clip.start_ms
                || index == 0 && clip.transition_ms != 0
            {
                return Err(failure("E-RENDER-TIMELINE"));
            }
            let pixels =
                u64::from(clip.source.image.width()) * u64::from(clip.source.image.height());
            if pixels == 0 || pixels > options.maximum_pixels {
                return Err(failure("E-RENDER-ASSET"));
            }
            for zoom in [clip.motion.start_zoom, clip.motion.end_zoom] {
                if !zoom.is_finite() || zoom < 1.0 {
                    return Err(failure("E-RENDER-TIMELINE"));
                }
            }
            for pan in clip.motion.start_pan.into_iter().chain(clip.motion.end_pan) {
                if !pan.is_finite() || !(0.0..=1.0).contains(&pan) {
                    return Err(failure("E-RENDER-TIMELINE"));
                }
            }
            end = clip.end_ms;
        }
        if end != self.duration_ms {
            return Err(failure("E-RENDER-TIMELINE"));
        }
        if self.working_bytes(options)? > options.maximum_cached_bytes {
            return Err(failure("E-RENDER-SETTINGS"));
        }
        for character in &self.characters {
            if character.character_id.is_empty()
                || !character.scale.is_finite()
                || character.scale <= 0.0
            {
                return Err(failure("E-RENDER-TIMELINE"));
            }
            validate_ranges(
                character.cues.iter().map(|cue| (cue.start_ms, cue.end_ms)),
                self.duration_ms,
            )?;
        }
        for subtitles in &self.subtitles {
            if subtitles.channel_id != self.channel_id
                || subtitles.left < 0
                || subtitles.top < 0
                || subtitles.left as f64 + f64::from(subtitles.layout.area_width_px)
                    > f64::from(options.source_size.width)
                || subtitles.top as f64 + f64::from(subtitles.layout.area_height_px)
                    > f64::from(options.source_size.height)
            {
                return Err(failure("E-RENDER-TIMELINE"));
            }
            validate_ranges(
                subtitles
                    .layout
                    .cues
                    .iter()
                    .map(|cue| (cue.start_ms, cue.end_ms)),
                self.duration_ms,
            )?;
        }
        for (index, left) in self.subtitles.iter().enumerate() {
            for right in &self.subtitles[index + 1..] {
                let spatial = (left.left as f64)
                    < right.left as f64 + f64::from(right.layout.area_width_px)
                    && (right.left as f64)
                        < left.left as f64 + f64::from(left.layout.area_width_px)
                    && (left.top as f64)
                        < right.top as f64 + f64::from(right.layout.area_height_px)
                    && (right.top as f64) < left.top as f64 + f64::from(left.layout.area_height_px);
                if spatial
                    && left.layout.cues.iter().any(|a| {
                        right
                            .layout
                            .cues
                            .iter()
                            .any(|b| a.start_ms < b.end_ms && b.start_ms < a.end_ms)
                    })
                {
                    return Err(failure("E-RENDER-TIMELINE"));
                }
            }
        }
        Ok(())
    }
}
fn validate_ranges(ranges: impl Iterator<Item = (u64, u64)>, duration: u64) -> Result<()> {
    let mut previous = 0;
    for (start, end) in ranges {
        if start < previous || start >= end || end > duration {
            return Err(failure("E-RENDER-TIMELINE"));
        }
        previous = end;
    }
    Ok(())
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VideoProbe {
    pub width: u32,
    pub height: u32,
    pub frames: u64,
    pub duration_seconds: f64,
    pub audio_present: bool,
    pub video_codec: String,
}
#[derive(Serialize)]
pub struct RenderReport {
    pub schema_version: u32,
    pub channel_id: ChannelId,
    pub job_id: String,
    pub at: Timestamp,
    pub tools: ToolProvenance,
    pub version_warnings: Vec<String>,
    pub mode: RenderMode,
    pub source_size: VideoSize,
    pub output_size: VideoSize,
    pub frame_rate: [u32; 2],
    pub frames: u64,
    pub duration_ms: u64,
    pub encoder: EncoderSelection,
    pub background_pixels_sha256: Vec<String>,
    pub subtitle_ranges: Vec<[u64; 2]>,
    pub subtitle_fonts: Vec<Vec<String>>,
    pub probe: VideoProbe,
}
pub struct RenderOutput {
    pub directory: PathBuf,
    pub video_path: PathBuf,
    pub report_path: PathBuf,
    pub report: RenderReport,
}
pub struct RenderRequest<'a> {
    pub timeline: &'a RenderTimeline<'a>,
    pub options: &'a RenderOptions,
    pub tools: &'a MediaTools,
    pub output_directory: &'a Path,
    pub job_id: &'a str,
    pub gpu_permit: Option<&'a GpuPermit>,
}
struct CachedSubtitle {
    image: RasterizedSubtitle,
    left: i64,
    top: i64,
}

pub struct TimelineRenderer<P> {
    text: TextLayoutEngine,
    process: P,
}
impl<P: RenderProcess> TimelineRenderer<P> {
    pub fn new(text: TextLayoutEngine, process: P) -> Self {
        Self { text, process }
    }
    pub fn into_process(self) -> P {
        self.process
    }
    pub async fn render(
        &mut self,
        request: RenderRequest<'_>,
        cancel: &mut watch::Receiver<bool>,
    ) -> Result<RenderOutput> {
        let mut phase = "validate";
        let channel_id = request.timeline.channel_id.clone();
        let job_id = request.job_id;
        self.render_inner(request, cancel, &mut phase)
            .await
            .inspect_err(
                |error| tracing::error!(phase,channel_id=channel_id.as_str(),job_id,code=%error.code,"レンダーの失敗工程を記録しました"),
            )
    }
    async fn render_inner(
        &mut self,
        request: RenderRequest<'_>,
        cancel: &mut watch::Receiver<bool>,
        phase: &mut &'static str,
    ) -> Result<RenderOutput> {
        let RenderRequest {
            timeline,
            options,
            tools,
            output_directory,
            job_id,
            gpu_permit,
        } = request;
        timeline.validate(options)?;
        check(cancel)?;
        if job_id.trim().is_empty()
            || !tools.ffmpeg.is_absolute()
            || !tools.ffprobe.is_absolute()
            || !output_directory.is_absolute()
            || output_directory
                .try_exists()
                .map_err(|_| failure("E-RENDER-OUTPUT"))?
        {
            return Err(failure("E-RENDER-OUTPUT"));
        }
        let parent = output_directory
            .parent()
            .ok_or_else(|| failure("E-RENDER-OUTPUT"))?;
        *phase = "tool_versions";
        let mut versions = Vec::new();
        for tool in [&tools.ffmpeg, &tools.ffprobe] {
            let response = self
                .command(
                    tool,
                    &["-version"],
                    RenderCommandKind::Version,
                    &options.run,
                    cancel,
                )
                .await?;
            let text =
                std::str::from_utf8(&response.stdout).map_err(|_| failure("E-RENDER-VERSION"))?;
            versions.push(
                text.lines()
                    .next()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| failure("E-RENDER-VERSION"))?
                    .to_owned(),
            );
        }
        let provenance = ToolProvenance {
            ffmpeg_version: versions.remove(0),
            ffprobe_version: versions.remove(0),
        };
        let mut warnings = Vec::new();
        for (name, expected, actual) in [
            (
                "ffmpeg",
                options.expected_ffmpeg_version.as_ref(),
                &provenance.ffmpeg_version,
            ),
            (
                "ffprobe",
                options.expected_ffprobe_version.as_ref(),
                &provenance.ffprobe_version,
            ),
        ] {
            if expected.is_some_and(|expected| expected != actual) {
                tracing::warn!(tool = name, "外部ソフトの版が基準と異なります");
                warnings.push(format!("{name}: expected version differs"));
            }
        }
        *phase = "encoder_selection";
        let available = self
            .command(
                &tools.ffmpeg,
                &["-hide_banner", "-encoders"],
                RenderCommandKind::Encoders,
                &options.run,
                cancel,
            )
            .await?;
        let encoder = select_encoder(
            &timeline.channel_id,
            &available.stdout,
            &options.encoder_candidates,
            gpu_permit,
        )?;
        *phase = "subtitle_raster";
        let target = options.target_size();
        let ratio = f64::from(target.width) / f64::from(options.source_size.width);
        let mut subtitles = Vec::new();
        let mut cached_bytes = timeline.working_bytes(options)?;
        for track in &timeline.subtitles {
            for index in 0..track.layout.cues.len() {
                let raster_pixels = f64::from(track.layout.area_width_px).ceil()
                    * f64::from(track.layout.area_height_px).ceil();
                // ラスター化中のfill/strokeとpreviewのRGBA32F中間も確保前に検査する。
                if !raster_pixels.is_finite()
                    || raster_pixels <= 0.0
                    || raster_pixels > u64::MAX as f64
                    || (raster_pixels as u64)
                        .checked_mul(48)
                        .and_then(|bytes| bytes.checked_add(cached_bytes))
                        .is_none_or(|bytes| bytes > options.maximum_cached_bytes)
                {
                    return Err(failure("E-RENDER-SETTINGS"));
                }
                let mut image = self
                    .text
                    .rasterize_cue(&track.layout, index, &track.raster)?;
                if ratio != 1.0 {
                    let width = (f64::from(image.image.width()) * ratio)
                        .round_ties_even()
                        .max(1.0) as u32;
                    let height = (f64::from(image.image.height()) * ratio)
                        .round_ties_even()
                        .max(1.0) as u32;
                    image.image = character::resize_premultiplied(&image.image, width, height);
                }
                cached_bytes = cached_bytes
                    .checked_add(image.image.as_raw().len() as u64)
                    .ok_or_else(|| failure("E-RENDER-SETTINGS"))?;
                if cached_bytes > options.maximum_cached_bytes {
                    return Err(failure("E-RENDER-SETTINGS"));
                }
                let left = scaled_coordinate(track.left, ratio)?;
                let top = scaled_coordinate(track.top, ratio)?;
                if left < 0
                    || top < 0
                    || left as u64 + u64::from(image.image.width()) > u64::from(target.width)
                    || top as u64 + u64::from(image.image.height()) > u64::from(target.height)
                {
                    return Err(failure("E-RENDER-TIMELINE"));
                }
                subtitles.push(CachedSubtitle { image, left, top });
            }
        }
        *phase = "encode";
        let stage = tempfile::Builder::new()
            .prefix("render-stage-")
            .tempdir_in(parent)
            .map_err(|_| failure("E-RENDER-OUTPUT"))?;
        let movie = stage.path().join(VIDEO_FILENAME);
        let report_path = stage.path().join(REPORT_FILENAME);
        let frames = options.frame_count(timeline.duration_ms)?;
        let (sender, chunks) = mpsc::channel(options.frame_queue_capacity);
        let command = encode_command(
            tools,
            &timeline.audio.audio_path,
            &movie,
            options,
            &encoder,
            frames,
            timeline.duration_ms,
        )?;
        let process = self.process.run(
            command,
            Some(proc::ProcessInput {
                chunks,
                max_chunk_bytes: usize::try_from(target.pixels()? * 4)
                    .map_err(|_| failure("E-RENDER-SETTINGS"))?,
            }),
        );
        let producer_cancel = cancel.clone();
        let producer = async {
            for frame in 0..frames {
                check(&producer_cancel)?;
                let image = render_frame(timeline, options, &subtitles, frame)?;
                sender
                    .send(Ok(image.into_raw()))
                    .await
                    .map_err(|_| failure("E-RENDER-ENCODE"))?;
            }
            drop(sender);
            Ok::<(), AppError>(())
        };
        cancellable(
            async {
                tokio::try_join!(process, producer)?;
                Ok(())
            },
            cancel,
        )
        .await?;
        *phase = "verify_output";
        paths::require_regular_file(&movie)?;
        let mut args = arguments(&[
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ]);
        args.push(movie.as_os_str().into());
        let response = run_cancel(
            &mut self.process,
            RenderCommand {
                kind: RenderCommandKind::Probe,
                program: tools.ffprobe.clone(),
                arguments: args,
                limits: run_limits(&options.run),
            },
            None,
            cancel,
        )
        .await?;
        let probe = parse_video_probe(&response.stdout, options, frames, timeline.duration_ms)?;
        let report = RenderReport {
            schema_version: 1,
            channel_id: timeline.channel_id.clone(),
            job_id: job_id.to_owned(),
            at: Timestamp::parse(&clock::now_utc_iso())?,
            tools: provenance,
            version_warnings: warnings,
            mode: options.mode.clone(),
            source_size: options.source_size,
            output_size: target,
            frame_rate: [options.frame_rate.numerator, options.frame_rate.denominator],
            frames,
            duration_ms: timeline.duration_ms,
            encoder,
            background_pixels_sha256: timeline
                .backgrounds
                .iter()
                .map(|clip| {
                    let mut hash = Sha256::new();
                    hash.update(clip.source.image.width().to_le_bytes());
                    hash.update(clip.source.image.height().to_le_bytes());
                    hash.update(clip.source.image.as_raw());
                    hash.finalize()
                        .iter()
                        .map(|byte| format!("{byte:02x}"))
                        .collect()
                })
                .collect(),
            subtitle_ranges: subtitles
                .iter()
                .map(|cue| [cue.image.start_ms, cue.image.end_ms])
                .collect(),
            subtitle_fonts: timeline
                .subtitles
                .iter()
                .map(|track| track.layout.font_families.clone())
                .collect(),
            probe,
        };
        let bytes = serde_json::to_vec_pretty(&report).map_err(|_| failure("E-RENDER-OUTPUT"))?;
        let mut file = fsutil::new_file_writer(&report_path)?;
        file.write_all(&bytes)
            .map_err(|_| failure("E-RENDER-OUTPUT"))?;
        file.finish()?;
        check(cancel)?;
        *phase = "publish";
        fsutil::publish_new_directory(stage.path(), output_directory)?;
        let _published = stage.keep();
        Ok(RenderOutput {
            directory: output_directory.to_owned(),
            video_path: output_directory.join(VIDEO_FILENAME),
            report_path: output_directory.join(REPORT_FILENAME),
            report,
        })
    }
    async fn command(
        &mut self,
        tool: &Path,
        args: &[&str],
        kind: RenderCommandKind,
        limits: &AudioRunLimits,
        cancel: &mut watch::Receiver<bool>,
    ) -> Result<RenderProcessOutput> {
        run_cancel(
            &mut self.process,
            RenderCommand {
                kind,
                program: tool.to_owned(),
                arguments: arguments(args),
                limits: run_limits(limits),
            },
            None,
            cancel,
        )
        .await
    }
}

fn arguments(values: &[&str]) -> Vec<OsString> {
    values.iter().map(OsString::from).collect()
}
fn run_limits(limits: &AudioRunLimits) -> proc::RunOptions {
    proc::RunOptions {
        timeout: Duration::from_millis(limits.timeout_ms),
        max_output_bytes: limits.max_output_bytes,
    }
}
async fn cancellable<T>(
    operation: impl Future<Output = Result<T>>,
    cancel: &mut watch::Receiver<bool>,
) -> Result<T> {
    check(cancel)?;
    tokio::pin!(operation);
    loop {
        tokio::select! {result=&mut operation=>{check(cancel)?;return result},changed=cancel.changed()=>{if changed.is_err()||*cancel.borrow(){return Err(failure("E-RENDER-CANCELLED"));}}}
    }
}
async fn run_cancel<P: RenderProcess>(
    process: &mut P,
    command: RenderCommand,
    input: Option<proc::ProcessInput>,
    cancel: &mut watch::Receiver<bool>,
) -> Result<RenderProcessOutput> {
    cancellable(process.run(command, input), cancel).await
}

pub fn select_encoder(
    channel: &ChannelId,
    bytes: &[u8],
    candidates: &[EncoderCandidate],
    permit: Option<&GpuPermit>,
) -> Result<EncoderSelection> {
    let text = std::str::from_utf8(bytes).map_err(|_| failure("E-RENDER-ENCODER"))?;
    let available = text.split_whitespace().collect::<BTreeSet<_>>();
    let mut skipped = Vec::new();
    for candidate in candidates {
        if !available.contains(candidate.encoder.name()) {
            skipped.push(format!("{}: unavailable", candidate.encoder.name()));
            continue;
        }
        let (device, uuid) = if candidate.encoder == VideoEncoder::H264Nvenc {
            let Some(permit) = permit else {
                skipped.push("h264_nvenc: GPU permit required".into());
                continue;
            };
            permit.ensure_channel(channel)?;
            (
                Some(permit.device_index()),
                Some(permit.device_uuid().to_owned()),
            )
        } else {
            (None, None)
        };
        return Ok(EncoderSelection {
            encoder: candidate.encoder,
            preset: candidate.preset.clone(),
            quality: candidate.quality,
            gpu_device: device,
            gpu_uuid: uuid,
            skipped,
        });
    }
    Err(failure("E-RENDER-ENCODER"))
}

fn encode_command(
    tools: &MediaTools,
    audio: &Path,
    output: &Path,
    options: &RenderOptions,
    encoder: &EncoderSelection,
    frames: u64,
    duration_ms: u64,
) -> Result<RenderCommand> {
    let size = options.target_size();
    let rate = format!(
        "{}/{}",
        options.frame_rate.numerator, options.frame_rate.denominator
    );
    let mut args = arguments(&[
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-n",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgba",
        "-video_size",
        &format!("{}x{}", size.width, size.height),
        "-framerate",
        &rate,
        "-i",
        "pipe:0",
        "-i",
    ]);
    args.push(audio.as_os_str().into());
    args.extend(arguments(&[
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        encoder.encoder.name(),
        "-preset",
        &encoder.preset,
    ]));
    match encoder.encoder {
        VideoEncoder::Libx264 => args.extend(arguments(&["-crf", &encoder.quality.to_string()])),
        VideoEncoder::H264Nvenc => {
            args.extend(arguments(&[
                "-rc",
                "vbr",
                "-cq",
                &encoder.quality.to_string(),
                "-b:v",
                "0",
                "-gpu",
                &encoder
                    .gpu_device
                    .ok_or_else(|| failure("E-RENDER-ENCODER"))?
                    .to_string(),
            ]));
        }
    }
    args.extend(arguments(&[
        "-pix_fmt",
        "yuv420p",
        "-threads",
        &options.encoding_threads.to_string(),
        "-c:a",
        "aac",
        "-b:a",
        &format!("{}k", options.audio_bitrate_kbps),
        "-frames:v",
        &frames.to_string(),
        "-t",
        &format!("{}.{:03}", duration_ms / 1000, duration_ms % 1000),
        "-movflags",
        "+faststart",
    ]));
    args.push(output.as_os_str().into());
    Ok(RenderCommand {
        kind: RenderCommandKind::Encode,
        program: tools.ffmpeg.clone(),
        arguments: args,
        limits: run_limits(&options.run),
    })
}

fn parse_video_probe(
    bytes: &[u8],
    options: &RenderOptions,
    frames: u64,
    duration_ms: u64,
) -> Result<VideoProbe> {
    let value: Value = serde_json::from_slice(bytes).map_err(|_| failure("E-RENDER-VERIFY"))?;
    let streams = value["streams"]
        .as_array()
        .ok_or_else(|| failure("E-RENDER-VERIFY"))?;
    let video = streams
        .iter()
        .filter(|stream| stream["codec_type"] == "video")
        .collect::<Vec<_>>();
    let audio = streams
        .iter()
        .filter(|stream| stream["codec_type"] == "audio")
        .collect::<Vec<_>>();
    if video.len() != 1 || audio.len() != 1 {
        return Err(failure("E-RENDER-VERIFY"));
    }
    let number = |value: &Value| -> Result<f64> {
        value
            .as_str()
            .ok_or_else(|| failure("E-RENDER-VERIFY"))?
            .parse::<f64>()
            .ok()
            .filter(|value| value.is_finite() && *value > 0.0)
            .ok_or_else(|| failure("E-RENDER-VERIFY"))
    };
    let duration = number(&value["format"]["duration"])?;
    let target = options.target_size();
    let frame_count = video[0]["nb_frames"]
        .as_str()
        .and_then(|value| value.parse::<u64>().ok())
        .ok_or_else(|| failure("E-RENDER-VERIFY"))?;
    let rate = video[0]["avg_frame_rate"]
        .as_str()
        .and_then(|text| text.split_once('/'))
        .and_then(|(n, d)| Some((n.parse::<u32>().ok()?, d.parse::<u32>().ok()?)))
        .filter(|(n, d)| *n > 0 && *d > 0)
        .ok_or_else(|| failure("E-RENDER-VERIFY"))?;
    if video[0]["width"].as_u64() != Some(u64::from(target.width))
        || video[0]["height"].as_u64() != Some(u64::from(target.height))
        || frame_count != frames
        || video[0]["codec_name"] != "h264"
        || u64::from(rate.0) * u64::from(options.frame_rate.denominator)
            != u64::from(rate.1) * u64::from(options.frame_rate.numerator)
        || audio[0]["codec_name"] != "aac"
        || (duration * 1000.0 - duration_ms as f64).abs() > options.duration_tolerance_ms as f64
    {
        return Err(failure("E-RENDER-VERIFY"));
    }
    Ok(VideoProbe {
        width: target.width,
        height: target.height,
        frames: frame_count,
        duration_seconds: duration,
        audio_present: true,
        video_codec: "h264".into(),
    })
}

fn scaled_coordinate(value: i64, ratio: f64) -> Result<i64> {
    let value = value as f64 * ratio;
    if !value.is_finite() || value <= i64::MIN as f64 || value >= i64::MAX as f64 {
        return Err(failure("E-RENDER-SETTINGS"));
    }
    Ok(value.round_ties_even() as i64)
}

fn render_frame(
    timeline: &RenderTimeline<'_>,
    options: &RenderOptions,
    subtitles: &[CachedSubtitle],
    frame: u64,
) -> Result<RgbaImage> {
    let time = options.frame_rate.timestamp(frame)?;
    let milliseconds = time.as_millis();
    let index = timeline
        .backgrounds
        .iter()
        .position(|clip| {
            u128::from(clip.start_ms) <= milliseconds && milliseconds < u128::from(clip.end_ms)
        })
        .ok_or_else(|| failure("E-RENDER-TIMELINE"))?;
    let clip = &timeline.backgrounds[index];
    let local =
        (time.as_secs_f64() * 1000.0 - clip.start_ms as f64) / (clip.end_ms - clip.start_ms) as f64;
    let size = options.target_size();
    let mut image = background_frame(clip, size, local, options)?;
    if clip.transition_ms > 0 && milliseconds < u128::from(clip.start_ms + clip.transition_ms) {
        let previous = background_frame(&timeline.backgrounds[index - 1], size, 1.0, options)?;
        let mix = (time.as_secs_f64() * 1000.0 - clip.start_ms as f64) / clip.transition_ms as f64;
        for (pixel, previous) in image.pixels_mut().zip(previous.pixels()) {
            for component in 0..4 {
                pixel[component] = (f64::from(previous[component]) * (1.0 - mix)
                    + f64::from(pixel[component]) * mix)
                    .round() as u8;
            }
        }
    }
    let ratio = f64::from(size.width) / f64::from(options.source_size.width);
    for track in &timeline.characters {
        if let Some(cue) = track.cues.iter().find(|cue| {
            u128::from(cue.start_ms) <= milliseconds && milliseconds < u128::from(cue.end_ms)
        }) {
            let local = time.saturating_sub(Duration::from_millis(cue.start_ms));
            let local_frame = u64::try_from(
                local.as_nanos() * u128::from(options.frame_rate.numerator)
                    / (1_000_000_000 * u128::from(options.frame_rate.denominator)),
            )
            .map_err(|_| failure("E-RENDER-TIMELINE"))?;
            let mut character = track.prepared.frame(&CharacterFrameRequest {
                channel_id: &timeline.channel_id,
                character_id: &track.character_id,
                speaking: cue.speaking,
                expression: cue.expression.as_deref(),
                frame: local_frame,
                frame_rate: options.frame_rate,
                phonemes: cue.phonemes,
                mouth_map: &track.mouth_map,
                motion: cue.motion,
            })?;
            character.offset_x = scaled_coordinate(character.offset_x, ratio)?;
            character.offset_y = scaled_coordinate(character.offset_y, ratio)?;
            character::place_character(
                &mut image,
                &character,
                scaled_coordinate(track.left, ratio)?,
                scaled_coordinate(track.top, ratio)?,
                track.scale * ratio,
                track.allow_clipping,
                &options.character_limits,
            )?;
        }
    }
    for cue in subtitles {
        if u128::from(cue.image.start_ms) <= milliseconds
            && milliseconds < u128::from(cue.image.end_ms)
        {
            character::composite_at(&mut image, &cue.image.image, cue.left, cue.top);
        }
    }
    Ok(image)
}
fn background_frame(
    clip: &BackgroundClip<'_>,
    size: VideoSize,
    time: f64,
    options: &RenderOptions,
) -> Result<RgbaImage> {
    let zoom = clip.motion.start_zoom + (clip.motion.end_zoom - clip.motion.start_zoom) * time;
    let source = &clip.source.image;
    let cover = (f64::from(size.width) / f64::from(source.width()))
        .max(f64::from(size.height) / f64::from(source.height()));
    if !(cover * zoom).is_finite() {
        return Err(failure("E-RENDER-TIMELINE"));
    }
    let crop_width = (f64::from(size.width) / (cover * zoom))
        .round()
        .max(1.0)
        .min(f64::from(source.width())) as u32;
    let crop_height = (f64::from(size.height) / (cover * zoom))
        .round()
        .max(1.0)
        .min(f64::from(source.height())) as u32;
    let pan = [0, 1].map(|axis| {
        clip.motion.start_pan[axis]
            + (clip.motion.end_pan[axis] - clip.motion.start_pan[axis]) * time
    });
    let left = (f64::from(source.width() - crop_width) * pan[0]).round() as u32;
    let top = (f64::from(source.height() - crop_height) * pan[1]).round() as u32;
    let crop = image::imageops::crop_imm(source, left, top, crop_width, crop_height).to_image();
    let resized = if crop.dimensions() == (size.width, size.height) {
        crop
    } else {
        character::resize_premultiplied(&crop, size.width, size.height)
    };
    let mut result =
        RgbaImage::from_pixel(size.width, size.height, Rgba(options.background_fill_rgba));
    character::composite_at(&mut result, &resized, 0, 0);
    Ok(result)
}

#[cfg(test)]
#[path = "render_tests.rs"]
mod tests;
