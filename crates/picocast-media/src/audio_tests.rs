#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::*;
use std::f64::consts::PI;
fn options() -> AudioMixOptions {
    AudioMixOptions {
        sample_rate: 48000,
        channels: 2,
        target_lufs: -14.,
        true_peak_dbtp: -1.,
        true_peak_headroom_db: 0.2,
        loudness_range_lu: 7.,
        integrated_tolerance_lu: 1.,
        linear_normalization: false,
        duration_tolerance_ms: 2,
        max_clips: 8,
        max_duration_ms: 30000,
        max_filter_bytes: 20000,
        filter_threads: 1,
        encoding_threads: 1,
        ducking: DuckingOptions {
            threshold: 0.01,
            ratio: 10.,
            attack_ms: 5.,
            release_ms: 100.,
            voice_gain: 1.,
            bgm_gain: 0.5,
        },
        run: AudioRunLimits {
            timeout_ms: 10000,
            max_output_bytes: 100000,
        },
    }
}
fn pauses() -> PauseProfile {
    PauseProfile {
        genre: "fixture".into(),
        base_ms: 0,
        comma_ms: 100,
        terminal_ms: 200,
        newline_ms: 300,
        speaker_change_ms: 150,
    }
}

pub(super) fn fixture_output(
    channel: &ChannelId,
    audio_path: PathBuf,
    duration_ms: u64,
) -> AudioOutput {
    let stats = LoudnormStats {
        input_i: -14.,
        input_tp: -1.2,
        input_lra: 0.,
        input_thresh: -24.,
        target_offset: 0.,
        normalization_type: "dynamic".into(),
    };
    let report = AudioReport {
        schema_version: 1,
        channel_id: channel.clone(),
        at: Timestamp::parse("2026-01-01T00:00:00Z").unwrap(),
        tools: ToolProvenance {
            ffmpeg_version: "synthetic-ffmpeg".into(),
            ffprobe_version: "synthetic-ffprobe".into(),
        },
        options: options(),
        pause_profile: PauseProfile {
            comma_ms: 0,
            terminal_ms: 0,
            newline_ms: 0,
            speaker_change_ms: 0,
            ..pauses()
        },
        timeline: vec![ClipTimeline {
            index: 0,
            speaker_id: "fixture".into(),
            start_ms: 0,
            end_ms: duration_ms,
            pause_after_ms: 0,
        }],
        duration_ms,
        has_bgm: false,
        first_pass: stats.clone(),
        second_pass: stats,
        measured: Measurement {
            integrated_lufs: -14.,
            true_peak_dbtp: -1.2,
            loudness_range_lu: 0.,
        },
    };
    AudioOutput {
        report_path: audio_path.with_extension("report.json"),
        audio_path,
        report,
    }
}
fn clip(speaker: &str, text: &str, duration_ms: u64) -> SpokenClip {
    SpokenClip {
        path: PathBuf::from("unused"),
        speaker_id: speaker.into(),
        text: text.into(),
        duration_ms,
    }
}

