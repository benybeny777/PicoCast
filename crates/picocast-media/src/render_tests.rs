#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::*;
use crate::subtitle::{FontSource, LayoutOptions, SubtitleAlignment, TextStyle};
use serde_json::json;

fn options() -> RenderOptions {
    RenderOptions {
        source_size: VideoSize {
            width: 128,
            height: 72,
        },
        mode: RenderMode::Final,
        frame_rate: FrameRate {
            numerator: 10,
            denominator: 1,
        },
        maximum_pixels: 100_000,
        maximum_frames: 100,
        maximum_duration_ms: 10_000,
        maximum_cached_bytes: 10_000_000,
        frame_queue_capacity: 2,
        duration_tolerance_ms: 120,
        encoding_threads: 1,
        audio_bitrate_kbps: 64,
        encoder_candidates: vec![
            EncoderCandidate {
                encoder: VideoEncoder::H264Nvenc,
                preset: "p4".into(),
                quality: 10,
            },
            EncoderCandidate {
                encoder: VideoEncoder::Libx264,
                preset: "ultrafast".into(),
                quality: 10,
            },
        ],
        run: AudioRunLimits {
            timeout_ms: 15_000,
            max_output_bytes: 1_000_000,
        },
        expected_ffmpeg_version: None,
        expected_ffprobe_version: None,
        background_fill_rgba: [0, 0, 0, 255],
        character_limits: CharacterLimits {
            maximum_file_bytes: 1_000_000,
            maximum_pixels: 100_000,
            maximum_layers: 100,
            maximum_variants: 100,
            maximum_decoded_bytes: 10_000_000,
        },
    }
}
fn motion() -> ZoomPan {
    ZoomPan {
        start_zoom: 1.,
        end_zoom: 1.,
        start_pan: [0.5, 0.5],
        end_pan: [0.5, 0.5],
    }
}
fn probe() -> Vec<u8> {
    serde_json::to_vec(&json!({"streams":[{"codec_type":"video","codec_name":"h264","width":128,"height":72,"nb_frames":"6","avg_frame_rate":"10/1"},{"codec_type":"audio","codec_name":"aac"}],"format":{"duration":"0.600"}})).unwrap()
}
#[derive(Default)]
struct FakeProcess {
    commands: Vec<RenderCommand>,
    frames: Vec<Vec<u8>>,
    bad_probe: bool,
    probe_override: Option<Vec<u8>>,
}
impl RenderProcess for FakeProcess {
    fn run<'a>(
        &'a mut self,
        command: RenderCommand,
        mut input: Option<proc::ProcessInput>,
    ) -> RenderProcessFuture<'a> {
        Box::pin(async move {
            let stdout = match command.kind {
                RenderCommandKind::Version => b"fixture version 1\n".to_vec(),
                RenderCommandKind::Encoders => b"V..... h264_nvenc\nV..... libx264\n".to_vec(),
                RenderCommandKind::Encode => {
                    let chunks = &mut input.as_mut().unwrap().chunks;
                    while let Some(chunk) = chunks.recv().await {
                        self.frames.push(chunk?);
                    }
                    let output = PathBuf::from(command.arguments.last().unwrap());
                    fsutil::atomic_write_new(&output, b"fake-mp4")?;
                    Vec::new()
                }
                RenderCommandKind::Probe => {
                    if self.bad_probe {
                        b"{}".to_vec()
                    } else {
                        self.probe_override.clone().unwrap_or_else(probe)
                    }
                }
            };
            self.commands.push(command);
            Ok(RenderProcessOutput {
                stdout,
                stderr: Vec::new(),
            })
        })
    }
}

#[test]
fn settings_encoder_frame_count_and_rational_probe_boundaries() {
    let channel = ChannelId::new("fixture").unwrap();
    let mut settings = options();
    settings.validate().unwrap();
    assert_eq!(settings.frame_count(601).unwrap(), 7);
    settings.frame_rate = FrameRate {
        numerator: 20,
        denominator: 2,
    };
    assert!(parse_video_probe(&probe(), &settings, 6, 600).is_ok());
    let selected = select_encoder(
        &channel,
        b"h264_nvenc libx264",
        &settings.encoder_candidates,
        None,
    )
    .unwrap();
    assert_eq!(selected.encoder, VideoEncoder::Libx264);
    assert_eq!(selected.skipped.len(), 1);
    assert!(select_encoder(&channel, b"h264_nvenc", &settings.encoder_candidates, None).is_err());
    settings.mode = RenderMode::Preview {
        size: VideoSize {
            width: 64,
            height: 40,
        },
    };
    assert!(settings.validate().is_err());
    settings = options();
    settings.frame_queue_capacity = usize::MAX;
    assert!(settings.validate().is_err());
    settings = options();
    settings.frame_rate.denominator = 0;
    assert!(settings.frame_count(600).is_err());
}

