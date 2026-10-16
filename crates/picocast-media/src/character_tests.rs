#![cfg(test)]
#![allow(clippy::unwrap_used)]
use super::{
    digest_hex, maximum_difference, place_character, CharacterBinding, CharacterFrame,
    CharacterFrameRequest, CharacterLayers, CharacterLimits, CharacterMotion, EntranceBounce,
    FrameRate, MouthShape, PhonemeSpan, PhonemeTimeline, PhonemeTimingPolicy, TalkWiggle,
    TimeRange,
};
use image::{ImageEncoder, Rgba, RgbaImage};
use picocast_core::{fsutil, ChannelId};
use picocast_store::{
    repository::{Character, CharacterKey},
    DataMode, Store, StoreOptions, StorePaths,
};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    io::Write,
    path::{Path, PathBuf},
    time::Duration,
};

fn limits() -> CharacterLimits {
    CharacterLimits {
        maximum_file_bytes: 1_000_000,
        maximum_pixels: 4096,
        maximum_layers: 32,
        maximum_variants: 32,
        maximum_decoded_bytes: 1_000_000,
    }
}
fn fixture_json() -> Value {
    serde_json::from_str(include_str!("../tests/fixtures/character-pillow.json")).unwrap()
}
fn pixels(value: &Value) -> RgbaImage {
    let values: Vec<[u8; 4]> = serde_json::from_value(value.clone()).unwrap();
    RgbaImage::from_raw(2, 2, values.into_iter().flatten().collect()).unwrap()
}
fn sparse(index: usize, color: [u8; 4]) -> RgbaImage {
    let mut image = RgbaImage::new(2, 2);
    image.put_pixel((index % 2) as u32, (index / 2) as u32, Rgba(color));
    image
}
fn png(image: &RgbaImage) -> Vec<u8> {
    let mut bytes = Vec::new();
    image::codecs::png::PngEncoder::new(&mut bytes)
        .write_image(
            image.as_raw(),
            image.width(),
            image.height(),
            image::ExtendedColorType::Rgba8,
        )
        .unwrap();
    bytes
}
fn new_file(path: &Path, bytes: &[u8]) {
    let mut file = fsutil::new_file_writer(path).unwrap();
    file.write_all(bytes).unwrap();
    file.finish().unwrap();
}
fn image_record(path: &Path, relative: &str, image: &RgbaImage) -> Value {
    let bytes = png(image);
    new_file(&path.join(relative), &bytes);
    json!({"path":relative,"sha256":digest_hex(&bytes),"bytes":bytes.len()})
}