#[test]
fn explicit_genre_pauses_and_speaker_changes_produce_shared_ms_timeline() {
    let profile = pauses();
    assert_eq!(pause_after("理由、", false, &profile).unwrap(), 100);
    assert_eq!(pause_after("理由。", true, &profile).unwrap(), 350);
    assert_eq!(pause_after("理由\n", true, &profile).unwrap(), 450);
    assert_eq!(
        phrases("理由、具体例。\n次の説明！"),
        vec!["理由、", "具体例。\n", "次の説明！"]
    );
    let rows = timeline(
        &[clip("a", "理由、", 500), clip("b", "疑問？", 300)],
        &profile,
        &options(),
    )
    .unwrap();
    assert_eq!(rows[0].pause_after_ms, 250);
    assert_eq!(rows[1].start_ms, 750);
    assert_eq!(rows[1].end_ms, 1050);
    let filter = graph(
        &[clip("a", "理由、", 500), clip("b", "疑問？", 300)],
        &rows,
        true,
        &options(),
    )
    .unwrap();
    assert!(filter.contains("sidechaincompress=threshold=0.01:ratio=10"));
    assert!(filter.contains("normalize=0"));
    let mut invalid = options();
    invalid.ducking.attack_ms = f64::NAN;
    assert!(invalid.validate().is_err());
    let overflow = PauseProfile {
        base_ms: u64::MAX,
        ..profile
    };
    assert!(pause_after("句点。", false, &overflow).is_err());
}
#[test]
fn strict_measurement_rejects_silence_and_incomplete_reports() {
    let summary="Summary:\n Integrated loudness:\n I: -14.1 LUFS\n LRA: 2.0 LU\n True peak:\n Peak: -1.2 dBFS\n";
    assert_eq!(
        parse_ebur128(summary).unwrap(),
        Measurement {
            integrated_lufs: -14.1,
            true_peak_dbtp: -1.2,
            loudness_range_lu: 2.
        }
    );
    assert!(parse_ebur128(&summary.replace("-14.1", "-inf")).is_err());
    assert!(parse_ebur128("no summary").is_err());
    assert!(parse_loudnorm(r#"{"input_i":"-inf","input_tp":"-20","input_lra":"0","input_thresh":"-30","target_offset":"0","normalization_type":"linear"}"#).is_err());
}
#[tokio::test]
async fn pre_cancel_never_starts_tools_or_publishes_output() {
    let directory = tempfile::tempdir().unwrap();
    let target = directory.path().join("result");
    let (sender, mut cancel) = watch::channel(true);
    let tools = MediaTools {
        ffmpeg: PathBuf::from("missing"),
        ffprobe: PathBuf::from("missing"),
    };
    let clips = [clip("fixture", "説明", 1000)];
    let error = mix(
        &ChannelId::new("fixture").unwrap(),
        &tools,
        MixRequest {
            clips: &clips,
            bgm: None,
            options: &options(),
            pause_profile: &pauses(),
            output_directory: &target,
        },
        &mut cancel,
    )
    .await
    .err()
    .unwrap();
    assert_eq!(error.code, "E-AUDIO-CANCELLED");
    assert!(!target.exists());
    drop(sender);
}

fn wav(path: &Path, hz: f64, amplitude: f64) {
    let samples = 48000u32 * 3;
    let size = samples * 2;
    let mut bytes = Vec::with_capacity(size as usize + 44);
    bytes.extend(b"RIFF");
    bytes.extend((36 + size).to_le_bytes());
    bytes.extend(b"WAVEfmt ");
    bytes.extend(16u32.to_le_bytes());
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(48000u32.to_le_bytes());
    bytes.extend(96000u32.to_le_bytes());
    bytes.extend(2u16.to_le_bytes());
    bytes.extend(16u16.to_le_bytes());
    bytes.extend(b"data");
    bytes.extend(size.to_le_bytes());
    for index in 0..samples {
        let value =
            (amplitude * (2. * PI * hz * f64::from(index) / 48000.).sin() * f64::from(i16::MAX))
                .round() as i16;
        bytes.extend(value.to_le_bytes());
    }
    fsutil::atomic_write_new(path, &bytes).unwrap();
}
fn spectral_ratio(path: &Path) -> f64 {
    let bytes = std::fs::read(path).unwrap();
    let mut offset = 12;
    let mut audio = None;
    while offset + 8 <= bytes.len() {
        let size = u32::from_le_bytes(bytes[offset + 4..offset + 8].try_into().unwrap()) as usize;
        if &bytes[offset..offset + 4] == b"data" {
            audio = Some(&bytes[offset + 8..offset + 8 + size]);
            break;
        }
        offset += 8 + size + (size % 2);
    }
    let audio = audio.unwrap();
    let mut voice = 0.;
    let mut bgm = 0.;
    for index in 24000..120000 {
        let start = index * 6;
        let packed = i32::from_le_bytes([
            audio[start],
            audio[start + 1],
            audio[start + 2],
            if audio[start + 2] & 128 != 0 { 255 } else { 0 },
        ]);
        let value = f64::from(packed) / 8388608.;
        voice += value * (2. * PI * 1000. * index as f64 / 48000.).sin();
        bgm += value * (2. * PI * 200. * index as f64 / 48000.).sin();
    }
    (bgm / voice).abs()
}

/// このPCの導入済実体を明示注入したときだけ実行する。音源は全て3秒の合成PCM。
#[tokio::test]
#[ignore = "PICOCAST_TEST_FFMPEGへ既存絶対パスを指定して明示実行する"]
async fn installed_ffmpeg_three_second_mix_meets_lufs_peak_and_ducking() -> Result<()> {
    let ffmpeg = picocast_core::settings::validation_ffmpeg_path()?;
    let tools = MediaTools {
        ffprobe: ffmpeg.with_file_name(if cfg!(windows) {
            "ffprobe.exe"
        } else {
            "ffprobe"
        }),
        ffmpeg,
    };
    let directory = tempfile::tempdir().unwrap();
    let speech = directory.path().join("voice.wav");
    let bgm = directory.path().join("bgm.wav");
    wav(&speech, 1000., 0.08);
    wav(&bgm, 200., 0.08);
    let speech_before = std::fs::read(&speech).unwrap();
    let bgm_before = std::fs::read(&bgm).unwrap();
    let target = directory.path().join("result");
    let clips = [SpokenClip {
        path: speech.clone(),
        speaker_id: "fixture".into(),
        text: "合成音声".into(),
        duration_ms: 3000,
    }];
    let profile = PauseProfile {
        genre: "fixture".into(),
        base_ms: 0,
        comma_ms: 0,
        terminal_ms: 0,
        newline_ms: 0,
        speaker_change_ms: 0,
    };
    let config = options();
    let (sender, mut cancel) = watch::channel(false);
    let output = mix(
        &ChannelId::new("fixture").unwrap(),
        &tools,
        MixRequest {
            clips: &clips,
            bgm: Some(&bgm),
            options: &config,
            pause_profile: &profile,
            output_directory: &target,
        },
        &mut cancel,
    )
    .await
    .unwrap();
    assert!((output.report.measured.integrated_lufs + 14.).abs() <= 1.);
    assert!(output.report.measured.true_peak_dbtp <= -1.);
    assert!(spectral_ratio(&output.audio_path) < 0.25);
    assert_eq!(std::fs::read(&speech).unwrap(), speech_before);
    assert_eq!(std::fs::read(&bgm).unwrap(), bgm_before);
    let report: AudioReport =
        serde_json::from_slice(&std::fs::read(&output.report_path).unwrap()).unwrap();
    assert_eq!(report.schema_version, 1);
    assert!(report.tools.ffmpeg_version.starts_with("ffmpeg version"));
    let original = std::fs::read(&output.audio_path).unwrap();
    assert!(mix(
        &ChannelId::new("fixture").unwrap(),
        &tools,
        MixRequest {
            clips: &clips,
            bgm: Some(&bgm),
            options: &config,
            pause_profile: &profile,
            output_directory: &target
        },
        &mut cancel
    )
    .await
    .is_err());
    assert_eq!(std::fs::read(&output.audio_path).unwrap(), original);
    let failed = directory.path().join("rejected");
    let mut wrong = clips.clone();
    wrong[0].duration_ms = 2000;
    assert!(mix(
        &ChannelId::new("fixture").unwrap(),
        &tools,
        MixRequest {
            clips: &wrong,
            bgm: None,
            options: &config,
            pause_profile: &profile,
            output_directory: &failed
        },
        &mut cancel
    )
    .await
    .is_err());
    assert!(!failed.exists());
    let limited = directory.path().join("limited");
    let mut low_output = config.clone();
    low_output.run.max_output_bytes = 1;
    let error = mix(
        &ChannelId::new("fixture").unwrap(),
        &tools,
        MixRequest {
            clips: &clips,
            bgm: None,
            options: &low_output,
            pause_profile: &profile,
            output_directory: &limited,
        },
        &mut cancel,
    )
    .await
    .err()
    .unwrap();
    assert_eq!(error.code, "E-PROCESS-OUTPUT");
    assert!(!limited.exists());
    let timeout = directory.path().join("timeout");
    let mut short = config.clone();
    short.run.timeout_ms = 1;
    let error = mix(
        &ChannelId::new("fixture").unwrap(),
        &tools,
        MixRequest {
            clips: &clips,
            bgm: None,
            options: &short,
            pause_profile: &profile,
            output_directory: &timeout,
        },
        &mut cancel,
    )
    .await
    .err()
    .unwrap();
    assert_eq!(error.code, "E-PROCESS-TIMEOUT");
    assert!(!timeout.exists());
    let interrupted = directory.path().join("cancelled");
    let (stop, mut interruption) = watch::channel(false);
    let channel = ChannelId::new("fixture").unwrap();
    let operation = mix(
        &channel,
        &tools,
        MixRequest {
            clips: &clips,
            bgm: None,
            options: &config,
            pause_profile: &profile,
            output_directory: &interrupted,
        },
        &mut interruption,
    );
    let trigger = async {
        tokio::task::yield_now().await;
        stop.send(true).unwrap();
    };
    let (result, ()) = tokio::join!(operation, trigger);
    assert_eq!(result.err().unwrap().code, "E-AUDIO-CANCELLED");
    assert!(!interrupted.exists());
    tracing::info!(
        "fixture: {:.1} LUFS / {:.1} dBTP; ducking spectral ratio {:.4}; {}",
        report.measured.integrated_lufs,
        report.measured.true_peak_dbtp,
        spectral_ratio(&output.audio_path),
        report.tools.ffmpeg_version
    );
    drop(sender);
    Ok(())
}