#[cfg(windows)]
fn engine() -> TextLayoutEngine {
    TextLayoutEngine::new(
        &[
            FontSource {
                path: "C:/Windows/Fonts/YuGothR.ttc".into(),
            },
            FontSource {
                path: "C:/Windows/Fonts/YuGothB.ttc".into(),
            },
        ],
        "ja-JP".into(),
    )
    .unwrap()
}
#[cfg(windows)]
fn subtitles(text: &mut TextLayoutEngine, channel: &ChannelId) -> RenderSubtitles {
    let layout = text
        .layout(
            "検証",
            &[],
            200,
            400,
            &LayoutOptions {
                width_px: 100.,
                height_px: 30.,
                max_lines_per_cue: 1,
                max_graphemes_per_line: 12,
                min_graphemes_per_line: 2,
                max_input_graphemes: 100,
                max_measurements: 1000,
                allow_inside_phrase_break: true,
                prohibited_line_start: "、。".into(),
                prohibited_line_end: "「".into(),
                minimum_display_ms: 100,
                max_graphemes_per_second: 20.,
                style: TextStyle {
                    family: "Yu Gothic".into(),
                    font_size: 16.,
                    line_height: 26.,
                    normal_weight: 400,
                    emphasis_weight: 700,
                    normal_rgba: [255; 4],
                    emphasis_rgba: [255; 4],
                    stroke_px: 1.,
                },
            },
        )
        .unwrap();
    RenderSubtitles {
        channel_id: channel.clone(),
        layout,
        left: 14,
        top: 40,
        raster: SubtitleRasterOptions {
            alignment: SubtitleAlignment::Center,
            stroke_rgba: [0, 0, 0, 255],
            maximum_pixels: 10_000,
            maximum_stroke_kernel_samples: 25,
        },
    }
}
fn background(channel: &ChannelId) -> RenderBackground {
    RenderBackground {
        channel_id: channel.clone(),
        source_id: "fixture-background".into(),
        image: RgbaImage::from_pixel(128, 72, Rgba([20, 30, 40, 255])),
    }
}
fn timeline<'a>(
    channel: &ChannelId,
    audio: &'a AudioOutput,
    background: &'a RenderBackground,
) -> RenderTimeline<'a> {
    RenderTimeline {
        channel_id: channel.clone(),
        duration_ms: 600,
        audio,
        backgrounds: vec![BackgroundClip {
            start_ms: 0,
            end_ms: 600,
            source: background,
            motion: motion(),
            transition_ms: 0,
        }],
        characters: vec![],
        subtitles: vec![],
    }
}
fn bright(frame: &[u8]) -> usize {
    frame
        .chunks_exact(4)
        .filter(|pixel| pixel[0] > 180 && pixel[1] > 180 && pixel[2] > 180)
        .count()
}