struct Fixture {
    _temporary: tempfile::TempDir,
    store: Store,
    channel: ChannelId,
    assets: PathBuf,
    manifest: Value,
}
impl Fixture {
    fn new() -> Self {
        Self::with_reference_drift(false)
    }
    fn with_reference_drift(drift: bool) -> Self {
        let temporary = tempfile::tempdir().unwrap();
        let paths = StorePaths::new(temporary.path(), DataMode::Development).unwrap();
        let mut store = Store::open(
            &paths,
            StoreOptions {
                busy_timeout: Duration::from_secs(2),
                backup_pages_per_step: 8,
                backup_pause: Duration::from_millis(1),
            },
        )
        .unwrap();
        let channel = ChannelId::new("character-fixture").unwrap();
        store.create_channel(&channel, "合成fixture").unwrap();
        let character = Character {
            channel_id: channel.clone(),
            id: "fixture".into(),
            name: "合成".into(),
            voice_provider: "voicevox".into(),
            speaker_id: "3".into(),
            style_map_json: json!({}),
            credit_text: "fixture".into(),
            usage_rules_json: json!({}),
            layer_manifest_sha256: None,
        };
        store
            .repository(&channel)
            .unwrap()
            .save(&character)
            .unwrap();
        let source = temporary.path().join("source");
        let reference = fixture_json();
        let expression = pixels(&reference["expected"]["expression"]);
        let input = [
            ("0", None, true, RgbaImage::new(2, 2)),
            ("0/0", Some("0"), false, pixels(&reference["base"])),
            ("0/1", Some("0"), false, sparse(0, [0, 0, 0, 255])),
            ("0/2", Some("0"), false, sparse(0, [255, 128, 0, 128])),
            ("0/3", Some("0"), false, sparse(0, [240, 5, 50, 210])),
            ("0/4", Some("0"), false, sparse(1, [0, 0, 255, 140])),
            ("0/5", Some("0"), false, sparse(1, [30, 30, 30, 220])),
            ("0/6", Some("0"), false, {
                let mut image = RgbaImage::new(2, 2);
                image.put_pixel(0, 0, *expression.get_pixel(0, 0));
                image.put_pixel(1, 0, *expression.get_pixel(1, 0));
                image
            }),
            ("1", None, true, RgbaImage::new(2, 2)),
            (
                "1/0",
                Some("1"),
                false,
                RgbaImage::from_pixel(2, 2, Rgba([255, 255, 0, 255])),
            ),
        ];
        let selected: BTreeMap<String, bool> = input
            .iter()
            .map(|(id, _, _, _)| {
                (
                    id.to_string(),
                    ["0", "0/0", "0/1", "0/4", "1/0"].contains(id),
                )
            })
            .collect();
        let mut layers = Vec::new();
        for (order, (id, parent, group, image)) in input.iter().enumerate() {
            let record = image_record(&source, &format!("layers/{order:06}.png"), image);
            layers.push(json!({"id":id,"parent_id":parent,"order":order,"name":id,"kind":"pixel","visible":selected[*id],"opacity":255,"blend_mode":"norm","clipping":false,"bbox":[0,0,2,2],"is_group":group,"image":record}));
        }
        let requests = [
            ("default", "base", vec![]),
            ("native:base", "base", vec![]),
            (
                "native:mouth_half",
                "half",
                vec![("0/1", false), ("0/2", true)],
            ),
            (
                "native:mouth_open",
                "open",
                vec![("0/1", false), ("0/3", true)],
            ),
            (
                "native:eye_closed",
                "blink",
                vec![("0/4", false), ("0/5", true)],
            ),
            (
                "expression:smile",
                "expression",
                vec![("0/1", false), ("0/4", false), ("0/6", true)],
            ),
        ];
        let mut variants = Vec::new();
        for (index, (id, name, changes)) in requests.into_iter().enumerate() {
            let mut visible = selected.clone();
            for (layer, value) in changes {
                visible.insert(layer.into(), value);
            }
            let mut expected = pixels(&reference["expected"][name]);
            if drift && index == 0 {
                expected.get_pixel_mut(0, 0)[0] = 1;
            }
            let record = image_record(&source, &format!("variants/{index:06}.png"), &expected);
            variants.push(json!({"id":id,"visibility":visible,"image":record,"validation":{"max_abs_channel_diff":0,"mismatched_pixels":0,"qualified":true}}));
        }
        let manifest = json!({"schema_version":1,"source":{"sha256":"a".repeat(64),"bytes":1,"psd_tools_version":"fixture","depth":8,"color_mode":"RGB"},"canvas":{"width":2,"height":2},"pixel_tolerance":0,"layers":layers,"variants":variants,"unsupported_composition":[],"expression_overlay_policy":"disable_mouth_and_blink_on_expression_png","coverage":{"kind":"explicit_variants"},"qualified":true});
        let manifest_path = source.join("manifest.json");
        new_file(&manifest_path, &serde_json::to_vec(&manifest).unwrap());
        let assets = paths.assets_directory();
        store
            .register_character_layers(&channel, "fixture", &manifest_path, &assets)
            .unwrap();
        Self {
            _temporary: temporary,
            store,
            channel,
            assets,
            manifest,
        }
    }
    fn load(&self) -> CharacterLayers {
        CharacterLayers::load(
            &self.store,
            &self.channel,
            "fixture",
            &self.assets,
            limits(),
        )
        .unwrap()
    }
}
fn binding() -> CharacterBinding {
    CharacterBinding {
        base_variant: "native:base".into(),
        mouth_half_variant: Some("native:mouth_half".into()),
        mouth_open_variant: Some("native:mouth_open".into()),
        blink_variant: Some("native:eye_closed".into()),
        expressions: BTreeMap::from([("smile".into(), "expression:smile".into())]),
        lipsync: true,
        blink: true,
    }
}
fn motion() -> CharacterMotion {
    CharacterMotion {
        blinks: vec![TimeRange {
            start: Duration::ZERO,
            end: Duration::from_millis(500),
        }],
        blink_only_speaking: true,
        wiggle: None,
        bounce: None,
    }
}
fn timeline(channel: &ChannelId) -> PhonemeTimeline {
    PhonemeTimeline {
        channel: channel.clone(),
        spans: vec![PhonemeSpan {
            phoneme: "a".into(),
            range: TimeRange {
                start: Duration::ZERO,
                end: Duration::from_secs(1),
            },
        }],
        audio_duration: Duration::from_secs(1),
    }
}

#[test]
fn registered_cas_layers_equal_old_pillow_and_expression_disables_both_face_changes() {
    let fixture = Fixture::new();
    let character = fixture.load().prepare(&binding()).unwrap();
    let reference = fixture_json();
    let motion = motion();
    let timeline = timeline(&fixture.channel);
    let map = BTreeMap::from([("a".into(), MouthShape::Half)]);
    let mut request = CharacterFrameRequest {
        channel_id: &fixture.channel,
        character_id: "fixture",
        speaking: true,
        expression: None,
        frame: 0,
        frame_rate: FrameRate {
            numerator: 30,
            denominator: 1,
        },
        phonemes: &timeline,
        mouth_map: &map,
        motion: &motion,
    };
    let frame = character.frame(&request).unwrap();
    assert_eq!(frame.image, pixels(&reference["expected"]["half-blink"]));
    assert_eq!(frame.mouth, MouthShape::Half);
    assert!(frame.blinking);
    request.expression = Some("smile");
    let frame = character.frame(&request).unwrap();
    assert_eq!(frame.image, pixels(&reference["expected"]["expression"]));
    assert_eq!(
        (frame.mouth_layer_changes, frame.blink_layer_changes),
        (0, 0)
    );
    assert!(!frame.blinking);
    assert!(frame.expression_active);
    request.expression = Some("missing");
    assert!(character.frame(&request).is_err());
    request.expression = None;
    request.speaking = false;
    assert_eq!(
        character.frame(&request).unwrap().image,
        pixels(&reference["expected"]["base"])
    );
    let destination = fixture._temporary.path().join("composed.png");
    frame.save_new_png(&destination).unwrap();
    assert!(frame.save_new_png(&destination).is_err());
}

#[test]
fn wrong_channel_reference_corruption_unsupported_blend_and_pixel_drift_stop() {
    let drift = Fixture::with_reference_drift(true);
    assert!(CharacterLayers::load(
        &drift.store,
        &drift.channel,
        "fixture",
        &drift.assets,
        limits()
    )
    .is_err());
    let fixture = Fixture::new();
    let other = ChannelId::new("other").unwrap();
    fixture.store.create_channel(&other, "他fixture").unwrap();
    let mut copied = fixture
        .store
        .repository(&fixture.channel)
        .unwrap()
        .get::<Character>(&CharacterKey {
            channel_id: fixture.channel.clone(),
            id: "fixture".into(),
        })
        .unwrap()
        .unwrap();
    copied.channel_id = other.clone();
    fixture
        .store
        .repository(&other)
        .unwrap()
        .save(&copied)
        .unwrap();
    assert!(
        CharacterLayers::load(&fixture.store, &other, "fixture", &fixture.assets, limits())
            .is_err()
    );
    let mut unsupported = fixture.manifest.clone();
    unsupported["layers"][0]["blend_mode"] = json!("mul");
    assert!(picocast_store::character_layers::validate_manifest(
        &serde_json::to_vec(&unsupported).unwrap()
    )
    .is_err());
    let hash = fixture.manifest["layers"][1]["image"]["sha256"]
        .as_str()
        .unwrap();
    let path = fsutil::content_asset_path(&fixture.assets, hash, "png").unwrap();
    fsutil::atomic_write(&path, b"corrupt-fixture-only").unwrap();
    assert!(CharacterLayers::load(
        &fixture.store,
        &fixture.channel,
        "fixture",
        &fixture.assets,
        limits()
    )
    .is_err());
    let mut changed = pixels(&fixture_json()["expected"]["base"]);
    changed.get_pixel_mut(0, 0)[0] = 1;
    assert_eq!(
        maximum_difference(&changed, &pixels(&fixture_json()["expected"]["base"])).unwrap(),
        1
    );
}