#[cfg(windows)]
#[tokio::test]
async fn streamed_frames_same_font_subtitle_timing_noclobber_and_failed_publish() {
    let root = tempfile::tempdir().unwrap();
    let channel = ChannelId::new("fixture").unwrap();
    let path = root.path().join("audio.wav");
    fsutil::atomic_write_new(&path, b"fixture").unwrap();
    let audio = crate::audio::fixture_output(&channel, path, 600);
    let bg = background(&channel);
    let mut text = engine();
    let mut timeline = timeline(&channel, &audio, &bg);
    timeline.subtitles.push(subtitles(&mut text, &channel));
    let settings = options();
    let tools = MediaTools {
        ffmpeg: root.path().join("ffmpeg.exe"),
        ffprobe: root.path().join("ffprobe.exe"),
    };
    let target = root.path().join("render");
    let (_sender, mut cancel) = watch::channel(false);
    let mut renderer = TimelineRenderer::new(text, FakeProcess::default());
    let output = renderer
        .render(
            RenderRequest {
                timeline: &timeline,
                options: &settings,
                tools: &tools,
                output_directory: &target,
                job_id: "fixture",
                gpu_permit: None,
            },
            &mut cancel,
        )
        .await
        .unwrap();
    assert_eq!(output.report.frames, 6);
    assert!(output.report_path.is_file());
    assert_eq!(output.report.encoder.encoder, VideoEncoder::Libx264);
    assert!(renderer
        .render(
            RenderRequest {
                timeline: &timeline,
                options: &settings,
                tools: &tools,
                output_directory: &target,
                job_id: "fixture",
                gpu_permit: None
            },
            &mut cancel
        )
        .await
        .is_err());
    let process = renderer.into_process();
    assert_eq!(process.frames.len(), 6);
    assert_eq!(
        process
            .frames
            .iter()
            .map(|frame| bright(frame) > 0)
            .collect::<Vec<_>>(),
        vec![false, false, true, true, false, false]
    );
    let encode = process
        .commands
        .iter()
        .find(|command| matches!(command.kind, RenderCommandKind::Encode))
        .unwrap();
    assert!(!encode
        .arguments
        .iter()
        .any(|arg| arg.to_string_lossy().contains("drawtext")));
    assert!(encode.arguments.iter().any(|arg| arg == "pipe:0"));
    let mut preview = options();
    preview.mode = RenderMode::Preview {
        size: VideoSize {
            width: 64,
            height: 36,
        },
    };
    let mut preview_probe: Value = serde_json::from_slice(&probe()).unwrap();
    preview_probe["streams"][0]["width"] = json!(64);
    preview_probe["streams"][0]["height"] = json!(36);
    let mut preview_renderer = TimelineRenderer::new(
        engine(),
        FakeProcess {
            probe_override: Some(serde_json::to_vec(&preview_probe).unwrap()),
            ..Default::default()
        },
    );
    preview_renderer
        .render(
            RenderRequest {
                timeline: &timeline,
                options: &preview,
                tools: &tools,
                output_directory: &root.path().join("preview"),
                job_id: "preview",
                gpu_permit: None,
            },
            &mut cancel,
        )
        .await
        .unwrap();
    let preview_process = preview_renderer.into_process();
    assert!(preview_process
        .frames
        .iter()
        .all(|frame| frame.len() == 64 * 36 * 4));
    assert_eq!(
        preview_process
            .frames
            .iter()
            .map(|frame| bright(frame) > 0)
            .collect::<Vec<_>>(),
        vec![false, false, true, true, false, false]
    );
    let mut renderer = TimelineRenderer::new(
        engine(),
        FakeProcess {
            bad_probe: true,
            ..Default::default()
        },
    );
    let failed = root.path().join("failed");
    assert!(renderer
        .render(
            RenderRequest {
                timeline: &timeline,
                options: &settings,
                tools: &tools,
                output_directory: &failed,
                job_id: "fixture",
                gpu_permit: None
            },
            &mut cancel
        )
        .await
        .is_err());
    assert!(!failed.exists());
    let (sender, mut stopped) = watch::channel(true);
    let cancelled = root.path().join("cancelled");
    assert!(renderer
        .render(
            RenderRequest {
                timeline: &timeline,
                options: &settings,
                tools: &tools,
                output_directory: &cancelled,
                job_id: "fixture",
                gpu_permit: None
            },
            &mut stopped
        )
        .await
        .is_err());
    drop(sender);
    assert!(!cancelled.exists());
}

#[test]
fn timeline_gaps_other_channel_and_crossfade_are_checked() {
    let root = tempfile::tempdir().unwrap();
    let channel = ChannelId::new("fixture").unwrap();
    let path = root.path().join("audio.wav");
    fsutil::atomic_write_new(&path, b"fixture").unwrap();
    let audio = crate::audio::fixture_output(&channel, path, 600);
    let bg = background(&channel);
    let mut timeline = timeline(&channel, &audio, &bg);
    let settings = options();
    timeline.validate(&settings).unwrap();
    timeline.backgrounds[0].start_ms = 1;
    assert!(timeline.validate(&settings).is_err());
    timeline.backgrounds[0].start_ms = 0;
    let mut other = background(&ChannelId::new("other").unwrap());
    other.image = RgbaImage::from_pixel(128, 72, Rgba([220, 30, 40, 255]));
    timeline.backgrounds[0].end_ms = 200;
    timeline.backgrounds.push(BackgroundClip {
        start_ms: 200,
        end_ms: 600,
        source: &other,
        motion: motion(),
        transition_ms: 200,
    });
    assert!(timeline.validate(&settings).is_err());
    // 借用中の素材は不変にするため、同じ色のチャンネル内素材で作り直す。
    let red = RenderBackground {
        channel_id: channel.clone(),
        source_id: "red".into(),
        image: RgbaImage::from_pixel(128, 72, Rgba([220, 30, 40, 255])),
    };
    timeline.backgrounds[1].source = &red;
    timeline.validate(&settings).unwrap();
    assert_eq!(
        render_frame(&timeline, &settings, &[], 2)
            .unwrap()
            .get_pixel(0, 0)[0],
        20
    );
    assert_eq!(
        render_frame(&timeline, &settings, &[], 3)
            .unwrap()
            .get_pixel(0, 0)[0],
        120
    );
    assert_eq!(
        render_frame(&timeline, &settings, &[], 4)
            .unwrap()
            .get_pixel(0, 0)[0],
        220
    );
}