#[test]
fn synthesis_padding_is_closed_and_decoder_uses_even_rounding() {
    let channel = ChannelId::new("timing-padding").unwrap();
    let mut query = speech_query();
    query["speedScale"] = json!(2.0);
    let speech = picocast_voice::SynthesisResult {
        channel_id: channel.clone(),
        style_id: 3,
        kana: "fixture".into(),
        query: query.clone(),
        audio: picocast_voice::WaveAudio {
            bytes: Vec::new(),
            sample_rate: 24000,
            channels: 1,
            frames: 18656,
            trailing_silent_frames: 12000,
        },
    };
    let timeline = PhonemeTimeline::from_synthesis(&speech, &timing_policy()).unwrap();
    assert_eq!(timeline.phoneme_at(Duration::from_millis(700)), Some("sil"));
    assert!(PhonemeTimeline::from_query(
        &channel,
        &query,
        timeline.audio_duration,
        &timing_policy()
    )
    .is_err());
    let mut query = speech_query();
    query["prePhonemeLength"] = json!(0.5 / 93.75);
    query["postPhonemeLength"] = json!(0.5 / 93.75);
    query["accent_phrases"][0]["moras"][0]["vowel_length"] = json!(1.5 / 93.75);
    query["accent_phrases"][0]["moras"][1]["vowel_length"] = json!(2.5 / 93.75);
    query["accent_phrases"][0]["pause_mora"] = Value::Null;
    let timeline = PhonemeTimeline::from_query(
        &channel,
        &query,
        Duration::from_secs_f64(9.0 / 93.75),
        &timing_policy(),
    )
    .unwrap();
    assert_eq!(timeline.spans[0].phoneme, "k");
    assert_eq!(timeline.spans[0].range.start, Duration::ZERO);
    assert_eq!(
        timeline.spans[1].range.end.as_nanos(),
        7 * 256 * 1_000_000_000 / 24000
    );
}

fn timing_policy() -> PhonemeTimingPolicy {
    PhonemeTimingPolicy {
        decoder_sample_rate: 24000,
        decoder_hop_samples: 256,
        interrogative_upspeak: true,
        interrogative_length: Duration::from_millis(150),
        legacy_pause_scale: 1.0,
        maximum_phonemes: 100,
        allowed_audio_drift: Duration::from_millis(1),
    }
}
fn speech_query() -> Value {
    json!({"speedScale":1.0,"prePhonemeLength":0.1,"postPhonemeLength":0.5,"pauseLengthScale":1.0,"pauseLength":null,"accent_phrases":[{"is_interrogative":false,"moras":[{"consonant":"k","consonant_length":0.05,"vowel":"a","vowel_length":0.1,"pitch":5.0},{"consonant":null,"consonant_length":null,"vowel":"i","vowel_length":0.2,"pitch":5.0}],"pause_mora":{"consonant":null,"vowel":"pau","vowel_length":0.1,"pitch":0.0}}]})
}
#[test]
fn query_decoder_rounding_drives_mouth_within_one_video_frame() {
    let channel = ChannelId::new("timing-fixture").unwrap();
    let rate = 93.75;
    let timeline = PhonemeTimeline::from_query(
        &channel,
        &speech_query(),
        Duration::from_secs_f64(98.0 / rate),
        &timing_policy(),
    )
    .unwrap();
    assert_eq!(
        timeline
            .spans
            .iter()
            .map(|span| span.phoneme.as_str())
            .collect::<Vec<_>>(),
        vec!["sil", "k", "a", "i", "pau", "sil"]
    );
    let frame_rate = FrameRate {
        numerator: 30,
        denominator: 1,
    };
    let first_open = (0..40)
        .find(|frame| timeline.phoneme_at(frame_rate.timestamp(*frame).unwrap()) == Some("a"))
        .unwrap();
    assert_eq!(first_open, 5);
    assert!(
        frame_rate
            .timestamp(first_open)
            .unwrap()
            .abs_diff(Duration::from_secs_f64(14.0 / rate))
            <= frame_rate.timestamp(1).unwrap()
    );
    assert_eq!(
        timeline.phoneme_at(frame_rate.timestamp(8).unwrap()),
        Some("i")
    );
    let mut query = speech_query();
    query["accent_phrases"][0]["is_interrogative"] = json!(true);
    let interrogative = PhonemeTimeline::from_query(
        &channel,
        &query,
        Duration::from_secs_f64(112.0 / rate),
        &timing_policy(),
    )
    .unwrap();
    assert_eq!(interrogative.spans[4].phoneme, "i");
    assert!(PhonemeTimeline::from_query(
        &channel,
        &query,
        Duration::from_secs(50),
        &timing_policy()
    )
    .is_err());
    assert!(FrameRate {
        numerator: 0,
        denominator: 1
    }
    .timestamp(1)
    .is_err());
}

#[test]
fn motion_is_speaker_only_and_placement_keeps_original_pixels_and_alpha_edges() {
    let fixture = Fixture::new();
    let character = fixture.load().prepare(&binding()).unwrap();
    let timeline = timeline(&fixture.channel);
    let map = BTreeMap::from([("a".into(), MouthShape::Open)]);
    let mut motion = motion();
    motion.wiggle = Some(TalkWiggle {
        x_pixels: 2.0,
        y_pixels: 3.0,
        cycles_per_second: 1.0,
    });
    motion.bounce = Some(EntranceBounce {
        duration: Duration::from_secs(1),
        scale_amplitude: 0.04,
    });
    let mut request = CharacterFrameRequest {
        channel_id: &fixture.channel,
        character_id: "fixture",
        speaking: true,
        expression: None,
        frame: 0,
        frame_rate: FrameRate {
            numerator: 30,
            denominator: 1,
        },
        phonemes: &timeline,
        mouth_map: &map,
        motion: &motion,
    };
    let frame = character.frame(&request).unwrap();
    assert_eq!(frame.offset_y, 3);
    request.speaking = false;
    let frame = character.frame(&request).unwrap();
    assert_eq!((frame.offset_x, frame.offset_y, frame.scale), (0, 0, 1.0));
    let mut canvas = RgbaImage::from_pixel(2, 2, Rgba([255, 255, 255, 0]));
    place_character(&mut canvas, &frame, 0, 0, 1.0, false, &limits()).unwrap();
    assert_eq!(canvas, frame.image);
    assert!(place_character(&mut canvas, &frame, -1, 0, 1.0, false, &limits()).is_err());
    assert!(place_character(&mut canvas, &frame, i64::MAX, 0, 1.0, true, &limits()).is_err());
    let edge = CharacterFrame {
        image: {
            let mut image = RgbaImage::from_pixel(2, 2, Rgba([0, 0, 255, 0]));
            image.put_pixel(0, 0, Rgba([255, 0, 0, 255]));
            image
        },
        mouth: MouthShape::Closed,
        blinking: false,
        mouth_layer_changes: 0,
        blink_layer_changes: 0,
        expression_active: false,
        offset_x: 0,
        offset_y: 0,
        scale: 1.0,
    };
    let mut canvas = RgbaImage::new(4, 4);
    place_character(&mut canvas, &edge, 0, 0, 2.0, false, &limits()).unwrap();
    assert!(canvas
        .pixels()
        .filter(|pixel| pixel[3] > 0)
        .all(|pixel| pixel[2] == 0));
}