#[cfg(windows)]
#[tokio::test]
#[ignore = "PICOCAST_TEST_FFMPEGへ導入済み絶対パスを指定しCPU合成のみを明示実行する"]
async fn installed_cpu_ffmpeg_preserves_audio_duration_and_subtitle_frames() -> Result<()> {
    let ffmpeg = picocast_core::settings::validation_ffmpeg_path()?;
    let tools = MediaTools {
        ffprobe: ffmpeg.with_file_name("ffprobe.exe"),
        ffmpeg,
    };
    let root = tempfile::tempdir().unwrap();
    let channel = ChannelId::new("fixture")?;
    let path = root.path().join("synthetic.wav");
    let samples = (0..14_400)
        .map(|index| ((index as f64 * 440. * std::f64::consts::TAU / 24_000.).sin() * 3000.) as i16)
        .collect::<Vec<_>>();
    let data_bytes = (samples.len() * 2) as u32;
    let mut wav = Vec::new();
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + data_bytes).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&1u16.to_le_bytes());
    wav.extend_from_slice(&24_000u32.to_le_bytes());
    wav.extend_from_slice(&48_000u32.to_le_bytes());
    wav.extend_from_slice(&2u16.to_le_bytes());
    wav.extend_from_slice(&16u16.to_le_bytes());
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&data_bytes.to_le_bytes());
    for sample in samples {
        wav.extend_from_slice(&sample.to_le_bytes());
    }
    fsutil::atomic_write_new(&path, &wav)?;
    let audio = crate::audio::fixture_output(&channel, path, 600);
    let bg = background(&channel);
    let mut timeline = timeline(&channel, &audio, &bg);
    let mut text = engine();
    timeline.subtitles.push(subtitles(&mut text, &channel));
    let mut settings = options();
    settings
        .encoder_candidates
        .retain(|candidate| candidate.encoder == VideoEncoder::Libx264);
    let target = root.path().join("cpu-output");
    let (_sender, mut cancel) = watch::channel(false);
    let result = TimelineRenderer::new(text, CoreRenderProcess)
        .render(
            RenderRequest {
                timeline: &timeline,
                options: &settings,
                tools: &tools,
                output_directory: &target,
                job_id: "cpu-fixture",
                gpu_permit: None,
            },
            &mut cancel,
        )
        .await?;
    assert_eq!(result.report.frames, 6);
    assert!(result.report.probe.audio_present);
    assert_eq!(result.report.output_size, settings.source_size);
    let mut args = arguments(&["-v", "error", "-i"]);
    args.push(result.video_path.as_os_str().into());
    args.extend(arguments(&[
        "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgba", "-threads", "1", "pipe:1",
    ]));
    let decoded = proc::run(
        &tools.ffmpeg,
        &args,
        proc::RunOptions {
            timeout: Duration::from_secs(10),
            max_output_bytes: 128 * 72 * 4 * 7,
        },
    )
    .await?;
    let frames = decoded
        .stdout
        .chunks_exact(128 * 72 * 4)
        .collect::<Vec<_>>();
    assert_eq!(frames.len(), 6);
    assert_eq!(
        frames
            .iter()
            .map(|frame| bright(frame) > 0)
            .collect::<Vec<_>>(),
        vec![false, false, true, true, false, false]
    );
    // 実際に出力音声を復号し、無音や空ストリームを取り違えない。
    let mut args = arguments(&["-v", "error", "-i"]);
    args.push(result.video_path.as_os_str().into());
    args.extend(arguments(&[
        "-map",
        "0:a:0",
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "24000",
        "-ac",
        "1",
        "pipe:1",
    ]));
    let decoded = proc::run(
        &tools.ffmpeg,
        &args,
        proc::RunOptions {
            timeout: Duration::from_secs(10),
            max_output_bytes: 40_000,
        },
    )
    .await?;
    assert!(decoded.stdout.len() >= 28_000);
    assert!(
        decoded
            .stdout
            .chunks_exact(2)
            .map(|sample| i16::from_le_bytes([sample[0], sample[1]]).unsigned_abs())
            .max()
            .unwrap()
            > 1000
    );
    Ok(())
}
